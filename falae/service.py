"""Orchestrates: article -> chunks -> TTS -> joined MP3 -> storage."""

from __future__ import annotations

import hashlib

from .audio import concat_mp3
from .models import Article, SynthesisOptions, SynthesisResult
from .storage import Storage, slugify
from .text import build_chunks, display_title
from .tts import ChirpSynthesizer, Synthesizer


def output_filename(article: Article) -> str:
    """<date>-<title-slug>.mp3; the date is omitted if unknown, and the slug falls back
    to the first heading, then to a content hash."""
    title = display_title(article)
    if title:
        name = slugify(title)
    else:
        name = "article-" + hashlib.sha1(article.content.encode()).hexdigest()[:8]
    date = article.published_date
    return f"{date.isoformat()}-{name}.mp3" if date else f"{name}.mp3"


def synthesize_article(
    article: Article,
    storage: Storage,
    options: SynthesisOptions = SynthesisOptions(),
    synthesizer: Synthesizer | None = None,
) -> SynthesisResult:
    synthesizer = synthesizer or ChirpSynthesizer(
        voice=options.voice, speaking_rate=options.speaking_rate
    )
    chunks = build_chunks(article, options.input_format, options.max_chunk_bytes)
    parts = synthesizer.synthesize(chunks, article.language, options.input_format)

    metadata = {
        "title": display_title(article),
        "artist": article.author,
        "date": article.published_date.isoformat() if article.published_date else None,
        "comment": article.link,
        "language": article.language,
    }
    output = concat_mp3(
        parts,
        storage.path_for(output_filename(article)),
        metadata={k: v for k, v in metadata.items() if v},
    )
    size = output.stat().st_size  # read before publish: remote storages delete the local copy
    location = storage.publish(output)
    return SynthesisResult(
        location=location,
        chunks=len(chunks),
        characters=sum(len(c) for c in chunks),
        bytes=size,
    )
