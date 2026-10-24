# AnimeUp

**Local, offline anime upscaler for Apple Silicon Macs.**
AnimeUp batch-upscales anime episodes to 1080p and beyond with
[Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) and
[Real-CUGAN](https://github.com/bilibili/ailab/tree/main/Real-CUGAN)
(ncnn-vulkan builds, running on the Mac GPU through Metal). It comes with a
browser UI for analysing your sources, comparing models side by side on
difficult clips, and running long, resumable jobs.

Everything lives in one folder: Python, dependencies, binaries and models.
No Homebrew and no system Python are needed. Copy the folder to another Mac
and it works the same way there.

> **Language note:** the user interface and the in-depth docs
> ([LEGGIMI.md](LEGGIMI.md), [TARATURE.md](TARATURE.md)) are currently in
> Italian. An English localisation is planned.

---

## Features

- **Never degrades the source before the model sees it.** Frames are
  extracted at full quality, and the files in `INPUT/` are only ever read.
- **Proper source analysis.** Resolution, frame rate, interlacing and telecine,
  truncated files and odd formats are detected before a job starts, so they
  don't cause a crash halfway through.
- **Model comparison on real footage.** AnimeUp finds difficult 10-second
  clips in your episode (dark, bright, static, fast motion) and renders them
  with each model. You can then compare 1:1 crops and pick by eye.
- **Model recommendation by source resolution.** Below ~380p Real-ESRGAN
  animevideov3 wins. Above ~560p Real-CUGAN no-denoise wins. In between,
  the UI tells you what to check.
- **Deduplication.** Anime is often animated "on twos" or "on threes".
  Repeated frames are upscaled only once, which measured nearly 2× faster.
- **Chunked, resumable jobs.** Work is saved one chunk at a time. A crash,
  a closed lid or a `kill` loses at most the current chunk. **Resume** always
  reuses the original parameters.
- **Faithful output.** HEVC 10-bit (x265, CRF 18 `slower` by default) with
  **all original tracks remuxed**: audio, subtitles, chapters and attachments,
  fansub fonts included.
- **Honest time estimates.** Estimates are calibrated on *your* Mac
  (`./animeup taratura`) and include the encoding passes, not just the
  upscale.

## Requirements

- A Mac with **Apple Silicon** (M1 or later)
- Developed and tested on macOS 26 (Tahoe)
- An internet connection **on the first launch only**. AnimeUp downloads a
  private Python runtime and FFmpeg into its own folder, then works offline.
- Disk space: upscaling extracts frames to disk, and a single episode can
  temporarily take tens of GB. The UI shows the space it needs and lets you
  set a cap.

## Installation

### Option A: release zip (recommended)

1. Download `AnimeUp-<version>-macos-arm64.zip` from the
   [latest release](https://github.com/Interstellar0verdrive/AnimeUp/releases/latest)
   and unzip it wherever you like. An external drive works fine.
2. Double-click **`Avvia AnimeUp.command`** ("Launch AnimeUp").

   macOS blocks it the first time because the script isn't signed by an
   identified developer. Open **System Settings → Privacy & Security**,
   scroll down and click **Open Anyway**. Alternatively, run this once in
   Terminal on the unzipped folder:

   ```bash
   xattr -dr com.apple.quarantine ~/Downloads/AnimeUp
   ```

3. A Terminal window opens. On the first launch AnimeUp:
   - removes the macOS quarantine flag from **its own folder** only, so the
     bundled tools aren't blocked one by one;
   - downloads a private Python runtime and the dependencies (once);
   - asks for confirmation, then downloads a static **FFmpeg** build
     (see [why FFmpeg isn't bundled](#why-ffmpeg-isnt-bundled)).
4. The UI opens in your browser at <http://localhost:8899>. Keep the
   Terminal window open while you use it: that window is the server.

### Option B: from source

```bash
git clone https://github.com/Interstellar0verdrive/AnimeUp.git
cd AnimeUp
./animeup setup     # downloads FFmpeg, Real-ESRGAN, Real-CUGAN and the models into bin/
./animeup ui
```

The launcher also fetches [uv](https://github.com/astral-sh/uv), the tool
that sets up the private Python environment, if you don't have it. Every
third-party download comes from a pinned official release and is verified
with SHA256. The one exception is FFmpeg, which comes from a rolling
snapshot and is checked for the encoders and filters AnimeUp needs.

## How it works

1. **Copy** your episodes (`.mkv`, `.mp4`, …) into `INPUT/`.
2. **Sources**: check the analysis of each file (resolution, frame rate,
   warnings). Click a row to expand it.
3. **Compare** (recommended for the first episode of a series): let AnimeUp
   find difficult clips, render them with the candidate models and compare
   the results.
4. **Processing**: tick the files, confirm the suggested model and start the
   job. The GPU runs one job at a time. Progress, fps and the remaining time
   appear on each file's row.
5. The finished files appear in `OUTPUT/` under their original name plus the
   parameters, for example
   `Episode 01 [upscale 1080p cugan x3 crf18 dd].mkv`. A report sums up the
   whole queue at the end.
6. **To quit**, click **Chiudi AnimeUp** ("Close AnimeUp") at the bottom of
   the sidebar. Running jobs keep going even if you close the browser or
   the Terminal. You'll find them again on the next launch.

<!-- Screenshots will be added with the English UI. -->

### Folders

| Folder | What it's for |
|---|---|
| `INPUT/` | Your source episodes. Never modified. |
| `OUTPUT/` | Finished files. |
| `LAVORAZIONI/` | Jobs in progress or interrupted ("work"), one subfolder per episode. A subfolder deletes itself when its job finishes cleanly. |
| `anteprime/` | Cache for the Compare tab ("previews"). Safe to delete at any time. |
| `registri/` | Logs, plus job history, calibration and settings ("records"). |
| `bin/` | FFmpeg, the ncnn upscalers, the models and uv. |

### Command line

```bash
./animeup ui              # web UI (port 8899; --porta N to change it)
./animeup analyze FILE    # analyse a source
./animeup plan FILE       # show what would be done, without doing it
./animeup run FILE        # run a job from the terminal (same pipeline as the UI)
./animeup taratura        # calibrate time estimates on this Mac (~10 min)
./animeup doctor          # check that the folder is self-contained
./animeup setup           # (re)download missing binaries and models
./animeup test            # regression tests
```

## Why FFmpeg isn't bundled

The static FFmpeg build AnimeUp uses is compiled with x264 and x265, which
makes it **GPLv3**. Redistributing it would mean shipping its complete
corresponding source code as well. AnimeUp therefore downloads it on first
launch from [Martin Riedl's macOS builds](https://ffmpeg.martin-riedl.de),
straight into `bin/`. AnimeUp only runs `ffmpeg`/`ffprobe` as separate
programs and doesn't link to them, so its own code stays under the MIT
licence.

The Real-ESRGAN and Real-CUGAN binaries, their models and uv are under
permissive licences. They are included in the release zip, with their
licence texts in [`LICENSES/`](LICENSES).

## License

AnimeUp is released under the [MIT License](LICENSE).
Third-party components keep their own licences (see below).

## Credits & third-party licenses

AnimeUp is a front end and pipeline built around the work of others. Many
thanks to all of them.

| Component | Used for | License |
|---|---|---|
| [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) by Xintao Wang et al. | `realesr-animevideov3` and `realesrgan-x4plus(-anime)` models | BSD-3-Clause ([text](LICENSES/Real-ESRGAN.txt)) |
| [Real-ESRGAN-ncnn-vulkan](https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan) | Real-ESRGAN inference binary (release [v0.2.5.0](https://github.com/xinntao/Real-ESRGAN/releases/tag/v0.2.5.0)) | MIT ([text](LICENSES/Real-ESRGAN-ncnn-vulkan.txt)) |
| [Real-CUGAN](https://github.com/bilibili/ailab/tree/main/Real-CUGAN) by bilibili AI Lab | Real-CUGAN models (`models-se`, `models-pro`, `models-nose`) | MIT ([text](LICENSES/Real-CUGAN.txt)) |
| [realcugan-ncnn-vulkan](https://github.com/nihui/realcugan-ncnn-vulkan) by nihui | Real-CUGAN inference binary (release [20220728](https://github.com/nihui/realcugan-ncnn-vulkan/releases/tag/20220728)) | MIT ([text](LICENSES/realcugan-ncnn-vulkan.txt)) |
| [ncnn](https://github.com/Tencent/ncnn) by Tencent | Neural network inference framework inside both binaries | BSD-3-Clause ([text](LICENSES/ncnn.txt)) |
| [MoltenVK](https://github.com/KhronosGroup/MoltenVK) | Vulkan-on-Metal layer linked into both binaries | Apache-2.0 ([text](LICENSES/MoltenVK.txt)) |
| [FFmpeg](https://ffmpeg.org), static macOS builds by [Martin Riedl](https://ffmpeg.martin-riedl.de) | Decoding, analysis, encoding (x265), remuxing. **Downloaded on first launch, not distributed.** | GPLv3 for this build |
| [uv](https://github.com/astral-sh/uv) by Astral | Self-contained Python runtime and dependencies | MIT / Apache-2.0 ([MIT](LICENSES/uv-MIT.txt), [Apache](LICENSES/uv-APACHE.txt)) |
| [Streamlit](https://github.com/streamlit/streamlit) | Web UI | Apache-2.0 |
| [Typer](https://github.com/fastapi/typer) | Command-line interface | MIT |
| [Rich](https://github.com/Textualize/rich) | Terminal output | MIT |
| [Pillow](https://github.com/python-pillow/Pillow) | Image handling | MIT-CMU |
| [Inter](https://github.com/rsms/inter) by Rasmus Andersson | UI typeface | SIL OFL 1.1 ([text](LICENSES/Inter-OFL.txt)) |
| [JetBrains Mono](https://github.com/JetBrains/JetBrainsMono) | UI monospace typeface | SIL OFL 1.1 ([text](LICENSES/JetBrainsMono-OFL.txt)) |
| [Big Buck Bunny](https://peach.blender.org) © 2008 Blender Foundation | 20-second sample clip in `campioni/`, used for calibration | CC BY 3.0 |

Python dependencies are installed by uv from PyPI on first launch and are
not part of this repository.
