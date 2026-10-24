---
title: 01. Install and first launch
description: Download AnimeUp, get past Gatekeeper, and understand what the first launch sets up.
---

<span class="eyebrow">Step 01 · Install</span>

# 01. Install and first launch

Put the AnimeUp folder wherever you like, double-click one file, and let the first launch set up everything inside that folder.

## Choose how to get it

There are two ways to install AnimeUp. Both end with the same self-contained folder.

| | Release zip (recommended) | `git clone` (from source) |
|---|---|---|
| For | Most people | People who want to follow development or read the code |
| Includes | The program, the Real-ESRGAN and Real-CUGAN binaries with their models, and uv | The program only |
| Downloaded on first launch | Python runtime, dependencies, FFmpeg | Python runtime, dependencies, FFmpeg, the upscalers and their models, uv |
| Gatekeeper prompt | Yes, once | No (git doesn't mark files as downloaded) |
| Updating | Download the new zip (see [Updating](#updating-from-an-older-version)) | `git pull` |

!!! tip "Where to put the folder"
    Anywhere you can write to, external drives included. Choose a disk with room to spare: frames are extracted next to the program, in `JOBS/`, and a single episode can temporarily take tens of GB.

### Option A: the release zip

1. Download `AnimeUp-<version>-macos-arm64.zip` from the [latest release](https://github.com/Interstellar0verdrive/AnimeUp/releases/latest).
2. Unzip it where you want AnimeUp to live.
3. Double-click **`Avvia AnimeUp.command`** (Italian for "Launch AnimeUp") and follow [The first launch](#the-first-launch).

### Option B: from source

```bash
git clone https://github.com/Interstellar0verdrive/AnimeUp.git
cd AnimeUp
./animeup setup     # downloads FFmpeg, Real-ESRGAN, Real-CUGAN and the models into bin/
./animeup ui
```

You can also skip the two commands and double-click **`Avvia AnimeUp.command`**: it runs `setup` by itself when something is missing from `bin/`. If you have no `uv` on your system, the launcher downloads it too.

Every third-party download comes from a pinned official release and is verified with SHA256. The one exception is FFmpeg, which comes from a rolling snapshot and is checked instead for the encoders and filters AnimeUp needs.

## Get past Gatekeeper

The first time you double-click **`Avvia AnimeUp.command`** from the zip, macOS refuses to open it, because the script isn't signed by an identified developer. This is expected.

1. Close the warning.
2. Open **System Settings → Privacy & Security**.
3. Scroll down to the message about `Avvia AnimeUp.command` and click **Open Anyway**.
4. Confirm. From now on the file opens with a normal double-click.

<!-- IMG: macOS System Settings → Privacy & Security with the "Open Anyway" button for Avvia AnimeUp.command -->

!!! tip "The Terminal alternative"
    Instead of the steps above, you can run this once on the unzipped folder (adjust the path to where you put it):

    ```bash
    xattr -dr com.apple.quarantine ~/Downloads/AnimeUp
    ```

You only have to do this for the launcher. Once it runs, AnimeUp removes the quarantine flag from **its own folder** (and nothing outside it), so the bundled tools aren't blocked one by one.

## The first launch

A Terminal window opens and AnimeUp prepares itself. Everything it downloads goes inside the AnimeUp folder.

| What you see in Terminal | What's happening |
|---|---|
| `Folder downloaded from the Internet: removing the macOS quarantine from its files.` | The quarantine flag is removed from the AnimeUp folder only. |
| `Downloading uv 0.11.4 (the Python environment manager, ~20 MB)...` | Only if `bin/uv` is missing (a `git clone` without uv on the system). |
| `First launch: setting up the environment inside the folder (only once)...` | uv downloads a private Python runtime and the dependencies into `.python/` and `.venv/`. This is the step that needs the Internet. |
| `To make the folder self-contained, these will be downloaded:` followed by a list and `Go ahead with the download? [y/N]` | The `setup` step: it lists what's missing from `bin/` (FFmpeg and ffprobe from the zip; the upscalers and models too from a clone), with the source URLs and the total size. Type `y` and press Return. |
| `ffmpeg vendored, static and complete.` | The download was checked: the build depends on nothing outside macOS and has the encoders and filters AnimeUp uses. |
| `Interface at http://localhost:8899 — Ctrl+C to stop it.` | The interface is running, and your browser opens on it. |

!!! info "Why FFmpeg is downloaded and not bundled"
    The static FFmpeg build AnimeUp uses includes x264 and x265, which makes it GPLv3. Shipping it would mean shipping its complete source code as well, so AnimeUp downloads it from [Martin Riedl's macOS builds](https://ffmpeg.martin-riedl.de) straight into `bin/`, and only after you confirm.

!!! warning "If you answer no to the download"
    You'll see `Cancelled. Without these binaries no job can start.` The interface still opens, but nothing can be analysed or processed until FFmpeg is in place. Run `./animeup setup` from the AnimeUp folder whenever you're ready.

On later launches none of this repeats: the environment is already there, and the interface opens in a few seconds. If AnimeUp is already running when you double-click the launcher, it just says `AnimeUp is already running: opening the browser.` and opens a new browser tab.

## Keep the Terminal window open

The Terminal window that appears **is** the AnimeUp server. Leave it open for as long as you use the interface.

| You close... | What happens |
|---|---|
| The browser tab | Nothing stops. Reopen <http://localhost:8899>, or double-click the launcher again. |
| The Terminal window | The interface shuts down. Jobs that are running **don't** stop: they carry on in the background and you'll find them on the next launch. |
| **Close AnimeUp** in the sidebar | Same as closing the Terminal, but clean. See [03. The interface](03-interface.md). |

To stop a running job rather than the interface, use **Stop** or **Stop all** in the Processing tab: see [06. Processing](06-processing.md).

## Check the folder with `doctor`

Once setup has finished, it suggests a final check. From the AnimeUp folder in Terminal:

```bash
./animeup doctor
```

It prints the version, the project folder, and a table with one row per external tool (ffmpeg, ffprobe, realesrgan-ncnn-vulkan, realcugan-ncnn-vulkan). Each binary is actually run, not just looked at.

| Status | Test | Meaning |
|---|---|---|
| **vendored** | **runs** | The tool is in `bin/` and works. This is what you want. |
| **from the system** | **runs** | AnimeUp found it on the system (Homebrew, for example), not in `bin/`. It works here, but the folder wouldn't work on another Mac. Run `./animeup setup`. |
| **MISSING** | — | Not found anywhere. Run `./animeup setup`. |
| any | **can't run**, **not responding** or **no response** | The file is there but broken: truncated, the wrong architecture, or it lost its execute permission while being copied. Try `chmod +x bin/*`, then `./animeup setup`. |

When everything is vendored and runs, the last line reads `The folder is self-contained: you can move it to another Mac and it will work exactly the same.`

The sidebar of the interface shows the same problem in short: a line such as **2 system dependencies** or **The folder isn't self-contained: `./animeup setup`**.

## Moving the folder

You can move or copy the whole AnimeUp folder to another place or another Apple Silicon Mac. On the next launch the launcher checks that its Python environment points at the new location and repairs it if needed (this may need the Internet once). Don't move `src/`, `ui/` or the hidden folders out of the AnimeUp folder.

!!! tip "Keeping your data elsewhere"
    The only setting outside the interface is the environment variable `ANIMEUP_ROOT`: point it at another folder and AnimeUp keeps `INPUT/`, `OUTPUT/`, `JOBS/` and its records there instead.

## Updating from an older version

**From a `git clone`**: run `git pull` in the AnimeUp folder, then relaunch. Your `INPUT/`, `OUTPUT/`, `JOBS/`, `anteprime/` and `registri/` aren't tracked by git, so they're left alone.

**From the zip**: unzip the new version into a new folder, then move your data across from the old one before you launch it:

| Move this folder | Because it holds |
|---|---|
| `INPUT/` | Your sources. |
| `OUTPUT/` | Your finished files. |
| `JOBS/` | Interrupted jobs you want to resume. |
| `registri/` | Your settings, the job history that refines the estimates, and your calibration. |

`anteprime/` (the Compare cache) can come too, or be left behind: it's regenerated on demand.

!!! note "Coming from 1.3.2 or earlier"
    Until version 1.3.2 the jobs folder was called `LAVORAZIONI/`. Since the interface is in English it's called `JOBS/`. You don't need to do anything: on launch, if `LAVORAZIONI/` exists and `JOBS/` doesn't, AnimeUp renames it, and your interrupted jobs stay where it looks for them.

## Before you move on

!!! success "Check"
    - [ ] The interface is open at <http://localhost:8899> and shows the three tabs **Sources**, **Compare** and **Processing**.
    - [ ] The Terminal window is still open behind it.
    - [ ] The sidebar doesn't report system dependencies (or `./animeup doctor` says the folder is self-contained).
    - [ ] You know that closing the Terminal stops the interface but not a running job.

[Next: 02. Calibrate your Mac →](02-calibration.md)
