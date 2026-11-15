"""Google Cloud TTS (Chirp 3 HD) synthesis of pre-built chunks into MP3 bytes."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

from google.cloud import texttospeech

from .models import InputFormat


class Synthesizer(Protocol):
    def synthesize(self, chunks: list[str], language: str, fmt: InputFormat) -> list[bytes]: ...


def voice_name(language: str, voice: str) -> str:
    """Accept a short Chirp 3 HD name ("Charon") or a full voice name."""
    return voice if "-" in voice else f"{language}-Chirp3-HD-{voice}"


class ChirpSynthesizer:
    def __init__(
        self,
        voice: str = "Charon",
        speaking_rate: float = 1.0,
        max_workers: int = 4,
        client: texttospeech.TextToSpeechClient | None = None,
    ):
        self.voice = voice
        self.speaking_rate = speaking_rate
        self.max_workers = max_workers
        self._client = client

    @property
    def client(self) -> texttospeech.TextToSpeechClient:
        if self._client is None:
            self._client = texttospeech.TextToSpeechClient()
        return self._client

    def synthesize(self, chunks: list[str], language: str, fmt: InputFormat) -> list[bytes]:
        voice = texttospeech.VoiceSelectionParams(
            language_code=language, name=voice_name(language, self.voice)
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=self.speaking_rate,
        )

        def one(chunk: str) -> bytes:
            field = {"ssml": chunk} if fmt is InputFormat.SSML else {"markup": chunk}
            response = self.client.synthesize_speech(
                input=texttospeech.SynthesisInput(**field),
                voice=voice,
                audio_config=audio_config,
            )
            return response.audio_content

        # map() preserves input order, so the parts come back in article order.
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            return list(pool.map(one, chunks))
