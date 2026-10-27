"""Stderr displays for each output mode, driven by pipeline events."""

import sys
import time
from collections.abc import Callable, Mapping

from . import __version__
from .config import Settings
from .pipeline import RunResult, Step


def hops_per_pass(settings: Settings) -> int:
    return len(settings.chain) - 1


def total_hops(settings: Settings) -> int:
    return hops_per_pass(settings) * settings.repeat


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


def make_display(*, quiet: bool, verbose: bool, steps: bool, stream, environ: Mapping[str, str],
                 platform: str = sys.platform, clock: Callable[[], float] = time.monotonic) -> Display:
    if quiet:
        return Display()
    if verbose or steps:
        return PlainDisplay(stream, verbose=verbose, steps=steps, clock=clock)
    return Display()
