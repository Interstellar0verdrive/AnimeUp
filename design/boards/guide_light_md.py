#!/usr/bin/env python3
"""Give every guide picture that has a light twin its theme switch.

    guide_light_md.py <docs dir>

Markdown pictures get `#only-dark` and a light twin with `#only-light` beside
them; videos and HTML pictures get the classes `au-only-dark` / `au-only-light`
(rules in extra.css). A picture whose twin doesn't exist is left alone.
Running it twice changes nothing.
"""
import re
import sys
from pathlib import Path

docs = Path(sys.argv[1])
img = docs / "guide/img/v2"


def twin(name: str) -> str | None:
    stem = name[:-5]
    light = stem[:-5] + "-light" if stem.endswith("-dark") else stem + "-light"
    return light + ".webp" if (img / f"{light}.webp").exists() else None


MD = re.compile(r"!\[([^\]]*)\]\(([^)\s#]*img/v2/)([A-Za-z0-9-]+\.webp)\)(\{[^}]*\})?")


def md(m):
    alt, path, name, attrs = m.group(1), m.group(2), m.group(3), m.group(4) or ""
    t = twin(name)
    if not t:
        return m.group(0)
    return f"![{alt}]({path}{name}#only-dark){attrs}\n![{alt}]({path}{t}#only-light){attrs}"


VIDEO = re.compile(r'<video class="au"([^>]*)poster="([^"]*img/v2/)(Guide\w+)\.webp"([^>]*)>(.*?)</video>', re.S)


def video(m):
    pre, path, name, post, body = m.groups()
    if not twin(name + ".webp"):
        return m.group(0)
    light = body.replace(f"{name}.webm", f"{name}-light.webm").replace(f"{name}.mp4", f"{name}-light.mp4")
    return (f'<video class="au au-only-dark"{pre}poster="{path}{name}.webp"{post}>{body}</video>\n'
            f'<video class="au au-only-light"{pre}poster="{path}{name}-light.webp"{post}>{light}</video>')


HTMLIMG = re.compile(r'<img src="([^"]*img/v2/)(renewal-20d-dark)\.webp"([^>]*)>')


def htmlimg(m):
    path, name, rest = m.groups()
    if not twin(name + ".webp"):
        return m.group(0)
    return (f'<img class="au-only-dark" src="{path}{name}.webp"{rest}>\n'
            f'  <img class="au-only-light" src="{path}renewal-20d-light.webp"{rest}>')


for f in sorted((docs / "guide").rglob("*.md")):
    s = f.read_text()
    if "#only-dark" in s or "au-only-dark" in s:
        print("already done:", f.relative_to(docs))
        continue
    n = MD.sub(md, s)
    n = VIDEO.sub(video, n)
    n = HTMLIMG.sub(htmlimg, n)
    if n != s:
        f.write_text(n)
        print("updated:", f.relative_to(docs))
