"""Inline the guide's SVG so its colors follow the selected site theme.

The picture and image tags remain usable when the source files are read on GitHub.
"""

from pathlib import Path


_DIAGRAMS = {
    "guide/deep-dives/how-it-works.md": (
        '<img src="../img/job-flow.svg" width="440" height="1144" alt="Flow from the source file through analysis, planning, checks, extraction, deduplication, chunk processing, assembly and verification to the finished MKV">',
        "job-flow.svg",
    ),
}

_HOME_PICTURE = '''<picture>
  <source media="(max-width: 44em)" srcset="img/guide-path-mobile.svg">
  <img src="img/guide-path.svg" width="820" height="372" alt="Set up AnimeUp with Install and optional first-use Calibrate, then follow four numbered steps: Sources, Compare, Processing, Output.">
</picture>'''


def on_page_markdown(markdown, page, config, files):
    if page.file.src_uri == "guide/index.md":
        image_dir = Path(config.docs_dir) / "guide/img"
        wide = (image_dir / "guide-path.svg").read_text(encoding="utf-8")
        narrow = (image_dir / "guide-path-mobile.svg").read_text(encoding="utf-8")
        return markdown.replace(
            _HOME_PICTURE,
            f'<figure class="animeup-flow animeup-guide-path">\n{wide}\n{narrow}\n</figure>',
            1,
        )

    diagram = _DIAGRAMS.get(page.file.src_uri)
    if diagram is None:
        return markdown

    image, filename = diagram
    svg = (Path(config.docs_dir) / "guide/img" / filename).read_text(encoding="utf-8")
    return markdown.replace(image, f'<figure class="animeup-flow">\n{svg}\n</figure>', 1)
