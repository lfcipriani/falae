"""Minimal sentence segmentation.

The TTS engine does its own sentence detection, so this only has two jobs:
- `ends_sentence`: decide whether a line break ends a paragraph (markdown.py)
- `split_sentences`: find safe cut points when a single paragraph is too big
  for one TTS request (text.py), so a request never ends mid-sentence

Deliberately simple: no abbreviation lists. A cut that lands after "Dr." only
causes a slightly odd pause, and only in the rare oversized-paragraph case.
"""

from __future__ import annotations

import re

_TERMINAL = ".!?…"
_CJK_TERMINAL = "。！？"
_CLOSERS = "\"'”’»)]}」』）"

# Terminal punctuation plus any closing quotes/brackets, then whitespace.
# CJK punctuation needs no whitespace after it.
_CANDIDATE = re.compile(
    rf"[{re.escape(_TERMINAL)}]+[{re.escape(_CLOSERS)}]*\s+"
    rf"|[{_CJK_TERMINAL}]+[{re.escape(_CLOSERS)}]*\s*"
)
_LINE_ENDS_SENTENCE = re.compile(rf"[{re.escape(_TERMINAL)}:{_CJK_TERMINAL}][{re.escape(_CLOSERS)}]*$")


def ends_sentence(line: str) -> bool:
    """True if a line ends like a sentence (so a line break after it is a paragraph break)."""
    return bool(_LINE_ENDS_SENTENCE.search(line))


def split_sentences(paragraph: str) -> list[str]:
    sentences: list[str] = []
    start = 0
    for m in _CANDIDATE.finditer(paragraph):
        if m.end() < len(paragraph) and not _is_boundary(paragraph, m):
            continue
        sentence = paragraph[start:m.end()].strip()
        if sentence:
            sentences.append(sentence)
        start = m.end()
    tail = paragraph[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def _is_boundary(text: str, m: re.Match[str]) -> bool:
    if m.group(0)[0] in _CJK_TERMINAL:
        return True
    # The next sentence must not start lowercase ("etc. e mais"), ignoring opening quotes.
    following = text[m.end():].lstrip("\"'“‘«([{¿¡—–- ")
    if following[:1].islower():
        return False
    # An initial ("J. R. R. Tolkien"): a single capital letter before the period.
    before = text[: m.start()].split()
    return not (before and len(before[-1]) == 1 and before[-1].isupper())
