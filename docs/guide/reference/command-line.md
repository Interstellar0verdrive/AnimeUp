---
title: Command-line reference
description: Every ./animeup command and option, with defaults, examples and exit codes.
---

<span class="eyebrow">Reference · Command line</span>

# Command-line reference

Everything the interface does can also be done from Terminal with `./animeup`, plus a few maintenance commands the interface doesn't have.

## Basics

Run the commands from the AnimeUp folder:

```bash
cd /path/to/AnimeUp
./animeup --help            # list of commands
./animeup run --help        # options of one command
```

`./animeup` with no arguments shows the list of commands. The launcher sets up the private Python environment on the first run (see [01. Install](../01-install.md)) and then hands over to the command.

| Command | What it does |
|---|---|
| [`ui`](#ui) | Opens the interface in the browser |
| [`analyze`](#analyze) | Analyses sources and prints the report, without changing anything |
| [`plan`](#plan) | Shows what a job would do to each file, without running it |
| [`run`](#run) | Runs the full job, the same pipeline as the interface |
| [`taratura`](#taratura) | Calibrates the time estimates on this Mac |
| [`doctor`](#doctor) | Checks that the folder is self-contained |
| [`setup`](#setup) | Downloads missing binaries and models into `bin/` |
| [`test`](#test) | Runs the regression tests |
| [`version`](#version) | Prints the version |

!!! note "Italian option names"
    AnimeUp was written in Italian, and some option names still are: `--altezza` (height), `--scala` (scale), `--forza` (force), `--disco` (disk), `--modello` (model), `--si` (yes), `--porta` (port), `--pausa` (pause). The help texts are in the language chosen in the interface.

!!! info "Usage line"
    `--help` prints `Usage: python -m animeup.cli …`. That's how the launcher calls the program internally: you always type `./animeup`.

## Choosing files

`analyze`, `plan` and `run` take any number of files or folders. With none, they use the `INPUT/` folder.

- A folder contributes the video files directly inside it (`.mkv`, `.mp4`, `.mov`, `.avi`, `.m4v`, `.ts`, `.webm`), in alphabetical order. Subfolders aren't searched.
- A path that doesn't exist is skipped with `Skipped (doesn't exist): …`.
- The same file named twice (APFS is case-insensitive, so `ep01.mkv` and `EP01.mkv` are one file) is only processed once.

```bash
./animeup plan                          # everything in INPUT/
./animeup plan "INPUT/Episode 01.mkv"   # one file (quote names with spaces)
./animeup run INPUT/Season2 ~/Videos/special.mkv
```

## ui

Opens the interface. This is what **Avvia AnimeUp.command** runs.

```bash
./animeup ui
./animeup ui --porta 8900
```

| Option | What it does | Default |
|---|---|---|
| `--porta <int>` | Local port the interface listens on. | `8899` |

It prints `Interface at http://localhost:8899 — Ctrl+C to stop it.` and opens the browser. Press **Ctrl+C** in that Terminal window to stop the interface; running jobs carry on.

If the port is already in use, it doesn't start a second copy. It explains that another interface is open (and that an old session keeps the code from when it was started), prints the command to close it, `lsof -ti :8899 | xargs kill`, and suggests `./animeup ui --porta 8900` as an alternative. Exit code 1.

## analyze

Analyses sources and prints a report: geometry, frame rate and timing, fields (progressive, interlaced, telecine), colour tags, tracks, and the warnings worth knowing. It doesn't change anything. This is the same analysis as the [Sources tab](../04-sources.md).

```bash
./animeup analyze
./animeup analyze --duplicati "INPUT/Episode 01.mkv"
```

| Option | What it does | Default |
|---|---|---|
| `--duplicati` / `--no-duplicati` | Also measure identical frames, and report how much of the file is animated on ones, twos or threes. Costs a full decode of the file. | `--no-duplicati` |
| `--veloce` | Quick mode: skip the fields and geometry checks, timing only. | off |

A file that can't be read is reported as `… can't be analysed — …` and the others carry on.

## plan

Shows what a job would do to each file, without running anything: source, model (and whether it's the recommended one), the pipeline and downscale ratio, output size, restoration, deduplication, encoding, how many chunks and the peak disk use, the estimated time and the output file name. With several files it ends with the estimated total.

```bash
./animeup plan
./animeup plan --altezza 1440 -m cugan "INPUT/Episode 01.mkv"
```

`plan` takes the same job options as `run`, so it shows exactly what `run` would do with them:

| Option | What it does | Default |
|---|---|---|
| `--altezza <int>` | Final height in pixels. The width follows the real aspect ratio, with square pixels. At least 64. | `1080` |
| `--crf <int>` | x265 quality: lower is better and bigger. 0 to 51. | `18` |
| `--preset <str>` | x265 preset: `medium`, `slow`, `slower` or `veryslow`. Slower makes a smaller file at the same quality; it affects encoding time, not the upscale. | `slower` |
| `-m`, `--modello <str>` | Model: `animevideov3` (Real-ESRGAN animevideov3), `cugan-denoise` (Real-CUGAN light denoise) or `cugan` (Real-CUGAN no-denoise). Empty means the one recommended for the file's resolution. | recommended |
| `--scala <int>` | Force the model's scale (2, 3 or 4). CUGAN light denoise only has scale 2. Empty means AnimeUp chooses. | automatic |
| `--denoise` / `--no-denoise` | Light denoise before the upscale. Only useful on noisy sources. | `--no-denoise` |
| `--dedup` / `--no-dedup` | Process repeated frames only once. | `--dedup` |
| `--forza` | Go ahead even when the upscale is below the minimum (1.25×), which normally is refused because it costs the hours of a full upscale for few extra pixels. | off |
| `--disco <float>` | Maximum disk space per file, in GB: extracted frames, chunks and segments together. More space means fewer chunks. | `40.0` |

See [The models and when to use them](../deep-dives/models.md) for choosing `-m`, and [How a job works inside](../deep-dives/how-it-works.md) for chunks and deduplication.

!!! note "Defaults differ from the interface"
    The command line has fixed defaults. The interface's disk cap is computed from your free space and its pause between files defaults to 5 minutes; here they're 40 GB and 0. Pass the options explicitly if you want the same behaviour.

## run

Runs the full job on each file, with the same pipeline as the interface.

```bash
./animeup run
./animeup run --si --pausa 5 INPUT/
./animeup run -m animevideov3 --altezza 1080 "INPUT/Episode 01.mkv"
```

It analyses the files, prints the plan of each one, then announces the total, for example `3 files, estimated time 2h10m - 3h05m`, and asks `Go ahead? [y/N]`. Answer `y` (or `yes`; the Italian `s`/`si` work too). Files whose output is already in `OUTPUT/` are skipped (`Already there, skipped: …`) and aren't counted in the estimate.

It accepts all the [`plan` options](#plan), plus:

| Option | What it does | Default |
|---|---|---|
| `--si` | Don't ask for confirmation before starting. | off |
| `--pausa <int>` | Minutes of rest between one file and the next, to let the CPU and GPU breathe on long runs. 0 means none. Never after the last file. | `0` |
| `--tieni-temp` | Keep the working folder in `JOBS/` after a successful job, instead of deleting it. | off |

These options exist for the interface, which splits a queue into one `run` command per model. You don't need them by hand:

| Option | What it does | Default |
|---|---|---|
| `--pausa-prima` | Rest before the first file too. | off |
| `--catena-totale <int>` | How many files the whole queue has, for "file N of M". | `0` |
| `--catena-inizio <int>` | How many files of the queue come before this command. | `0` |
| `--lancio <str>` | Label shared by all the commands of one launch, used to rebuild the end-of-queue summary. | empty |

### While it runs

Each file shows a progress bar with the phase and the frames done. At the end of a file you get `Done:` with the size, frames and duration (and the deduplication saving), and the path of the output.

| What you see | Meaning |
|---|---|
| `  ! …` in yellow | A warning from the final checks. The file is done; read the warning. |
| `Incomplete output, set aside as ….PARZIALE.mkv. Run again to redo it.` | The final checks found a defect. The file was renamed so that it isn't mistaken for a good one; running the command again redoes it. |
| `Failed: …` and `Partial work kept in …` | The job failed. Its work stays in `JOBS/`; running the same command again resumes from there. |
| `Stopped by the user: it can be resumed from …` | The file was stopped with **Stop** in the interface. The queue moves on. |
| `Pausing for 5 min to let the machine breathe...` | The `--pausa` between files. |

**To stop** a `run`, press **Ctrl+C** in its Terminal window. A job started from the command line uses the same `JOBS/` folder and lock as the interface, so it also appears in the Processing tab while it runs. The file in progress stays in `JOBS/`, and running the **same command** again resumes it with the work already done. Resuming only reuses work when the parameters match; different parameters never reuse the wrong frames.

**Exit code**: 0 when every file was completed or already there; 1 when at least one file couldn't be planned, failed, or produced an incomplete output, with a final line `2 of 5 not completed: …`. Scripts can rely on it.

## taratura

Measures the speed of this Mac on the sample clip and calibrates every time estimate. *Taratura* is Italian for calibration. No options.

```bash
./animeup taratura
```

It takes about 10 minutes and needs the GPU idle: with a job or queue running it refuses (`A job is running: stop everything from the interface …`, exit code 1). At the end it prints the measured speeds next to the factory ones and saves them to `registri/taratura.json`. The same calibration is available from the sidebar: see [02. Calibrate your Mac](../02-calibration.md) for what it measures and when to redo it.

## doctor

Checks that the folder is self-contained and ready to use.

```bash
./animeup doctor
```

It prints the version and project folder, then one row for each of `ffmpeg`, `ffprobe`, `realesrgan-ncnn-vulkan` and `realcugan-ncnn-vulkan`, with its **Status** (`vendored`, `from the system`, `MISSING`), a **Test** (each binary is actually run: `runs`, or why it doesn't) and its **Path**. The meaning of each status is in [01. Install](../01-install.md#check-the-folder-with-doctor).

## setup

Downloads the binaries and models missing from `bin/`, so the folder works on any Apple Silicon Mac.

```bash
./animeup setup
./animeup setup --si
```

| Option | What it does | Default |
|---|---|---|
| `--si` | Don't ask for confirmation. | off |

It lists what it will download and from where, with the approximate total size, and asks `Go ahead with the download? [y/N]`. FFmpeg and ffprobe are the pinned 9.0.2 release of Martin Riedl's static macOS builds, verified by SHA256 and checked for the encoders and filters AnimeUp needs; Real-ESRGAN and Real-CUGAN come from pinned official releases, verified the same way. An FFmpeg already in `bin/` but of a different version is replaced with the pinned one, so every installation encodes with the same build. If everything is already there: `All binaries and models are already in bin/.` It only works on Apple Silicon; on another architecture it tells you to copy the binaries by hand.

## test

Runs the regression tests in `tests/run.py`. Without the maintainer's sample videos they generate small synthetic clips with FFmpeg, so they work on any installation. The exit code is the tests' own.

```bash
./animeup test
```

## version

```bash
./animeup version     # AnimeUp 1.4.0
```

## Environment

| Variable | What it does |
|---|---|
| `ANIMEUP_ROOT` | Keep the data (`INPUT/`, `OUTPUT/`, `JOBS/`, `anteprime/`, `registri/`) in another folder instead of the AnimeUp folder. |

The language of the messages is the one chosen in the interface, saved in `registri/impostazioni.json`; English when there's none.

[Next: Troubleshooting →](troubleshooting.md)
