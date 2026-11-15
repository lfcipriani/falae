"""Chirp 3 HD voices and languages, and resolving a bare language ("en") to a locale.

Source: https://docs.cloud.google.com/text-to-speech/docs/chirp3-hd (checked 2026-11-15).
Update VOICES and LANGUAGES by hand when Google adds or changes them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Voice:
    name: str  # short name; the full name is <locale>-Chirp3-HD-<name>
    gender: str


@dataclass(frozen=True)
class Language:
    code: str  # BCP-47 locale, as Google spells it
    name: str
    preview: bool = False


VOICES: tuple[Voice, ...] = (
    Voice("Achernar", "Female"),
    Voice("Achird", "Male"),
    Voice("Algenib", "Male"),
    Voice("Algieba", "Male"),
    Voice("Alnilam", "Male"),
    Voice("Aoede", "Female"),
    Voice("Autonoe", "Female"),
    Voice("Callirrhoe", "Female"),
    Voice("Charon", "Male"),
    Voice("Despina", "Female"),
    Voice("Enceladus", "Male"),
    Voice("Erinome", "Female"),
    Voice("Fenrir", "Male"),
    Voice("Gacrux", "Female"),
    Voice("Iapetus", "Male"),
    Voice("Kore", "Female"),
    Voice("Laomedeia", "Female"),
    Voice("Leda", "Female"),
    Voice("Orus", "Male"),
    Voice("Pulcherrima", "Female"),
    Voice("Puck", "Male"),
    Voice("Rasalgethi", "Male"),
    Voice("Sadachbia", "Male"),
    Voice("Sadaltager", "Male"),
    Voice("Schedar", "Male"),
    Voice("Sulafat", "Female"),
    Voice("Umbriel", "Male"),
    Voice("Vindemiatrix", "Female"),
    Voice("Zephyr", "Female"),
    Voice("Zubenelgenubi", "Male"),
)

LANGUAGES: tuple[Language, ...] = (
    Language("ar-XA", "Arabic (Generic)"),
    Language("bn-IN", "Bengali (India)"),
    Language("bg-BG", "Bulgarian (Bulgaria)"),
    Language("yue-HK", "Chinese (Hong Kong)", preview=True),
    Language("hr-HR", "Croatian (Croatia)"),
    Language("cs-CZ", "Czech (Czech Republic)"),
    Language("da-DK", "Danish (Denmark)"),
    Language("nl-BE", "Dutch (Belgium)"),
    Language("nl-NL", "Dutch (Netherlands)"),
    Language("en-AU", "English (Australia)"),
    Language("en-IN", "English (India)"),
    Language("en-GB", "English (United Kingdom)"),
    Language("en-US", "English (United States)"),
    Language("et-EE", "Estonian (Estonia)"),
    Language("fi-FI", "Finnish (Finland)"),
    Language("fr-CA", "French (Canada)"),
    Language("fr-FR", "French (France)"),
    Language("de-DE", "German (Germany)"),
    Language("el-GR", "Greek (Greece)"),
    Language("gu-IN", "Gujarati (India)"),
    Language("he-IL", "Hebrew (Israel)"),
    Language("hi-IN", "Hindi (India)"),
    Language("hu-HU", "Hungarian (Hungary)"),
    Language("id-ID", "Indonesian (Indonesia)"),
    Language("it-IT", "Italian (Italy)"),
    Language("ja-JP", "Japanese (Japan)"),
    Language("kn-IN", "Kannada (India)"),
    Language("ko-KR", "Korean (South Korea)"),
    Language("lv-LV", "Latvian (Latvia)"),
    Language("lt-LT", "Lithuanian (Lithuania)"),
    Language("ml-IN", "Malayalam (India)"),
    Language("cmn-CN", "Mandarin Chinese (China)"),
    Language("mr-IN", "Marathi (India)"),
    Language("nb-NO", "Norwegian Bokmål (Norway)"),
    Language("pl-PL", "Polish (Poland)"),
    Language("pt-BR", "Portuguese (Brazil)"),
    Language("pa-IN", "Punjabi (India)", preview=True),
    Language("ro-RO", "Romanian (Romania)"),
    Language("ru-RU", "Russian (Russia)"),
    Language("sr-RS", "Serbian (Cyrillic)"),
    Language("sk-SK", "Slovak (Slovakia)"),
    Language("sl-SI", "Slovenian (Slovenia)"),
    Language("es-ES", "Spanish (Spain)"),
    Language("es-US", "Spanish (United States)"),
    Language("sw-KE", "Swahili (Kenya)"),
    Language("sv-SE", "Swedish (Sweden)"),
    Language("ta-IN", "Tamil (India)"),
    Language("te-IN", "Telugu (India)"),
    Language("th-TH", "Thai (Thailand)"),
    Language("tr-TR", "Turkish (Turkey)"),
    Language("uk-UA", "Ukrainian (Ukraine)"),
    Language("ur-IN", "Urdu (India)"),
    Language("vi-VN", "Vietnamese (Vietnam)"),
)

# Which locale a bare language picks. Only languages with more than one locale need
# an entry; a language with a single locale (e.g. "pt" -> "pt-BR") picks it on its own.
DEFAULT_LOCALES: dict[str, str] = {
    "en": "en-US",
    "es": "es-ES",
    "fr": "fr-FR",
    "nl": "nl-NL",
}

_BY_CODE = {lang.code.lower(): lang.code for lang in LANGUAGES}


def resolve_language(value: str) -> str:
    """Return the supported locale for "en-US", "en-us" or a bare "en".

    Raises ValueError if the language isn't supported by Chirp 3 HD.
    """
    key = value.strip().replace("_", "-").lower()
    if key in _BY_CODE:
        return _BY_CODE[key]
    if "-" not in key:
        if key in DEFAULT_LOCALES:
            return DEFAULT_LOCALES[key]
        matches = [code for code in _BY_CODE.values() if code.lower().split("-")[0] == key]
        if len(matches) == 1:
            return matches[0]
        if matches:
            raise ValueError(
                f"language {value!r} has several locales ({', '.join(matches)}); "
                f"pick one or add a default to DEFAULT_LOCALES"
            )
    raise ValueError(f"language {value!r} isn't supported by Chirp 3 HD voices")
