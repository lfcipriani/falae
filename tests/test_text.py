import datetime as dt
import xml.etree.ElementTree as ET

import pytest

from falae.models import Article, InputFormat
from falae.styles import STYLES, BlockStyle
from falae.text import article_blocks, build_chunks, display_title


def text_of(ssml: str) -> str:
    return "".join(ET.fromstring(ssml).itertext())


def test_narration_order_intro_takeaways_then_body(article):
    blocks = [(b.kind, b.text) for b in article_blocks(article)]
    assert blocks[:6] == [
        ("title", "Um título"),
        ("byline", "Por Ana Souza. Publicado em \0DATE\0."),
        ("takeaways_label", "Principais pontos."),
        ("list_item", "Ponto um."),
        ("list_item", "Ponto dois."),
        ("separator", ""),
    ]
    # the "# Um título" heading duplicates the title, so it's dropped
    assert blocks[6] == ("heading", "Introdução")


def test_ssml_structure(article):
    [chunk] = build_chunks(article, InputFormat.SSML)
    root = ET.fromstring(chunk)  # well-formed XML
    assert root.tag == "speak"
    assert "<s>" not in chunk
    assert chunk.count("Um título") == 1
    paragraphs = ["".join(p.itertext()) for p in root.iter("p")]
    assert "Este é o primeiro parágrafo, com um link no meio." in paragraphs
    assert "Ele tem duas frases & um símbolo: 1 < 2." in paragraphs
    assert "https://example.com" not in chunk  # neither the content link nor the link field
    h2 = STYLES["h2"]
    assert f'<break time="{h2.pause_before}"/><p>Introdução</p><break time="{h2.pause_after}"/>' in chunk
    assert '<say-as interpret-as="date" format="yyyymmdd" detail="1">2026-11-11</say-as>' in chunk


def test_heading_style_is_configurable_with_prosody(article):
    styles = {**STYLES, "h2": BlockStyle(pause_before="2s", rate="90%", pitch="-2st")}
    [chunk] = build_chunks(article, InputFormat.SSML, styles=styles)
    assert '<break time="2s"/><p><prosody rate="90%" pitch="-2st">Introdução</prosody></p>' in chunk
    ET.fromstring(chunk)


def test_markup_format(article):
    [chunk] = build_chunks(article, InputFormat.MARKUP)
    assert "<" not in chunk.replace("1 < 2", "")
    assert chunk.startswith("Um título [pause]")
    assert "[pause long]\n\nIntrodução [pause]" in chunk
    assert "Publicado em 2026-11-11." in chunk


def test_markup_neutralizes_brackets_in_content():
    art = Article("en-US", "See \\[pause long\\] here.")
    [chunk] = build_chunks(art, InputFormat.MARKUP)
    assert "(pause long)" in chunk


def test_all_optional_fields_missing():
    art = Article("en-US", "Just text.")
    [chunk] = build_chunks(art, InputFormat.SSML)
    assert chunk == "<speak><p>Just text.</p></speak>"


@pytest.mark.parametrize("author, date, byline", [
    ("Jane", None, "By Jane."),
    (None, dt.date(2026, 1, 2), "Published on \0DATE\0."),
])
def test_partial_byline(author, date, byline):
    blocks = article_blocks(Article("en-US", "x", author=author, published_date=date))
    assert blocks[0].kind == "byline" and blocks[0].text == byline


def test_display_title_falls_back_to_first_heading():
    assert display_title(Article("en", "Intro.\n\n## First heading\n\ntext")) == "First heading"
    assert display_title(Article("en", "no headings")) is None
    assert display_title(Article("en", "# H", title="T")) == "T"


@pytest.mark.parametrize("fmt", list(InputFormat))
def test_long_article_respects_byte_limit_and_keeps_order(fmt):
    paragraphs = [f"Parágrafo {i}. " + "Informação e coração em ação. " * 40 for i in range(30)]
    art = Article("pt-BR", "\n\n".join(paragraphs), title="Título")
    chunks = build_chunks(art, fmt, max_bytes=4500)

    assert len(chunks) > 3
    assert all(len(c.encode()) <= 4500 for c in chunks)
    joined = " ".join(text_of(c) if fmt is InputFormat.SSML else c for c in chunks)
    positions = [joined.index(f"Parágrafo {i}.") for i in range(30)]
    assert positions == sorted(positions)


@pytest.mark.parametrize("fmt", list(InputFormat))
def test_oversized_paragraph_and_sentence_are_split(fmt):
    art = Article("en-US", "palavra " * 2000)  # ~16 KB, no sentence breaks
    chunks = build_chunks(art, fmt, max_bytes=1000)
    assert all(len(c.encode()) <= 1000 for c in chunks)
    words = sum((text_of(c) if fmt is InputFormat.SSML else c).count("palavra") for c in chunks)
    assert words == 2000
    if fmt is InputFormat.SSML:
        for c in chunks:
            ET.fromstring(c)


def test_unknown_language_falls_back_to_english():
    art = Article("ja-JP", "本文。", author="Jane", takeaways="要点。")
    [chunk] = build_chunks(art, InputFormat.SSML)
    assert "By Jane." in chunk and "Key takeaways." in chunk


@pytest.mark.parametrize("fmt, unexpected", [
    (InputFormat.SSML, '"/><break'),
    (InputFormat.MARKUP, "] ["),
])
def test_adjacent_pauses_are_merged(fmt, unexpected):
    art = Article("pt-BR", "- item\n\n## Seção\n\n---\n\n> citação", takeaways="- ponto")
    [chunk] = build_chunks(art, fmt)
    assert unexpected not in chunk.replace("]\n\n[", "] [")


def test_merged_break_keeps_the_longest():
    art = Article("pt-BR", "- item\n\n## Seção")
    [chunk] = build_chunks(art, InputFormat.SSML)
    assert f'<p>item</p><break time="{STYLES["h2"].pause_before}"/><p>Seção</p>' in chunk


def test_markup_merge_keeps_paragraph_break():
    [chunk] = build_chunks(Article("pt-BR", "- item\n\n> citação"), InputFormat.MARKUP)
    assert "item [pause short]\n\ncitação" in chunk
