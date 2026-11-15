import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from falae import api
import datetime as dt

from falae.models import Article, InputFormat, SynthesisOptions
from falae.service import output_filename, synthesize_article
from falae.storage import LocalStorage, slugify
from falae.tts import voice_name

from .conftest import FakeSynthesizer


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:format_tags",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)["format"]


@pytest.fixture
def local_storage(tmp_path):
    api.app.dependency_overrides[api.get_storage] = lambda: LocalStorage(tmp_path)
    yield
    api.app.dependency_overrides.clear()


def test_synthesize_article_joins_parts_into_one_tagged_mp3(tmp_path, article, silent_mp3):
    fake = FakeSynthesizer(silent_mp3)
    options = SynthesisOptions(max_chunk_bytes=300)
    result = synthesize_article(article, LocalStorage(tmp_path), options, synthesizer=fake)

    assert result.chunks > 1
    assert result.location == str(tmp_path / "2026-11-11-um-titulo.mp3")
    fmt = probe(result.location)
    assert float(fmt["duration"]) > 0.5 * (result.chunks - 0.5)
    assert fmt["tags"]["title"] == "Um título"
    assert fmt["tags"]["artist"] == "Ana Souza"
    assert fmt["tags"]["comment"] == "https://example.com/artigo"
    assert list(tmp_path.iterdir()) == [tmp_path / "2026-11-11-um-titulo.mp3"]  # temp parts cleaned


def test_api_synthesize(local_storage, monkeypatch, silent_mp3):
    fake = FakeSynthesizer(silent_mp3)
    monkeypatch.setattr(api, "synthesize_article",
                        lambda a, s, o: synthesize_article(a, s, o, synthesizer=fake))

    resp = TestClient(api.app).post("/synthesize", json={
        "title": "Hello World", "author": "Jane", "published_date": "2026-11-11",
        "language": "en-US", "content": "First paragraph.\n\nSecond one.", "input_format": "markup",
    })
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body == {"status": "accepted", "location": body["location"]}
    assert body["location"].endswith("2026-11-11-hello-world.mp3")
    assert fake.calls[0][1:] == ("en-US", InputFormat.MARKUP)
    assert Path(body["location"]).stat().st_size > 0  # TestClient runs background tasks before returning


def test_api_accepts_before_synthesis_and_logs_failures(local_storage, monkeypatch, caplog):
    def boom(a, s, o):
        raise RuntimeError("TTS down")

    monkeypatch.setattr(api, "synthesize_article", boom)
    resp = TestClient(api.app).post("/synthesize", json={"language": "en", "content": "Hi."})
    assert resp.status_code == 202, resp.text
    assert "synthesis failed" in caplog.text and "TTS down" in caplog.text


def test_api_validates_input():
    resp = TestClient(api.app).post("/synthesize", json={"title": "x"})
    assert resp.status_code == 422


def test_helpers():
    assert voice_name("pt-BR", "Charon") == "pt-BR-Chirp3-HD-Charon"
    assert voice_name("pt-BR", "pt-BR-Neural2-A") == "pt-BR-Neural2-A"
    assert slugify("Ação & Reação: um título!") == "acao-reacao-um-titulo"


def test_output_filename_fallbacks():
    d = dt.date(2026, 11, 11)
    assert output_filename(Article("pt-BR", "x", title="Olá Mundo", published_date=d)) == "2026-11-11-ola-mundo.mp3"
    assert output_filename(Article("pt-BR", "## Primeira seção\n\ntexto")) == "primeira-secao.mp3"
    assert output_filename(Article("pt-BR", "só texto")).startswith("article-")


def test_api_only_required_fields(local_storage, monkeypatch, silent_mp3):
    fake = FakeSynthesizer(silent_mp3)
    monkeypatch.setattr(api, "synthesize_article",
                        lambda a, s, o: synthesize_article(a, s, o, synthesizer=fake))
    resp = TestClient(api.app).post("/synthesize", json={
        "language": "pt-BR", "content": "# Seção\n\nTexto em **Markdown**.",
        "takeaways": "- Um ponto.",
    })
    assert resp.status_code == 202, resp.text
    assert resp.json()["location"].endswith("secao.mp3")
    [chunks] = [c[0] for c in fake.calls]
    assert "Principais pontos." in chunks[0] and "**" not in chunks[0]


def test_api_resolves_bare_language(local_storage, monkeypatch, silent_mp3):
    fake = FakeSynthesizer(silent_mp3)
    monkeypatch.setattr(api, "synthesize_article",
                        lambda a, s, o: synthesize_article(a, s, o, synthesizer=fake))
    resp = TestClient(api.app).post("/synthesize", json={"language": "en", "content": "Hi."})
    assert resp.status_code == 202, resp.text
    assert fake.calls[0][1] == "en-US"


def test_api_rejects_unsupported_language():
    resp = TestClient(api.app).post("/synthesize", json={"language": "xx", "content": "Hi."})
    assert resp.status_code == 422
    assert "isn't supported" in resp.text


@pytest.mark.parametrize("typo", ["takeaway", "takeways", "Takeaways"])
def test_api_rejects_unknown_fields(typo):
    resp = TestClient(api.app).post("/synthesize", json={
        "language": "pt-BR", "content": "Texto.", typo: "- Um ponto."})
    assert resp.status_code == 422
    assert typo in resp.text


OPTIONAL_FIELDS = ["title", "author", "published_date", "link", "takeaways",
                   "voice", "input_format", "speaking_rate"]


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_blank_optional_fields_count_as_unset(blank):
    req = api.SynthesizeRequest.model_validate(
        {"language": "pt-BR", "content": "Texto.", **{f: blank for f in OPTIONAL_FIELDS}})
    assert req == api.SynthesizeRequest(language="pt-BR", content="Texto.")
    assert (req.voice, req.input_format, req.speaking_rate) == ("Charon", InputFormat.SSML, 1.0)


@pytest.mark.parametrize("field", ["language", "content"])
@pytest.mark.parametrize("blank", ["", None])
def test_blank_required_fields_are_still_rejected(field, blank):
    resp = TestClient(api.app).post("/synthesize", json={"language": "pt-BR", "content": "Texto.",
                                                         field: blank})
    assert resp.status_code == 422


@pytest.mark.parametrize("value, expected", [
    ("2026-11-15", dt.date(2026, 11, 15)),
    ("2026-11-15T10:30:00Z", dt.date(2026, 11, 15)),  # ISO datetime, as n8n often sends
    ("2026-11-15T10:30:00.000+01:00", dt.date(2026, 11, 15)),
    ("15/11/2026", None),
    ("yesterday", None),
    ("2026-02-30", None),
    ([2026, 11, 15], None),
])
def test_invalid_published_date_is_ignored(value, expected):
    req = api.SynthesizeRequest.model_validate(
        {"language": "pt-BR", "content": "Texto.", "published_date": value})
    assert req.published_date == expected


def test_api_accepts_blank_fields_and_bad_date(local_storage, monkeypatch, silent_mp3):
    fake = FakeSynthesizer(silent_mp3)
    monkeypatch.setattr(api, "synthesize_article",
                        lambda a, s, o: synthesize_article(a, s, o, synthesizer=fake))
    resp = TestClient(api.app).post("/synthesize", json={
        "language": "pt-BR", "content": "Texto.", "title": "Olá", "author": "",
        "published_date": "not a date", "link": None, "takeaways": "",
        "voice": "", "input_format": None, "speaking_rate": "",
    })
    assert resp.status_code == 202, resp.text
    assert resp.json()["location"].endswith("/ola.mp3")
    [(chunks, _, fmt)] = fake.calls
    assert fmt == InputFormat.SSML and "Por" not in chunks[0]
