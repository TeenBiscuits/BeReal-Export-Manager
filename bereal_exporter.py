import json
import os
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime as dt
from shutil import copy2 as cp
from typing import Optional

import pytz
from exiftool import ExifToolHelper as et
from PIL import Image, ImageDraw
from timezonefinder import TimezoneFinder


def init_parser() -> argparse.Namespace:
    """
    Initializes the argparse module.
    """
    parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument(
        "-v",
        "--verbose",
        default=False,
        action="store_true",
        help="Explain what is being done",
    )
    parser.add_argument(
        "--exiftool-path",
        dest="exiftool_path",
        type=str,
        help="Set the path to the ExifTool executable (needed if it isn't on the $PATH)",
    )
    parser.add_argument(
        "-t",
        "--timespan",
        type=str,
        help="Exports the given timespan\n"
        "Valid format: 'DD.MM.YYYY-DD.MM.YYYY'\n"
        "Wildcards can be used: 'DD.MM.YYYY-*'",
    )
    parser.add_argument("-y", "--year", type=int, help="Exports the given year")
    parser.add_argument(
        "-p",
        "--out-path",
        dest="out_path",
        type=str,
        default="./out",
        help="Set a custom output path (default ./out)",
    )
    parser.add_argument(
        "--bereal-path",
        dest="bereal_path",
        type=str,
        default=".",
        help="Set a custom BeReal path (default ./)",
    )
    parser.add_argument(
        "--no-memories",
        dest="memories",
        default=True,
        action="store_false",
        help="Don't export the memories",
    )
    parser.add_argument(
        "--realmojis",
        dest="realmojis",
        default=False,
        action="store_true",
        help="Export realmojis (optional; not all exports include them)",
    )
    parser.add_argument(
        "--no-posts",
        dest="posts",
        default=True,
        action="store_false",
        help="Don't export the posts",
    )
    parser.add_argument(
        "--no-conversations",
        dest="conversations",
        default=True,
        action="store_false",
        help="Don't export the conversations",
    )
    parser.add_argument(
        "--fallback-timezone",
        dest="fallback_timezone",
        type=str,
        default="Europe/Madrid",
        help="Fallback timezone name (default Europe/Madrid)",
    )
    parser.add_argument(
        "--no-gps-timezone",
        dest="gps_timezone",
        default=True,
        action="store_false",
        help="Don't determine timezone from GPS; use --fallback-timezone",
    )
    parser.add_argument(
        "--composite",
        dest="composite",
        default=False,
        action="store_true",
        help="Create BeReal-style composite images",
    )
    parser.add_argument(
        "--max-workers",
        dest="max_workers",
        type=int,
        default=4,
        help="Maximum number of parallel workers (default 4)",
    )
    args = parser.parse_args()
    if args.year and args.timespan:
        print("Timespan argument will be prioritized")
    return args


class BeRealExporter:
    def __init__(self, args: argparse.Namespace):
        self.time_span = self.init_time_span(args)
        self.exiftool_path = args.exiftool_path
        self.out_path = args.out_path.strip().removesuffix("/")
        self.bereal_path = args.bereal_path.strip().removesuffix("/")
        self.verbose = args.verbose

        self.fallback_timezone = args.fallback_timezone
        self.gps_timezone = args.gps_timezone
        self.composite = args.composite
        self.max_workers = max(1, args.max_workers)

        self._timezone_finder = TimezoneFinder() if self.gps_timezone else None

    @staticmethod
    def init_time_span(args: argparse.Namespace) -> tuple[dt, dt]:
        """Initializes local-time timespan based on arguments."""
        if args.timespan:
            try:
                start_str, end_str = args.timespan.strip().split("-")
                start = (
                    dt.fromtimestamp(0)
                    if start_str == "*"
                    else dt.strptime(start_str, "%d.%m.%Y")
                )
                end = dt.now() if end_str == "*" else dt.strptime(end_str, "%d.%m.%Y")
                return start, end
            except ValueError as exc:
                raise ValueError(
                    "Invalid timespan format. Use 'DD.MM.YYYY-DD.MM.YYYY'."
                ) from exc
        if args.year:
            return dt(args.year, 1, 1), dt(args.year, 12, 31)
        return dt.fromtimestamp(0), dt.now()

    def verbose_msg(self, msg: str):
        """
        Prints an explanation of what is being done to the terminal.
        """
        if self.verbose:
            print(msg)

    @staticmethod
    def print_progress_bar(
        iteration: int,
        total: int,
        prefix: str = "",
        suffix: str = "",
        decimals: int = 1,
        length: int = 60,
        fill: str = "█",
        print_end: str = "\r",
    ):
        """
        Call in a loop to create terminal progress bar.
        Not my creation: https://stackoverflow.com/questions/3173320/text-progress-bar-in-terminal-with-block-characters
        """
        percent = ("{0:." + str(decimals) + "f}").format(
            100 * (iteration / float(total))
        )
        filled_length = int(length * iteration // total)
        bar = fill * filled_length + "-" * (length - filled_length)
        print(f"\r{prefix} |{bar}| {percent}% {suffix}", end=print_end)
        if iteration == total:
            print()

    @staticmethod
    def get_img_filename(image: dict) -> str:
        """
        Returns the image filename from an image object (frontImage, backImage, primary, secondary).
        """
        return image["path"].split("/")[-1]

    def convert_to_local_time(self, utc_dt: dt, location: Optional[dict] = None) -> dt:
        """Convert a UTC datetime to local time.

        Uses timezone derived from GPS coordinates when available, otherwise falls back
        to `--fallback-timezone`. Returns a naive local datetime for EXIF + filenames.
        """
        if utc_dt.tzinfo is None:
            utc_dt = pytz.UTC.localize(utc_dt)
        else:
            utc_dt = utc_dt.astimezone(pytz.UTC)

        timezone_name = self.fallback_timezone
        if (
            self._timezone_finder
            and location
            and "latitude" in location
            and "longitude" in location
        ):
            try:
                detected = self._timezone_finder.timezone_at(
                    lat=location["latitude"],
                    lng=location["longitude"],
                )
                if detected:
                    timezone_name = detected
                    self.verbose_msg(f"Using timezone {detected} from GPS location")
            except Exception as exc:
                self.verbose_msg(f"Error determining timezone from GPS: {exc}")

        try:
            local_tz = pytz.timezone(timezone_name)
        except Exception:
            local_tz = pytz.timezone("Europe/Madrid")

        return utc_dt.astimezone(local_tz).replace(tzinfo=None)

    @staticmethod
    def get_datetime_from_str(time: str) -> dt:
        """Parse BeReal datetime strings into naive UTC datetimes."""
        formats = [
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%S.000Z",
            "%Y-%m-%dT%H:%M:%SZ",
        ]
        for fmt in formats:
            try:
                return dt.strptime(time, fmt)
            except ValueError:
                continue

        try:
            return dt.fromtimestamp(float(time))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid datetime format: {time}") from exc

    def apply_metadata(self, img_name: str, img_dt: dt, img_location=None):
        """Apply local-time EXIF metadata to an existing file."""
        ext = os.path.splitext(img_name)[1].lower()

        video_exts = [".mp4", ".mov", ".avi", ".mkv", ".m4v", ".hevc", ".webm"]
        image_exts = [".jpg", ".jpeg", ".tif", ".tiff", ".png", ".heic", ".webp"]

        is_video = ext in video_exts
        is_image = ext in image_exts
        if not (is_image or is_video):
            return

        local_dt = self.convert_to_local_time(img_dt, img_location)
        datetime_str = local_dt.strftime("%Y:%m:%d %H:%M:%S")

        if is_image:
            tags = {
                "DateTimeOriginal": datetime_str,
                "CreateDate": datetime_str,
                "ModifyDate": datetime_str,
            }
        else:
            tags = {
                "CreationDate": datetime_str,
                "CreateDate": datetime_str,
                "ModifyDate": datetime_str,
            }

        if img_location:
            tags.update(
                {
                    "GPSLatitude*": img_location["latitude"],
                    "GPSLongitude*": img_location["longitude"],
                }
            )

        try:
            with (
                et(executable=self.exiftool_path) if self.exiftool_path else et()
            ) as exif:
                exif.set_tags(img_name, tags=tags, params=["-P", "-overwrite_original"])
        except Exception:
            pass

    def export_img(
        self, old_img_name: str, img_name: str, img_dt: dt, img_location=None
    ):
        """Copy an image/video and write EXIF metadata."""
        self.verbose_msg(f"Export {old_img_name} image to {img_name}")

        if not os.path.isfile(old_img_name):
            self.verbose_msg(f"File not found: {old_img_name}")
            return

        os.makedirs(os.path.dirname(img_name), exist_ok=True)
        cp(old_img_name, img_name)
        self.apply_metadata(img_name, img_dt, img_location)

    def create_rounded_mask(self, size: tuple[int, int], radius: int) -> Image.Image:
        scale = 4
        large_size = (size[0] * scale, size[1] * scale)
        large_radius = radius * scale

        mask = Image.new("L", large_size, 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle(
            (0, 0, large_size[0], large_size[1]), radius=large_radius, fill=255
        )
        return mask.resize(size, Image.Resampling.LANCZOS)

    def create_composite_image(
        self,
        primary_path: str,
        secondary_path: str,
        output_path: str,
        img_dt: dt,
        img_location=None,
    ):
        """Create a BeReal-style composite image.

        Uses `primary` as background and overlays `secondary` in the top-left corner.
        """
        try:
            with (
                Image.open(primary_path) as primary,
                Image.open(secondary_path) as secondary,
            ):
                secondary_width = primary.width // 4
                secondary_height = int(
                    secondary.height * (secondary_width / secondary.width)
                )
                secondary_resized = secondary.resize(
                    (secondary_width, secondary_height), Image.Resampling.LANCZOS
                )

                corner_radius = max(2, min(secondary_width, secondary_height) // 10)
                border_width = 4

                bordered_width = secondary_width + (border_width * 2)
                bordered_height = secondary_height + (border_width * 2)

                bordered_image = Image.new(
                    "RGBA", (bordered_width, bordered_height), (0, 0, 0, 255)
                )
                border_mask = self.create_rounded_mask(
                    (bordered_width, bordered_height), corner_radius + border_width
                )
                bordered_image.putalpha(border_mask)

                inner_mask = self.create_rounded_mask(
                    (secondary_width, secondary_height), corner_radius
                )
                secondary_rgba = secondary_resized.convert("RGBA")
                secondary_rgba.putalpha(inner_mask)

                bordered_image.paste(
                    secondary_rgba, (border_width, border_width), secondary_rgba
                )

                composite = primary.convert("RGBA")
                padding = 20
                composite.paste(bordered_image, (padding, padding), bordered_image)

                final_composite = Image.new("RGB", composite.size, (255, 255, 255))
                final_composite.paste(composite, mask=composite.split()[-1])

                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                final_composite.save(output_path, "WEBP", quality=95)

            # Apply metadata to composite
            self.apply_metadata(output_path, img_dt, img_location)

        except Exception as exc:
            self.verbose_msg(f"Failed to create composite {output_path}: {exc}")

    @staticmethod
    def clean_media_path(json_path: str) -> str:
        json_path = json_path.lstrip("/")
        parts = json_path.split("/")
        if len(parts) > 3 and parts[0] == "Photos":
            return os.path.join(parts[0], parts[2], *parts[3:])
        return json_path

    def process_memory(
        self,
        memory: dict,
        memory_dt_utc: dt,
        memory_dt_local: dt,
        out_path_memories: str,
    ) -> Optional[str]:
        img_location = memory.get("location")
        base = memory_dt_local.strftime("%Y-%m-%d_%H-%M-%S")

        types: list[tuple[str, str]] = [("frontImage", "webp"), ("backImage", "webp")]
        if "btsMedia" in memory:
            types.append(("btsMedia", "mp4"))

        for key, ext in types:
            suffix = key.removesuffix("Image").removesuffix("Media")
            img_name = os.path.join(out_path_memories, f"{base}_{suffix}.{ext}")

            json_path = memory[key]["path"]
            old_img_name = os.path.join(
                self.bereal_path, self.clean_media_path(json_path)
            )
            self.export_img(old_img_name, img_name, memory_dt_utc, img_location)

        if self.composite:
            front_path = os.path.join(out_path_memories, f"{base}_front.webp")
            back_path = os.path.join(out_path_memories, f"{base}_back.webp")
            composite_path = os.path.join(out_path_memories, f"{base}_composited.webp")
            if (
                os.path.exists(front_path)
                and os.path.exists(back_path)
                and not os.path.exists(composite_path)
            ):
                self.create_composite_image(
                    back_path, front_path, composite_path, memory_dt_utc, img_location
                )

        return base

    def process_post(
        self,
        post: dict,
        post_dt_utc: dt,
        post_dt_local: dt,
        out_path_posts: str,
    ) -> Optional[str]:
        post_location = post.get("location")
        base = post_dt_local.strftime("%Y-%m-%d_%H-%M-%S")

        types: list[tuple[str, str]] = [("primary", "webp"), ("secondary", "webp")]
        if "btsMedia" in post:
            types.append(("bts", "mp4"))

        for key, ext in types:
            json_key = "btsMedia" if key == "bts" else key
            img_name = os.path.join(out_path_posts, f"{base}_{key}.{ext}")

            json_path = post[json_key]["path"]
            old_img_name = os.path.join(
                self.bereal_path, self.clean_media_path(json_path)
            )
            self.export_img(old_img_name, img_name, post_dt_utc, post_location)

        if self.composite:
            primary_path = os.path.join(out_path_posts, f"{base}_primary.webp")
            secondary_path = os.path.join(out_path_posts, f"{base}_secondary.webp")
            composite_path = os.path.join(out_path_posts, f"{base}_composited.webp")
            if (
                os.path.exists(primary_path)
                and os.path.exists(secondary_path)
                and not os.path.exists(composite_path)
            ):
                self.create_composite_image(
                    primary_path,
                    secondary_path,
                    composite_path,
                    post_dt_utc,
                    post_location,
                )

        return base

    def export_memories(self, memories: list):
        """Exports memories (filtered in converted local time)."""
        out_path_memories = os.path.join(self.out_path, "memories")
        os.makedirs(out_path_memories, exist_ok=True)

        valid: list[tuple[dict, dt, dt]] = []
        for memory in memories:
            memory_dt_utc = self.get_datetime_from_str(memory["takenTime"])
            img_location = memory.get("location")
            memory_dt_local = self.convert_to_local_time(memory_dt_utc, img_location)
            if self.time_span[0] <= memory_dt_local <= self.time_span[1]:
                valid.append((memory, memory_dt_utc, memory_dt_local))

        if not valid:
            self.verbose_msg("No memories found in the specified time range")
            return

        total = len(valid)
        self.verbose_msg(f"Exporting {total} memories with {self.max_workers} workers")

        completed = 0
        latest = ""
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(
                    self.process_memory,
                    memory,
                    memory_dt_utc,
                    memory_dt_local,
                    out_path_memories,
                ): i
                for i, (memory, memory_dt_utc, memory_dt_local) in enumerate(valid, 1)
            }
            for future in as_completed(futures):
                completed += 1
                try:
                    result = future.result()
                    if result:
                        latest = result
                except Exception as exc:
                    self.verbose_msg(f"Memory export failed: {exc}")

                suffix = f"- latest {latest}" if latest else ""
                self.print_progress_bar(
                    completed, total, prefix="Exporting Memories", suffix=suffix
                )

    def export_realmojis(self, realmojis: list):
        """
        Exports all realmojis from the Photos/realmoji directory to the corresponding output folder.
        """
        out_path_realmojis = os.path.join(self.out_path, "realmojis")
        os.makedirs(out_path_realmojis, exist_ok=True)

        valid: list[tuple[dict, dt, dt]] = []
        skipped = 0
        for realmoji in realmojis:
            posted_at = realmoji.get("postedAt")
            media = realmoji.get("media")

            if not posted_at or not isinstance(media, dict) or "path" not in media:
                skipped += 1
                continue

            try:
                realmoji_dt_utc = self.get_datetime_from_str(posted_at)
            except Exception:
                skipped += 1
                continue

            realmoji_dt_local = self.convert_to_local_time(realmoji_dt_utc, None)
            if self.time_span[0] <= realmoji_dt_local <= self.time_span[1]:
                valid.append((realmoji, realmoji_dt_utc, realmoji_dt_local))

        if skipped:
            self.verbose_msg(f"Skipped {skipped} realmojis missing metadata")

        total = len(valid)
        if not total:
            self.verbose_msg("No realmojis found in the specified time range")
            return

        for i, (realmoji, realmoji_dt_utc, realmoji_dt_local) in enumerate(valid, 1):
            img_name = os.path.join(
                out_path_realmojis,
                f"{realmoji_dt_local.strftime('%Y-%m-%d_%H-%M-%S')}.webp",
            )
            old_img_name = os.path.join(
                self.bereal_path,
                f"Photos/realmoji/{self.get_img_filename(realmoji['media'])}",
            )
            self.export_img(old_img_name, img_name, realmoji_dt_utc)
            self.print_progress_bar(
                i,
                total,
                prefix="Exporting Realmojis",
                suffix=f"- {realmoji_dt_local.strftime('%Y-%m-%d')}",
            )

    def export_posts(self, posts: list):
        """Exports posts (filtered in converted local time)."""
        out_path_posts = os.path.join(self.out_path, "posts")
        os.makedirs(out_path_posts, exist_ok=True)

        valid: list[tuple[dict, dt, dt]] = []
        for post in posts:
            post_dt_utc = self.get_datetime_from_str(post["takenAt"])
            post_location = post.get("location")
            post_dt_local = self.convert_to_local_time(post_dt_utc, post_location)
            if self.time_span[0] <= post_dt_local <= self.time_span[1]:
                valid.append((post, post_dt_utc, post_dt_local))

        if not valid:
            self.verbose_msg("No posts found in the specified time range")
            return

        total = len(valid)
        self.verbose_msg(f"Exporting {total} posts with {self.max_workers} workers")

        completed = 0
        latest = ""
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(
                    self.process_post, post, post_dt_utc, post_dt_local, out_path_posts
                ): i
                for i, (post, post_dt_utc, post_dt_local) in enumerate(valid, 1)
            }
            for future in as_completed(futures):
                completed += 1
                try:
                    result = future.result()
                    if result:
                        latest = result
                except Exception as exc:
                    self.verbose_msg(f"Post export failed: {exc}")

                suffix = f"- latest {latest}" if latest else ""
                self.print_progress_bar(
                    completed, total, prefix="Exporting Posts", suffix=suffix
                )

    @staticmethod
    def detect_primary_overlay_conversation(
        original_files: list[str], exported_files: list[str]
    ) -> tuple[str, str]:
        """Best-effort heuristic to pick conversation primary vs overlay.

        Returns (primary_path, overlay_path).
        """

        if len(original_files) != 2 or len(exported_files) != 2:
            return exported_files[0], exported_files[1]

        file1_name = os.path.basename(original_files[0]).lower()
        file2_name = os.path.basename(original_files[1]).lower()

        # Pattern 1: "secondary" is usually selfie/overlay
        if "secondary" in file1_name and "secondary" not in file2_name:
            return exported_files[1], exported_files[0]
        if "secondary" in file2_name and "secondary" not in file1_name:
            return exported_files[0], exported_files[1]

        # Pattern 2: explicit front/back naming
        if "front" in file1_name and "back" in file2_name:
            return exported_files[1], exported_files[0]
        if "back" in file1_name and "front" in file2_name:
            return exported_files[0], exported_files[1]

        # Pattern 3: aspect ratio heuristic
        try:
            with (
                Image.open(exported_files[0]) as img1,
                Image.open(exported_files[1]) as img2,
            ):
                ratio1 = img1.width / img1.height
                ratio2 = img2.width / img2.height

            if abs(ratio1 - ratio2) > 0.2:
                # Assume the more square-ish one is the selfie
                if abs(ratio1 - 1.0) < abs(ratio2 - 1.0):
                    return exported_files[1], exported_files[0]
                return exported_files[0], exported_files[1]
        except Exception:
            pass

        # Pattern 4: alphabetical fallback
        if file1_name < file2_name:
            return exported_files[0], exported_files[1]
        return exported_files[1], exported_files[0]

    def load_conversation_chat_log_by_id(self, chat_log_path: str) -> dict[str, dict]:
        """Load `chat_log.json` and index messages by their `id`."""

        if not os.path.exists(chat_log_path):
            return {}

        try:
            with open(chat_log_path, encoding="utf-8") as file:
                chat_log_data = json.load(file)
        except Exception as exc:
            self.verbose_msg(f"Could not read chat log: {exc}")
            return {}

        messages: list[dict] = []
        if isinstance(chat_log_data, dict) and isinstance(
            chat_log_data.get("messages"), list
        ):
            messages = [m for m in chat_log_data["messages"] if isinstance(m, dict)]
        elif isinstance(chat_log_data, list):
            messages = [m for m in chat_log_data if isinstance(m, dict)]

        by_id: dict[str, dict] = {}
        for message in messages:
            if "id" in message:
                by_id[str(message["id"])] = message

        return by_id

    def export_conversations(self):
        """Export conversation images under `conversations/`.

        - Exports images into `out/conversations/<conversation_id>/`
        - Uses `chat_log.json` timestamps when available
        - Creates composites for paired images when `--composite` is enabled
        """

        conversations_path = os.path.join(self.bereal_path, "conversations")
        if not os.path.isdir(conversations_path):
            self.verbose_msg("No conversations folder found")
            return

        out_path_conversations = os.path.join(self.out_path, "conversations")
        os.makedirs(out_path_conversations, exist_ok=True)

        conversation_folders = [
            folder
            for folder in os.listdir(conversations_path)
            if os.path.isdir(os.path.join(conversations_path, folder))
        ]

        if not conversation_folders:
            self.verbose_msg("No conversation subfolders found")
            return

        total = len(conversation_folders)
        for i, conversation_id in enumerate(sorted(conversation_folders), 1):
            conversation_folder = os.path.join(conversations_path, conversation_id)
            out_conversation_folder = os.path.join(
                out_path_conversations, conversation_id
            )
            os.makedirs(out_conversation_folder, exist_ok=True)

            chat_log_by_id = self.load_conversation_chat_log_by_id(
                os.path.join(conversation_folder, "chat_log.json")
            )

            image_files: list[str] = []
            for entry in os.listdir(conversation_folder):
                entry_path = os.path.join(conversation_folder, entry)
                if not os.path.isfile(entry_path):
                    continue

                ext = os.path.splitext(entry)[1].lower()
                if ext in {".webp", ".jpg", ".jpeg", ".png"}:
                    image_files.append(entry_path)

            image_groups: dict[str, list[str]] = {}
            for image_file in image_files:
                filename = os.path.basename(image_file)
                file_id = filename.split("-")[0] if "-" in filename else "misc"
                image_groups.setdefault(file_id, []).append(image_file)

            for file_id in image_groups:
                image_groups[file_id].sort()

            for file_id, group_files in image_groups.items():
                img_dt_utc: dt
                entry = chat_log_by_id.get(str(file_id))
                if entry and entry.get("createdAt"):
                    try:
                        img_dt_utc = self.get_datetime_from_str(entry["createdAt"])
                    except Exception:
                        img_dt_utc = dt.fromtimestamp(os.path.getmtime(group_files[0]))
                else:
                    img_dt_utc = dt.fromtimestamp(os.path.getmtime(group_files[0]))

                img_dt_local = self.convert_to_local_time(img_dt_utc, None)
                if not (self.time_span[0] <= img_dt_local <= self.time_span[1]):
                    continue

                exported_files: list[str] = []
                for idx, image_file in enumerate(group_files, 1):
                    base_name, ext = os.path.splitext(os.path.basename(image_file))
                    output_filename = f"{img_dt_local.strftime('%Y-%m-%d_%H-%M-%S')}_id{file_id}_{idx}_{base_name}{ext.lower()}"
                    output_path = os.path.join(out_conversation_folder, output_filename)
                    self.export_img(image_file, output_path, img_dt_utc, None)
                    if os.path.exists(output_path):
                        exported_files.append(output_path)

                if self.composite and len(exported_files) == 2:
                    composite_filename = f"{img_dt_local.strftime('%Y-%m-%d_%H-%M-%S')}_id{file_id}_composited.webp"
                    composite_path = os.path.join(
                        out_conversation_folder, composite_filename
                    )
                    primary_img, overlay_img = self.detect_primary_overlay_conversation(
                        group_files, exported_files
                    )
                    self.create_composite_image(
                        primary_img, overlay_img, composite_path, img_dt_utc, None
                    )

            self.print_progress_bar(
                i,
                total,
                prefix="Exporting Conversations",
                suffix=f"- {conversation_id}",
            )


if __name__ == "__main__":
    args = init_parser()
    exporter = BeRealExporter(args)

    if args.memories:
        exporter.verbose_msg("Open memories.json file")
        try:
            with open(
                os.path.join(exporter.bereal_path, "memories.json"), encoding="utf-8"
            ) as memories_file:
                exporter.verbose_msg("Start exporting memories")
                exporter.export_memories(json.load(memories_file))
        except FileNotFoundError:
            print("memories.json file not found.")
        except json.JSONDecodeError:
            print("Error decoding memories.json file.")

    if args.realmojis:
        exporter.verbose_msg("Open realmojis.json file")
        try:
            with open(
                os.path.join(exporter.bereal_path, "realmojis.json"), encoding="utf-8"
            ) as realmojis_file:
                exporter.verbose_msg("Start exporting realmojis")
                exporter.export_realmojis(json.load(realmojis_file))
        except FileNotFoundError:
            print("realmojis.json file not found.")
        except json.JSONDecodeError:
            print("Error decoding realmojis.json file.")

    if args.posts:
        exporter.verbose_msg("Open posts.json file")
        try:
            with open(
                os.path.join(exporter.bereal_path, "posts.json"), encoding="utf-8"
            ) as posts_file:
                exporter.verbose_msg("Start exporting posts")
                exporter.export_posts(json.load(posts_file))
        except FileNotFoundError:
            print("posts.json file not found.")
        except json.JSONDecodeError:
            print("Error decoding posts.json file.")

    if args.conversations:
        exporter.verbose_msg("Start exporting conversations")
        exporter.export_conversations()
