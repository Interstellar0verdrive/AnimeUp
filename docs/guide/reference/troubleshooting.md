---
title: Troubleshooting
description: Symptoms, what they mean and how to fix them, from the first launch to finished videos.
---

<span class="eyebrow">Reference · Troubleshooting</span>

# Troubleshooting

Find the symptom, read what it means, apply the fix. Nothing on this page can damage your videos: AnimeUp only reads the originals.

!!! tip "Where the details are"
    Every processed file has its log: **Show Log** in its drawer, or `logs/` in the work folder. AnimeUp's own log opens with **Help › Open Log in Console**. **Help › Report a Problem…** opens a new issue on GitHub.

## Installing and the first launch

| Symptom | What it means | What to do |
|---|---|---|
| macOS says AnimeUp can't be opened | AnimeUp isn't signed with an Apple Developer ID. | **System Settings › Privacy & Security › Open Anyway**. See [01. Install](../01-install.md#install-the-app). |
| The video tools window says **The download stopped** | The connection dropped. | **Try Again**: it picks up from where it stopped. |
| A tool **arrived damaged, so it was set aside** | The download didn't match its published checksum. | **Try Again**. If it keeps happening, check the connection (a proxy or captive portal can alter downloads). |
| **The engine didn't start** | AnimeUp's background engine couldn't start, or stopped several times in a row. | **Show Log** says why. Quit and reopen AnimeUp; if it persists, report it with the log. |
| The tools window comes back on its own | A tool went missing, its models are gone, or FFmpeg isn't the version AnimeUp expects. | Let it download that tool again. |

## Adding videos

| Symptom | What it means | What to do |
|---|---|---|
| **No videos in "folder"** | Nothing AnimeUp recognises in that folder. | **Look in Subfolders**, or check the files' format. |
| **That video is already in the Queue** | Adding the same file twice changes nothing. Videos AnimeUp made itself are always left out. | Nothing to do. |
| A file says **can't be processed** | It's interlaced or telecined, unreadable, or has no video track. Its Source tab says which. | Prepare it with a dedicated tool (deinterlacing, inverse telecine), then add the result. |
| A note says the file is **probably truncated** | The video stops before the duration its container declares. | The output would stop there too: get a complete copy if you can. |
| A file changed but its report didn't | Reports are kept per file. | **Re-analyse** on its row (⌘R). |
| **The file is no longer where it was added from** | It was moved or renamed, or its disk is disconnected. | Put it back, or remove it and add it again. |

## Folders and disks

| Symptom | What it means | What to do |
|---|---|---|
| **AnimeUp can't write in "folder"** | macOS doesn't allow changes there. | Pick another folder, or check its permissions in the Finder (Get Info). |
| **Work files need a folder of their own** | The work folder is inside the finished videos' folder. | Pick one outside it, so cleaning up never touches a finished video. |
| **The work disk isn't connected** | The disk with the work folder was disconnected. | Connect it: the queue waits, nothing is lost. |
| A yellow note under **Space AnimeUp may use there** says how little the disk has left | Work files need tens of GB, and the system needs some room too. | Free up some space, or choose a work folder on another disk. |
| A file waits before starting | It would go past **Space AnimeUp may use there**. | Free some space, or raise the limit in Start or Settings › Folders. |
| A plan's note starts with **Tight on space** | The space per file is lower than ideal. | Nothing: it's only a bit slower. More space means fewer chunks. |

## Processing

| Symptom | What it means | What to do |
|---|---|---|
| **Start Processing** is greyed out | Nothing is ticked, a queue is already running, or a calibration is using the GPU. | Tick some files, or wait. |
| A model says it **can't reach** the output height | That model only exists at 2×, which isn't enough from this source. | Pick another model, or lower this file's height. |
| A row says **interrupted** | The file was stopped, AnimeUp was quit, or the Mac shut down. | **Resume** continues from the chunk it was in; **Discard** throws the work away. |
| A file **failed** | The upscaler or the encoder stopped with an error. Its outcome says where. | Open its log; tick it to try again. If it fails at the same point, report it with the log. |
| A `….DEFECTIVE.mkv` appears where the finished video would be | The final checks found a problem (frames, size, audio), so the video was set aside. | Process the file again. |
| The work folder takes a lot of space | Interrupted files keep their work, or **Keep everything** is on. | Resume or **Discard** interrupted files; check Settings › Folders. |
| Estimates are far from the real time | The Mac isn't calibrated, or the material is unusual. | [Calibrate](../03-calibration.md). Estimates also learn from every finished file. |

## Compare

| Symptom | What it means | What to do |
|---|---|---|
| **The GPU is busy with the processing queue** | The test waits for the queue. | Wait, or **Pause the Queue**. |
| **The test stopped** | It was stopped, or a version failed. | **Render the Rest** fills the gaps; what finished stays. |
| **No clips to test in this file** | Nothing in it stands out, or it's shorter than one clip. | Pick another file; this file's model can still be chosen in the Queue. |
| A model is **not available for this file** | It only exists at 2× and can't reach the output height. | Lower this file's output height to try it. |

## Calibration

| Symptom | What it means | What to do |
|---|---|---|
| **Calibrate after the queue** | Timing the models while the queue uses the GPU would give wrong numbers. | Calibrate when the queue finishes. |
| **Calibration didn't finish** | One step stopped with an error. Nothing was saved. | Close other apps and try again. |
| The new numbers are much lower than before | Something else used the GPU or CPU, or a laptop ran on battery. | Close other apps, plug in, calibrate again. |
| The sidebar says **From another Mac** | The settings folder was copied from a different Mac. | Calibrate this one. |

[Next: How a job works inside →](../deep-dives/how-it-works.md)
