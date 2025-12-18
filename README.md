# BeReal Export Manager

> [!IMPORTANT] 
>This python script doesn't export photos and realmojis from the social media platform BeReal directly for that, you have to make a request to the BeReal. See the [how to guide further down](#request-to-bereal-your-data).

This python script processes the data from the BeReal export and exports the images and videos with comprehensive metadata, including:
- **Date and time** when the photo/video was taken (in the correct timezone)
- **GPS location** data (if available)
- **Multiple date fields** for compatibility with various photo management apps

All exported files (images and videos) are automatically enriched with this metadata using ExifTool so you can move your old BeReals to Apple Photos, Google Photos, [Immich](https://immich.app/), and others. 

> [!TIP]
> You can also save your BeReals as a BeReal-style composite images using the `--composite` flag.

> [!NOTE]
> Shout-out to [berealgdprviewer](https://berealgdprviewer.eu/), an open-source, privacy-focused tool for exploring and analyzing BeReal's GDPR-compliant data exports. If you're looking for a tool to quickly view all your BeReal data and statistics, this is the tool for you. Repo: [casungo/bereal-gdpr-explorer-zip](https://github.com/casungo/bereal-gdpr-explorer-zip)

## Installation

1. Clone the repository:
    ```sh
    git clone https://github.com/TeenBiscuits/BeReal-Export-Manager
    cd BeReal-Export-Manager
    ```

2. Install the `uv` package and project manager if you haven't already:
    ```sh
    # macOS/Linux
    curl -LsSf https://astral.sh/uv/install.sh | sh
    
    # Windows
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    ```
    _See the [uv docs for more information](https://docs.astral.sh/uv/)._

3. Create a virtual environment and install dependencies:
    ```sh
    uv venv
    source .venv/bin/activate # Or on Windows: .venv\Scripts\activate
    uv pip install -r requirements.txt
    ```

4. Ensure you have `exiftool` installed on your system and set it up as a `PATH` variable. You can download it [here](https://exiftool.org/) or:
    ```sh
    # On macOS
    brew install exiftool
    # On Ubuntu/Debian
    sudo apt install exiftool
    ```

## Features

### Timezone-aware timestamps

BeReal exports store timestamps in UTC (`...Z`). This script converts them to local time using the GPS location when available, and otherwise falls back to `--fallback-timezone` (default `Europe/Madrid`). Filtering via `--timespan` / `--year` is also done in this converted local time.

### Composite images (optional)

If you want BeReal-style merged images (selfie overlaid on the main photo), enable `--composite`.

### Conversation images (optional)

Some BeReal exports include a `conversations/` folder (others don’t). If it’s present, the script will export those images too. If `chat_log.json` is present, its timestamps are used; otherwise file modification time is used. If the folder is missing, conversations are automatically skipped.

### Performance

Exports can run in parallel via `--max-workers`.

### Metadata Support

The script automatically embeds metadata into all exported files:

#### Images (`.webp`, `.jpg`, `.jpeg`, `.png`, `.heic`, `.tif`, `.tiff`)
- `DateTimeOriginal` - When the photo was taken
- `CreateDate` - File creation date
- `ModifyDate` - Last modification date
- `GPSLatitude` / `GPSLongitude` - Location coordinates (when available)

#### Videos (`.mp4`, `.mov`, `.avi`, `.mkv`, `.m4v`, `.hevc`, `.webm`)
- `CreationDate` - When the video was taken
- `CreateDate` - File creation date
- `ModifyDate` - Last modification date
- `GPSLatitude` / `GPSLongitude` - Location coordinates (when available)

This ensures your exported BeReal memories are properly sorted and organized in photo management apps like Apple Photos, Google Photos, and others.

## Request to BeReal your data.

To request your data from BeReal, use the in-app help section to submit a GDPR request for a copy of your info, and BeReal will send a download link to your messages, containing your photos (in WebP format) and profile data in JSON files. You can find this process under **Profile > Settings > Help & Support > Other > Contact Us**, then request your data, they will replay shortly after with two links:

- The Analytics Data (.json.gz)
- The Media Archive (.zip)


## Usage

> [!WARNING]
> Before runing the script move the Media Archive Zip to the root of this project and extract it.

Make sure your virtual environment is activated, then run the script within the BeReal export folder:
```sh
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
python bereal_exporter.py [OPTIONS]
```

> [!NOTE]  
> RealMojis are optional (`--realmojis`). My export had incomplete RealMoji metadata, so it is disabled by default.

> [!TIP]
> If you have a _good computer_ use the script with `--max-workers 8` or more, for a better performance.

## Options

- `-v, --verbose`: Explain what is being done.
- `-t, --timespan`: Exports the given timespan. 
  - Valid format: `DD.MM.YYYY-DD.MM.YYYY`.
  - Wildcards can be used: `DD.MM.YYYY-*`.
- `--exiftool-path`: Set the path to the ExifTool executable (needed if it isn't on the $PATH)
- `-y, --year`: Exports the given year.
- `-p, --out-path`: Set a custom output path (default is `./out`).
- `--bereal-path`: Set a custom BeReal path (default `./`)
- `--fallback-timezone`: Fallback timezone name (default `Europe/Madrid`).
- `--no-gps-timezone`: Don't determine timezone from GPS; always use `--fallback-timezone`.
- `--max-workers`: Maximum number of parallel workers (default `4`). Use `--max-workers 1` to disable parallelism.
- `--composite`: Create BeReal-style composite images (`_composited.webp`).
- `--no-memories`: Don't export the memories.
- `--no-posts`: Don't export the posts.
- `--realmojis`: Export realmojis (optional; disabled by default).
- `--no-conversations`: Don't export conversation images.

## Examples

1. Export data for the year 2022:
    ```sh
    python bereal_exporter.py --year 2022
    ```

2. Export data for a specific timespan:
    ```sh
    python bereal_exporter.py --timespan '04.01.2022-31.12.2022'
    ```

3. Export data to a custom output path:
    ```sh
    python bereal_exporter.py --out-path /path/to/output
    ```

4. Specify the BeReal export folder:
    ```sh
    python bereal_exporter.py --bereal-path /path/to/export
    ```

5. Use portable installed exiftool application:
    ```sh
    python bereal_exporter.py --exiftool-path /path/to/exiftool.exe
    ```

6. Export memories only:
    ```sh
    python bereal_exporter.py --no-posts
    ```

7. Export posts only:
    > [!TIP] 
    > In my experience, the posts folder contained all my bereals and was redundant with the memories folder, so this would be the most useful command for me, but check how your export was done.
    ```sh
    python bereal_exporter.py --no-memories
    ```

8. Create BeReal-style composite images:
    ```sh
    python bereal_exporter.py --composite
    ```

9. Export faster with more workers:
    ```sh
    python bereal_exporter.py --max-workers 8
    ```

10. Force a specific fallback timezone (don’t use GPS):
    ```sh
    python bereal_exporter.py --no-gps-timezone --fallback-timezone Europe/Madrid
    ```

11. Export conversations only:
    ```sh
    python bereal_exporter.py --no-memories --no-posts
    ```

## Output

The script creates an `out` directory (or custom path specified with `-p`) containing:
- `memories/` - Front and back camera images from your BeReal memories, plus BTS (behind-the-scenes) videos
- `posts/` - Primary and secondary camera images from your BeReal posts, plus BTS videos
- `realmojis/` - Your RealMoji reactions (only when `--realmojis` is enabled)
- `conversations/` - Conversation images (when present in the export)

All files are named with the format: `YYYY-MM-DD_HH-MM-SS_[type].[ext]` and include embedded metadata for proper date/location sorting in photo apps. If you enable `--composite`, you’ll also get `*_composited.webp` images (for posts/memories, and for conversation image pairs).

## Known issues and limitations

By default, BeReals are saved as **two separate photos**, one from the front camera and one from the rear camera. Both photos share the same metadata and are at their maximum resolution. If you prefer to also save a merged image, run with `--composite` to generate `*_composited.webp` files.

Some BeReal exports do **not** include `conversations/` data. In that case, conversation export is skipped automatically. 

RealMoji data can be incomplete/missing metadata depending on your export. For that reason RealMojis are disabled by default; enable them with `--realmojis` if your export supports it.

The **reposts** you made are **not included** when you request your data, since they were not your posts, they were the posts of another person who tagged you, so it is in their account not yours and therefore is their property not yours, so the GDPR article does not apply.

## License

> [!NOTE]
> Timezone conversion, composite image generation, and parallel export are inspired by [SoPat712/BeReal-Export-Manager](https://github.com/SoPat712/BeReal-Export-Manager) shout-out for his amazing work.

This project is licensed under the MIT License. See the [LICENSE](./LICENSE.md) file for more details.
