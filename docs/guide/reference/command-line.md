---
title: Command line
description: The portable folder and the ./animeup commands, with their options and defaults.
---

<span class="eyebrow">Reference · Command line</span>

# Command line

The app is the way to use AnimeUp. For running it from an external drive, or in scripts, the release also has a **portable folder**: the same engine, used from the Terminal with `./animeup`.

## The portable folder

1. Download **`AnimeUp-v2.0.0-macos-arm64.zip`** from the [latest release](https://github.com/Interstellar0verdrive/AnimeUp/releases/latest) and unzip it where you want AnimeUp to live: anywhere you can write to, external drives included.
2. In the Terminal, go into the folder and run the setup once. It downloads FFmpeg (which can't be bundled, because of its licence) and checks everything else:

```bash
cd /path/to/AnimeUp
./animeup setup      # downloads what's missing into bin/
./animeup doctor     # checks the folder is ready
```

The folder already contains uv, Real-ESRGAN, Real-CUGAN and their models; the first command also sets up a private Python runtime inside it. Nothing is installed on the Mac, and the folder can be moved to another Mac as it is.

The folder has its own `INPUT/` and `OUTPUT/`: put videos in the first, finished ones land in the second, work files in `OUTPUT/JOBS/` and logs in `OUTPUT/logs/`. The portable folder and the app don't share settings, calibration or queue.

## Commands

| Command | What it does |
|---|---|
| `./animeup analyze [files]` | Analyses the sources and prints the report, without changing anything |
| `./animeup plan [files]` | Shows what would be done to each file: model, size, chunks, estimate |
| `./animeup run [files]` | Runs the full job, the same pipeline as the app |
| `./animeup calibrate` | Measures this Mac's speed, like the app's calibration |
| `./animeup setup` | Downloads the missing tools and models into `bin/` |
| `./animeup doctor` | Checks that the folder is self-contained and ready |
| `./animeup test` | Runs the regression tests |
| `./animeup version` | Shows the version |

`./animeup <command> --help` lists each command's options.

`analyze`, `plan` and `run` take any number of files or folders; with none, they use `INPUT/`. Quote names with spaces:

```bash
./animeup plan "INPUT/Episode 01.mkv"
./animeup run INPUT/Season2 ~/Videos/special.mkv
```

## Options of run and plan

| Option | Default | What it does |
|---|---|---|
| `--height <px>` | 1080 | Final height |
| `--model`, `-m <key>` | the recommended one | `animevideov3`, `cugan-denoise`, `cugan` (no-denoise) or `cugan-conservative` |
| `--crf <n>` | 18 | x265 quality: lower is better, and larger |
| `--preset <name>` | slower | x265 preset: `medium`, `slow`, `slower`, `veryslow` |
| `--disk <GB>` | 40 | The most one file may use while processed |
| `--dedup` / `--no-dedup` | dedup | Skip repeated frames |
| `--denoise` / `--no-denoise` | off | A light denoise (`hqdn3d`) before the model |
| `--scale <n>` | automatic | Force the model's scale (2, 3 or 4) |
| `--force` | off | Go ahead even below the minimum enlargement (1.25×) |
| `--yes` | off | `run` only: don't ask for confirmation before starting |
| `--pause <min>` | 0 | `run` only: minutes of rest between files |
| `--keep-temp` | off | `run` only: keep the work folder when a file is done |

`analyze` also has `--quick` (timing only) and `--duplicates` / `--no-duplicates` (measure the repeated frames, which takes a full decode).

An interrupted `run` resumes when you run it again on the same file with the same options: what can be kept is kept (see [How a job works inside](../deep-dives/how-it-works.md#resuming-what-is-kept-and-what-is-redone)).

**Exit code**: 1 when at least one file couldn't be planned, failed or produced a defective output, or when a calibration is running; 143 when the run is terminated; otherwise 0, so a file stopped on purpose doesn't count as a failure. Scripts can rely on it.

[Next: Troubleshooting →](troubleshooting.md)
