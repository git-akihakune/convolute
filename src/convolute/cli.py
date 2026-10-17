"""Shell-friendly command-line interface."""

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from . import __version__
from .client import TranslationClient
from .config import resolve_settings
from .languages import PRESETS
from .pipeline import Step, run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="convolute",
        description="Paraphrase text through a chain of LLM translations.",
        epilog=("Defaults: long preset (5 translations), faithful mode, repeat 1, "
                "local Ollama at http://127.0.0.1:11434/v1, model qwen2.5:7b. "
                "With no text or --file, read UTF-8 stdin. Use -- before text starting with '-'."),
    )
    parser.add_argument("text", nargs="?", help="text to paraphrase")
    parser.add_argument("--file", metavar="PATH", help="read UTF-8 text from a file; '-' reads stdin")
    chains = parser.add_mutually_exclusive_group()
    chains.add_argument("--preset", choices=PRESETS, help="short (2), long (5, default), extended (9 translations)")
    chains.add_argument("--chain", metavar="CODES", help="closed language chain, e.g. EN,CN,KR,JP,ID,EN")
    parser.add_argument("--mode", choices=("faithful", "creative"), help="translation style (or CONVOLUTE_MODE)")
    parser.add_argument("--endpoint", help="OpenAI-compatible API base URL (or CONVOLUTE_ENDPOINT)")
    parser.add_argument("--model", help="model name (or CONVOLUTE_MODEL)")
    parser.add_argument("--repeat", type=int, metavar="N", help="complete passes, including the first (default: 1)")
    parser.add_argument("--timeout", type=float, metavar="SECONDS", help="HTTP timeout (default: 120 seconds)")
    parser.add_argument("--retries", type=int, metavar="N", help="opt-in retries per hop (default: 0)")
    parser.add_argument("--temperature", type=float, help="optional sampling temperature, 0–2; otherwise server default")
    parser.add_argument("--show-steps", action="store_true", help="print intermediate translations to stderr")
    parser.add_argument("--json", action="store_true", help="emit the complete run record as JSON")
    parser.add_argument("--dry-run", action="store_true", help="print a plan without sending text or contacting the endpoint")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _stdin_text() -> str:
    if hasattr(sys.stdin, "buffer"):
        return sys.stdin.buffer.read().decode("utf-8")
    return sys.stdin.read()


def _show_step(step: Step) -> None:
    print(f"pass {step.pass_number}, step {step.step_number}: {step.source} -> {step.target}\n{step.text}\n",
          file=sys.stderr, flush=True)


def _execute(argv: Sequence[str] | None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.text is not None and args.file is not None:
        parser.error("text and --file cannot be used together")
    if args.dry_run and (args.json or args.show_steps):
        parser.error("--dry-run cannot be combined with --json or --show-steps")
    try:
        settings = resolve_settings(args, os.environ)
    except ValueError as error:
        parser.error(str(error))
    try:
        if args.text is not None:
            text = args.text
        elif args.file is not None and args.file != "-":
            text = Path(args.file).read_bytes().decode("utf-8")
        else:
            if args.file is None and sys.stdin.isatty():
                parser.error("provide text, --file PATH, or UTF-8 stdin")
            text = _stdin_text()
    except UnicodeError:
        parser.error("input must be valid UTF-8")
    except OSError:
        parser.error("cannot read input; check the file path and permissions")
    if not text.strip():
        parser.error("input must contain non-whitespace text")

    if args.dry_run:
        plan = {
            "schema_version": 1, "status": "planned", "preset": settings.preset,
            "chain": settings.chain, "mode": settings.mode, "repeat": settings.repeat,
            "model": settings.model, "endpoint": settings.endpoint,
            "request_settings": settings.request_settings(),
            "total_calls": (len(settings.chain) - 1) * settings.repeat,
            "input_characters": len(text),
        }
        print(json.dumps(plan, ensure_ascii=False), flush=True)
        return 0

    with TranslationClient(settings) as client:
        result = run(text, settings, client.translate, _show_step if args.show_steps else None)
    if args.json:
        print(json.dumps(asdict(result), ensure_ascii=False), flush=True)
    elif result.status == "success":
        # Preserve translation whitespace, adding a newline only if needed.
        sys.stdout.write(result.output + ("" if result.output.endswith("\n") else "\n"))
        sys.stdout.flush()
    if result.error:
        error = result.error
        print(f"convolute: pass {error['pass_number']}, step {error['step_number']}: "
              f"{error['source']} -> {error['target']}: {error['message']}", file=sys.stderr)
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return _execute(argv)
    except KeyboardInterrupt:
        print("convolute: interrupted", file=sys.stderr)
        return 130
    except BrokenPipeError:
        # Silence whichever stream failed, so shutdown cannot override exit 1.
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.flush()
            except BrokenPipeError:
                try:
                    descriptor = os.open(os.devnull, os.O_WRONLY)
                    try:
                        os.dup2(descriptor, stream.fileno())
                    finally:
                        os.close(descriptor)
                except (OSError, ValueError, AttributeError):
                    pass
            except (OSError, ValueError):
                pass
        return 1
