"""Terminal capability detection and ANSI styling for stderr decoration."""

import os
import re
import sys
import threading
import time
import unicodedata
from collections.abc import Callable, Mapping, Sequence
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


def printable(text: str) -> str:
    """Replace control characters, tabs included, with spaces so a live row's width is predictable."""
    return "".join(" " if unicodedata.category(char) == "Cc" else char for char in text)


def _char_width(char: str) -> int:
    if char == "️":
        return 1  # emoji presentation selector: most terminals draw the character before it two columns wide
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


class LiveRegion:
    """A block of lines at the bottom of a terminal stream, redrawn in place.

    The block occupies `rows` lines with the cursor resting at the end of the last one. Text
    printed above it scrolls into the terminal's history. Any stream error disables the region
    quietly, so a closed terminal can never raise out of an animation.
    """

    def __init__(self, stream, *, width: Callable[[], int] | None = None, clock=time.monotonic,
                 interval: float = FRAME_SECONDS, threaded: bool = True):
        self._stream = stream
        self._width = width or (lambda: terminal_width(stream))
        self._clock, self._interval, self._threaded = clock, interval, threaded
        self.lock = threading.RLock()
        self._render: Callable[[float], list[str]] | None = None
        self._rows = 0
        self._started = self._closed = self._dead = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def columns(self) -> int:
        try:
            return self._width()
        except (OSError, ValueError):
            return 80

    def _write(self, text: str) -> None:
        try:
            self._stream.write(text)
            self._stream.flush()
        except (OSError, ValueError):
            self._dead = True

    def _erase(self) -> str:
        rows, self._rows = self._rows, 0
        if not rows:
            return ""
        return "\r" + (f"\x1b[{rows - 1}A" if rows > 1 else "") + "\x1b[J"

    def _block(self) -> str:
        if self._render is None:
            return ""
        width = max(self.columns() - 1, 1)
        lines = [clip(line, width) for line in self._render(self._clock())]
        self._rows = len(lines)
        return "\n".join(lines)

    def start(self, render: Callable[[float], list[str]]) -> None:
        with self.lock:
            if self._dead or self._closed:
                return
            self._render, self._started = render, True
            self._write("\x1b[?25l")
            if self._threaded and not self._dead:
                self._thread = threading.Thread(target=self._animate, daemon=True)
                self._thread.start()

    def _animate(self) -> None:
        while not self._stop.wait(self._interval):
            self.tick()

    def tick(self) -> None:
        with self.lock:
            if self._dead or self._closed or self._render is None:
                return
            self._write(self._erase() + self._block())

    def print_above(self, text: str) -> None:
        with self.lock:
            if self._dead or self._closed:
                return
            self._write(self._erase() + text + "\n" + self._block())

    def finish(self, final: Sequence[str] = ()) -> None:
        with self.lock:
            if self._closed:
                return
            self._closed = True
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=1)
        with self.lock:
            if self._dead:
                return
            self._write(self._erase() + "".join(line + "\n" for line in final)
                        + ("\x1b[?25h" if self._started else ""))

    def close(self) -> None:
        self.finish()
