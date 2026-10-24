---
title: How a job works inside
description: What AnimeUp does to a file from analysis to the finished MKV, why it works in chunks, and how resuming knows what it can keep.
---

<span class="eyebrow">Deep dive · Inside a job</span>

# How a job works inside

What happens between pressing **Start processing** and a new file appearing in `OUTPUT/`, and why each step is built the way it is.

You don't need this page to use AnimeUp. It's for when you want to understand a phase name on a progress line, a warning in a plan, or why stopping at one moment costs nothing and at another costs a few minutes.

## The whole path at a glance

```text
 INPUT/episode.mkv
      │
      ▼
 1. Analysis ─────── what the file really is (once, saved)
      │
      ▼
 2. Plan ─────────── size, model, scale, chunks, estimate (nothing runs yet)
      │
      ▼
 3. Checks ───────── free space, output folder writable, lock
      │
      ▼
 4. Extraction ───── every frame → PNG, one sequential pass      ┐ phase 1/3
      │                                                          ┘
 5. Deduplication ── which frames are repeats
      │
      ▼
 6. Chunks, one after another:                                   ┐
      upscale (GPU) → restore repeats → encode segment (CPU)     │ phase 2/3
      │                                                          ┘
      ▼
 7. Assembly ─────── join segments + copy audio, subs, fonts,    ┐ phase 3/3
      │              chapters from the source                    ┘
      ▼
 8. Verification ─── frame count, size, audio
      │
      ▼
 OUTPUT/episode [upscale 1080p … ].mkv   + job report, JOBS/ folder deleted
```

The "phase 1/3, 2/3, 3/3" on a Processing row map onto this: extraction, the chunk loop (upscale with encoding in between), and the encoding of the last chunk plus assembly.

## 1. Analysis

Before anything is planned, AnimeUp works out what the file really contains, with `ffprobe` and a pass over its timestamps. This is the analysis you see in [Sources](../04-sources.md). A few principles drive it:

- **Timing is measured in whole timebase ticks, never in seconds.** MKV stores timestamps to the millisecond, so a 23.976 fps file alternates between 41 and 42 ms per frame. Measured in seconds, every constant-frame-rate file would look variable.
- **The frame rate comes from the average over the whole file**, and is snapped to a standard value (23.976, 24, 25, 29.97…) only when the difference is negligible.
- **Variable frame rate, missing frames and telecine are told apart**, because each needs a different treatment.
- **The source is never re-encoded to "fix" its timing.**

Interlaced or telecined sources are **detected and flagged, not treated**. Detection can't reliably tell hard telecine from true interlacing, and applying the wrong cure destroys the original progressive frames. Prepare such a source with a dedicated tool first.

The result is saved in `JOBS/.analisi/` and reused until the file changes, so the list opens instantly next time.

**Deep analysis** (on by default, see [03. The interface](../03-interface.md)) adds one more measurement: how many frames deduplication will be able to skip. It decodes six 4-second windows spread across the file, in a single pass, and applies the same rule the real deduplication uses. Validated against real jobs, it was off by 1.3 percentage points on average. The guess it replaced, based on files of a similar length, was off by 26.9.

## 2. The plan

The plan turns "what the file is" into "what will be done", without running anything. That's why Compare and Processing can show sizes, models and estimates instantly.

**Output size.** The height is your **Output height**. The width comes from the source's real display aspect ratio, with square pixels, rounded to an even number. Two limits apply:

| Rule | Value | What happens |
|---|---|---|
| Maximum enlargement | 4× the source height | The target is lowered, with a warning ("Target lowered from 1080p to 960p…") |
| Minimum gain | 1.25× | The file is refused ("upscale too small") unless **Allow upscales below the minimum** is on |

**Model and scale.** If you haven't chosen a model, AnimeUp proposes one from the source height. The model upscales by a whole factor (2, 3 or 4), and AnimeUp picks the factor that brings the final resize closest to an exact 2:1 reduction. If no factor of the chosen model reaches the target, the plan is refused, because the gap would be filled by plain interpolation. All of this is in [The models and when to use them](models.md).

**Encoding.** x265, 10-bit 4:2:0, your CRF and preset, plus fixed settings tuned for animation: negative deblocking and SAO off to keep lines sharp, `aq-mode=3` against banding in flat areas, psy-rd to keep texture. Colour space tags are copied from the source. A source that doesn't declare them gets the usual convention (BT.709 from 720 lines up, BT.601 below).

**Chunks and disk space.** See [Why chunks](#why-chunks) below.

**Estimate.** See [How the time estimate is built](#how-the-time-estimate-is-built).

## 3. Before starting: three checks

1. **Disk space.** The plan's peak disk use, minus frames already extracted by an earlier run, is compared with the free space, also subtracting what other running jobs have claimed. If it doesn't fit, the job is refused before a single frame is written: *"about N GB needed, M GB free"*. A full disk halfway through wouldn't just ruin this file. It would stall the system and could corrupt other jobs' state.
2. **The output folder is writable.** A missing permission used to be discovered at assembly, after hours of GPU work. Now AnimeUp writes a test file into `OUTPUT/` first.
3. **The lock.** AnimeUp creates `in-corso.lock` in the job folder, holding its process ID. If another live process holds it, the job refuses to start. A lock left behind by a crashed process is recognised as dead (zombie processes included) and taken over. If the previous owner was killed hard, AnimeUp also kills its orphaned upscaler before starting, so two processes never write the same frames.

## 4. Extraction

Every frame of the source is decoded **once, from start to finish, with no seeking** and written to `frames/` as an 8-bit RGB PNG.

- **No seeking**, because on encodes with many reference frames a fast seek produces reconstructed, approximate frames.
- **8-bit**, because the models work in 8-bit internally and return 8-bit (16-bit input measured 49.7 dB away from 8-bit, i.e. no difference) and 16-bit would quadruple the disk space. 10-bit sources are reduced with dithering here, which is better than the hard truncation the model loader would do.
- **A constant frame grid** at the file's frame rate: missing frames are repeated and extra ones dropped, so extraction and the deduplication scan see exactly the same set of frames.
- **Denoise**, if you turned it on, is applied here (`hqdn3d=1.5:1.5:6:6`), before the model sees the frame.

Extraction is the one step that isn't split into chunks: all source frames stay on disk for the whole job. That's why they dominate the disk-space budget.

## 5. Deduplication

With **Deduplicate frames** on, AnimeUp measures the difference between each frame and the **last frame it kept**, and marks a frame as a repeat only if:

> no single pixel, on any of the three colour channels, differs by more than 16/255.

This isn't a similarity score. It's an upper bound on the error. If a mouth moves, those pixels change a lot and the frame is kept, however small the moving area. Comparing with the last *kept* frame, not the previous one, stops a slow fade from being frozen by adding up tiny differences. At most 5 consecutive frames can be skipped, which limits the reach of any mistake to a fraction of a second.

The map is then **audited** by an independent check on the structure actually used to copy frames. If a frame is found to have been wrongly marked as a repeat, only that frame is put back into the work (a warning says how many). If the map itself is malformed, deduplication is dropped for the file: it costs time, not correctness. The map is saved as `dedup.json`.

How much it saves depends entirely on the material. On real files it skipped 11% to 57% of frames.

## 6. Why chunks { #why-chunks }

The upscaled frames of one episode would need hundreds of gigabytes as PNG. So after extraction the frames are processed in **chunks**, one after another. Each chunk goes through:

1. **Gather.** The frames this chunk needs, minus repeats, are linked (not copied) into `chunkNNNN-in/`. If a run of repeats crosses the chunk boundary, its reference frame is included.
2. **Upscale.** `realesrgan-ncnn-vulkan` or `realcugan-ncnn-vulkan` runs on the GPU and writes `chunkNNNN-up/`. If no new frame appears for 15 minutes the upscaler is declared stuck and the job fails rather than hanging forever. (The slowest frame measured takes under two seconds.)
3. **Restore repeats.** The full sequence is rebuilt in `chunkNNNN-full/` with hard links: each repeated frame points at its upscaled original, costing no disk space.
4. **Encode.** FFmpeg resizes to the exact target with lanczos and encodes with x265 in the same pass, so there's one compression and no intermediate generation. The result is a segment in `segments/`. This step uses the CPU. On the Processing row it shows as *"encoding chunk (CPU) … upscale resumes shortly"*.
5. **Clean up.** The three chunk folders are deleted and the segment is recorded in `state.json`.

How big a chunk is depends on your **Max disk space per file** setting, spent in a fixed order:

1. First the parts that can't be split: all extracted source frames, plus the encoded segments and the final file (both are on disk at the moment of assembly).
2. What's left goes to the chunk being upscaled.

On top of that, four rules:

| Rule | Value | Why |
|---|---|---|
| At least | 3 chunks | A chunk is atomic: if it's interrupted it restarts. With three chunks a power cut costs at most a third of the work. |
| At most | 20 chunks | Each chunk has a fixed cost of about a minute (measured at 1.16 min); beyond 20 that outweighs the savings |
| Chunk never bigger than | 40 GB of upscaled frames | Even on a huge disk, one chunk shouldn't hold most of the work an accident could take away. Relaxed if keeping to it would need more than 20 chunks and there's room. |
| Chunk never smaller than | 800 frames | Below that the fixed minute weighs more than the work inside |

The disk never gets filled beyond 85% of its free space, whatever you set.

!!! tip "Where it's cheapest to stop"
    Work is secured **one chunk at a time**. If you stop in the middle of a chunk, that chunk restarts from its first frame on resume. That's why the Processing row also says something like "742/1778 of chunk 3 of 10": it counts down to the next point where a Stop costs nothing. See [06. Processing](../06-processing.md).

## 7. Assembly and remux

When every chunk is encoded, the segments are joined in order and the rest of the source is copied in from the original file:

- all audio tracks, copied untouched;
- all subtitle tracks, copied (only `mov_text` is converted to SRT, because MKV can't hold it);
- attachments, including fansub fonts;
- chapters.

Tracks are interleaved strictly by timestamp. Without that, a source with sparse subtitles and fonts once produced a file with all its audio bunched at the start, which players then treated as silent.

The file is written as `<name>.mkv.inlavorazione` and renamed to its real name only when complete. The rename is atomic, so `OUTPUT/` never holds a truncated file under a good name.

## 8. Verification and the job report

The finished file is checked:

| Check | If it fails |
|---|---|
| Number of frames equals the number extracted | Defect |
| Width × height equal the target | Defect |
| Audio can be read after seeking into the middle | Defect |
| The frame count couldn't be read at all | Warning only |

A file with any **defect** is renamed `….PARZIALE.mkv` and its job folder is kept for inspection (see [07. Output files and folders](../07-output-and-folders.md)). Otherwise:

- a line is added to `registri/esiti.jsonl`: real duration (paused time excluded, earlier interrupted runs included), measured deduplication, warnings, model, output name. This is what makes the row say "done", and what future estimates learn from;
- the job folder in `JOBS/` is deleted.

Warnings (as opposed to defects) don't keep the job folder. A note isn't worth the 31 GB that the extracted frames of a 24-minute 720p episode take.

## Pausing

**Pause** in Processing doesn't stop anything. It freezes the upscaler or encoder process exactly where it is (a `SIGSTOP` signal), and **Resume** wakes it up (`SIGCONT`). Both programs write one file at a time and hold nothing open between files, so nothing is lost. This was verified byte for byte on the PNGs and with a full decode of the video. The time spent paused is subtracted from the file's recorded duration, so a three-hour pause doesn't distort future estimates.

## Resuming: what is kept and what is redone

A job can be interrupted by **Stop**, **Stop all**, a crash, a power cut or closing the Mac's lid. Everything needed to resume is in its `JOBS/` folder. When the job starts again, AnimeUp compares two **signatures** saved in `state.json` with the current plan:

| Signature | Made of | If it changes |
|---|---|---|
| **Extraction** | Source file name and size, denoise filter, frame-rate grid | The extracted frames are thrown away and extraction starts again |
| **Job** | The extraction signature, plus frame count, model, scale, output width and height, codec, pixel format, preset, x265 settings (CRF included), deduplication on/off, frame rate | Encoded segments are thrown away. Extracted frames are **kept** if the extraction signature still matches. The deduplication map is also kept, since it only depends on the frames. |

So changing the CRF or the model costs you the encoded chunks but not the hours of extraction. Changing denoise costs everything. Some things are deliberately **not** in the signature:

- **Disk space and chunk size.** These depend on the free space at the moment of planning. When there are segments to protect, a resumed job **adopts the chunk layout it started with**, so segments already encoded stay valid even if free space or the slider have changed.
- **The source's modification date.** It changes with a backup restore or `rsync` without a single bit of content changing. Only the size counts.

More safeguards on resume:

- **Each saved segment is checked** with `ffprobe` for the exact number of frames it should hold. A truncated segment left by a power cut is redone instead of producing a short video.
- **Segments are recorded by the frame range they cover**, not by their number, so a different chunk layout can never stitch the wrong frames together.
- **If extraction produced a different number of frames** than when the segments were made (which happens between FFmpeg builds, i.e. between Macs), the segments are discarded rather than reused one frame out of step.

**Resume in the interface** goes one step further: it restarts with the parameters saved in `parametri.json` when the job first started, whatever the sidebar says now. That's why resuming from the interface can never throw work away. The command line has no such file to go on: running `./animeup run` again on the same file uses whatever parameters you give it, and the signatures decide what can be kept.

!!! info "Resuming on another Mac"
    Job folders are identified by the file's path inside the AnimeUp folder, not the full disk path. Copy the whole folder to another Mac (or rename it, or mount the drive somewhere else) and interrupted jobs are still found and resumed. Job folders created by older versions, which used the full path, are still recognised and renamed on their next run.

## How the time estimate is built

The estimate on each row is the sum of steps that run one after another:

- **GPU time**: frames left after deduplication × source megapixels ÷ the model's speed in megapixels per second at that scale;
- **extraction** and the **deduplication scan**, scaled by the source's pixel count;
- **encoding**, scaled by the output's pixel count.

Where those speeds come from:

1. **Factory values**, measured on one specific Mac, until you calibrate.
2. **Calibration** (`registri/taratura.json`) replaces them with this Mac's real speeds. See [02. Calibrate your Mac](../02-calibration.md).
3. **History** (`registri/esiti.jsonl`): as soon as you've finished some files, the expected deduplication and a correction factor for "work the model doesn't count" (assembly, final checks, idle time) are learned from what similar files actually did.

The estimate is shown as a range. Its lower end assumes the best case already seen, its upper end the worst. Without any history, the upper end adds a 25% safety margin and the lower end assumes deduplication saves up to 60% (the most observed was 57%). Once a job has run for a few minutes, the deduplication actually measured on that file replaces the guess, and the range narrows.

The numbers behind all of this, and what happens if each is wrong, are in [TUNING.md](../../TUNING.md).

## Before you move on

!!! success "Check"
    - [ ] You know the three phases on a Processing row: extraction, chunks, assembly
    - [ ] You know work is secured one chunk at a time
    - [ ] You know changing CRF or model on an interrupted job keeps the extracted frames, while changing denoise doesn't
    - [ ] You know where the estimate's numbers come from: factory, calibration, history

[Next: The models and when to use them →](models.md)
