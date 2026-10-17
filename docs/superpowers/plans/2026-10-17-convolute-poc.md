# Convolute POC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Deliver an installable CLI that paraphrases text through configurable, sequential LLM translations, with a five-translation default and optional creative mode.

**Architecture:** A Python package separates configuration and language normalization, HTTP transport, the sequential pipeline, and CLI input/output. Every hop uses a fresh OpenAI-compatible chat request containing only translation instructions and the current text. The CLI renders a complete result or a structured failure; no hidden model downloads or network fallback occur.

**Tech Stack:** Python 3.11+, argparse, httpx; pytest and a local HTTP server for tests; setuptools and wheel for packaging.

**Spec:** `docs/superpowers/specs/2026-10-17-convolute-design.md` (approved 2026-10-17).

**Status:** Approved by the user on 2026-10-17; native implementation complete, awaiting final independent review.

## Global Constraints

- Default preset `long`: `en,fr,de,ja,es,en`; `short`: `en,fr,en`; `extended`: `en,fr,de,es,pt,it,zh,ja,ko,en`.
- Default mode `faithful`; alternate `creative`; mode, chain, repeat, and temperature are independent.
- Default endpoint `http://127.0.0.1:11434/v1`; model `qwen2.5:7b`; repeat `1`; timeout `120` seconds per attempt; retries `0`; omit temperature unless supplied.
- CLI values override tool-specific environment settings, which override defaults. Keys only come from `CONVOLUTE_API_KEY`; never include them in errors or records.
- Supported languages: `en,fr,de,es,pt,it,zh,ko,ja,id,ru,ar,hi,vi,th,tr,nl,pl,uk`; aliases `cn→zh`, `kr→ko`, `jp→ja`.
- Closed chains require at least two translations and distinct adjacent languages. Explicit `--preset` and `--chain` conflict.
- Input is whole-document UTF-8. Do not silently chunk or truncate; defer batching, concurrency, caching, resumability, and semantic scoring.
- Plain stdout contains only final output; intermediate steps and diagnostics use stderr. JSON failures have `output: null` and completed steps.
- Exit codes: success `0`, configuration/input `2`, translation/transport/protocol failure `1`, interruption `130`.
- Preserve the existing license. Do not publish, push, or contact a live paid endpoint as part of automated tests.

## File Structure and Interfaces

| File | Responsibility |
| --- | --- |
| `pyproject.toml`, `.gitignore` | Build metadata, Python/dependency requirements, console script, generated-file exclusions |
| `src/convolute/__init__.py`, `__main__.py` | Package version and module entry point |
| `src/convolute/languages.py` | Language names, fixed presets, `resolve_chain(preset: str | None, chain: str | None) -> tuple[str, ...]` |
| `src/convolute/config.py` | Frozen `Settings` dataclass; `resolve_settings(options: argparse.Namespace, environ: Mapping[str, str]) -> Settings`; `normalize_endpoint(value: str) -> str` |
| `src/convolute/client.py` | `TranslationError(code: str, message: str)`; context-managed `TranslationClient(settings: Settings)` and `translate(text: str, source: str, target: str) -> str` |
| `src/convolute/pipeline.py` | `Step`, `RunResult`; `run(text: str, settings: Settings, translate: Callable[[str, str, str], str], on_step: Callable[[Step], None] | None = None) -> RunResult` |
| `src/convolute/cli.py` | `build_parser() -> argparse.ArgumentParser`; `main(argv: Sequence[str] | None = None) -> int`; input, stdout/stderr, dry-run and exit handling |
| `tests/conftest.py`, `test_config.py`, `test_client.py`, `test_pipeline.py`, `test_cli.py` | Shared HTTP fixture and behavior-focused tests |
| `README.md` | Installation, local setup, examples, flags, data handling, limits, development checks |

`Settings` fields: `chain: tuple[str, ...]`, `preset: str | None`, `mode: str`, `repeat: int`, `endpoint: str`, `model: str`, `timeout: float`, `retries: int`, `temperature: float | None`, `api_key: str | None`. Exclude `api_key` from dataclass repr and from serialization; explicitly construct public settings records.

`Step` fields: `pass_number`, `step_number`, `source`, `target`, `text`, `duration_seconds`. `RunResult` fields: `schema_version` (integer `1`), `status` (`success` or `error`), `input`, `output`, `chain`, `preset`, `mode`, `repeat`, `model`, `endpoint`, `request_settings`, `steps`, `error`. `error` is null or an object containing `code`, safe `message`, `pass_number`, `step_number`, `source`, and `target`. `request_settings` contains timeout, retries, and optional temperature; no credentials.

## Review Focus

- Bare IPv6 loopback addresses and trailing-slash/custom-path endpoints must normalize without corrupting URLs (Task 1).
- NaN/infinite numbers and whitespace-only model/environment values must fail before network calls, without echoing credentials (Task 1).
- Refusal or tool-call content, including a nominal `finish_reason: stop`, must never become the next translation input (Task 2).
- Retry-After HTTP dates and malformed values must not cause unbounded waits; no retry of read timeouts (Task 2).
- Mid-chain failure, invalid UTF-8 stdin, Ctrl-C, and closed output pipes must not emit tracebacks or successful partial paraphrases (Tasks 3–4).

## Task 1: Configuration and language contracts

**Files:** Create package/build metadata, `languages.py`, `config.py`, and `tests/test_config.py`.

**Interfaces:** Produce `Settings`, `resolve_settings`, `normalize_endpoint`, and `resolve_chain` as defined above. Raise `ValueError` with safe messages for invalid configuration. The later parser supplies optional values as `None` so environment precedence is explicit.

- [x] After checking environment/network policy, create an isolated development virtualenv under `work/`, install pytest, httpx, build, and setuptools there, and use its Python for subsequent commands. During initial red tests use `PYTHONPATH=src python -m pytest ...`; after package metadata exists install `python -m pip install -e '.[test]'` so subsequent test commands resolve the package normally. Keep generated files ignored.
- [x] Write tests: `resolve_chain(None, None) == ('en','fr','de','ja','es','en')`; named presets have 2/5/9 hops; `resolve_chain(None, ' EN, CN, KR, JP, ID, EN ') == ('en','zh','ko','ja','id','en')`; reject conflicting selectors, unknown codes, empty entries, adjacent duplicates, and nonclosed/too-short chains.
- [x] Add endpoint/numeric/precedence tests: `127.0.0.1:11434` and `[::1]:11434` become loopback HTTP `/v1` bases; `https://host/custom/v1/` retains its base path without a trailing slash; origin-only URLs gain `/v1`; reject nonloopback schemeless hosts, invalid ports, userinfo, query, fragments, operation URLs, nonpositive repeats/timeouts, negative retries, nonfinite values, out-of-range temperature, blank models, and invalid modes. Assert CLI overrides environment for endpoint/model/mode; defaults apply otherwise; credentials never appear in repr/errors.
- [x] Run `python -m pytest tests/test_config.py -q`; confirm failures identify missing package/functions, then implement the smallest package/configuration code to satisfy these contracts. Define `requires-python = ">=3.11"`, runtime `httpx>=0.27,<1`, a test extra containing pytest, and the `convolute = "convolute.cli:main"` entry point.
- [x] Install the editable package and re-run `python -m pytest tests/test_config.py -q`; all tests must pass. Review normalization against the spec, then commit the task.

## Task 2: OpenAI-compatible translation client

**Files:** Create `client.py`, `tests/conftest.py`, and `tests/test_client.py`.

**Interfaces:** Consume `Settings`. Produce `TranslationError` and context-managed `TranslationClient.translate` as defined above. Inject a sleep callable/clock into retry helpers for fast deterministic tests; production defaults use monotonic timing, UTC dates, and normal sleep.

- [x] Write a local HTTP fixture that captures request path/headers/JSON and returns queued responses. Assert one POST to `/v1/chat/completions` or the preserved custom base path, correct model, `stream: false`, exactly system/user messages, unmodified Unicode user content, optional Bearer header, and temperature omitted unless supplied. In both modes assert target/source names and facts-preservation instructions; creative mode additionally requests freer expression. Successful content is returned without stripping quotes or markup.
- [x] Add failures: connection errors; HTTP `400/401/404/413/422/429/500/502/503/504`; redirect refusal; malformed JSON/schema; missing/empty/nonstring content; missing/non-stop finish reason; refusal/tool calls even with `stop`. Assert safe errors omit echoed bodies and credentials. Check zero retries by default; opted-in retry counts/backoff; bounded numeric/date Retry-After; malformed headers fall back to backoff; read/write timeouts and nonretryable responses fail immediately. Use injected/mock transports for connection/timeout classes that cannot be reliably induced by the local server.
- [x] Run `python -m pytest tests/test_client.py -q` and confirm missing-client failures, then implement requests with a persistent `httpx.Client`, verified TLS, redirects disabled, finite timeouts, a mode-specific system prompt, strict response validation, and retries only for connection failures or `429/502/503/504`. Cap exponential delay at 10 seconds and fail rather than shorten a valid Retry-After above 10 seconds. Use safe status/category messages, not raw response data.
- [x] Re-run configuration and client tests; all must pass. Review key handling and retry request counts, then commit the task.

## Task 3: Ordered translation execution and run records

**Files:** Create `pipeline.py` and `tests/test_pipeline.py`.

**Interfaces:** Consume `Settings`, a translate callable, and `TranslationError`. Produce `Step`, `RunResult`, and `run` as defined above; each completed step triggers `on_step` if supplied. Translation failures produce an error result; interruptions propagate to the CLI.

- [x] Write a recording translator test: for chain `en,fr,en`, repeat `2`, assert pairs `[('en','fr'),('fr','en'),('en','fr'),('fr','en')]`, each next input equals the previous output, four steps have correct pass/local-step numbers, and final output equals the fourth result. Assert the default produces five calls and both modes preserve the selected chain. Successful results include schema version, original input, public settings, steps, and nonnegative durations without credentials.
- [x] Write a translator failing on call three; assert exactly three calls, two completed steps, `status == 'error'`, `output is None`, and the failing pair/pass/step in the error record. Assert step callbacks run only for completed hops. Assert `KeyboardInterrupt` propagates and does not become a translation error. Test multiline input and quoted output without destructive cleanup.
- [x] Run `python -m pytest tests/test_pipeline.py -q` and confirm missing-pipeline failures; implement the sequential loops with monotonic per-hop durations, explicit public serialization, and immediate termination on `TranslationError`.
- [x] Run all tests through this task; all must pass. Review repeat boundaries and partial-result serialization, then commit the task.

## Task 4: CLI, documentation, and installable distribution

**Files:** Create `cli.py`, `__main__.py`, and `tests/test_cli.py`; update `README.md` and finish package metadata.

**Interfaces:** Consume `resolve_settings`, `TranslationClient`, and `run`. Produce the console and module entry points. `main` reads standard streams, returns exit codes, and leaves raising `SystemExit` to the entry-point wrapper.

- [x] Write CLI tests for positional/file/stdin selection, `--file -`, positional/file conflict, strict UTF-8 failure, empty input, terminal-without-input usage, text starting with a dash via `--`, and all documented flags. Assert `--help` makes no network calls, stdout is final text plus one newline, and `--show-steps` uses only stderr. Isolate environment variables in tests.
- [x] Add successful/failed JSON tests, safe diagnostics and exact exit codes, interruption `130`, and broken-pipe handling without traceback (exit `1`). Dry-run must report effective public settings, canonical chain/mode, call count, and character count without text/key, and instantiate no client. Reject dry-run with JSON/show-steps. Use the real HTTP fixture for subprocess tests of the default five calls, aliases/custom chain/repeat, creative prompt, environment auth, and a middle-hop failure that leaves plain stdout empty.
- [x] Run `python -m pytest tests/test_cli.py -q` and confirm missing-entry-point failures. Implement argparse options and mutual exclusions, safe input/config error handling, step rendering, JSON serialization, dry-run short circuit, and entry points. Handle input decoding/file errors as exit `2`, transport/protocol failures as `1`, and user interruption as `130`.
- [x] Document `pipx install .`, local Ollama preparation (`ollama pull qwen2.5:7b` and a running server), default/creative/preset/custom-chain examples, environment precedence, API base URLs, retries, JSON schema, stdout/stderr conventions, whole-document context limits, model-dependent fidelity, supported codes/aliases, and development commands. Link research sources from the spec. Do not claim live translation quality without live evaluation.
- [x] Run `python -m pytest -q` and `git diff --check`; build sdist/wheel with `python -m build`, install the wheel into an isolated virtualenv, run both `convolute --help` and `python -m convolute --dry-run 'test'`, and confirm default dry-run reports five calls and faithful mode. Verify the built artifact contains the license and package. If a configured live endpoint is available, perform the spec's comparison corpus; otherwise explicitly report live quality as unverified. Review the final diff against the spec and commit the task.

## Execution Prerequisites and Handoff

Before product edits, obtain the user's plan review and execution-method selection. At execution time read the applicable worktree, execution, test-first, and verification skills. Inspect repository instructions and environment/network policy before installing dependencies. Use the already isolated native checkout if applicable; otherwise create a worktree according to the worktree skill. Keep generated virtualenvs, distributions, and scratch assets ignored. Never overwrite pre-existing user changes.

Self-review completed: all approved spec sections map to the four tasks; all five review-focus classes have explicit verification; interfaces and result fields are consistent across tasks; live quality validation remains conditional on endpoint availability. No product code or dependencies have been added by this planning step.

## Execution Verification

- Automated suite: `python -m pytest -q` — 123 tests passed.
- Built both sdist and wheel with `python -m build --no-isolation`.
- Installed the wheel in a separate virtualenv; console help and isolated module dry-run succeeded with five default calls and faithful mode.
- Verified wheel package files and GPL-3.0-only license metadata.
- No live LLM endpoint was configured; paraphrase quality has not been measured.
