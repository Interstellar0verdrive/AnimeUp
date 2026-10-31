---
title: 08. Files and folders
description: Where finished videos, work files, logs and AnimeUp's own data go, and what the names mean.
---

<span class="eyebrow">Using AnimeUp · Files</span>

# 08. Files and folders

Your videos never move. AnimeUp reads the originals where they are, writes the finished videos where you chose, and keeps its own work in folders of its own.

## Finished videos

By default each finished video goes **next to its original**, in the same folder. To collect them all in one place, choose a folder in [Start](04-start.md#2-where-files-go) or Settings › Folders. Each file keeps the folder that was chosen when it entered the Queue.

The name keeps the original one and adds what was done:

```
Morevna Ep2 [480p] [upscale 1080p animevideov3 x4 crf18 dd].mkv
```

| Part | Meaning |
|---|---|
| `upscale 1080p` | The output height (`supersampling` when the source is already that tall) |
| `animevideov3`, `cugan`, `cugan-denoise`, `cugan-conservative` | The model |
| `x4` | The model's scale, before the final resize |
| `crf18` | The x265 quality |
| `dd` | Repeated frames were skipped |
| `dn` | A light denoise before the model (command line only) |
| `medium`, `slow`, `veryslow` | The x265 preset, only when it isn't the default `slower` |

Because the name says how a video was made, versions made with different models or heights live side by side and never overwrite each other. A video with the same name is only replaced if you confirm it with [Redo](05-queue.md#redo-a-finished-file).

The finished video is always an MKV with x265 (HEVC) 10-bit video, and every audio track, subtitle track, chapter and attached font of the original. Text subtitles that MKV can't hold (mostly `mov_text`, common in MP4) are converted to SRT; the outcome says so.

!!! note "A video is written under its real name only when complete"
    While it's being assembled, the file has a temporary name, and it gets its real name at the very end. A file whose final check fails (wrong number of frames, wrong size, unreadable audio) is set aside as `….DEFECTIVE.mkv`, and its work files are kept so nothing is lost.

## Work files

While a file is processed, AnimeUp keeps its extracted frames, the chunk being upscaled and the encoded chunks in the **work folder**: `~/Movies/AnimeUp Jobs` by default, or the one you chose.

```
AnimeUp Jobs/
├── JOBS/      one folder per file in progress or interrupted
└── logs/      one log per processed file
```

A single 24-minute episode can take tens of GB while it runs, mostly its extracted frames. When the file is done, its work folder is deleted and only the log stays (unless **After a file finishes** is set to **Keep everything** in Settings). An interrupted file keeps its work folder until you resume it or **Discard** it.

!!! warning "Don't move or rename files in JOBS by hand"
    Everything AnimeUp needs to resume a file is in its folder. To free space, discard interrupted files from the Queue instead.

If you change the work folder while some files are interrupted, AnimeUp warns you: their work stays in the old folder and they can only be resumed from there.

## Logs

Every processed file has its log, named like its video, in `logs/` inside the work folder. **Show Log** on a finished or failed file opens it. AnimeUp's own log opens with **Help › Open Log in Console**.

## AnimeUp's own data

`~/Library/Application Support/AnimeUp 2` holds everything else: settings, calibration and its history, the record of finished files (which the estimates learn from), the analysis of each file, the clips rendered by Compare, and the video tools. Deleting it resets AnimeUp to its first launch; it doesn't touch any video.

[Next: Command line →](reference/command-line.md)
