"""Turn Markdown (or plain text, which is valid Markdown) into speakable blocks.

What gets read:
- headings, paragraphs, list items (ordered items keep their number), blockquotes
- link text, but never the URL; autolinks and bare URLs are dropped entirely
- inline code and emphasis, as plain text

- small tables, row by row (header first), cells left to right separated by commas

What is skipped: images, fenced code, raw HTML, and tables with MAX_TABLE_ROWS
or more data rows or MAX_TABLE_COLUMNS or more columns. Indented code blocks
are disabled on purpose, so indented plain text is still read as a paragraph.
A thematic break (---) becomes a pause.

Within a paragraph, a line break after sentence-ending punctuation starts a new
paragraph. That way, plain text with one paragraph per line splits properly,
while hard-wrapped lines are still joined.
"""

from __future__ import annotations

import re

from markdown_it import MarkdownIt
from markdown_it.token import Token

from .models import Block
from .sentences import ends_sentence

_MD = MarkdownIt("commonmark").enable("table").disable("code")

# Trailing punctuation is left out of the URL so "see https://x.com." keeps its period.
_BARE_URL = re.compile(r"(?:https?://|www\.)\S*[^\s.,;:!?)\]}'\"»”]")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([.,;:!?…)\]}»”])")
_SKIP_BLOCKS = {"fence", "code_block", "html_block"}

# Tables at or above either limit are skipped; reading them aloud isn't useful.
MAX_TABLE_ROWS = 15  # data rows, header row not counted
MAX_TABLE_COLUMNS = 7


def parse_markdown(text: str) -> list[Block]:
    blocks: list[Block] = []
    containers: list[str] = []  # "blockquote" / "list_item", innermost last
    heading_level = 0
    item_prefix: str | None = None  # number for the first paragraph of an ordered item
    table: list[list[str]] | None = None  # rows of cell texts while inside a table
    header_rows = 0

    for tok in _MD.parse(text):
        t = tok.type
        if t == "table_open":
            table, header_rows = [], 0
        elif t == "table_close":
            blocks.extend(_table_blocks(table or [], header_rows))
            table = None
        elif table is not None:
            if t == "tr_open":
                table.append([])
            elif t == "thead_close":
                header_rows = len(table)
            elif t == "inline" and table:
                table[-1].append(" ".join(_inline_paragraphs(tok)))
        elif t in _SKIP_BLOCKS:
            continue
        elif t == "hr":
            blocks.append(Block("separator"))
        elif t == "heading_open":
            heading_level = int(tok.tag[1])
        elif t == "heading_close":
            heading_level = 0
        elif t == "blockquote_open":
            containers.append("blockquote")
        elif t == "list_item_open":
            containers.append("list_item")
            item_prefix = f"{tok.info}." if tok.info else None
        elif t in ("blockquote_close", "list_item_close"):
            containers.pop()
        elif t == "inline":
            paragraphs = _inline_paragraphs(tok)
            if heading_level:
                if paragraphs:
                    blocks.append(Block("heading", " ".join(paragraphs), heading_level))
                continue
            kind = containers[-1] if containers else "paragraph"
            for para in paragraphs:
                if item_prefix:
                    para = f"{item_prefix} {para}"
                    item_prefix = None
                blocks.append(Block(kind, para))
    return blocks


def _table_blocks(rows: list[list[str]], header_rows: int) -> list[Block]:
    columns = max((len(r) for r in rows), default=0)
    if len(rows) - header_rows >= MAX_TABLE_ROWS or columns >= MAX_TABLE_COLUMNS:
        return []
    blocks = []
    for row in rows:
        text = ", ".join(cell for cell in row if cell)
        if text:
            blocks.append(Block("table_row", text if ends_sentence(text) else f"{text}."))
    return blocks


def _inline_paragraphs(tok: Token) -> list[str]:
    """Extract speakable text from an inline token, split at sentence-ending line breaks."""
    paragraphs: list[str] = []
    current: list[str] = []
    in_autolink = False

    def flush() -> None:
        text = _clean("".join(current))
        if text:
            paragraphs.append(text)
        current.clear()

    for child in tok.children or []:
        c = child.type
        if c == "link_open" and child.markup == "autolink":
            in_autolink = True
        elif c == "link_close" and child.markup == "autolink":
            in_autolink = False
        elif in_autolink:
            continue
        elif c in ("text", "code_inline"):
            current.append(child.content)
        elif c in ("softbreak", "hardbreak"):
            if ends_sentence("".join(current).rstrip()):
                flush()
            else:
                current.append(" ")
        # link_open/close (text kept), em/strong, image (alt dropped), html_inline: ignored
    flush()
    return paragraphs


def _clean(text: str) -> str:
    text = _BARE_URL.sub("", text)
    text = " ".join(text.split())
    return _SPACE_BEFORE_PUNCT.sub(r"\1", text)
