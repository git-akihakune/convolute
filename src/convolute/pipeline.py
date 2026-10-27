"""Sequential round trips and public, credential-free run records."""

from collections.abc import Callable
from dataclasses import dataclass, field
from time import monotonic

from .client import TranslationError
from .config import Settings


@dataclass(frozen=True)
class Step:
    pass_number: int
    step_number: int
    source: str
    target: str
    text: str
    duration_seconds: float


@dataclass
class RunResult:
    input: str
    chain: tuple[str, ...]
    preset: str | None
    mode: str
    repeat: int
    model: str
    endpoint: str
    request_settings: dict
    schema_version: int = 1
    status: str = "success"
    output: str | None = None
    steps: list[Step] = field(default_factory=list)
    error: dict | None = None


def run(text: str, settings: Settings,
        translate: Callable[[str, str, str], str],
        on_step: Callable[[Step], None] | None = None,
        on_start: Callable[[int, int, str, str], None] | None = None) -> RunResult:
    result = RunResult(
        input=text, chain=settings.chain, preset=settings.preset, mode=settings.mode,
        repeat=settings.repeat, model=settings.model, endpoint=settings.endpoint,
        request_settings=settings.request_settings(),
    )
    current = text
    for pass_number in range(1, settings.repeat + 1):
        for step_number, (source, target) in enumerate(zip(settings.chain, settings.chain[1:]), 1):
            if on_start is not None:
                on_start(pass_number, step_number, source, target)
            started = monotonic()
            try:
                current = translate(current, source, target)
            except TranslationError as error:
                result.status = "error"
                result.error = {
                    "code": error.code, "message": str(error),
                    "pass_number": pass_number, "step_number": step_number,
                    "source": source, "target": target,
                }
                return result
            step = Step(pass_number, step_number, source, target, current, monotonic() - started)
            result.steps.append(step)
            if on_step is not None:
                on_step(step)
    result.output = current
    return result
