---
title: 01. Install and first launch
description: Download AnimeUp, get past Gatekeeper, and understand what the first launch sets up.
---

<span class="eyebrow">Step 01 · Install</span>

# 01. Install and first launch

Install the app (or the portable folder), approve it once in macOS, and let the first launch download AnimeUp's tools.

## Choose how to get it

| | **The app** (recommended) | The portable folder | From source (`git clone`) |
|---|---|---|---|
| For | Most people | Running from an external drive, or from the Terminal | Following development |
| You get | `AnimeUp.app`, a normal Mac app with its own window | A folder you open with `Start AnimeUp.command`; the interface opens in your browser | The repository |
| Your videos (`INPUT/`, `OUTPUT/`) | `~/Movies/AnimeUp` (each folder changeable in the sidebar) | Inside the folder | Inside the folder |
| AnimeUp's own data, tools and Python | `~/Library/Application Support/AnimeUp` | Inside the folder | Inside the folder |
| Gatekeeper prompt | Yes, once | Yes, once | No |
| Updating | Replace the app | Download the new zip | `git pull` |

Every third-party download comes from a pinned official release and is verified with SHA256, FFmpeg included (release 9.0.2, which is also checked for the encoders and filters AnimeUp needs).

## Install the app

1. Download `AnimeUp-<version>-macos-app.zip` from the [latest release](https://github.com/Interstellar0verdrive/AnimeUp/releases/latest) and unzip it.
2. **Drag `AnimeUp.app` into Applications.** Don't run it from Downloads: until it's approved, macOS starts an app from a temporary read-only copy (a security feature called App Translocation).
3. Open it. macOS refuses, because AnimeUp isn't signed by an identified developer: the project has no paid Apple Developer account. Close the warning.
4. Open **System Settings → Privacy & Security**, scroll down to the message about AnimeUp and click **Open Anyway**. Confirm with your password or Touch ID if asked.
5. AnimeUp opens. From now on it opens normally.

<!-- IMG: macOS System Settings → Privacy & Security with the "Open Anyway" button for AnimeUp -->

!!! note "Right-click → Open no longer works"
    On older macOS versions you could bypass the warning with right-click → Open. Recent versions (macOS 15 Sequoia and later) only allow **Open Anyway** in Privacy & Security.

### The app's first launch

1. A small window says **Preparing AnimeUp…**, with the step it's on underneath: it downloads uv and a private Python runtime and installs AnimeUp's dependencies. It needs an internet connection and takes about a minute.
2. The main window opens on **Welcome to AnimeUp**. It lists what's still missing (FFmpeg 9.0.2 and the Real-ESRGAN/Real-CUGAN engines with their models, about 180 MB) and offers **Download and continue**. The download runs from the official releases and is verified by checksum.
3. When it's done, the normal interface appears. From now on AnimeUp works offline.

If something goes wrong in step 1, a window shows the last lines of the log with **Try Again**, **Open Log** and **Quit**. The log is `~/Library/Application Support/AnimeUp/logs/app.log`.

### Where the app keeps things

| What | Where |
|---|---|
| The videos to process | `~/Movies/AnimeUp/INPUT`, or the folder you choose in the sidebar as **Videos to process folder** |
| The finished videos, with each file's log (`logs/`) and the jobs in progress or interrupted (`JOBS/`) | `~/Movies/AnimeUp/OUTPUT`, or the folder you choose in the sidebar as **Finished videos folder** |
| AnimeUp's own data: history, settings, calibration (`records/`) and caches (`cache/`) | `~/Library/Application Support/AnimeUp` |
| Python, its environment, FFmpeg, the upscalers and their models | `~/Library/Application Support/AnimeUp` (about 1 GB) |
| The program | `AnimeUp.app`, which is never modified |

Each of the two video folders can be on an external drive. AnimeUp switches to a new choice right away and remembers it until you change it. If a chosen folder isn't available at launch, for example on a disconnected drive, AnimeUp uses the default one and says so in the sidebar. [07. Output files and folders](07-output-and-folders.md#where-animeup-keeps-things) has the full list.

The app runs its interface on port 8898, reachable only from this Mac, so it can run alongside the portable folder (port 8899).

### Using and updating the app

- **Closing the window** doesn't quit AnimeUp: it keeps running in the background, jobs included. Click its icon in the Dock to bring the window back.
- **Quit** with **⌘Q** (or **AnimeUp → Quit AnimeUp**). If a job is running, AnimeUp asks first: quitting stops the job and the rest of the queue. The work done so far is kept, so you can resume it later.
- **File → Open Videos to Process Folder** (⇧⌘O) and **File → Open Finished Videos Folder** (⇧⌘F) show your videos in Finder; **File → Open in Browser** opens the same interface in your browser; **File → Show Log** opens the app's log.
- **Updating**: once a day AnimeUp asks GitHub for the latest release and, if there's a newer one, shows a note at the top of the sidebar with an **Install update** button (you can turn the check off with **Check for updates**). Click it and confirm: AnimeUp downloads the new app from the GitHub release, checks it against the SHA256 checksum GitHub publishes for that file, checks the app inside (identifier, version, signature), replaces itself and restarts. Jobs in progress keep running; your files, settings and calibration are untouched.

    !!! tip "No new approval needed"
        macOS asks for **Open Anyway** again for every version downloaded with a browser, because the browser marks the file as downloaded from the internet. An update installed by AnimeUp itself carries no such mark, so it opens straight away. This needs the app to be in a folder you can write to (Applications is fine) and not running from Downloads.

    You can still update by hand: quit AnimeUp and replace `AnimeUp.app` in Applications with the one from the new release zip (then you'll have to approve it once in Privacy & Security).
- **Removing** AnimeUp: delete the app, then `~/Library/Application Support/AnimeUp` (tools, Python, history, settings and calibration) and, if you no longer want them, your videos in `~/Movies/AnimeUp` (or in the folders you chose).

## The portable folder

The rest of this page is about the portable folder and the source checkout: the same program, run from a folder you choose.

1. Download `AnimeUp-<version>-macos-arm64.zip` from the [latest release](https://github.com/Interstellar0verdrive/AnimeUp/releases/latest) and unzip it where you want AnimeUp to live: anywhere you can write to, external drives included. Choose a disk with room to spare: a single episode can temporarily take tens of GB in `OUTPUT/JOBS/`.
2. Double-click **`Start AnimeUp.command`** and follow [The first launch](#the-first-launch).

From source:

```bash
git clone https://github.com/Interstellar0verdrive/AnimeUp.git
cd AnimeUp
./animeup setup     # downloads FFmpeg, Real-ESRGAN, Real-CUGAN and the models into bin/
./animeup ui
```

You can also skip the two commands and double-click **`Start AnimeUp.command`**: it runs `setup` by itself when something is missing from `bin/`. If you have no `uv` on your system, the launcher downloads it too.

## Get past Gatekeeper

The first time you double-click **`Start AnimeUp.command`** from the zip, macOS refuses to open it, because the script isn't signed by an identified developer. This is expected.

1. Close the warning.
2. Open **System Settings → Privacy & Security**.
3. Scroll down to the message about `Start AnimeUp.command` and click **Open Anyway**.
4. Confirm. From now on the file opens with a normal double-click.


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

!!! tip "Keeping your videos elsewhere"
    In the portable folder the folders are chosen with environment variables, from the Terminal: `ANIMEUP_INPUT` for the videos to process, `ANIMEUP_OUTPUT` for the finished videos (and their jobs), `ANIMEUP_ROOT` for a base folder that holds both. AnimeUp's own data stays in the AnimeUp folder. See [07. Output files and folders](07-output-and-folders.md#choosing-the-folders-from-the-terminal).

## Updating from an older version

**From a `git clone`**: run `git pull` in the AnimeUp folder, then relaunch. Your `INPUT/`, `OUTPUT/`, `records/` and `cache/` aren't tracked by git, so they're left alone.

**From the zip**: unzip the new version into a new folder, then move your data across from the old one before you launch it:

| Move this folder | Because it holds |
|---|---|
| `INPUT/` | Your sources. |
| `OUTPUT/` | Your finished files, their logs, and in `OUTPUT/JOBS/` the interrupted jobs you want to resume. |
| `records/` | Your settings, the job history that refines the estimates, and your calibration. |

`cache/` (source analyses and the Compare clips) can come too, or be left behind: it's regenerated on demand.

!!! note "Coming from 1.5 or earlier"
    An old folder has `INPUT/`, `OUTPUT/`, `JOBS/`, `anteprime/` and `registri/`. Move `INPUT/`, `OUTPUT/`, `JOBS/` and `registri/` into the new folder as they are: on the first launch AnimeUp moves them into the 1.6 layout by itself. See [Upgrading from 1.5](07-output-and-folders.md#upgrading-from-15).

!!! note "Coming from 1.3.2 or earlier"
    Until version 1.3.2 the jobs folder was called `LAVORAZIONI/`. Since the interface is in English it's called `JOBS/`. You don't need to do anything: on launch, if `LAVORAZIONI/` exists and `JOBS/` doesn't, AnimeUp renames it and then moves it into `OUTPUT/` like any other old `JOBS/`, and your interrupted jobs stay resumable.

## Before you move on

!!! success "Check"
    - [ ] The interface is open at <http://localhost:8899> and shows the three tabs **Sources**, **Compare** and **Processing**.
    - [ ] The Terminal window is still open behind it.
    - [ ] The sidebar doesn't report system dependencies (or `./animeup doctor` says the folder is self-contained).
    - [ ] You know that closing the Terminal stops the interface but not a running job.

[Next: 02. Calibrate your Mac →](02-calibration.md)
