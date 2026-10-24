---
title: 07. Output files and folders
description: How finished files are named, what they contain, where AnimeUp keeps things and what each folder is for, what you can safely delete, and how to move AnimeUp to another Mac.
---

<span class="eyebrow">Step 07 · Output and folders</span>

# 07. Output files and folders

Where your finished episodes end up, what's inside them, and what every other folder in AnimeUp is for.

## Where the result goes

Finished files land in `OUTPUT/`, always as `.mkv`, whatever the source container was. The source in `INPUT/` is never modified: AnimeUp only reads it.

## How output files are named

The output name is the original file name, unchanged, followed by the job's parameters in square brackets:

```text
Episode 01 [upscale 1080p cugan x3 crf18 dd].mkv
```

| Part | Meaning | Possible values |
|---|---|---|
| `upscale` / `supersampling` | What kind of job it was (see below) | `upscale`, `supersampling` |
| `1080p` | Output height actually produced | The **Output height** setting, or lower if AnimeUp had to lower it (4× limit) |
| `cugan` | The model | `animevideov3`, `cugan-denoise` (Real-CUGAN light denoise), `cugan` (Real-CUGAN no-denoise) |
| `x3` | Scale the model ran at, before the final resize | `x2`, `x3`, `x4` |
| `crf18` | x265 quality | `crf14` to `crf24` from the interface |
| `dn` | **Denoise before upscaling** was on | present or absent |
| `dd` | **Deduplicate frames** was on | present or absent |
| `veryslow` etc. | x265 preset, **only if it isn't `slower`** | `medium`, `slow`, `veryslow` |

A few more examples:

```text
Episode 02 [upscale 1440p animevideov3 x4 crf16 dn dd veryslow].mkv
Episode 03 [supersampling 1080p cugan x2 crf18 dd].mkv
```

The original name is kept intact so you can still recognise the episode. The bracket separates two different jobs on the same source, so a 1080p and a 1440p version, or a CUGAN and an animevideov3 version, live side by side instead of overwriting each other.

### Upscale vs supersampling

- **`upscale`**: the output is taller than the source. This is the normal case.
- **`supersampling`**: the output is the same height as the source or smaller. The model enlarges the image and AnimeUp scales it back down, which acts as high-quality anti-aliasing but adds no resolution. AnimeUp refuses this unless **Allow upscales below the minimum** is on (see [03. The interface](03-interface.md)), so you'll only see it if you asked for it.

Files produced by older versions used `upscale` for both cases. AnimeUp still recognises them as done, so it won't redo a file just because the label changed.

### Why `x3` for a 1080p output from 720p?

The model always upscales by a whole number (2, 3 or 4), then AnimeUp resizes to the exact target in the same pass as encoding. It picks the scale that brings that final resize closest to an exact 2:1 reduction, which averages the pixels and smooths away the model's ringing and shimmer. From 720p to 1080p that's x3 (2160 → 1080). The details are in [The models and when to use them](deep-dives/models.md).

## What the output file contains

| Track | What happens to it |
|---|---|
| **Video** | New: HEVC (x265), 10-bit 4:2:0 (`yuv420p10le`), at the output height, square pixels, width from the real aspect ratio. Encoded once, at the CRF and preset you chose, with x265 settings tuned for animation. Colour information is written explicitly (BT.709 for HD sources, BT.601 for SD sources that don't declare it). |
| **Audio** | Every audio track, copied untouched (not re-encoded) |
| **Subtitles** | Every subtitle track copied, ASS styling and positioning included. The only exception is `mov_text` (an MP4 subtitle format MKV can't hold), which is converted to SRT. Picture-based subtitles are copied as they are. |
| **Attachments** | Copied, including the fonts that fansub subtitles depend on |
| **Chapters** | Copied |

The output is 10-bit even from 8-bit sources, which reduces banding in gradients. The video is a single main stream: an embedded cover image in the source isn't carried over as video.

!!! info "Frame rate"
    A variable-frame-rate source is brought onto a constant frame grid during extraction (frames are repeated or dropped, never re-encoded). The plan warns you when this happens.

### While a file is being assembled

During the last minute or so of a job, AnimeUp writes the final file under a temporary name, `<name>.mkv.incomplete`, and renames it to the real name only once it's complete. If anything interrupts the assembly, the half-written file is deleted. You never get a truncated file under a good name.

## `.DEFECTIVE.mkv`: a file that failed its checks

After assembly, AnimeUp checks the finished file:

- it has exactly as many frames as were extracted from the source;
- it has the expected width and height;
- its audio can be read after seeking into the middle.

If any check fails, the file is **defective**. It's renamed `….DEFECTIVE.mkv` instead of keeping the proper name, its job folder in `OUTPUT/JOBS/` is kept for inspection, and the row in Processing shows **needs redoing**.

| What you see | What it means | What to do |
|---|---|---|
| `Episode [upscale … ].DEFECTIVE.mkv` in `OUTPUT/` | The job finished but the result failed a check | Run the file again from Processing; it's redone. Then delete the `.DEFECTIVE` file. |
| `….mkv.incomplete` in `OUTPUT/` while nothing is running | Left over from a hard crash (power cut, kill) during assembly | Delete it; resume the job in Processing |

The `.DEFECTIVE` name is what stops a broken file from passing itself off as good. With the proper name, a later run would see the output "already there" and skip it.

!!! note "Warnings are not defects"
    A job can finish with *warnings*, for example "duration partly estimated: the file was interrupted and resumed". Those are notes: the file keeps its proper name, the warnings are recorded in the job report and shown on the row, and the job folder is cleaned up as usual.

## Where AnimeUp keeps things

AnimeUp keeps things in three places. The first two hold your videos and can be chosen independently, for example the sources on one drive and the finished files on another. The third holds AnimeUp's own data.

| Place | What's in it | Default in the app | Default in the portable folder | To choose another one |
|---|---|---|---|---|
| **Videos to process folder** (`INPUT/`) | Your source episodes | `~/Movies/AnimeUp/INPUT` | `INPUT/` inside the AnimeUp folder | App: **Videos to process folder → Change…** in the sidebar, or from the empty Sources tab. Terminal: `ANIMEUP_INPUT` |
| **Finished videos folder** (`OUTPUT/`) | The finished videos, one log per file in `logs/`, and the jobs in progress or interrupted in `JOBS/` | `~/Movies/AnimeUp/OUTPUT` | `OUTPUT/` inside the AnimeUp folder | App: **Finished videos folder → Change…** in the sidebar. Terminal: `ANIMEUP_OUTPUT` |
| **AnimeUp's own data** | History, settings and calibration in `records/`; caches in `cache/` | `~/Library/Application Support/AnimeUp` | The AnimeUp folder itself | Terminal only: `ANIMEUP_STATO` |

In the app, a folder you choose stays chosen until you change it. Files already in the old folder aren't moved. If a chosen folder isn't available at launch, for example because its drive isn't connected, AnimeUp uses the default one for now and the sidebar says so.

`JOBS/` lives inside the finished videos folder on purpose. A job in progress can take tens of GB, and that space is needed on the disk the finished file is written to. For the same reason the default for **Max disk space per file** is computed from the free space on that disk.

All file and folder names on disk are in English, whatever the interface language.

### The portable folder

```text
AnimeUp/
├── Start AnimeUp.command   ← double-click to open AnimeUp
├── animeup                 ← the same from Terminal: ./animeup ui
├── INPUT/                  ← your episodes go here
├── OUTPUT/                 ← finished files appear here
│   ├── logs/               ← one log per processed file
│   └── JOBS/               ← jobs in progress or interrupted
├── records/                ← history, calibration, settings
├── cache/                  ← source analyses, Compare clips
├── bin/                    ← ffmpeg, ffprobe, the upscalers and their models, uv
├── samples/                ← the sample clip used by calibration
├── src/  ui/  tests/  design/  docs/   ← the program and its documentation
└── .venv  .python  .cache  .streamlit  ← self-contained Python environment (hidden)
```

### The app

```text
~/Movies/AnimeUp/                        ← unless you chose other folders
├── INPUT/
└── OUTPUT/
    ├── logs/
    └── JOBS/

~/Library/Application Support/AnimeUp/
├── records/                             ← history, calibration, settings
├── cache/                               ← source analyses, Compare clips
├── bin/                                 ← ffmpeg, ffprobe, the upscalers and their models
├── logs/app.log                         ← the app's own log
└── .python  .venv  .cache               ← Python and its environment (hidden)
```

The program itself is `AnimeUp.app`, which is never modified.

UPPERCASE folders are yours: you put things in and take things out. Lowercase folders are internal and look after themselves.

### INPUT/

The source episodes. Accepted extensions: `.mkv`, `.mp4`, `.mov`, `.avi`, `.m4v`, `.ts`, `.webm`. Files are read, never modified.

!!! warning "Only files directly inside INPUT"
    AnimeUp lists the files directly inside `INPUT/`. Files inside subfolders of `INPUT/` are **not** picked up. Put episodes at the top level.

### OUTPUT/

The finished files, named as described above. Move, rename or archive them whenever you like. If you move a finished file away, its row in Processing says the output is no longer in `OUTPUT/` instead of quietly redoing it, and asks before putting it back in the queue.

### OUTPUT/logs/

One file per processed file, `<output name>.log`: the full technical log of that file's processing. It's for reading when something went wrong. No estimate uses it, so the files are safe to delete whenever you like.

### OUTPUT/JOBS/

One folder per job that is in progress or interrupted, named `<episode> <date> <fingerprint>`, for example `Episode 01 2026-08-12 77e45fba`. The date is when the job started. The 8-character fingerprint comes from the file's path relative to the folder that contains `INPUT/`, so two episodes with the same name in different places never share a folder.

A job folder contains:

| Item | What it is |
|---|---|
| `frames/` | Every frame of the source, extracted as PNG. This is usually the biggest item. |
| `chunk0003-in/`, `-up/`, `-full/` | The chunk being worked on: its source frames, the upscaled frames, the full sequence with duplicates restored. Deleted as soon as the chunk is encoded. |
| `segments/` | The chunks already encoded, `seg00000000-00001500.mkv` and so on. Kept until the final assembly. |
| `state.json` | What's done so far and the job's signature (used for resuming) |
| `parameters.json` | The parameters the job was started with. **Resume** uses these, not the sidebar. |
| `dedup.json` | The deduplication map for this file |
| `running.lock` | Present only while a process is working on this folder. Contains its process ID. |
| `upscaler.pgid` | Lets AnimeUp kill an orphaned upscaler after a crash |
| `.suspended`, `.paused_seconds` | Pause markers: present while the job is paused, and the total time spent paused |

**When a job finishes successfully, its folder deletes itself.** If the result is defective (`.DEFECTIVE`), the folder stays so you can see what went wrong. If a folder takes up a lot of space, a job is half-finished: resume it, or **Discard** it in Processing, which deletes the folder and frees the space (two-step confirmation; it never touches the source or the finished videos).

`JOBS/` also contains some hidden items that belong to AnimeUp as a whole:

| Hidden item | What it is |
|---|---|
| `.reservations/` | Disk space claimed by running jobs, one small file per process. Cleans itself. |
| `.queue` | Present while a queue is running ("file 2 of 5") |
| `.pause` | Present during a pause between files |
| `.calibration/` | Temporary work of a calibration in progress, here so it measures the same disk the jobs write to. Cleans itself. |

!!! tip "Empty job folders"
    On macOS, Finder sometimes recreates a `.DS_Store` file inside a folder while AnimeUp is deleting it, which can leave an empty job folder behind. An empty folder with nothing but `.DS_Store` is harmless and can be deleted.

### records/

The data AnimeUp learns from and the files that describe your setup. These are worth keeping.

| File | Contents | If you delete it |
|---|---|---|
| `history.jsonl` | One line per finished file: real duration, measured deduplication, warnings, model, output name | Rows stop saying "done" for past files, and estimates lose what they learned from your history |
| `calibration.json` | Calibration: this Mac's measured speed for each model and scale, extraction, encoding, the deduplication scan and the best number of save threads. One entry per chip, so several Macs can share the file. | Estimates fall back to factory values until you calibrate again (about 10 minutes, see [02. Calibration](02-calibration.md)) |
| `settings.json` | Your sidebar settings, including language | Settings go back to factory defaults (English) |
| `launches.jsonl` | One line per queue started: feeds the end-of-queue summary | Past summaries are gone |
| `.last-launch-seen` | Which summary you've already seen | The last summary may pop up again |
| `update-check.json` | When AnimeUp last checked for a new release | The check runs again |
| `queue.log` | The Terminal output of the last queue started from the interface | Nothing: it's a log |
| `interface.log` | The interface's own log | Nothing: it's a log |

Nothing breaks if you delete them. You lose history, calibration and preferences.

### cache/

Things AnimeUp can rebuild on its own:

| Folder | What it is |
|---|---|
| `analysis/` | The saved analysis of each source (the Sources tab). Deleting it means every file is analysed again. |
| `previews/` | The cache for the [Compare](05-compare.md) tab: thumbnails, short animated clips, the index of difficult clips found in each episode (`clips/`), and the test renders, organised by episode and settings. The test renders inside are ordinary MKV files, fine to copy out and show someone. |

**It can be emptied at any time** while nothing is running. The worst that happens is the analyses and the difficult-clip scans are redone, which takes a few minutes per episode.

### bin/

The programs AnimeUp runs, kept inside its own folder so it doesn't depend on anything installed on your Mac:

- `ffmpeg`, `ffprobe`: decoding, encoding, analysis (FFmpeg 9.0.2, the version AnimeUp is tested with);
- `realesrgan-ncnn-vulkan` with `models/`, and `realcugan-ncnn-vulkan` with `models-se/`, `models-pro/`, `models-nose/`: the upscalers and their model files (AnimeUp's catalogue uses only some of them; see [The models](deep-dives/models.md));
- `uv`: the manager for the self-contained Python environment.

If something here is missing or damaged, the sidebar shows **N system dependencies**. `./animeup setup` restores it, and `./animeup doctor` checks the result.

!!! note "An FFmpeg installed with Homebrew doesn't interfere"
    AnimeUp always uses the copy in its own `bin/` first. Installing or updating FFmpeg on your Mac (for example with `brew upgrade`) changes nothing for AnimeUp. A system copy is used only as a fallback when the one in `bin/` is missing, and the sidebar then shows it as a system dependency.

### samples/

`bbb-480p.mkv`: a 20-second clip from *Big Buck Bunny* (© 2008 Blender Foundation, CC BY 3.0), 854×480, used by [calibration](02-calibration.md). It ships with AnimeUp. Don't delete it, or calibration has nothing to measure.

### src/, ui/, tests/, design/, docs/

The program: `src/animeup/` is the engine, `ui/` the interface, `tests/` the regression tests (`./animeup test`), `design/` the visual reference, `docs/` the documentation. Leave them alone.

## What's safe to delete

| Item | Safe? | Consequence |
|---|---|---|
| Finished files in `OUTPUT/` | Yes, they're yours | AnimeUp notices the output is gone and asks before redoing it |
| `….DEFECTIVE.mkv` | Yes | None, it's a defective result |
| Files in `OUTPUT/logs/` | Yes | None |
| A folder in `OUTPUT/JOBS/` | Yes, preferably with **Discard** in Processing | That job's progress is lost; the file starts from scratch next time |
| Everything in `OUTPUT/JOBS/` | Only when no job is running | All interrupted progress lost |
| `cache/` | Yes, when nothing is running | Sources are analysed again; Compare rebuilds its cache (a few minutes per episode) |
| `.log` files in `records/` | Yes | None |
| Data files in `records/` | Yes, but think first | History, calibration and preferences lost (see above) |
| `bin/` | No | AnimeUp can't work until `./animeup setup` |
| `samples/` | No | Calibration can't run |
| `src/`, `ui/`, hidden `.venv` etc. | No | The program breaks (`.venv`, `.python`, `.cache` are rebuilt on the next launch, at the cost of a download) |

!!! danger "Never while a job is running"
    Don't delete anything in `JOBS/` while a job is running. Stop it first, or use **Discard**, which is disabled while the GPU is busy for exactly this reason.

## Moving AnimeUp to another Mac

Everything the portable folder needs lives inside it: Python, its dependencies, FFmpeg, the upscalers and the models. Neither Homebrew nor a system Python is required. To move it:

1. Close AnimeUp (and stop any running job, or let it finish).
2. Copy the **whole** folder, for example onto an external drive, or run AnimeUp straight from that drive.
3. Open it on the other Mac as usual. On the first launch `./animeup` repairs the Python environment if needed.

What carries over:

- **Interrupted jobs resume.** Jobs and analyses are identified by the file's path relative to the folder that contains `INPUT/`, not the full disk path, so a copy elsewhere still finds its extracted frames and encoded segments.
- **History carries over.** `history.jsonl` describes your content (how many repeated frames to expect, how far off past estimates were), so it's valid on any Mac.
- **Calibration doesn't.** `calibration.json` is stored per chip. On a Mac with a different chip, the sidebar's Calibration row says **Never** until you calibrate there. On a Mac with the same chip, the existing measurements are used.

With the app, install it on the other Mac and copy your video folders across. To bring your history, settings and calibration too, copy `records/` from `~/Library/Application Support/AnimeUp` on the old Mac to the same place on the new one, with AnimeUp closed on both.

The other Mac also needs Apple Silicon. If it downloaded the folder from the Internet, see [01. Install and first launch](01-install.md) for the Gatekeeper prompt.

## Choosing the folders from the Terminal

The app has the two folder choices in the sidebar. The portable folder and the command line use environment variables instead:

| Variable | What it sets |
|---|---|
| `ANIMEUP_INPUT` | The videos to process folder |
| `ANIMEUP_OUTPUT` | The finished videos folder, with its `logs/` and `JOBS/` |
| `ANIMEUP_ROOT` | The base folder: the defaults become `<base>/INPUT` and `<base>/OUTPUT`. It's also where AnimeUp looks for a pre-1.6 layout to move (see [Upgrading from 1.5](#upgrading-from-15)). It doesn't move AnimeUp's own data. |
| `ANIMEUP_STATO` | Where AnimeUp's own data goes: `records/`, `cache/`, and also `bin/` and the Python environment. Without it, they stay in the AnimeUp folder. |

```bash
ANIMEUP_INPUT="/Volumes/Sources/Anime" \
ANIMEUP_OUTPUT="/Volumes/Big Disk/AnimeUp OUTPUT" ./animeup ui
```

Things to know before you use them:

- They're advanced options meant for the Terminal. Double-clicking `Start AnimeUp.command` doesn't set them for you.
- `ANIMEUP_INPUT`, `ANIMEUP_OUTPUT` and `ANIMEUP_ROOT` only move your videos. Your settings, calibration and history stay in the AnimeUp folder's `records/`, and FFmpeg, the upscalers and the models are still taken from its `bin/`, so the video folders need nothing but your files.
- `ANIMEUP_STATO` moves everything AnimeUp keeps for itself. A new, empty folder starts with no settings, calibration or history, and the first launch sets up Python and downloads the tools into it again (`./animeup setup`).
- The default for **Max disk space per file** is computed from the free space on the disk of the finished videos folder, where `JOBS/` lives.

For most people, moving the whole AnimeUp folder to the bigger disk is simpler.

## Upgrading from 1.5

Before 1.6, everything lived in one folder: `INPUT/`, `OUTPUT/`, `JOBS/`, `anteprime/` and `registri/`, with Italian file names. On the first launch of 1.6 AnimeUp moves the old layout into the new one by itself:

| Before 1.6 | From 1.6 |
|---|---|
| `registri/` | `records/`, with the files renamed (`esiti.jsonl` → `history.jsonl`, `taratura.json` → `calibration.json`, `impostazioni.json` → `settings.json`, `lavorazione.log` → `queue.log`, and so on) and their keys translated to English |
| `registri/<output name>.log` | `OUTPUT/logs/` |
| `JOBS/` | `OUTPUT/JOBS/`. Interrupted jobs stay resumable. |
| `JOBS/.analisi/` | `cache/analysis/` |
| `anteprime/` | Deleted: it's a cache of Compare clips with Italian file names, and Compare makes them again when you need them |
| `<name>.mkv.inlavorazione` | `<name>.mkv.incomplete` |
| `<name>.PARZIALE.mkv` | `<name>.DEFECTIVE.mkv` |

In the app, the old folder is `~/Movies/AnimeUp`, or the data folder you had chosen in 1.5. That folder stays the base: `INPUT/` and `OUTPUT/` are still the ones inside it until you choose others. `records/` and `cache/` move to `~/Library/Application Support/AnimeUp`.

You don't need to do anything. Apart from the Compare cache, nothing is deleted before it has been written in its new place, and the move is repeatable: if a step fails, for example on a full disk, the old files stay where they were and AnimeUp tries again on the next launch.

## Before you move on

!!! success "Check"
    - [ ] You can read an output name and know which model, scale and CRF made it
    - [ ] You know `.DEFECTIVE.mkv` means "run it again", not "keep it"
    - [ ] You know the three places: the videos to process, the finished videos (with `logs/` and `JOBS/`), and AnimeUp's own data
    - [ ] You know which folders are yours (`INPUT`, `OUTPUT`, `JOBS`) and which look after themselves
    - [ ] You know the data files in `records/` are worth keeping

[Next: Command-line reference →](reference/command-line.md)
