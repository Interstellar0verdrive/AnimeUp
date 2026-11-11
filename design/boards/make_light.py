#!/usr/bin/env python3
"""Light twins of the AnimeUp design boards.

The design file (Claude Design artifact "AnimeUp home redesign") keeps every
board as `project/<Name>.dc.html`. Each board defines its palette once, as CSS
custom properties on its root div (`--desk:…;--bg:…`). A light twin is the same
board with:

1. the root palette replaced by the approved light palette (LIGHT below, taken
   from the published DSFoundationsLight board, accent C1 and red included);
2. the few colours written by hand outside the palette mapped by RULES, each
   with the reason it changes or stays;
3. the title and visible "dark" captions switched to "light".

Usage
  make_light.py boards  <in_dir> <out_dir> [Name …]   write <Name>Light.dc.html
  make_light.py audit   <dir> [Name …]                list hand-written colours left
  make_light.py canvas  <canvas.json> <out.json>      add the "Native screens · light" page
  make_light.py contrast                              WCAG ratios of the light text tokens

Boards are read from a local copy (download them with the Artifact tool, action
"read", `paths` = project/<Name>.dc.html). Nothing here talks to the network.
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

DARK = ("--desk:#2A2D33;--bg:#101113;--side:rgba(30,33,38,.78);--surface:#16181B;--raised:#1C1F23;"
        "--surface-hover:#1C1F23;--inset:rgba(0,0,0,.25);--control:#1C1F23;--glass:rgba(255,255,255,.07);"
        "--glass-hover:rgba(255,255,255,.11);--glass-press:rgba(255,255,255,.15);--glass-line:rgba(255,255,255,.10);"
        "--line:#26292E;--text:#E8EAED;--text-2:#9BA1A9;--text-3:#80868E;--text-code:#C6CBD2;--primary:#2AC9DE;"
        "--primary-hover:#4FD5E7;--primary-press:#1FB0C4;--on-primary:#06252A;--primary-text:#2AC9DE;"
        "--focus:rgba(42,201,222,.5);--sel:rgba(42,201,222,.16);--soft:rgba(42,201,222,.07);"
        "--soft-line:rgba(42,201,222,.28);--track:#2A2E34;--track-soft:rgba(255,255,255,.14);--green:#3DD68C;"
        "--green-text:#7FE3AC;--green-bg:rgba(18,161,80,.12);--green-line:rgba(61,214,140,.35);--yellow:#F2B84B;"
        "--yellow-hover:#F5C76E;--yellow-text:#F5CB78;--yellow-bg:#2A2110;--yellow-line:rgba(242,184,75,.45);"
        "--on-yellow:#2A1C00;--red:#CD3725;--red-hover:#D83A27;--red-press:#B63121;--red-text:#F59B9B;"
        "--red-bg:rgba(242,109,109,.10);--red-bg-press:rgba(242,109,109,.17);--red-line:rgba(242,109,109,.55);"
        "--red-soft:rgba(242,109,109,.07);--red-tint:rgba(242,109,109,.16);--yellow-tint:rgba(242,184,75,.16);"
        "--green-tint:rgba(61,214,140,.16);--seg-on:#3A3E44;--chip-bg:#1C1F23;--chip-line:rgba(255,255,255,.10);"
        "--alert-bg:rgba(38,41,46,.92);--alert-shadow:rgba(0,0,0,.6);--box-line:rgba(255,255,255,.22);"
        "--seg-shadow:rgba(0,0,0,.4)")

LIGHT = ("--desk:#D9DDE3;--bg:#F6F7F9;--side:rgba(236,238,241,.82);--surface:#FFFFFF;--raised:#EEF0F2;"
         "--surface-hover:#F3F4F6;--inset:rgba(0,0,0,.04);--control:#FFFFFF;--glass:rgba(0,0,0,.04);"
         "--glass-hover:rgba(0,0,0,.07);--glass-press:rgba(0,0,0,.11);--glass-line:rgba(0,0,0,.12);"
         "--line:#E1E4E8;--text:#16181B;--text-2:#5C626A;--text-3:#656B73;--text-code:#3A3F46;--primary:#0275B6;"
         "--primary-hover:#067CC1;--primary-press:#056AA5;--on-primary:#FFFFFF;--primary-text:#206CA1;"
         "--focus:rgba(39,147,219,.45);--sel:rgba(39,147,219,.14);--soft:rgba(39,147,219,.07);"
         "--soft-line:rgba(39,147,219,.28);--track:#DADDE2;--track-soft:rgba(0,0,0,.10);--green:#12A150;"
         "--green-text:#146C3E;--green-bg:#E6F5EC;--green-line:rgba(18,161,80,.35);--yellow:#F5B400;"
         "--yellow-hover:#FFC21F;--yellow-text:#7F5300;--yellow-bg:#FFF0C4;--yellow-line:rgba(245,180,0,.45);"
         "--on-yellow:#2A1C00;--red:#CD3725;--red-hover:#D83A27;--red-press:#B63121;--red-text:#B42323;"
         "--red-bg:#FDECEA;--red-bg-press:#FADAD6;--red-line:rgba(217,64,46,.45);--red-soft:rgba(217,64,46,.05);"
         "--red-tint:rgba(217,64,46,.12);--yellow-tint:rgba(245,180,0,.22);--green-tint:rgba(18,161,80,.14);"
         "--seg-on:#FFFFFF;--chip-bg:#EEF0F2;--chip-line:rgba(0,0,0,.08);--alert-bg:rgba(246,247,249,.96);"
         "--alert-shadow:rgba(16,24,40,.28);--box-line:rgba(0,0,0,.25);--seg-shadow:rgba(0,0,0,.15)")

# Light values I drew for surfaces the palette does not name yet. They go into
# Tokens.swift as AU.sheet / AU.alert / AU.menu once the boards are approved.
SHEET_L = "#F3F4F6"   # sheets: a step below white, so the white cards inside them read as cards
ALERT_L = "#F6F7F9"   # AnimeUp's own alerts: the window ground, lifted by the shadow
MENU_L = "rgba(246,246,248,.97)"  # pop-up menus, as in DSControlsLight

KEEP = "keep"
# (regex, replacement, reason). Applied in order to everything except the root
# palette block. A replacement of KEEP documents a colour that stays as it is.
RULES = [
    # --- kept in both themes -------------------------------------------------
    (r"#FF5F57|#FEBC2E|#28C840", KEEP, "window traffic lights: system colours, same in light"),
    (r"background:#000\b", KEEP, "video frames: a picture is black behind, whatever the theme"),
    (r"mask-image:linear-gradient\(to bottom,#000", KEEP, "masks: only the alpha counts"),
    (r"\.dsol\{background:var\(--red\);color:#fff\}", KEEP, "white on the red button, both themes"),
    (r"background:rgba\(0,0,0,\.(55|6)\);color:#fff", KEEP, "captions laid on a video frame"),
    (r"box-shadow:0 0 0 1px rgba\(255,255,255,\.25\)", KEEP, "ring of a caption on a video frame"),
    (r"background:rgba\(255,255,255,\.18\)", KEEP, "key cap inside a video caption"),
    (r"border-radius:8px;background:#fff;box-shadow:0 1px 3px rgba\(0,0,0,\.45\)", KEEP,
     "slider knob and its shadow: white in both themes"),
    (r"background:#fff;box-shadow:0 2px 8px rgba\(0,0,0,\.4\)", KEEP, "before/after handle on a video frame"),
    (r"color:#16181B;font-size:11px;font-weight:700", KEEP, "arrows on the white before/after handle"),
    (r"border-radius:4px;background:rgba\(0,0,0,\.45\);overflow:hidden", KEEP, "progress bar drawn over the Dock icon"),
    (r"background:#FF3B30", KEEP, "Dock badge: system red"),

    # --- accent C1 -------------------------------------------------------------
    (r"rgba\(42,201,222,", "rgba(39,147,219,", "accent glow (breathe) and tints follow C1 light"),

    # --- surfaces --------------------------------------------------------------
    (r"background:#22252A", "background:" + SHEET_L, "sheets (AU.sheet)"),
    (r"background:#26292E", "background:" + ALERT_L, "AnimeUp alerts (AU.alert)"),
    (r"background:rgba\((44,47,53,\.97|48,51,56,\.96)\)", "background:" + MENU_L, "menus"),
    (r"background:#2A2D33", "background:#FFFFFF", "floating button over a list"),
    (r"background:#1E2024", "background:#FFFFFF", "open panel (macOS light)"),
    (r"var\(--side,#1B1D21\)", "var(--side,#ECEEF1)", "sidebar fallback"),
    (r"background:rgba\(20,22,26,\.9\)", "background:rgba(255,255,255,.94)", "toast pill"),
    (r"background:rgba\(40,43,48,\.88\)", "background:rgba(246,246,248,.86)", "notification banner (macOS light)"),
    (r"background:rgba\(30,32,36,\.85\)", "background:rgba(246,246,248,.8)", "menu bar (macOS light)"),
    (r"radial-gradient\(circle at 20% 20%,#3b4a6b,#1d2230 60%\)",
     "radial-gradient(circle at 20% 20%,#DCE6F7,#A9B9D6 60%)", "desktop wallpaper: a light one"),
    (r"background:#4BA3F5;color:#fff", "background:#0A6FE0;color:#fff", "selected row of the open panel"),
    (r"color:#4BA3F5", "color:#1E8CF0", "folder icon (macOS light)"),
    (r"background:#0A84FF", "background:#007AFF", "system blue button, light"),
    (r"inset:0;background:rgba\(0,0,0,\.55\)", "inset:0;background:rgba(16,24,40,.22)", "scrim behind a sheet"),
    (r"inset:0;background:rgba\(0,0,0,\.35\)", "inset:0;background:rgba(16,24,40,.14)", "lighter scrim"),
    (r"rgba\(255,255,255,\.(035|03|05|07|08|10|12|16)\)", lambda m: f"rgba(0,0,0,.{m.group(1)})",
     "white veils and hairlines become black ones of the same strength"),

    # --- text ------------------------------------------------------------------
    (r"color:#c9d1e0", "color:#3A3F46", "captions on the desk and the toast (text-code)"),

    # --- shadows: black at half strength, slightly blue as in --alert-shadow ---
    (r"(box-shadow:[^;\"]*?)rgba\(0,0,0,(\.\d+)\)", None, "shadows at half strength"),
]


def _shadow(m):
    a = float(m.group(2))
    return f"{m.group(1)}rgba(16,24,40,{round(a * 0.5, 2):g})".replace(",0.", ",.")


ROOT = re.compile(r'(<div style=")(--desk:[^"]*)(">)')


def light_board(html: str) -> str:
    m = ROOT.search(html)
    if not m:
        raise ValueError("no root palette block")
    keys = lambda b: [k for k, _ in re.findall(r"--([\w-]+):([^;]+)", b)]
    if keys(m.group(2)) != keys(DARK):
        # values may be older (e.g. the red before #CD3725); the names must match
        raise ValueError("root palette has other variables than the known dark palette")
    head, root, tail = html[:m.start()], m.group(0), html[m.end():]
    body = head + "\x00ROOT\x00" + tail
    # Protect what is kept, so later rules cannot touch it.
    kept = []

    def hold(mm):
        kept.append(mm.group(0))
        return f"\x00K{len(kept) - 1}\x00"

    for rx, rep, _ in RULES:
        if rep == KEEP:
            body = re.sub(rx, hold, body)
    for rx, rep, _ in RULES:
        if rep == KEEP:
            continue
        if rep is None:
            # several shadows may share one property
            prev = None
            while prev != body:
                prev = body
                body = re.sub(rx, _shadow, body)
        else:
            body = re.sub(rx, rep, body)
    body = re.sub(r"\x00K(\d+)\x00", lambda mm: kept[int(mm.group(1))], body)
    body = body.replace("\x00ROOT\x00", ROOT.sub(lambda mm: mm.group(1) + LIGHT + mm.group(3), root))
    body = re.sub(r"<title>(.*?)</title>", lambda mm: f"<title>{mm.group(1)} (light)</title>", body, count=1)
    body = body.replace("· dark<", "· light<")
    return body


COL = re.compile(r"#[0-9A-Fa-f]{6}\b|#[0-9A-Fa-f]{3}\b|rgba?\([^)]*\)")


def audit(paths):
    cnt, where = Counter(), {}
    for p in paths:
        s = ROOT.sub("", Path(p).read_text())
        s = re.sub(r"data:image/[^\"')]+", "", s)
        for m in COL.finditer(s):
            c = re.sub(r"\s", "", m.group(0))
            cnt[c] += 1
            where.setdefault(c, set()).add(Path(p).name.replace(".dc.html", ""))
    for c, n in cnt.most_common():
        print(f"{n:5} {c:28} {len(where[c]):3} {', '.join(sorted(where[c])[:4])}")


def canvas(src, dst, gap_y=0):
    c = json.loads(Path(src).read_text())
    if not any(p["id"] == "screens-light" for p in c["pages"]):
        i = next(i for i, p in enumerate(c["pages"]) if p["id"] == "screens")
        c["pages"].insert(i + 1, {"id": "screens-light", "name": "Native screens · light"})
    for name, b in list(c["boards"].items()):
        if b.get("page") != "screens":
            continue
        ln = name.replace(".dc.html", "Light.dc.html")
        nb = dict(b, page="screens-light", title=b["title"].replace("· dark", "· light"))
        c["boards"][ln] = nb
        if ln not in c["order"]:
            c["order"].append(ln)
    for k, n in list(c["notes"].items()):
        if n.get("page") == "screens":
            c["notes"][k + "-light"] = dict(n, page="screens-light", text=n["text"] + " · light")
    Path(dst).write_text(json.dumps(c, ensure_ascii=False, indent=1))


def _lum(hexc):
    v = [int(hexc[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    v = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in v]
    return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]


def _over(fg_rgba, bg_hex):
    r, g, b, a = fg_rgba
    bb = [int(bg_hex[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * a + y * (1 - a)):02X}" for x, y in zip((r, g, b), bb))


def ratio(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def contrast():
    t = dict(re.findall(r"--([\w-]+):([^;]+)", LIGHT))
    grounds = {"bg": t["bg"], "surface": t["surface"], "raised": t["raised"], "sheet": SHEET_L, "alert": ALERT_L}
    tints = {"sel": (39, 147, 219, .14), "soft": (39, 147, 219, .07), "red-tint": (217, 64, 46, .12),
             "yellow-tint": (245, 180, 0, .22), "green-tint": (18, 161, 80, .14)}
    for k, v in tints.items():
        grounds[k + "/surface"] = _over(v, t["surface"])
    grounds.update({"green-bg": t["green-bg"], "yellow-bg": t["yellow-bg"], "red-bg": t["red-bg"]})
    texts = ["text", "text-2", "text-3", "text-code", "primary-text", "green-text", "yellow-text", "red-text"]
    fails = 0
    print("text \\ ground".ljust(14) + "".join(g[:12].rjust(13) for g in grounds))
    for x in texts:
        row = []
        for g in grounds.values():
            r = ratio(t[x], g)
            fails += r < 4.5
            row.append(f"{r:5.2f}{'*' if r < 4.5 else ' '}".rjust(13))
        print(x.ljust(14) + "".join(row))
    for fg, bg in [("on-primary", "primary"), ("on-primary", "primary-hover"), ("on-primary", "primary-press"),
                   ("on-yellow", "yellow")]:
        print(f"{fg} on {bg}: {ratio(t[fg], t[bg]):.2f}")
    print(f"white on red: {ratio('#FFFFFF', t['red']):.2f}, on red-hover {ratio('#FFFFFF', t['red-hover']):.2f}")
    print(f"{fails} pairs under 4.5 (*)")


if __name__ == "__main__":
    cmd, *a = sys.argv[1:] or ["help"]
    if cmd == "boards":
        src, dst, *names = a
        dst = Path(dst)
        dst.mkdir(parents=True, exist_ok=True)
        files = [Path(src) / f"{n}.dc.html" for n in names] if names else sorted(Path(src).glob("*.dc.html"))
        for f in files:
            if f.stem.endswith("Light.dc"):
                continue
            out = dst / f.name.replace(".dc.html", "Light.dc.html")
            out.write_text(light_board(f.read_text()))
        print(f"{len(files)} boards → {dst}")
    elif cmd == "audit":
        d, *names = a
        audit([Path(d) / f"{n}.dc.html" for n in names] if names else sorted(Path(d).glob("*.dc.html")))
    elif cmd == "canvas":
        canvas(*a)
    elif cmd == "contrast":
        contrast()
    else:
        print(__doc__)
