---
title: 07. Output files and folders
description: How finished files are named, what they contain, what each folder in AnimeUp is for, what you can safely delete, and how to move AnimeUp to another Mac.
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

During the last minute or so of a job, AnimeUp writes the final file under a temporary name, `<name>.mkv.inlavorazione` ("in progress"), and renames it to the real name only once it's complete. If anything interrupts the assembly, the half-written file is deleted. You never get a truncated file under a good name.

## `.PARZIALE.mkv`: a file that failed its checks

After assembly, AnimeUp checks the finished file:

- it has exactly as many frames as were extracted from the source;
- it has the expected width and height;
- its audio can be read after seeking into the middle.

If any check fails, the file is **defective**. It's renamed `….PARZIALE.mkv` ("partial") instead of keeping the proper name, its job folder in `JOBS/` is kept for inspection, and the row in Processing shows **needs redoing**.

| What you see | What it means | What to do |
|---|---|---|
| `Episode [upscale … ].PARZIALE.mkv` in `OUTPUT/` | The job finished but the result failed a check | Run the file again from Processing; it's redone. Then delete the `.PARZIALE` file. |
| `….mkv.inlavorazione` in `OUTPUT/` while nothing is running | Left over from a hard crash (power cut, kill) during assembly | Delete it; resume the job in Processing |

The `.PARZIALE` name is what stops a broken file from passing itself off as good. With the proper name, a later run would see the output "already there" and skip it.

!!! note "Warnings are not defects"
    A job can finish with *warnings*, for example "duration partly estimated: the file was interrupted and resumed". Those are notes: the file keeps its proper name, the warnings are recorded in the job report and shown on the row, and the job folder is cleaned up as usual.

## The folders

```text
AnimeUp/
├── Avvia AnimeUp.command   ← double-click to open AnimeUp
├── animeup                 ← the same from Terminal: ./animeup ui
├── INPUT/                  ← your episodes go here
├── OUTPUT/                 ← finished files appear here
├── JOBS/                   ← jobs in progress or interrupted
├── anteprime/              ← Compare cache (previews)
├── registri/               ← job reports, calibration, settings, logs
├── bin/                    ← ffmpeg, ffprobe, the upscalers and their models, uv
├── campioni/               ← the sample clip used by calibration
├── src/  ui/  tests/  design/  docs/   ← the program and its documentation
└── .venv  .python  .cache  .streamlit  ← self-contained Python environment (hidden)
```

UPPERCASE folders are yours: you put things in and take things out. Lowercase folders are internal and look after themselves. (`anteprime` and `registri` are Italian for "previews" and "records". `campioni` means "samples".)

### INPUT/

The source episodes. Accepted extensions: `.mkv`, `.mp4`, `.mov`, `.avi`, `.m4v`, `.ts`, `.webm`. Files are read, never modified.

!!! warning "Only files directly inside INPUT"
    AnimeUp lists the files directly inside `INPUT/`. Files inside subfolders of `INPUT/` are **not** picked up. Put episodes at the top level.

### OUTPUT/

The finished files, named as described above. Move, rename or archive them whenever you like. If you move a finished file away, its row in Processing says the output is no longer in `OUTPUT/` instead of quietly redoing it, and asks before putting it back in the queue.

### JOBS/

One folder per job that is in progress or interrupted, named `<episode> <date> <fingerprint>`, for example `Episode 01 2026-08-12 77e45fba`. The date is when the job started. The 8-character fingerprint comes from the file's path inside the AnimeUp folder, so two episodes with the same name in different places never share a folder.

A job folder contains:

| Item | What it is |
|---|---|
| `frames/` | Every frame of the source, extracted as PNG. This is usually the biggest item. |
| `chunk0003-in/`, `-up/`, `-full/` | The chunk being worked on: its source frames, the upscaled frames, the full sequence with duplicates restored. Deleted as soon as the chunk is encoded. |
| `segments/` | The chunks already encoded, `seg00000000-00001500.mkv` and so on. Kept until the final assembly. |
| `state.json` | What's done so far and the job's signature (used for resuming) |
| `parametri.json` | The parameters the job was started with. **Resume** uses these, not the sidebar. |
| `dedup.json` | The deduplication map for this file |
| `in-corso.lock` | Present only while a process is working on this folder. Contains its process ID. |
| `upscaler.pgid` | Lets AnimeUp kill an orphaned upscaler after a crash |
| `.sospeso`, `.pause_totali` | Pause markers: present while the job is paused, and the total time spent paused |

**When a job finishes successfully, its folder deletes itself.** If the result is defective (`.PARZIALE`), the folder stays so you can see what went wrong. If a folder takes up a lot of space, a job is half-finished: resume it, or **Discard** it in Processing, which deletes the folder and frees the space (two-step confirmation; it never touches the source or `OUTPUT/`).

`JOBS/` also contains some hidden items that belong to AnimeUp as a whole:

| Hidden item | What it is |
|---|---|
| `.analisi/` | The saved analysis of each source (the Sources tab). Deleting it means every file is analysed again. |
| `.prenotazioni/` | Disk space claimed by running jobs, one small file per process. Cleans itself. |
| `.catena` | Present while a queue is running ("file 2 of 5") |
| `.pausa` | Present during a pause between files |

!!! tip "Empty job folders"
    On macOS, Finder sometimes recreates a `.DS_Store` file inside a folder while AnimeUp is deleting it, which can leave an empty job folder behind. An empty folder with nothing but `.DS_Store` is harmless and can be deleted.

### anteprime/ (previews)

The cache for the [Compare](05-compare.md) tab: thumbnails, short animated clips, the index of difficult clips found in each episode (`.spezzoni/`), and the test renders, organised by episode and settings. **It can be emptied at any time.** The worst that happens is the difficult-clip scan for an episode is redone, which takes a few minutes. The test renders inside are ordinary MKV files, fine to copy out and show someone.

### registri/ (records)

Two different kinds of file live here, and the difference matters.

**Logs, safe to delete whenever you like:**

| File | Contents |
|---|---|
| `<output name>.log` | One per job: the full technical log of that file's processing |
| `lavorazione.log` | The output of the processing commands started from the interface |
| other `.log` files | Diagnostic logs |

**Data, which AnimeUp learns from:**

| File | Contents | If you delete it |
|---|---|---|
| `esiti.jsonl` | The job report for every finished file: real duration, measured deduplication, warnings, model, output name | Rows stop saying "done" for past files, and estimates lose what they learned from your history |
| `taratura.json` | Calibration: this Mac's measured speed for each model and scale, extraction, encoding, the deduplication scan and the best number of save threads. One entry per chip, so several Macs can share the file. | Estimates fall back to factory values until you calibrate again (about 10 minutes, see [02. Calibration](02-calibration.md)) |
| `impostazioni.json` | Your sidebar settings, including language | Settings go back to factory defaults (English) |
| `lanci.jsonl` | One record per queue started: feeds the end-of-queue summary | Past summaries are gone |
| `.ultimo-lancio-visto` | Which summary you've already seen | The last summary may pop up again |

Nothing breaks if you delete them. You lose history, calibration and preferences.

### bin/

The programs AnimeUp runs, kept inside the folder so it doesn't depend on anything installed on your Mac:

- `ffmpeg`, `ffprobe`: decoding, encoding, analysis;
- `realesrgan-ncnn-vulkan` with `models/`, and `realcugan-ncnn-vulkan` with `models-se/`, `models-pro/`, `models-nose/`: the upscalers and their model files (AnimeUp's catalogue uses only some of them; see [The models](deep-dives/models.md));
- `uv`: the manager for the self-contained Python environment.

If something here is missing or damaged, the sidebar shows **N system dependencies**. `./animeup setup` restores it, and `./animeup doctor` checks the result.

### campioni/ (samples)

`bbb-480p.mkv`: a 20-second clip from *Big Buck Bunny* (© 2008 Blender Foundation, CC BY 3.0), 854×480, used by [calibration](02-calibration.md). It ships with AnimeUp. Don't delete it, or calibration has nothing to measure.

### src/, ui/, tests/, design/, docs/

The program: `src/animeup/` is the engine, `ui/` the interface, `tests/` the regression tests (`./animeup test`), `design/` the visual reference, `docs/` the documentation. Leave them alone.

## What's safe to delete

| Item | Safe? | Consequence |
|---|---|---|
| Files in `OUTPUT/` | Yes, they're yours | AnimeUp notices the output is gone and asks before redoing it |
| `….PARZIALE.mkv` | Yes | None, it's a defective result |
| A folder in `JOBS/` | Yes, preferably with **Discard** in Processing | That job's progress is lost; the file starts from scratch next time |
| Everything in `JOBS/` | Only when no job is running | All interrupted progress lost; sources are analysed again |
| `anteprime/` | Yes, any time | Compare rebuilds its cache (a few minutes per episode) |
| `.log` files in `registri/` | Yes | None |
| Data files in `registri/` | Yes, but think first | History, calibration and preferences lost (see above) |
| `bin/` | No | AnimeUp can't work until `./animeup setup` |
| `campioni/` | No | Calibration can't run |
| `src/`, `ui/`, hidden `.venv` etc. | No | The program breaks (`.venv`, `.python`, `.cache` are rebuilt on the next launch, at the cost of a download) |

!!! danger "Never while a job is running"
    Don't delete anything in `JOBS/` while a job is running. Stop it first, or use **Discard**, which is disabled while the GPU is busy for exactly this reason.

## Moving AnimeUp to another Mac

Everything AnimeUp needs lives inside its folder: Python, its dependencies, FFmpeg, the upscalers and the models. Neither Homebrew nor a system Python is required. To move it:

1. Close AnimeUp (and stop any running job, or let it finish).
2. Copy the **whole** folder, for example onto an external drive, or run AnimeUp straight from that drive.
3. Open it on the other Mac as usual. On the first launch `./animeup` repairs the Python environment if needed.

What carries over:

- **Interrupted jobs resume.** Jobs and analyses are identified by the file's path *inside* the AnimeUp folder, not the full disk path, so a copy elsewhere still finds its extracted frames and encoded segments.
- **History carries over.** `esiti.jsonl` describes your content (how many repeated frames to expect, how far off past estimates were), so it's valid on any Mac.
- **Calibration doesn't.** `taratura.json` is stored per chip. On a Mac with a different chip, the sidebar's Calibration row says **Never** until you calibrate there. On a Mac with the same chip, the existing measurements are used.

The other Mac also needs Apple Silicon. If it downloaded the folder from the Internet, see [01. Install and first launch](01-install.md) for the Gatekeeper prompt.

## Keeping data somewhere else: `ANIMEUP_ROOT`

AnimeUp recognises one environment variable, `ANIMEUP_ROOT`. If set, it points AnimeUp at a different folder for your data: `INPUT/`, `OUTPUT/`, `JOBS/`, `anteprime/` and `registri/`. The program itself, and the tools and models in `bin/`, stay where they are.

```bash
ANIMEUP_ROOT="/Volumes/Big Disk/AnimeUp data" ./animeup ui
```

Things to know before you use it:

- It's an advanced option meant for the Terminal. Double-clicking `Avvia AnimeUp.command` doesn't set it for you.
- FFmpeg, the upscalers and the models are always taken from the AnimeUp folder's own `bin/`, so the data folder needs nothing but your files.
- Your settings, calibration and history are in the new folder's `registri/`, so they start empty.
- The **Max disk space per file** cap is computed from the free space on the disk that holds this folder.

For most people, moving the whole AnimeUp folder to the bigger disk is simpler.

## Before you move on

!!! success "Check"
    - [ ] You can read an output name and know which model, scale and CRF made it
    - [ ] You know `.PARZIALE.mkv` means "run it again", not "keep it"
    - [ ] You know which folders are yours (`INPUT`, `OUTPUT`, `JOBS`) and which look after themselves
    - [ ] You know the data files in `registri/` are worth keeping

[Next: Command-line reference →](reference/command-line.md)
