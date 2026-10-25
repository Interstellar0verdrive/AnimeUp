"""Inline the guide's SVG so its colors follow the selected site theme.

The image tag remains usable when the source file is read on GitHub.
"""

from pathlib import Path


_DIAGRAMS = {
    "guide/deep-dives/how-it-works.md": (
        '<img src="../img/job-flow.svg" width="440" height="1144" alt="Flow from the source file through analysis, planning, checks, extraction, deduplication, chunk processing, assembly and verification to the finished MKV">',
        "job-flow.svg",
    ),
    "guide/index.md": (
        '<img src="img/guide-path.svg" width="440" height="844" alt="Six steps to use AnimeUp: install, optionally calibrate your Mac, inspect sources, compare models, process the files, and collect the output. Each step shows its action and approximate time.">',
        "guide-path.svg",
    ),
}


def on_page_markdown(markdown, page, config, files):
    diagram = _DIAGRAMS.get(page.file.src_uri)
    if diagram is None:
        return markdown

    image, filename = diagram
    svg = (Path(config.docs_dir) / "guide/img" / filename).read_text(encoding="utf-8")
    return markdown.replace(image, f'<figure class="animeup-flow">\n{svg}\n</figure>', 1)
