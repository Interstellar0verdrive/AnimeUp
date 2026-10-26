---
title: Troubleshooting
description: Symptoms, what they mean and how to fix them, from installation to finished files.
---

<span class="eyebrow">Reference · Troubleshooting</span>

# Troubleshooting

Find the symptom, read what it means, apply the fix. Nothing on this page can damage your sources: AnimeUp only ever reads the files in `INPUT/`.

!!! tip "Where the details are"
    When a job fails, the full story is in `registri/`: `lavorazione.log` for the jobs started from the interface, plus one `.log` per file. The `.log` files are diagnostic only and can be deleted at any time; the other files in `registri/` are data (see [07. Output files and folders](../07-output-and-folders.md)).

## Installing and launching

| Symptom | What it means | What to do |
|---|---|---|
| macOS says `Avvia AnimeUp.command` can't be opened | Gatekeeper blocks scripts from unidentified developers the first time. | **System Settings → Privacy & Security → Open Anyway**, or run `xattr -dr com.apple.quarantine` on the AnimeUp folder. See [01. Install](../01-install.md#get-past-gatekeeper). |
| `ERROR: setting up the environment failed.` | The first launch couldn't download Python and the dependencies. | Connect to the Internet and launch again. It's needed once per Mac (and after moving the folder, if the environment needs repairing). |
| `ERROR: bin/uv is missing, there's no uv in the PATH and the download failed.` | The tool that builds the Python environment couldn't be found or downloaded. | Check the connection and launch again, or install uv once with the command printed in the message; AnimeUp then copies it into `bin/`. |
| `Cancelled. Without these binaries no job can start.` | You answered no to the FFmpeg download. | Run `./animeup setup` and answer `y`. |
| `Binary 'ffmpeg' not found in … or on the PATH.` (or another tool) | A tool is missing from `bin/`. | `./animeup setup`. |
| The sidebar shows **N system dependencies** or **The folder isn't self-contained** | Some tools come from the system (Homebrew, for example) instead of `bin/`. Works here, not on another Mac. | `./animeup setup`, then `./animeup doctor`. |
| `doctor` shows **can't run**, **not responding** or **no response** | The binary is there but broken: truncated, wrong architecture, or the execute permission was lost while copying. | `chmod +x bin/*`, then `./animeup setup`. |
| `setup` says `unexpected checksum` | The downloaded archive isn't the one AnimeUp was verified with; it was discarded. | Try again later. If it persists, follow the manual fallback the message prints. |
| `setup` says the ffmpeg build is `NOT static` or `incomplete`, or reports an unexpected checksum | The downloaded file isn't the pinned FFmpeg 9.0.2 build (a damaged download, or the file changed on the server); it is discarded. | Try again; if it persists, download the file by hand as the message explains and check its SHA256. |
| `Architecture … isn't handled automatically` | You're not on Apple Silicon. | AnimeUp supports Apple Silicon Macs only. |

## The interface

| Symptom | What it means | What to do |
|---|---|---|
| `Port 8899 is already in use: another interface is open.` | An AnimeUp interface (maybe an old one) is still running. | Double-click the launcher: if AnimeUp is running it just opens the browser. To restart it, `lsof -ti :8899 \| xargs kill`, then launch again. Or `./animeup ui --porta 8900`. |
| The browser shows "connection refused" at `localhost:8899` | The server isn't running: the Terminal window was closed, or **Close AnimeUp** was clicked. | Double-click **Avvia AnimeUp.command** again. Running jobs weren't affected. |
| The interface behaves oddly after an update | An interface left open from before the update keeps the old code in memory. | Close it (**Close AnimeUp**, or `lsof -ti :8899 \| xargs kill`) and launch again. |
| The sidebar controls are greyed out with *Settings are locked while a job is running…* | By design: the queue keeps the parameters it started with. | Wait for the queue to finish, or **Stop all**. See [03. The interface](../03-interface.md). |
| *There's a paused file that was started with different parameters…* | An interrupted file will resume with its own settings, not the sidebar's. | Nothing, if that's what you want. Otherwise click **Reset the sidebar to the paused file's parameters**, or discard the job to redo it with new ones. |
| *Factory estimates: use "Run now"…* under the estimate | This Mac has never been calibrated. | [02. Calibrate your Mac](../02-calibration.md). |

## Sources

| Symptom | What it means | What to do |
|---|---|---|
| *No videos in INPUT* | Nothing AnimeUp recognises in `INPUT/`. | Copy `.mkv`, `.mp4`, `.mov`, `.avi`, `.m4v`, `.ts` or `.webm` files into `INPUT/`. |
| *File probably truncated…* | The video stops before the duration the container declares. | The output would end there too. Get a complete copy of the file if you can. |
| *Interlaced content…* or *3:2 telecine detected…* | AnimeUp doesn't deinterlace or inverse-telecine. It flags the file but doesn't refuse it: processed as it is, the combing lines end up upscaled in the output. | Prepare it with a dedicated tool, then put the result back in `INPUT/`. |
| *No usable video track* | The file has no video AnimeUp can read. | Check the file in a player; it can't be processed. |
| A file changed but its analysis didn't | Results are saved by file name. | **Re-analyse** on its row, or **Re-analyse all**. |

More warnings, and what each means, are in [04. Sources](../04-sources.md).

## Compare

| Symptom | What it means | What to do |
|---|---|---|
| Processing the clips stopped halfway | Any click, or leaving the page, interrupts the Compare renders. | Click **Process the clips** again: it picks up where it left off and keeps the clips already done. |
| *no comparison tool found. Install video-compare with: brew install video-compare* | Neither video-compare nor IINA is installed. | Install one of them, or judge with the 1:1 crops in the page. Everything else works without them. |
| Previews with green or pink blocks | An old cache from a file that was corrupted on seek. | Delete that episode's subfolder in `anteprime/` and generate the clips again. |
| *There are no more clips different enough…* | The file is short, or very uniform. | Work with the clips already found. |

## Processing

| Symptom | What it means | What to do |
|---|---|---|
| **Start processing** is disabled | A job, a queue or the pause between files is active, or nothing is selected. | One job at a time: wait, or **Stop all**. |
| A row says **cannot be processed** or **upscale too small** | The output height isn't a real upscale of this file (below 1.25×), or it's already larger. | Raise **Output height**, or turn on **Allow upscales below the minimum** if you really want it. |
| *… can't reach 1080p* on a model | That model's largest scale doesn't get there from this source. | Pick another model, or lower the output height. |
| *not enough space: about N GB needed, M GB free…* | The job wouldn't fit on the disk, so it didn't start. | Free up space, lower the output height, or lower **Max disk space per file** (more, smaller chunks). |
| *another job on this file is already running (folder …)* | A lock file says this file is being processed. | If nothing is really running, the lock belongs to a dead process and clears itself on the next run; if it persists, delete `in-corso.lock` in that folder of `JOBS/`. |
| *the model hung: no new frame for 15 minutes… It was stopped.* | The upscaler stopped producing frames. | Run it again: the job resumes where it left off. |
| *ffmpeg hasn't responded for 6 hours: stopped.* | Encoding froze, often because the disk disappeared. | Check that the disk is still connected, then resume. |
| *The job didn't start (exit code N). More details in the log: …* | The command behind the job failed right away. | Read the log it names. |
| A row stays **interrupted** | Stopped, crashed, or the Mac slept or shut down. | **Resume** continues with the original parameters; **Discard** throws the partial work away. See [06. Processing](../06-processing.md). |
| A row says **needs redoing**, or `OUTPUT/` contains a `.PARZIALE.mkv` | The final checks found a defect, so the output was set aside instead of keeping its proper name. | Run the file again: it's redone. |
| A file marked **done** asks to be redone | It was processed, but its output is no longer in `OUTPUT/` (moved or archived). | Confirm only if you want it again. |
| `JOBS/` takes a lot of space | A job is half-finished, or a finished job left its work folder behind. | Resume or **Discard** it: finished rows with a leftover folder have their own **Discard**. |
| Estimates are far from the real time | Uncalibrated Mac, or the first files of a new kind of material. | Calibrate (see below). Estimates also learn from every finished file. |

### Stopping a job without the interface

The job runs as a separate process, so it carries on even with the interface closed. To stop it from Terminal:

```bash
kill $(cat "JOBS/<job folder>/in-corso.lock")
```

The file stays resumable. To shut down the interface itself when nothing else works: `lsof -ti :8899 | xargs kill`.

## Calibration

| Symptom | What it means | What to do |
|---|---|---|
| **Run now** / **Redo** is greyed out | A job, a queue or the pause between files is active. | Wait, or **Stop all** in Processing. |
| *A job is running: the timer would be measuring a busy GPU…* | Same, seen from inside the window. | **Stop all**, then reopen the window. |
| `./animeup taratura` says *A job is running: stop everything from the interface…* | Same, from the command line. | Stop the queue, then run it again. |
| *Calibration interrupted: sample clip missing…* | `campioni/bbb-480p.mkv` was deleted. | Restore the `campioni/` folder from the release or the repository. |
| *Calibration interrupted: a calibration is already running on this machine…* | A previous run is still going in the background. | Wait a few minutes; the sidebar date changes when it's saved. |
| *Calibration interrupted: … produced N of 180 frames — measurement unreliable* | An upscaler didn't finish its batch. | Check the free space, close other apps, try again. |
| The sidebar still says **Never** after calibrating | The run didn't finish (the interface was closed during it), or the folder is on a Mac with a different chip. | Run it again and leave AnimeUp alone until **done**. |
| The new numbers are much lower than before | Something else was using the GPU or CPU during the run, or a laptop was on battery. | Close other apps, plug in, and **Redo**. |

The full story is in [02. Calibrate your Mac](../02-calibration.md).

## Still stuck?

- Run `./animeup doctor` and check every row says **vendored** and **runs**.
- Look at the end of the relevant `.log` in `registri/`.
- The reasoning behind every threshold mentioned here is in the [tuning notes](../../TUNING.md).

[Next: How a job works inside →](../deep-dives/how-it-works.md)
