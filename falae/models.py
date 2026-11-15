from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum


class InputFormat(str, Enum):
    """Which TTS input field to send. SSML is Preview for Chirp 3 HD; markup is the GA fallback."""

    SSML = "ssml"
    MARKUP = "markup"


@dataclass(frozen=True)
class Article:
    language: str  # BCP-47, e.g. "pt-BR"
    content: str  # Markdown (plain text is fine too)
    title: str | None = None
    author: str | None = None
    published_date: dt.date | None = None
    link: str | None = None  # never read aloud; stored in the MP3 metadata
    takeaways: str | None = None  # Markdown; read after the intro, before the content


@dataclass(frozen=True)
class Block:
    """A speakable unit. kind: title, byline, takeaways_label, heading, paragraph,
    list_item, blockquote, table_row or separator. level is the heading level (1-6)."""

    kind: str
    text: str = ""
    level: int = 0


@dataclass(frozen=True)
class SynthesisOptions:
    voice: str = "Charon"  # Chirp 3 HD voice short name, or a full voice name
    input_format: InputFormat = InputFormat.SSML
    speaking_rate: float = 1.0
    max_chunk_bytes: int = 4500  # API hard limit is 5000 bytes per request


@dataclass(frozen=True)
class SynthesisResult:
    location: str
    chunks: int
    characters: int
    bytes: int
