"""Stderr displays for each output mode, driven by pipeline events."""

import sys
import time
from collections.abc import Callable, Mapping, Sequence

from . import __version__
from .config import Settings
from .pipeline import RunResult, Step
from .terminal import (FRAME_SECONDS, FRAMES, LiveRegion, Painter, clip, detect_capabilities,
                       printable, spinner_frame, visible_width)

REVEAL_SECONDS = 1.0
REVEAL_CHARS_PER_SECOND = 60


def hops_per_pass(settings: Settings) -> int:
    return len(settings.chain) - 1


def total_hops(settings: Settings) -> int:
    return hops_per_pass(settings) * settings.repeat


def progress(settings: Settings, pass_number: int, step_number: int) -> str:
    label = f"hop {step_number}/{hops_per_pass(settings)}"
    if settings.repeat > 1:
        return f"pass {pass_number}/{settings.repeat} · {label}"
    return label


def step_tag(settings: Settings, pass_number: int, step_number: int) -> str:
    if settings.repeat > 1:
        return f"[p{pass_number} {step_number}/{hops_per_pass(settings)}]"
    return f"[{step_number}/{hops_per_pass(settings)}]"


def reveal_count(length: int, elapsed: float) -> int:
    """Characters of a translation shown `elapsed` seconds into its typing reveal."""
    duration = min(REVEAL_SECONDS, length / REVEAL_CHARS_PER_SECOND)
    if duration <= 0 or elapsed >= duration:
        return length
    return int(length * elapsed / duration)


def is_revealable(text: str, width: int) -> bool:
    """Only single-line text that fits one terminal row is typed out; anything else appears whole."""
    return "\n" not in text and visible_width(text) + 2 <= width - 1


def header_rows(settings: Settings, input_chars: int, *, arrow: str, sep: str) -> list[tuple[str, str]]:
    chain = f" {arrow} ".join(settings.chain)
    if settings.repeat > 1:
        chain += f" ({settings.repeat} passes)"
    return [
        ("model", settings.model),
        ("endpoint", settings.endpoint),
        ("chain", chain),
        ("mode", f"{settings.mode}{sep}{total_hops(settings)} hops{sep}{input_chars} chars in"),
    ]


class Display:
    """Shows nothing: the display for --quiet and for runs without an interactive terminal."""

    def begin(self, settings: Settings, input_chars: int) -> None:
        pass

    def hop_started(self, pass_number: int, step_number: int, source: str, target: str) -> None:
        pass

    def hop_finished(self, step: Step) -> None:
        pass

    def end(self, result: RunResult) -> None:
        pass

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class PlainDisplay(Display):
    """ASCII text lines for --verbose and --show-steps when stderr is not an interactive terminal."""

    def __init__(self, stream, *, verbose: bool, steps: bool, clock: Callable[[], float] = time.monotonic):
        self._stream, self._verbose, self._steps, self._clock = stream, verbose, steps, clock
        self._settings: Settings | None = None
        self._began = 0.0
        self._previous_chars = 0

    def _write(self, text: str) -> None:
        self._stream.write(text)
        self._stream.flush()

    def begin(self, settings: Settings, input_chars: int) -> None:
        self._settings, self._previous_chars = settings, input_chars
        if self._verbose:
            self._began = self._clock()
            rows = header_rows(settings, input_chars, arrow="->", sep=", ")
            self._write(f"convolute {__version__}\n" + "".join(f"{key:<9} {value}\n" for key, value in rows))

    def hop_finished(self, step: Step) -> None:
        label = f"pass {step.pass_number}, step {step.step_number}: {step.source} -> {step.target}"
        if not self._verbose:
            self._write(f"{label}\n{step.text}\n\n")
            return
        chars = len(step.text)
        line = f"{label}  {step.duration_seconds:.1f}s  {self._previous_chars} -> {chars} chars\n"
        self._previous_chars = chars
        self._write(line + (f"{step.text}\n\n" if self._steps else ""))

    def end(self, result: RunResult) -> None:
        if self._verbose and result.status == "success":
            elapsed = self._clock() - self._began
            self._write(f"done in {elapsed:.1f}s, {total_hops(self._settings)} hops\n")


class LiveDisplay(Display):
    """Base for displays that animate a live region on an interactive terminal."""

    def __init__(self, region: LiveRegion, painter: Painter, clock: Callable[[], float]):
        self._region, self._painter, self._clock = region, painter, clock
        self._settings: Settings | None = None
        self._began = 0.0

    def begin(self, settings: Settings, input_chars: int) -> None:
        self._settings, self._began = settings, self._clock()
        self._region.start(self._render)

    def _render(self, now: float) -> list[str]:
        raise NotImplementedError

    def _elapsed(self) -> float:
        return self._clock() - self._began

    def close(self) -> None:
        self._region.close()


def hop_status(paint: Painter, settings: Settings, hop: tuple[int, int, str, str, float], now: float) -> str:
    """The spinner line for the hop in progress: `⠹ de → ja  hop 3/5 · 1.2s`."""
    pass_number, step_number, source, target, started = hop
    status = f"{progress(settings, pass_number, step_number)} · {now - started:.1f}s"
    return (f"{paint.lang(target, spinner_frame(now))} {paint.lang(source, source)} {paint.dim('→')} "
            f"{paint.lang(target, target)}  {paint.dim(status)}")


class SpinnerDisplay(LiveDisplay):
    """One redrawn line while a hop runs, replaced by a dim summary when the run succeeds."""

    def __init__(self, region: LiveRegion, painter: Painter, clock: Callable[[], float]):
        super().__init__(region, painter, clock)
        self._hop: tuple[int, int, str, str, float] | None = None

    def hop_started(self, pass_number: int, step_number: int, source: str, target: str) -> None:
        with self._region.lock:
            self._hop = (pass_number, step_number, source, target, self._clock())

    def _render(self, now: float) -> list[str]:
        if self._hop is None:
            return []
        return [hop_status(self._painter, self._settings, self._hop, now)]

    def end(self, result: RunResult) -> None:
        if result.status != "success":
            self._region.finish()
            return
        summary = f"{total_hops(self._settings)} translations · {self._elapsed():.1f}s"
        self._region.finish([f"{self._painter.ok('✔')} {self._painter.dim(summary)}"])


class LogDisplay(LiveDisplay):
    """Colored --verbose log: a header, then every hop committed to the scrollback as it finishes.

    With `steps` each translation follows its hop line behind a colored bar (the chain log).
    """

    def __init__(self, region: LiveRegion, painter: Painter, clock: Callable[[], float], *, steps: bool):
        super().__init__(region, painter, clock)
        self._steps = steps
        self._pending: tuple[int, int, str, str, float] | None = None
        self._typing: tuple[str, str, float] | None = None
        self._previous_chars = 0

    def begin(self, settings: Settings, input_chars: int) -> None:
        paint, region = self._painter, self._region
        self._previous_chars = input_chars
        region.print_above(f"convolute {__version__}")
        rows = header_rows(settings, input_chars, arrow="→", sep=" · ")
        for index, (key, value) in enumerate(rows):
            glyph = "└" if index == len(rows) - 1 else "├"
            region.print_above(f"{paint.dim(f'{glyph} {key:<9}')}{value}")
        region.print_above("")
        super().begin(settings, input_chars)

    def hop_started(self, pass_number: int, step_number: int, source: str, target: str) -> None:
        with self._region.lock:
            self._pending = (pass_number, step_number, source, target, self._clock())

    def _text_lines(self, target: str, text: str) -> str:
        paint = self._painter
        return "\n".join(f"  {paint.lang(target, '┃')} {paint.lang(target, line)}" for line in text.split("\n"))

    def _flush_typing(self) -> None:
        if self._typing is not None:
            target, text, _ = self._typing
            self._typing = None
            self._region.print_above(self._text_lines(target, text))

    def hop_finished(self, step: Step) -> None:
        paint = self._painter
        with self._region.lock:
            self._flush_typing()
            self._pending = None
            tag = step_tag(self._settings, step.pass_number, step.step_number)
            chars = len(step.text)
            self._region.print_above(
                f"{paint.dim(tag)} {paint.lang(step.source, step.source)} {paint.dim('→')} "
                f"{paint.lang(step.target, step.target)}  {paint.ok('✔')} {paint.warn(f'{step.duration_seconds:.1f}s')}"
                f"  {paint.dim(f'{self._previous_chars} → {chars} chars')}")
            self._previous_chars = chars
            if not self._steps:
                return
            if is_revealable(printable(step.text), self._region.columns()):
                self._typing = (step.target, step.text, self._clock())
            else:
                self._region.print_above(self._text_lines(step.target, step.text))

    def _render(self, now: float) -> list[str]:
        paint, lines = self._painter, []
        if self._typing is not None:
            target, text, started = self._typing
            lines.append(self._text_lines(target, printable(text[:reveal_count(len(text), now - started)])))
        if self._pending is not None:
            pass_number, step_number, source, target, started = self._pending
            tag = step_tag(self._settings, pass_number, step_number)
            lines.append(f"{paint.dim(tag)} {paint.lang(source, source)} {paint.dim('→')} "
                         f"{paint.lang(target, target)}  {paint.lang(target, spinner_frame(now))} "
                         f"{paint.dim(f'{now - started:.1f}s')}")
        return lines

    def close(self) -> None:
        # An interrupt can arrive while the last translation is still being typed: keep it.
        with self._region.lock:
            self._flush_typing()
        super().close()

    def end(self, result: RunResult) -> None:
        with self._region.lock:
            self._flush_typing()
            self._pending = None
        if result.status != "success":
            self._region.finish()
            return
        summary = f"done in {self._elapsed():.1f}s · {total_hops(self._settings)} hops"
        self._region.finish(["", f"{self._painter.ok('✔')} {self._painter.dim(summary)}"])


def preview(text: str) -> str:
    return " ".join(printable(text).split())


def _rail(chain: Sequence[str], nodes: range, current: int, paint: Painter, phase: int, done: bool,
          segment: int) -> str:
    line = ""
    for index in nodes:
        code = chain[index]
        label = code.upper()
        line += paint.lang(code, label, bold=True) if done or index <= current else paint.dim(label)
        line += paint.lang(code, FRAMES[phase % len(FRAMES)]) if not done and index == current + 1 else " "
        if segment and index != nodes[-1]:
            if done or index < current:
                part = paint.lang(chain[index + 1], "━" * segment)
            elif index == current:
                position = (phase // 2) % segment
                part = paint.lang(chain[index + 1], "╌" * position + "━" + "╌" * (segment - position - 1))
            else:
                part = paint.dim("╌" * segment)
            line += f"{part} "
    return line.rstrip()


def rail_text(chain: Sequence[str], current: int, painter: Painter, *, phase: int, done: bool,
              width: int) -> str:
    """`EN ━━━━ FR ━━━━ DE ╌╌╌╌ JA`, shrunk, then windowed around the active language, to fit width."""
    limit, count = width - 1, len(chain)
    for segment in (4, 2, 1, 0):
        line = _rail(chain, range(count), current, painter, phase, done, segment)
        if visible_width(line) <= limit:
            return line
    center = min(current + 1, count - 1)
    for size in range(count - 1, 0, -1):
        start = max(0, min(center - size // 2, count - size))
        stop = start + size
        line = (("… " if start else "") + _rail(chain, range(start, stop), current, painter, phase, done, 0)
                + (" …" if stop < count else ""))
        if visible_width(line) <= limit:
            return line
    return clip(_rail(chain, range(center, center + 1), current, painter, phase, done, 0), width)


class RailDisplay(LiveDisplay):
    """--show-steps on a terminal: a progress rail with the latest translation under it, redrawn in place."""

    def __init__(self, region: LiveRegion, painter: Painter, clock: Callable[[], float]):
        super().__init__(region, painter, clock)
        self._hop: tuple[int, int, str, str, float] | None = None
        self._latest: tuple[str, str, float] | None = None

    def hop_started(self, pass_number: int, step_number: int, source: str, target: str) -> None:
        with self._region.lock:
            self._hop = (pass_number, step_number, source, target, self._clock())

    def hop_finished(self, step: Step) -> None:
        with self._region.lock:
            self._latest = (step.target, preview(step.text), self._clock())

    def _render(self, now: float) -> list[str]:
        if self._hop is None:
            return []
        paint, width = self._painter, self._region.columns()
        lines = [rail_text(self._settings.chain, self._hop[1] - 1, paint, phase=int(now / FRAME_SECONDS),
                           done=False, width=width),
                 hop_status(paint, self._settings, self._hop, now)]
        if self._latest is not None:
            target, text, finished = self._latest
            shown = text[:reveal_count(len(text), now - finished)] if is_revealable(text, width) else text
            lines.append(f"{paint.lang(target, '┃')} {paint.lang(target, shown)}")
        return lines

    def end(self, result: RunResult) -> None:
        if result.status != "success":
            self._region.finish()
            return
        paint = self._painter
        rail = rail_text(self._settings.chain, 0, paint, phase=0, done=True, width=self._region.columns())
        summary = f"done · {total_hops(self._settings)} hops · {self._elapsed():.1f}s"
        self._region.finish([rail, f"{paint.ok('✔')} {paint.dim(summary)}"])


def make_display(*, quiet: bool, verbose: bool, steps: bool, stream, environ: Mapping[str, str],
                 platform: str = sys.platform, clock: Callable[[], float] = time.monotonic) -> Display:
    if quiet:
        return Display()
    caps = detect_capabilities(stream, environ, platform)
    if caps.interactive:
        region, painter = LiveRegion(stream, clock=clock), Painter(caps.color)
        if verbose:
            return LogDisplay(region, painter, clock, steps=steps)
        if steps:
            return RailDisplay(region, painter, clock)
        return SpinnerDisplay(region, painter, clock)
    if verbose or steps:
        return PlainDisplay(stream, verbose=verbose, steps=steps, clock=clock)
    return Display()
