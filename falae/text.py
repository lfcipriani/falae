"""Turn an article into a list of TTS request payloads, each under the byte limit.

Order of the narration:
1. intro: title, then byline ("By <author>. Published on <date>."), each only if given
2. takeaways (Markdown), introduced by a spoken label, then a separator pause
3. content (Markdown); a leading heading identical to the title is dropped

Each block is rendered to SSML (<p>, <break>, optional <prosody>; no <s>, the
engine detects sentences) or markup, using the styles in styles.py. Blocks are
packed greedily into chunks. A block that is too big on its own is split by
sentences, and a sentence that is too big is split by words. Every chunk is a
self-contained document, so no element is ever split across two requests.
"""

from __future__ import annotations

import re
from xml.sax.saxutils import escape, quoteattr

from .markdown import parse_markdown
from .models import Article, Block, InputFormat
from .sentences import split_sentences
from .styles import STYLES, BlockStyle, style_key

INTRO_PHRASES = {  # (by author, published on date, takeaways label)
    "pt": ("Por {author}.", "Publicado em {date}.", "Principais pontos."),
    "es": ("Por {author}.", "Publicado el {date}.", "Puntos clave."),
    "fr": ("Par {author}.", "Publié le {date}.", "Points clés."),
    "de": ("Von {author}.", "Veröffentlicht am {date}.", "Die wichtigsten Punkte."),
    "it": ("Di {author}.", "Pubblicato il {date}.", "Punti chiave."),
    "en": ("By {author}.", "Published on {date}.", "Key takeaways."),
}
DATE_PLACEHOLDER = "\0DATE\0"  # rendered per format (SSML <say-as> vs plain)


def article_blocks(article: Article) -> list[Block]:
    by_tpl, date_tpl, takeaways_label = INTRO_PHRASES.get(
        article.language.split("-")[0].lower(), INTRO_PHRASES["en"]
    )
    title = (article.title or "").strip()
    author = (article.author or "").strip()

    blocks: list[Block] = []
    if title:
        blocks.append(Block("title", title))
    byline = []
    if author:
        byline.append(by_tpl.format(author=author))
    if article.published_date:
        byline.append(date_tpl.format(date=DATE_PLACEHOLDER))
    if byline:
        blocks.append(Block("byline", " ".join(byline)))

    takeaways = parse_markdown(article.takeaways) if article.takeaways else []
    if takeaways:
        blocks += [Block("takeaways_label", takeaways_label), *takeaways, Block("separator")]

    body = parse_markdown(article.content)
    if title and body and body[0].kind == "heading" and _same_text(body[0].text, title):
        body = body[1:]  # avoid reading the title twice
    return blocks + body


def display_title(article: Article) -> str | None:
    """The title for metadata and file names: the title field, else the first heading."""
    if article.title and article.title.strip():
        return article.title.strip()
    return next((b.text for b in parse_markdown(article.content) if b.kind == "heading"), None)


def _same_text(a: str, b: str) -> bool:
    def norm(s: str) -> str:
        return re.sub(r"\W+", " ", s).strip().casefold()
    return norm(a) == norm(b)


class Renderer:
    """Renders blocks into one input format and wraps chunks into full documents."""

    def __init__(self, fmt: InputFormat, date_iso: str | None = None,
                 styles: dict[str, BlockStyle] | None = None):
        self.fmt = fmt
        self.date_iso = date_iso
        self.styles = styles or STYLES

    def wrap(self, body: str) -> str:
        if self.fmt is InputFormat.SSML:
            return f"<speak>{_merge_ssml_breaks(body)}</speak>"
        return _merge_markup_pauses(body)

    def overhead(self) -> int:
        return len(self.wrap("").encode())

    def block(self, block: Block) -> str:
        style = self.styles.get(style_key(block), BlockStyle())
        if self.fmt is InputFormat.SSML:
            return self._ssml(block, style)
        return self._markup(block, style)

    def _ssml(self, block: Block, style: BlockStyle) -> str:
        out = f'<break time="{style.pause_before}"/>' if style.pause_before else ""
        if block.text:
            inner = escape(block.text).replace(DATE_PLACEHOLDER, self._ssml_date())
            prosody = {k: v for k, v in
                       (("rate", style.rate), ("pitch", style.pitch), ("volume", style.volume)) if v}
            if prosody:
                attrs = " ".join(f"{k}={quoteattr(v)}" for k, v in prosody.items())
                inner = f"<prosody {attrs}>{inner}</prosody>"
            out += f"<p>{inner}</p>"
        if style.pause_after:
            out += f'<break time="{style.pause_after}"/>'
        return out

    def _ssml_date(self) -> str:
        return f'<say-as interpret-as="date" format="yyyymmdd" detail="1">{self.date_iso}</say-as>'

    def _markup(self, block: Block, style: BlockStyle) -> str:
        # Square brackets in content could be read as pause tags.
        text = block.text.replace("[", "(").replace("]", ")")
        text = text.replace(DATE_PLACEHOLDER, self.date_iso or "")
        parts = [_pause_tag(style.pause_before), text, _pause_tag(style.pause_after)]
        return " ".join(p for p in parts if p) + "\n\n"


def _ms(duration: str) -> float:
    m = re.fullmatch(r"\s*([\d.]+)\s*(ms|s)\s*", duration)
    return float(m.group(1)) * (1 if m.group(2) == "ms" else 1000) if m else 500


def _pause_tag(duration: str | None) -> str:
    """Approximate an SSML break duration with a markup pause tag."""
    if not duration:
        return ""
    ms = _ms(duration)
    if ms < 500:
        return "[pause short]"
    return "[pause]" if ms < 1000 else "[pause long]"


# Adjacent pauses (e.g. end of a list item followed by a heading) collapse into the longest.
_SSML_BREAK_RUN = re.compile(r'(?:<break time="[^"]+"/>){2,}')
_MARKUP_PAUSE_RUN = re.compile(r"\[pause(?: short| long)?\](?:\s*\[pause(?: short| long)?\])+ *")
_MARKUP_PAUSE_ORDER = ["[pause short]", "[pause]", "[pause long]"]


def _merge_ssml_breaks(body: str) -> str:
    def longest(m: re.Match[str]) -> str:
        times = re.findall(r'time="([^"]+)"', m.group(0))
        return f'<break time="{max(times, key=_ms)}"/>'
    return _SSML_BREAK_RUN.sub(longest, body)


def _merge_markup_pauses(body: str) -> str:
    def longest(m: re.Match[str]) -> str:
        tags = re.findall(r"\[pause(?: short| long)?\]", m.group(0))
        separator = "\n\n" if "\n" in m.group(0) else " "  # keep the paragraph break
        return max(tags, key=_MARKUP_PAUSE_ORDER.index) + separator
    return _MARKUP_PAUSE_RUN.sub(longest, body)


def _split_oversized(block: Block, renderer: Renderer, budget: int) -> list[Block]:
    """Split a block that doesn't fit into smaller blocks of the same kind that do."""
    def fits(text: str) -> bool:
        return _size(renderer, Block(block.kind, text, block.level)) <= budget

    pieces: list[str] = []
    for sentence in split_sentences(block.text):
        if fits(sentence):
            pieces.append(sentence)
            continue
        current: list[str] = []
        for word in sentence.split(" "):
            if current and not fits(" ".join(current + [word])):
                pieces.append(" ".join(current))
                current = [word]
            else:
                current.append(word)
        if current:
            pieces.append(" ".join(current))

    out: list[Block] = []
    group: list[str] = []
    for piece in pieces:
        if group and not fits(" ".join(group + [piece])):
            out.append(Block(block.kind, " ".join(group), block.level))
            group = []
        group.append(piece)
    if group:
        out.append(Block(block.kind, " ".join(group), block.level))
    return out


def _size(renderer: Renderer, block: Block) -> int:
    return len(renderer.block(block).encode())


def build_chunks(article: Article, fmt: InputFormat, max_bytes: int = 4500,
                 styles: dict[str, BlockStyle] | None = None) -> list[str]:
    date_iso = article.published_date.isoformat() if article.published_date else None
    renderer = Renderer(fmt, date_iso, styles)
    budget = max_bytes - renderer.overhead()

    rendered: list[str] = []
    for block in article_blocks(article):
        if _size(renderer, block) <= budget:
            rendered.append(renderer.block(block))
        else:
            rendered.extend(renderer.block(b)
                            for b in _split_oversized(block, renderer, budget))

    chunks: list[str] = []
    current = ""
    for part in rendered:
        if current and len((current + part).encode()) > budget:
            chunks.append(renderer.wrap(current.strip()))
            current = ""
        current += part
    if current.strip():
        chunks.append(renderer.wrap(current.strip()))
    return chunks
