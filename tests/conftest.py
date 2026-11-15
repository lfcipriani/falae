import datetime as dt
import shutil
import subprocess

import pytest

from falae.models import Article, InputFormat

CONTENT = """# Um título

## Introdução

Este é o primeiro parágrafo, com um [link](https://example.com) no meio.
Ele tem duas frases & um símbolo: 1 < 2.

Segundo parágrafo com ação, coração e informação!
"""


@pytest.fixture
def article() -> Article:
    return Article(
        language="pt-BR",
        content=CONTENT,
        title="Um título",
        author="Ana Souza",
        published_date=dt.date(2026, 11, 11),
        link="https://example.com/artigo",
        takeaways="- Ponto um.\n- Ponto dois.",
    )


@pytest.fixture(scope="session")
def silent_mp3() -> bytes:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
         "anullsrc=r=24000:cl=mono", "-t", "0.5", "-b:a", "32k", "-f", "mp3", "-"],
        capture_output=True, check=True,
    )
    return out.stdout


class FakeSynthesizer:
    def __init__(self, audio: bytes):
        self.audio = audio
        self.calls: list[tuple[list[str], str, InputFormat]] = []

    def synthesize(self, chunks, language, fmt):
        self.calls.append((chunks, language, fmt))
        return [self.audio for _ in chunks]
