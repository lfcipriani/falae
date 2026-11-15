import pytest

from falae.sentences import ends_sentence, split_sentences


@pytest.mark.parametrize("text, expected", [
    ("Olá. Tudo bem? Sim! Ótimo.", ["Olá.", "Tudo bem?", "Sim!", "Ótimo."]),
    # next word lowercase: not a boundary
    ("Frutas, legumes etc. e outras coisas. Fim.", ["Frutas, legumes etc. e outras coisas.", "Fim."]),
    # initials
    ("J. R. R. Tolkien wrote it. Then he rested.", ["J. R. R. Tolkien wrote it.", "Then he rested."]),
    # closing quotes stay with their sentence; opening quotes don't hide a lowercase start
    ('Ele disse: "Acabou." Depois saiu.', ['Ele disse: "Acabou."', "Depois saiu."]),
    ('Ele disse "fim." "e depois" nada.', ['Ele disse "fim." "e depois" nada.']),
    # ellipsis, decimals, URLs
    ("Bem… Talvez amanhã. Custa 3.50 reais.", ["Bem…", "Talvez amanhã.", "Custa 3.50 reais."]),
    ("Veja example.com/a.b agora. Ok.", ["Veja example.com/a.b agora.", "Ok."]),
    # Spanish openers
    ("¿Vienes? ¡Claro! Vamos.", ["¿Vienes?", "¡Claro!", "Vamos."]),
    # CJK punctuation without spaces
    ("今日は晴れです。明日は雨です！本当？", ["今日は晴れです。", "明日は雨です！", "本当？"]),
    ("sem pontuação nenhuma", ["sem pontuação nenhuma"]),
    # known, accepted limitation: abbreviations before a capitalized word are cut
    ("O Dr. Silva chegou.", ["O Dr.", "Silva chegou."]),
])
def test_split_sentences(text, expected):
    assert split_sentences(text) == expected


@pytest.mark.parametrize("line, expected", [
    ("Fim.", True), ("Fim!", True), ('Ele disse "fim."', True), ("Lista:", True),
    ("終わり。", True), ("no meio da", False), ("", False),
])
def test_ends_sentence(line, expected):
    assert ends_sentence(line) is expected
