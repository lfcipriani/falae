import pytest

from falae.languages import DEFAULT_LOCALES, LANGUAGES, VOICES, resolve_language


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("en-US", "en-US"),
        ("en-us", "en-US"),
        ("en_GB", "en-GB"),
        ("en", "en-US"),
        ("EN", "en-US"),
        ("es", "es-ES"),
        ("fr", "fr-FR"),
        ("nl", "nl-NL"),
        ("pt", "pt-BR"),  # only one locale, no DEFAULT_LOCALES entry needed
        ("cmn", "cmn-CN"),
        ("yue-hk", "yue-HK"),
    ],
)
def test_resolve_language(value, expected):
    assert resolve_language(value) == expected


@pytest.mark.parametrize("value", ["xx", "pt-PT", "en-NZ", ""])
def test_unsupported_language_raises(value):
    with pytest.raises(ValueError, match="isn't supported"):
        resolve_language(value)


def test_every_multi_locale_language_has_a_default():
    bases = [lang.code.split("-")[0] for lang in LANGUAGES]
    ambiguous = {b for b in bases if bases.count(b) > 1}
    assert ambiguous == set(DEFAULT_LOCALES)
    codes = {lang.code for lang in LANGUAGES}
    assert set(DEFAULT_LOCALES.values()) <= codes


def test_catalog_sizes():
    assert len(LANGUAGES) == 53
    assert len(VOICES) == 30
    assert "Charon" in {v.name for v in VOICES}  # the default voice
