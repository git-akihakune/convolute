"""Terminal capability detection and ANSI styling for stderr decoration."""

import os
import re
import sys
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass

RESET = "\x1b[0m"
FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
FRAME_SECONDS = 0.08
# Readable on light and dark backgrounds: no black, white, or gray; colors repeat across languages.
LANGUAGE_COLORS = {
    "en": "36", "fr": "34", "de": "35", "es": "32", "pt": "92", "it": "96",
    "zh": "31", "ko": "95", "ja": "91", "id": "94", "ru": "36", "ar": "32",
    "hi": "35", "vi": "34", "th": "91", "tr": "92", "nl": "96", "pl": "31", "uk": "94",
}

_TOKEN = re.compile(r"(\x1b\[[0-9;?]*[A-Za-z])|(.)", re.DOTALL)


@dataclass(frozen=True)
class Capabilities:
    interactive: bool
    color: bool


def detect_capabilities(stream, environ: Mapping[str, str], platform: str = sys.platform) -> Capabilities:
    try:
        tty = bool(stream.isatty())
    except (AttributeError, ValueError):
        tty = False
    encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "").replace("_", "")
    interactive = (tty and environ.get("TERM") != "dumb" and encoding == "utf8"
                   and (platform != "win32" or "WT_SESSION" in environ))
    return Capabilities(interactive, interactive and not environ.get("NO_COLOR"))


def terminal_width(stream) -> int:
    try:
        return os.get_terminal_size(stream.fileno()).columns or 80
    except (AttributeError, OSError, ValueError):
        return 80


def spinner_frame(now: float) -> str:
    return FRAMES[int(now / FRAME_SECONDS) % len(FRAMES)]


def strip_ansi(text: str) -> str:
    return _TOKEN.sub(lambda match: match.group(2) or "", text)


def _char_width(char: str) -> int:
    if unicodedata.combining(char) or unicodedata.category(char) in ("Mn", "Me", "Cf"):
        return 0
    return 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1


def visible_width(text: str) -> int:
    return sum(_char_width(char) for char in strip_ansi(text))


def clip(text: str, width: int) -> str:
    """Fit text into width columns, ending in an ellipsis when it had to be cut."""
    if width <= 0:
        return ""
    if visible_width(text) <= width:
        return text
    kept, used, styled = [], 0, False
    for match in _TOKEN.finditer(text):
        if match.group(1):
            kept.append(match.group(1))
            styled = True
            continue
        char_width = _char_width(match.group(2))
        if used + char_width > width - 1:
            break
        kept.append(match.group(2))
        used += char_width
    return "".join(kept) + "…" + (RESET if styled else "")


class Painter:
    def __init__(self, color: bool):
        self.color = color

    def _wrap(self, code: str, text: str) -> str:
        return f"\x1b[{code}m{text}{RESET}" if self.color else text

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def ok(self, text: str) -> str:
        return self._wrap("32", text)

    def warn(self, text: str) -> str:
        return self._wrap("33", text)

    def lang(self, code: str, text: str, *, bold: bool = False) -> str:
        color = LANGUAGE_COLORS.get(code, "36")
        return self._wrap(f"1;{color}" if bold else color, text)
