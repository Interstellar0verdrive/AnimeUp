#!/usr/bin/env python3
"""Export the light twins of the guide's pictures, from the design file's boards.

    export_light.py <render dir> <docs dir>

<render dir> holds the light boards (`<Name>Light.dc.html`, from
`make_light.py boards`), the design file's `gassets/` beside them, and gets
`gassets/scr2light/` (light thumbnails of the screens, for the board that shows
every screen on one plane). Pictures go to <docs dir>/guide/img/v2 and
<docs dir>/images, named like the dark ones with `-light` (`GuideStart-light.webp`,
`ds-bar-light.webp`).

Rendering: headless Chrome at 3x (2x for the animated rows and the README), the
board's own size from the canvas. WebP rule of the guide: near-lossless 60 or
lossless, whichever is smaller; never lossy.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# board → (picture without extension, scale, folder)
GUIDE = {f"Guide{n}": (f"Guide{n}-light", 3, "guide") for n in (
    "Bar CalResults CalRunning Calibrate Compare Done Failed Finished RedoNew RedoSame "
    "Settings Start Tools Window SpotAddVideos SpotCalibrate SpotCompare SpotProcess").split()}
GUIDE.update({
    "GuideRow": ("GuideRow-light", 2, "guide"),
    "GuideRowLeft": ("GuideRowLeft-light", 2, "guide"),
    "GuideRowRight": ("GuideRowRight-light", 2, "guide"),
    "GuideAllScreens3": ("all-screens-plane-light", 3, "guide"),
    "GuideDsBar": ("ds-bar-light", 3, "guide"),
    "GuideDsButtons2": ("ds-buttons-light", 3, "guide"),
    "GuideDsCharts": ("ds-charts-light", 3, "guide"),
    "GuideDsChips": ("ds-chips-light", 3, "guide"),
    "GuideDsColour2": ("ds-colours-light", 3, "guide"),
    "GuideDsContrast": ("ds-contrast-light", 3, "guide"),
    "GuideDsIcons": ("ds-icons-light", 3, "guide"),
    "GuideDsTimes": ("ds-queue-card-light", 3, "guide"),
    "GuideDsResponsive": ("ds-responsive-light", 3, "guide"),
    "GuideDsStates2": ("ds-states-light", 3, "guide"),
    "GuideDsType": ("ds-type-light", 3, "guide"),
    "GuideScreens": ("narrow-clips-and-queue-light", 3, "guide"),
    "GuideRenewalA": ("renewal-16d-light", 3, "guide"),
    "GuideRenewalB": ("renewal-20d-light", 3, "guide"),
    "GuideScreens3": ("app-start-calibration-light", 2, "images"),
})
GUIDE.update({f"GuideRule{i}": (f"rule-{i}-light", 3, "guide") for i in range(1, 10)})

# Screens shown as thumbnails on GuideAllScreens3 (window crop, 340 x 210).
THUMBS = """CalDetailsB CalDetailsB2 CalDetailsB3 CalibrationSheetA CalibrationSheetB CompareClips
CompareEdgeGpu CompareEdgeMany CompareEdgeModels CompareEdgeNoClips CompareEdgeReach CompareEdgeSource
CompareEdgeStopped CompareModels CompareResults2 CompareResults3 CompareRunning CompareUseMany FilesAfter
FilesAfterB FilesAfterC FilesAfterD FilesAfterE FilesAnalysing FilesEmpty FilesPaused FilesPlan FilesReady
FilesResting FilesRunning FilesRunningOpen FinishedSheet OpenPanel StartFiles StartFirst StartReady""".split()


def shot(url: str, w: int, h: int, scale: float, out: Path) -> None:
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--allow-file-access-from-files", f"--force-device-scale-factor={scale}",
                    f"--window-size={w},{h}", "--virtual-time-budget=3000",
                    f"--screenshot={out}", url], check=True, capture_output=True)


def webp(png: Path, out: Path) -> None:
    with tempfile.TemporaryDirectory() as t:
        a, b = Path(t, "a.webp"), Path(t, "b.webp")
        subprocess.run(["cwebp", "-quiet", "-near_lossless", "60", "-z", "9", "-exact", str(png), "-o", str(a)], check=True)
        subprocess.run(["cwebp", "-quiet", "-lossless", "-z", "9", "-exact", str(png), "-o", str(b)], check=True)
        shutil.copy(min((a, b), key=lambda p: p.stat().st_size), out)


def thumbs(render: Path) -> None:
    out = render / "gassets/scr2light"
    out.mkdir(parents=True, exist_ok=True)
    for name in THUMBS:
        page = render / f"_thumb_{name}.html"
        page.write_text(f"<html><body style='margin:0;overflow:hidden'><div style='width:340px;height:210px;overflow:hidden'>"
                        f"<iframe src='{name}Light.dc.html' scrolling=no style='border:0;width:1440px;height:900px;"
                        f"transform:scale(.25) translate(-40px,-30px);transform-origin:0 0'></iframe></div></body></html>")
        png = render / f"_thumb_{name}.png"
        shot(page.as_uri(), 340, 210, 1, png)
        subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "88", str(png), "--out",
                        str(out / f"{name}-0.jpg")], check=True, capture_output=True)
        png.unlink(); page.unlink()
    board = render / "GuideAllScreens3Light.dc.html"
    s = board.read_text().replace("gassets/scr2/CompareEdgeMany-sunset.jpg", "gassets/scr2light/CompareEdgeMany-0.jpg")
    board.write_text(s.replace("gassets/scr2/", "gassets/scr2light/"))


def main(render: Path, docs: Path, sizes: dict[str, tuple[int, int]]) -> None:
    thumbs(render)
    tmp = render / "_png"
    tmp.mkdir(exist_ok=True)
    for board, (pic, scale, folder) in GUIDE.items():
        w, h = sizes[board]
        png = tmp / f"{pic}.png"
        shot((render / f"{board}Light.dc.html").as_uri(), w, h, scale, png)
        dest = docs / ("guide/img/v2" if folder == "guide" else "images") / f"{pic}.webp"
        webp(png, dest)
        print(f"{dest.relative_to(docs)}  {dest.stat().st_size // 1024} KB")


if __name__ == "__main__":
    render, docs, canvas = map(Path, sys.argv[1:4])
    boards = json.loads(canvas.read_text())["boards"]
    main(render, docs, {k[:-8]: (v["w"], v["h"]) for k, v in boards.items()})
