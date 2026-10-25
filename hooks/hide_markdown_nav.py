"""Keep chapter links in Markdown while using the generated footer on the site."""

import re


_CHAPTER_LINK = re.compile(r"(?m)^\[(?:Next|Start): [^\n]+\]\([^)]+\)[ \t]*\n?")


def on_page_markdown(markdown, page, config, files):
    if page.file.src_uri.startswith("guide/"):
        return _CHAPTER_LINK.sub("", markdown)
    return markdown
