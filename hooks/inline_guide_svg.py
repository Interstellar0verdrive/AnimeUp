"""Inline the guide's SVG so its colors follow the selected site theme.

The Markdown image remains usable when the source file is read on GitHub.
"""

from pathlib import Path


_IMAGE = "![Flow from the source file through analysis, planning, checks, extraction, deduplication, chunk processing, assembly and verification to the finished MKV](../img/job-flow.svg)"


def on_page_markdown(markdown, page, config, files):
    if page.file.src_uri != "guide/deep-dives/how-it-works.md":
        return markdown

    svg = (Path(config.docs_dir) / "guide/img/job-flow.svg").read_text(encoding="utf-8")
    return markdown.replace(_IMAGE, f'<figure class="animeup-flow">\n{svg}\n</figure>', 1)
