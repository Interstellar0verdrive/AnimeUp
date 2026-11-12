#!/usr/bin/env python3
"""The guide's animated Queue rows as 7 s seamless loops (MP4 + WebM, 2x).

    export_rows.py <render dir> <out dir> <ffmpeg> [suffix]

Renders each `<Board>Light.dc.html` (or the board as named, with suffix "")
frame by frame in headless Chrome: every CSS animation is paused and set to
the frame's time, so the loop is exact. The wave runs 3.5 s instead of 3.4 so
that 7 s holds two of it and five breaths of 1.4 s.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ROWS = {"GuideRow": (760, 200), "GuideRowLeft": (760, 230), "GuideRowRight": (760, 230)}
FPS, SECONDS = 25, 7

FREEZE = """<style>[style*="wavefix 3.4s"]{animation-duration:3.5s!important}</style>
<script>addEventListener('load',()=>{const t=+location.hash.slice(1);
document.getAnimations().forEach(a=>{a.pause();a.currentTime=t})})</script></body>"""


def main(render: Path, out: Path, ffmpeg: str, suffix: str = "Light") -> None:
    for board, (w, h) in ROWS.items():
        src = render / f"{board}{suffix}.dc.html"
        page = render / f"_frames_{board}.html"
        page.write_text(src.read_text().replace("</body>", FREEZE, 1))
        name = f"{board}-light" if suffix else board
        with tempfile.TemporaryDirectory() as t:
            for i in range(FPS * SECONDS):
                ms = i * 1000 / FPS
                subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                                "--allow-file-access-from-files", "--force-device-scale-factor=2",
                                f"--window-size={w},{h}", "--virtual-time-budget=500",
                                f"--screenshot={t}/f{i:04d}.png", f"{page.as_uri()}#{ms}"],
                               check=True, capture_output=True)
            frames = ["-framerate", str(FPS), "-i", f"{t}/f%04d.png"]
            subprocess.run([ffmpeg, "-y", "-loglevel", "error", *frames, "-c:v", "libx264", "-profile:v", "high",
                            "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart", str(out / f"{name}.mp4")], check=True)
            subprocess.run([ffmpeg, "-y", "-loglevel", "error", *frames, "-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p",
                            "-crf", "34", "-b:v", "0", str(out / f"{name}.webm")], check=True)
        page.unlink()
        print(name, (out / f"{name}.mp4").stat().st_size // 1024, "KB mp4,", (out / f"{name}.webm").stat().st_size // 1024, "KB webm")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], *(sys.argv[4:5]))
