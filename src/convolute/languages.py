"""Supported languages and deterministic round-trip presets."""

LANGUAGES = {
    "en": "English", "fr": "French", "de": "German", "es": "Spanish",
    "pt": "Portuguese", "it": "Italian", "zh": "Chinese", "ko": "Korean",
    "ja": "Japanese", "id": "Indonesian", "ru": "Russian", "ar": "Arabic",
    "hi": "Hindi", "vi": "Vietnamese", "th": "Thai", "tr": "Turkish",
    "nl": "Dutch", "pl": "Polish", "uk": "Ukrainian",
}
PRESETS = {
    "short": ("en", "fr", "en"),
    "long": ("en", "fr", "de", "ja", "es", "en"),
    "extended": ("en", "fr", "de", "es", "pt", "it", "zh", "ja", "ko", "en"),
}
ALIASES = {"cn": "zh", "kr": "ko", "jp": "ja"}


def resolve_chain(preset: str | None, chain: str | None) -> tuple[str, ...]:
    if preset is not None and chain is not None:
        raise ValueError("--preset and --chain cannot be used together")
    if chain is None:
        try:
            return PRESETS[preset if preset is not None else "long"]
        except KeyError:
            raise ValueError("preset must be short, long, or extended") from None
    codes = tuple(part.strip().lower() for part in chain.split(","))
    codes = tuple(ALIASES.get(code, code) for code in codes)
    if any(code not in LANGUAGES for code in codes):
        raise ValueError("chain contains an unsupported or empty language code")
    if len(codes) < 3 or codes[0] != codes[-1]:
        raise ValueError("chain must contain at least two translations and return to its source language")
    if any(a == b for a, b in zip(codes, codes[1:])):
        raise ValueError("adjacent chain languages must differ")
    return codes
