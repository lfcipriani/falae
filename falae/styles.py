"""How each kind of block sounds. Edit this to tune the narration.

`pause_before` / `pause_after` are SSML <break> durations ("500ms", "1.2s").
`rate`, `pitch` and `volume` wrap the block in SSML <prosody>, for example
rate="90%", pitch="-2st", volume="+2dB". Chirp 3 HD supports <prosody>, but
SSML is Preview and Google doesn't document valid ranges, so test changes
with a real run before relying on them. Prosody is ignored in markup mode,
where pauses are approximated with [pause short] / [pause] / [pause long].
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Block


@dataclass(frozen=True)
class BlockStyle:
    pause_before: str | None = None
    pause_after: str | None = None
    rate: str | None = None
    pitch: str | None = None
    volume: str | None = None


_HEADING_MINOR = BlockStyle(pause_before="900ms", pause_after="500ms")

STYLES: dict[str, BlockStyle] = {
    # Intro (from the request fields, not the Markdown)
    "title": BlockStyle(pause_after="800ms"),
    "byline": BlockStyle(pause_after="1500ms"),
    "takeaways_label": BlockStyle(pause_after="600ms"),
    # Markdown structure
    "h1": BlockStyle(pause_before="1500ms", pause_after="800ms"),
    "h2": BlockStyle(pause_before="1200ms", pause_after="600ms"),
    "h3": _HEADING_MINOR,
    "h4": _HEADING_MINOR,
    "h5": _HEADING_MINOR,
    "h6": _HEADING_MINOR,
    "paragraph": BlockStyle(),
    "list_item": BlockStyle(pause_after="300ms"),
    "blockquote": BlockStyle(pause_before="400ms", pause_after="400ms"),
    "table_row": BlockStyle(pause_after="400ms"),
    # Thematic break (---) and the end of the takeaways section
    "separator": BlockStyle(pause_after="1200ms"),
}


def style_key(block: Block) -> str:
    return f"h{block.level}" if block.kind == "heading" else block.kind
