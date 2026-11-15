#!/usr/bin/env python3
"""Run the article -> MP3 pipeline locally, without the HTTP server.

Example:
    ./falae_cli.py --language pt-BR --content-file article.md \
        --title "Meu artigo" --author "Fulano" --date 2026-11-11 \
        --link https://example.com/artigo --takeaways-file takeaways.md

Only --language and the content are required. Content is Markdown (plain text
is fine) and is read from stdin when --content-file is "-" or omitted.
Needs Google Application Default Credentials (gcloud auth application-default login).
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from dotenv import load_dotenv

from falae.languages import resolve_language
from falae.models import Article, InputFormat, SynthesisOptions
from falae.service import synthesize_article
from falae.storage import DEFAULT_GCS_BUCKET, GCSStorage, LocalStorage
from falae.text import build_chunks


def _language(value: str) -> str:
    try:
        return resolve_language(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def main(argv: list[str] | None = None) -> int:
    load_dotenv()  # .env next to this script; variables already in the environment win
    p = argparse.ArgumentParser(description="Turn a Markdown article into a single MP3 (Chirp 3 HD).")
    p.add_argument("--language", required=True, type=_language,
                   help='BCP-47 locale, e.g. pt-BR, or a bare language such as "en" (-> en-US)')
    p.add_argument("--content-file", default="-", help="Markdown article, or - for stdin")
    p.add_argument("--title")
    p.add_argument("--author")
    p.add_argument("--date", type=dt.date.fromisoformat, help="publish date, YYYY-MM-DD")
    p.add_argument("--link", help="article URL (metadata only, not read aloud)")
    p.add_argument("--takeaways-file", help="Markdown with key takeaways, read before the article")
    p.add_argument("--voice", default="Charon", help="Chirp 3 HD voice short name or full name")
    p.add_argument("--format", choices=[f.value for f in InputFormat], default="ssml")
    p.add_argument("--speaking-rate", type=float, default=1.0)
    p.add_argument("--storage", choices=["local", "gcs"], default="local",
                   help="where to save the MP3 (default: local)")
    p.add_argument("--output-dir", default="output", help="directory for --storage local")
    p.add_argument("--bucket", default=DEFAULT_GCS_BUCKET,
                   help=f"bucket for --storage gcs (default: {DEFAULT_GCS_BUCKET})")
    p.add_argument("--dry-run", action="store_true", help="print the chunks; don't call TTS")
    args = p.parse_args(argv)

    content = sys.stdin.read() if args.content_file == "-" else Path(args.content_file).read_text()
    takeaways = Path(args.takeaways_file).read_text() if args.takeaways_file else None
    article = Article(
        language=args.language, content=content, title=args.title, author=args.author,
        published_date=args.date, link=args.link, takeaways=takeaways,
    )
    options = SynthesisOptions(
        voice=args.voice, input_format=InputFormat(args.format), speaking_rate=args.speaking_rate
    )

    if args.dry_run:
        chunks = build_chunks(article, options.input_format, options.max_chunk_bytes)
        for i, chunk in enumerate(chunks, 1):
            print(f"--- chunk {i}/{len(chunks)} ({len(chunk.encode())} bytes) ---\n{chunk}\n")
        return 0

    storage = GCSStorage(args.bucket) if args.storage == "gcs" else LocalStorage(args.output_dir)
    result = synthesize_article(article, storage, options)
    print(f"Saved {result.location} ({result.chunks} chunks, {result.characters} billed chars, "
          f"{result.bytes / 1024:.0f} KiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
