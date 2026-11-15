from falae.markdown import MAX_TABLE_COLUMNS, MAX_TABLE_ROWS, parse_markdown
from falae.models import Block


def kinds(blocks):
    return [(b.kind, b.text, b.level) if b.kind == "heading" else (b.kind, b.text) for b in blocks]


def test_headings_paragraphs_and_levels():
    md = "# H1\n\nIntro.\n\n## H2\n\nBody.\n\n### H3"
    assert kinds(parse_markdown(md)) == [
        ("heading", "H1", 1), ("paragraph", "Intro."),
        ("heading", "H2", 2), ("paragraph", "Body."), ("heading", "H3", 3),
    ]


def test_links_keep_text_but_drop_urls():
    md = ("Leia [o relatório](https://x.com/r) agora. Veja <https://auto.link> e "
          "também https://bare.example.com/a?b=1. E www.site.com, ok.")
    [block] = parse_markdown(md)
    assert block.text == "Leia o relatório agora. Veja e também. E, ok."
    assert "http" not in block.text and "www" not in block.text


def test_reference_links_and_link_in_heading():
    md = "## Veja [isto][ref]\n\nTexto com [ref].\n\n[ref]: https://x.com"
    assert kinds(parse_markdown(md)) == [("heading", "Veja isto", 2), ("paragraph", "Texto com ref.")]


def test_images_code_and_html_are_skipped():
    md = """Antes ![gráfico](a.png) depois `x = 1`.

```python
print("não leia")
```

<div>html</div>

Fim."""
    assert kinds(parse_markdown(md)) == [("paragraph", "Antes depois x = 1."), ("paragraph", "Fim.")]


def test_emphasis_is_plain_text():
    [block] = parse_markdown("Isto é **muito** _importante_.")
    assert block.text == "Isto é muito importante."


def test_lists_one_block_per_item_and_ordered_numbers():
    md = "- maçã\n- pera\n\n1. primeiro\n2. segundo"
    assert kinds(parse_markdown(md)) == [
        ("list_item", "maçã"), ("list_item", "pera"),
        ("list_item", "1. primeiro"), ("list_item", "2. segundo"),
    ]


def test_blockquote_and_hr():
    md = "> Uma citação.\n\n---\n\nDepois."
    assert kinds(parse_markdown(md)) == [
        ("blockquote", "Uma citação."), ("separator", ""), ("paragraph", "Depois.")]


# Plain text is valid Markdown: paragraphs must still split sensibly.

def test_plain_text_blank_lines():
    assert kinds(parse_markdown("Um.\n\nDois.\n  \nTrês.")) == [
        ("paragraph", "Um."), ("paragraph", "Dois."), ("paragraph", "Três.")]


def test_plain_text_line_break_after_sentence_is_a_paragraph():
    assert kinds(parse_markdown("Primeiro parágrafo.\nSegundo parágrafo!")) == [
        ("paragraph", "Primeiro parágrafo."), ("paragraph", "Segundo parágrafo!")]


def test_plain_text_soft_wrapped_lines_are_joined():
    md = "Esta frase foi quebrada\nno meio por causa da\nlargura da coluna. Fim."
    assert parse_markdown(md) == [
        Block("paragraph", "Esta frase foi quebrada no meio por causa da largura da coluna. Fim.")]


def test_plain_text_without_breaks_is_one_paragraph():
    assert parse_markdown("Frase um. Frase dois.   Frase três.") == [
        Block("paragraph", "Frase um. Frase dois. Frase três.")]


def test_indented_plain_text_is_read_not_treated_as_code():
    assert parse_markdown("    Texto recuado.") == [Block("paragraph", "Texto recuado.")]


def test_hashtag_without_space_is_not_a_heading():
    assert kinds(parse_markdown("#falae é legal.")) == [("paragraph", "#falae é legal.")]


def test_empty_input():
    assert parse_markdown("  \n\n ") == []


def table(rows: int, cols: int) -> str:
    header = "| " + " | ".join(f"H{c}" for c in range(cols)) + " |"
    sep = "|" + "---|" * cols
    body = ["| " + " | ".join(f"r{r}c{c}" for c in range(cols)) + " |" for r in range(rows)]
    return "\n".join([header, sep, *body])


def test_table_is_read_row_by_row_left_to_right():
    md = """Antes.

| Nome | Idade | Site |
|------|------:|------|
| Ana  | 30    | [blog](https://ana.dev) |
| Beto |       | **ok** |

Depois."""
    assert kinds(parse_markdown(md)) == [
        ("paragraph", "Antes."),
        ("table_row", "Nome, Idade, Site."),
        ("table_row", "Ana, 30, blog."),
        ("table_row", "Beto, ok."),  # empty cell skipped
        ("paragraph", "Depois."),
    ]


def test_table_cell_ending_in_punctuation_gets_no_extra_period():
    [_, row] = parse_markdown("| a | b |\n|---|---|\n| x | fim! |")
    assert row.text == "x, fim!"


def test_table_limits():
    def rows_read(md):
        return sum(b.kind == "table_row" for b in parse_markdown(md))

    assert rows_read(table(MAX_TABLE_ROWS - 1, MAX_TABLE_COLUMNS - 1)) == MAX_TABLE_ROWS  # +header
    assert rows_read(table(MAX_TABLE_ROWS, 2)) == 0
    assert rows_read(table(2, MAX_TABLE_COLUMNS)) == 0


def test_skipped_table_does_not_leak_text():
    md = "Antes.\n\n" + table(MAX_TABLE_ROWS, 2) + "\n\nDepois."
    assert kinds(parse_markdown(md)) == [("paragraph", "Antes."), ("paragraph", "Depois.")]
