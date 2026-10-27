# CLI Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a spinner, `--verbose`, animated colored `--show-steps`, `--clipboard`, and `--quiet` to the `convolute` CLI without changing stdout, JSON, or exit-code contracts.

**Architecture:** `run()` gains a hop-start hook. A new `terminal.py` holds terminal capability detection, ANSI helpers, and a `LiveRegion` that redraws a block of lines in place. A new `display.py` holds one `Display` class per output mode, all driven by the same four events (`begin`, `hop_started`, `hop_finished`, `end`). `clipboard.py` shells out to the system's clipboard tool. `cli.py` only chooses a display and wires events.

**Tech Stack:** Python 3.11+, argparse, httpx (unchanged), pytest, hand-written ANSI escapes.

**Spec:** `docs/superpowers/specs/2026-10-28-cli-experience-design.md`

**Test command:** `python -m pytest -q` from the repository root, inside the project venv (`python3 -m venv work/venv`, `. work/venv/bin/activate`, `python -m pip install -e '.[test]'`; see README, "Development and validation").

## Global Constraints

- Python `>=3.11`; the only runtime dependency stays `httpx>=0.27,<1`. No new dependencies.
- Stdout, the `--json` schema, `--dry-run` output, settings precedence, and exit codes (`0` success, `1` translation/transport/protocol or output-pipe failure, `2` invalid configuration/input, `130` interruption) do not change. All decoration goes to stderr.
- Interactive means: stderr is a TTY, `TERM` is not `dumb`, stderr encoding is UTF-8, and on Windows `WT_SESSION` is set. Anything else gets plain, ASCII-only, unanimated output.
- `NO_COLOR` (non-empty) removes color but keeps animation. `--quiet` removes the spinner, the summary line, and the clipboard confirmation; errors and warnings still print.
- Existing tests pass unchanged: a non-interactive default run leaves stderr empty, and `--show-steps` without a terminal keeps `pass P, step S: src -> tgt`, the text, and a blank line byte-for-byte.
- Colors are basic 16-color SGR, readable on light and dark backgrounds (never SGR `30`, `37`, `90`, `97`), and defined for all 19 supported language codes.
- Reveal ("typing") applies only to single-line text that fits the terminal row, for at most 1.0 second per hop.
- `--verbose` and `--clipboard` are rejected with `--dry-run`; `--quiet` is rejected with `--verbose` or `--show-steps`. No short flags and no new environment variables.
- Tests never touch the real clipboard. Do not bump the version or publish.
- Match surrounding style: `src/` uses double quotes and type hints; `tests/` uses single quotes and compact asserts.

## Review Focus

1. `--preset extended` (ten languages) on a narrow terminal: the rail must never wrap (Task 8).
2. A multi-paragraph translation of several KB on a terminal: no reveal, no corrupted redraw, the full text in the chain log (Task 7).
3. Ctrl-C or an HTTP failure mid-hop on a terminal: spinner cleared before the error, cursor shown again, stdout empty (Task 6).
4. Japanese text with double-width characters: clipping never splits a character or overruns the row (Task 3), and the clipboard receives the exact bytes (Task 9).
5. `--repeat 2` on a terminal: labels show `pass N/M` and the rail restarts each pass (Tasks 6 and 8).

---

## File Structure

- Create `src/convolute/terminal.py`: capability detection, width helpers, `Painter`, `LiveRegion`.
- Create `src/convolute/display.py`: `Display` and its five subclasses, `make_display`, rail and reveal helpers.
- Create `src/convolute/clipboard.py`: `copy_text`, `ClipboardError`.
- Modify `src/convolute/pipeline.py` (hop-start hook) and `src/convolute/cli.py` (flags, wiring).
- Create `tests/test_terminal.py`, `tests/test_display.py`, `tests/test_clipboard.py`, `tests/test_cli_terminal.py`; modify `tests/test_pipeline.py`, `tests/test_cli.py`, `tests/conftest.py`; update `README.md` and `.gitignore`.

### Task 1: Flags, validation, housekeeping

**Files:**
- Modify: `src/convolute/cli.py` (`build_parser`, `_execute` validation), `.gitignore`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `args.verbose`, `args.clipboard`, `args.quiet` (all `store_true`). They do nothing until later tasks.

- [ ] **Step 1: Baseline and housekeeping.** Run `python -m pytest -q` and confirm every existing test passes. Add `.superpowers/` to `.gitignore`. Commit the design and this plan:

```bash
git add .gitignore docs/superpowers/specs/2026-10-28-cli-experience-design.md docs/superpowers/plans/2026-10-28-cli-experience.md
git commit -m "docs: add CLI experience design and plan"
```

- [ ] **Step 2: Write the failing tests.** Add four cases to the parametrized list in `test_invalid_cli_arguments` (exit 2, empty stdout, no traceback): `['--dry-run','--verbose','x']`, `['--dry-run','--clipboard','x']`, `['--quiet','--verbose','x']`, `['--quiet','--show-steps','x']`. Add:

```python
def test_help_lists_display_flags_and_quiet_dry_run_is_allowed():
    help_text = invoke(['--help']).stdout
    assert all(flag in help_text for flag in (b'--verbose', b'--clipboard', b'--quiet'))
    assert invoke(['--dry-run','--quiet','x']).returncode == 0
```

- [ ] **Step 3: Run the new tests.** `python -m pytest tests/test_cli.py -q`. Expected: the five new cases FAIL (unrecognized arguments).
- [ ] **Step 4: Implement.** In `build_parser`, add `--verbose` ("print a colored log of settings and per-hop results to stderr"), `--clipboard` ("copy the final translation to the system clipboard"), and `--quiet` ("suppress the spinner and all other stderr decoration; errors still print"). In `_execute`, extend the existing dry-run check to `--json`, `--show-steps`, `--verbose`, `--clipboard` and add `--quiet` with `--verbose` or `--show-steps`, both via `parser.error`.
- [ ] **Step 5: Run the full suite.** Expected: all PASS.
- [ ] **Step 6: Commit.** `git add src/convolute/cli.py tests/test_cli.py && git commit -m "feat: add --verbose, --clipboard and --quiet flags with validation"`

### Task 2: Pipeline hop-start hook

**Files:**
- Modify: `src/convolute/pipeline.py:38-63`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Produces: `run(text, settings, translate, on_step=None, on_start: Callable[[int, int, str, str], None] | None = None) -> RunResult`. `on_start(pass_number, step_number, source, target)` runs immediately before each `translate` call.

- [ ] **Step 1: Write the failing test.**

```python
def test_on_start_precedes_every_translation_including_the_failing_one():
    events = []
    def translate(text,source,target):
        events.append(('translate',source,target))
        if events.count(('translate','en','fr')) == 2:
            raise TranslationError('timeout','request timed out')
        return 'x'
    run('x',resolve_settings(Namespace(chain='en,fr,en',repeat=2),{}),translate,
        lambda s: events.append(('done',s.pass_number,s.step_number)),
        lambda *hop: events.append(('start',*hop)))
    assert events == [('start',1,1,'en','fr'),('translate','en','fr'),('done',1,1),
                      ('start',1,2,'fr','en'),('translate','fr','en'),('done',1,2),
                      ('start',2,1,'en','fr'),('translate','en','fr')]
```

- [ ] **Step 2: Run it.** `python -m pytest tests/test_pipeline.py -q`. Expected: FAIL (unexpected argument).
- [ ] **Step 3: Implement** the `on_start` parameter, called right before `translate(...)` inside the step loop.
- [ ] **Step 4: Run the full suite.** Expected: all PASS.
- [ ] **Step 5: Commit.** `git add src/convolute/pipeline.py tests/test_pipeline.py && git commit -m "feat: report hop starts from the pipeline"`

### Task 3: Terminal primitives

**Files:**
- Create: `src/convolute/terminal.py`
- Modify: `tests/conftest.py` (shared `FakeStream`)
- Test: `tests/test_terminal.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) Capabilities(interactive: bool, color: bool)`
  - `detect_capabilities(stream, environ: Mapping[str, str], platform: str = sys.platform) -> Capabilities`
  - `terminal_width(stream) -> int` (falls back to `80` when the stream has no terminal)
  - `strip_ansi(text: str) -> str` (removes every CSI sequence), `visible_width(text: str) -> int` (ignores escapes; East Asian wide/fullwidth count 2, combining marks 0)
  - `clip(text: str, width: int) -> str`: unchanged when it fits; otherwise at most `width - 1` columns, never splitting a double-width character, then `…`, plus `\x1b[0m` if the text held any escape; `''` when `width <= 0`
  - `FRAMES` (ten braille spinner glyphs) and `spinner_frame(now: float) -> str` (one frame per 0.08 s)
  - `LANGUAGE_COLORS: dict[str, str]` (language code → SGR parameter)
  - `Painter(color: bool)` with `dim`, `bold`, `ok` (green), `warn` (yellow), and `lang(code, text, *, bold=False)`, each returning the text unchanged when `color` is false

- [ ] **Step 1: Write the failing tests.** In `tests/conftest.py` add `FakeStream(io.StringIO)` with constructor `(tty=True, encoding='utf-8')`, an `isatty()` returning `tty`, and an `encoding` property; later tasks import it like `completion`. Tests in `tests/test_terminal.py`:

```python
@pytest.mark.parametrize('tty,env,platform,encoding,expected',[
    (True,{'TERM':'xterm'},'linux','utf-8',(True,True)),
    (True,{},'darwin','utf-8',(True,True)),
    (True,{'TERM':'dumb'},'linux','utf-8',(False,False)),
    (False,{'TERM':'xterm'},'linux','utf-8',(False,False)),
    (True,{'TERM':'xterm','NO_COLOR':'1'},'linux','utf-8',(True,False)),
    (True,{'TERM':'xterm','NO_COLOR':''},'linux','utf-8',(True,True)),
    (True,{'TERM':'xterm'},'linux','latin-1',(False,False)),
    (True,{'TERM':'xterm'},'win32','utf-8',(False,False)),
    (True,{'WT_SESSION':'x'},'win32','utf-8',(True,True)),
])
def test_capabilities(tty,env,platform,encoding,expected):
    caps = detect_capabilities(FakeStream(tty,encoding),env,platform)
    assert (caps.interactive,caps.color) == expected

def test_language_colors_cover_every_language_and_stay_readable():
    assert set(LANGUAGE_COLORS) == set(LANGUAGES)
    assert not {'30','37','90','97'} & set(LANGUAGE_COLORS.values())

def test_painter_is_plain_without_color_and_strippable_with_it():
    assert Painter(False).ok('x') == 'x' and Painter(False).lang('fr','x') == 'x'
    styled = Painter(True).lang('fr','x')
    assert styled != 'x' and styled.endswith('\x1b[0m') and strip_ansi(styled) == 'x'

def test_width_and_clip_handle_escapes_and_double_width_text():
    assert visible_width('\x1b[31mabc\x1b[0m') == 3 and visible_width('会議は') == 6
    assert clip('abc',3) == 'abc' and clip('abc',0) == ''
    assert clip('\x1b[31mabcdef\x1b[0m',4) == '\x1b[31mabc…\x1b[0m'
    assert clip('会議は金曜日',7) == '会議は…'
    assert visible_width(clip('x'*100+'会',20)) <= 20

def test_terminal_width_falls_back_without_a_terminal():
    assert terminal_width(FakeStream()) == 80
```

- [ ] **Step 2: Run them.** `python -m pytest tests/test_terminal.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `terminal.py` to the interfaces above. Interactive means a TTY, `TERM != "dumb"`, UTF-8 stream encoding, and on `win32` a set `WT_SESSION`; color means interactive and a non-empty `NO_COLOR` absent. Fill `LANGUAGE_COLORS` for every key of `languages.LANGUAGES` from SGR `31`-`36` and `91`-`96`, repeating colors where needed.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit.** `git add src/convolute/terminal.py tests/test_terminal.py && git commit -m "feat: add terminal capability detection and ANSI helpers"`

### Task 4: LiveRegion

**Files:**
- Modify: `src/convolute/terminal.py`
- Test: `tests/test_terminal.py`

**Interfaces:**
- Consumes: `clip`, `terminal_width` (Task 3).
- Produces `LiveRegion(stream, *, width: Callable[[], int] | None = None, clock=time.monotonic, interval: float = 0.08, threaded: bool = True)`:
  - `lock: threading.RLock`. Displays take it when they change state; `tick` holds it while rendering.
  - `start(render: Callable[[float], list[str]]) -> None`: hide the cursor, start a daemon thread calling `tick()` every `interval` when `threaded`.
  - `tick() -> None`: render one frame, clip every line to `width() - 1`, redraw the block in place.
  - `columns() -> int`: the current terminal width, for displays that size their own content.
  - `print_above(text: str) -> None`: erase the block, write `text` plus a newline, redraw the block.
  - `finish(final: Sequence[str] = ()) -> None`: stop the thread, erase the block, write each `final` line plus a newline, show the cursor. `close()` is `finish()`. Both are idempotent.
  - Any `OSError` or `ValueError` from the stream disables the region silently; later calls do nothing and never raise.
- Block mechanics: the block occupies `n` rows with the cursor at the end of the last row. Erasing writes `\r`, then `\x1b[{n-1}A` when `n > 1`, then `\x1b[J`. Each redraw is one `stream.write`. Hide and show cursor with `\x1b[?25l` and `\x1b[?25h`.

- [ ] **Step 1: Write the failing tests** (`region = LiveRegion(stream, width=lambda: 40, threaded=False)`):

```python
def test_block_is_redrawn_in_place():
    stream = FakeStream(); region = LiveRegion(stream,width=lambda: 40,threaded=False)
    region.start(lambda now: ['one','two']); region.tick(); region.tick()
    out = stream.getvalue()
    assert out.startswith('\x1b[?25l') and out.count('\x1b[1A') == 1 and 'one\ntwo' in out
    assert region.columns() == 40

def test_print_above_scrolls_text_and_keeps_the_block_below():
    stream = FakeStream(); region = LiveRegion(stream,width=lambda: 40,threaded=False)
    region.start(lambda now: ['spin']); region.tick(); region.print_above('done line')
    assert strip_ansi(stream.getvalue()).replace('\r','').endswith('done line\nspin')

def test_finish_leaves_final_lines_and_restores_the_cursor_once():
    stream = FakeStream(); region = LiveRegion(stream,width=lambda: 40,threaded=False)
    region.start(lambda now: ['spin']); region.tick(); region.finish(['final'])
    out = stream.getvalue(); region.close()
    assert out.endswith('final\n\x1b[?25h') and stream.getvalue() == out

def test_lines_are_clipped_to_one_column_less_than_the_width():
    stream = FakeStream(); region = LiveRegion(stream,width=lambda: 10,threaded=False)
    region.start(lambda now: ['x'*50,'会'*30]); region.tick()
    rows = strip_ansi(stream.getvalue()).replace('\r','').split('\n')
    assert max(visible_width(row) for row in rows) <= 9

def test_stream_errors_never_escape():
    class Failing(FakeStream):
        def write(self,*_):
            raise BrokenPipeError
    region = LiveRegion(Failing(),width=lambda: 40,threaded=False)
    region.start(lambda now: ['x']); region.tick(); region.print_above('y'); region.finish(['z']); region.close()

def test_thread_animates_until_finished():
    frames = []
    region = LiveRegion(FakeStream(),width=lambda: 40,interval=0.01)
    region.start(lambda now: frames.append(now) or ['x'])
    deadline = time.monotonic()+2
    while len(frames) < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    region.finish(); count = len(frames); time.sleep(0.05)
    assert count >= 3 and len(frames) == count
```

- [ ] **Step 2: Run them.** Expected: FAIL (`LiveRegion` missing).
- [ ] **Step 3: Implement** `LiveRegion` to the interface above. `Painter`, `clip`, and the other Task 3 names stay untouched.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit.** `git add src/convolute/terminal.py tests/test_terminal.py && git commit -m "feat: add in-place live region for terminal animation"`

### Task 5: Plain displays and non-interactive wiring

**Files:**
- Create: `src/convolute/display.py`
- Modify: `src/convolute/cli.py` (remove `_show_step`; wire the display in `_execute`)
- Test: `tests/test_display.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `Settings`, `Step`, `RunResult`, `detect_capabilities`.
- Produces:
  - `class Display`: no-op base with `begin(settings: Settings, input_chars: int)`, `hop_started(pass_number, step_number, source, target)`, `hop_finished(step: Step)`, `end(result: RunResult)`, `close()`, and `__enter__`/`__exit__` (which calls `close`).
  - `PlainDisplay(stream, *, verbose: bool, steps: bool, clock=time.monotonic)`
  - `header_rows(settings: Settings, input_chars: int, *, arrow: str, sep: str) -> list[tuple[str, str]]`: rows for `model`, `endpoint`, `chain` (languages joined by ` {arrow} `, plus `× N passes` when `repeat > 1`), and `mode` (`{mode}{sep}{hops} hops{sep}{input_chars} chars in`)
  - `make_display(*, quiet: bool, verbose: bool, steps: bool, stream, environ, platform=sys.platform, clock=time.monotonic) -> Display`. Until Task 6, an interactive stream gets the non-interactive choice. The choice is: `quiet` gives `Display()`; otherwise `PlainDisplay` when `verbose` or `steps`; otherwise `Display()`.
- Plain formats (ASCII only, each write flushed):
  - `steps` alone: `pass {p}, step {s}: {src} -> {tgt}\n{text}\n\n` (the old format).
  - `verbose`: a `convolute {version}` line, one `key  value` row per `header_rows` entry (`arrow='->'`, `sep=', '`), then per hop `pass {p}, step {s}: {src} -> {tgt}  {duration:.1f}s  {prev} -> {new} chars\n`, then on success `done in {elapsed:.1f}s, {hops} hops\n`. With `steps` too, `{text}\n\n` follows each hop line. `elapsed` is measured with `clock`, called exactly once in `begin` and once in `end`.

- [ ] **Step 1: Write the failing tests** in `tests/test_display.py`. Module constants, reused by later tasks:

```python
def fail(*_):
    raise TranslationError('timeout','request timed out')

SETTINGS = resolve_settings(Namespace(preset='short'),{})
LONG = resolve_settings(Namespace(),{})
RESULT = run('hello',SETTINGS,lambda *_: 'x')
RESULT_LONG = run('hello',LONG,lambda *_: 'x')
FAILED = run('hello',SETTINGS,fail)
```

Tests:

```python
def test_plain_steps_alone_is_byte_compatible_with_the_old_format():
    out = io.StringIO(); display = PlainDisplay(out,verbose=False,steps=True)
    display.begin(SETTINGS,5); display.hop_finished(Step(1,2,'fr','de','Hallo',0.4)); display.end(RESULT)
    assert out.getvalue() == 'pass 1, step 2: fr -> de\nHallo\n\n'

def test_plain_verbose_logs_header_hops_and_summary_without_text():
    out = io.StringIO(); times = iter([0.0,4.2])
    display = PlainDisplay(out,verbose=True,steps=False,clock=lambda: next(times))
    display.begin(SETTINGS,5)
    display.hop_finished(Step(1,1,'en','fr','Bonjour',2.1))
    display.hop_finished(Step(1,2,'fr','en','Hello there',2.0))
    display.end(RESULT)
    text = out.getvalue()
    assert 'qwen2.5:7b' in text and 'en -> fr -> en' in text and 'Bonjour' not in text
    assert 'pass 1, step 1: en -> fr  2.1s  5 -> 7 chars\n' in text
    assert 'pass 1, step 2: fr -> en  2.0s  7 -> 11 chars\n' in text
    assert text.endswith('done in 4.2s, 2 hops\n') and text.isascii()

def test_plain_verbose_with_steps_prints_text_under_each_hop():
    out = io.StringIO(); display = PlainDisplay(out,verbose=True,steps=True)
    display.begin(SETTINGS,5); display.hop_finished(Step(1,1,'en','fr','Bonjour',2.1))
    assert 'pass 1, step 1: en -> fr  2.1s  5 -> 7 chars\nBonjour\n\n' in out.getvalue()

def test_a_failed_run_prints_no_summary():
    out = io.StringIO(); display = PlainDisplay(out,verbose=True,steps=False)
    display.begin(SETTINGS,1); display.end(FAILED)
    assert 'done in' not in out.getvalue()

@pytest.mark.parametrize('kwargs,tty,expected',[
    ({'quiet':True,'verbose':True,'steps':True},False,Display),
    ({'quiet':False,'verbose':False,'steps':False},False,Display),
    ({'quiet':False,'verbose':False,'steps':True},False,PlainDisplay),
    ({'quiet':False,'verbose':True,'steps':False},False,PlainDisplay),
])
def test_make_display_for_non_interactive_streams(kwargs,tty,expected):
    assert type(make_display(stream=FakeStream(tty),environ={'TERM':'xterm'},**kwargs)) is expected
```
  Add to `tests/test_cli.py`:

```python
def test_verbose_without_a_terminal_is_a_plain_ascii_log(server):
    result = invoke(['--endpoint',server.endpoint,'--preset','short','--verbose','text'])
    err = result.stderr.decode()
    assert result.returncode == 0 and result.stdout == b'translated\n'
    assert 'pass 1, step 2: fr -> en' in err and 'done in' in err and err.isascii()

def test_verbose_with_steps_and_quiet_without_a_terminal(server):
    result = invoke(['--endpoint',server.endpoint,'--preset','short','--verbose','--show-steps','text'])
    assert b'pass 1, step 1: en -> fr' in result.stderr and b'translated\n\n' in result.stderr
    quiet = invoke(['--endpoint',server.endpoint,'--preset','short','--quiet','text'])
    assert quiet.returncode == 0 and quiet.stdout == b'translated\n' and quiet.stderr == b''
```

- [ ] **Step 2: Run them.** Expected: FAIL (`display` module missing; stderr empty for `--verbose`).
- [ ] **Step 3: Implement** `Display`, `PlainDisplay`, `header_rows`, `make_display` in `display.py`. In `_execute`, replace the `run(...)` call with: build the display from `args` and `sys.stderr`/`os.environ`; inside `with TranslationClient(settings) as client, display:` call `display.begin(settings, len(text))`, `result = run(text, settings, client.translate, display.hop_finished, display.hop_started)`, `display.end(result)`. Stdout and the error message are written after the `with` block, so the display is closed first. Do not swallow `BrokenPipeError` from displays.
- [ ] **Step 4: Run the full suite.** Expected: all PASS, including the existing `--show-steps` and closed-pipe tests unchanged.
- [ ] **Step 5: Commit.** `git add src/convolute/display.py src/convolute/cli.py tests/test_display.py tests/test_cli.py && git commit -m "feat: add plain verbose and quiet output"`

### Task 6: Spinner and interactive wiring

**Files:**
- Modify: `src/convolute/display.py`, `tests/conftest.py`
- Create: `tests/test_cli_terminal.py`
- Test: `tests/test_display.py`

**Interfaces:**
- Consumes: `LiveRegion`, `Painter`, `spinner_frame`, `Display`.
- Produces:
  - `SpinnerDisplay(region: LiveRegion, painter: Painter, clock)`. `begin` stores settings and starts the region; `hop_started` sets the current hop; the single live line is `{spinner} {src} → {tgt}  {progress} · {elapsed:.1f}s`, with colored codes. `end` on success calls `region.finish([painter.dim('✔ {hops} translations · {elapsed:.1f}s')])`; on failure `region.finish()`. `close()` calls `region.close()`.
  - `progress(settings, pass_number, step_number) -> str`: `hop 3/5`, or `pass 2/3 · hop 3/5` when `repeat > 1`.
  - `make_display` now returns `SpinnerDisplay(LiveRegion(stream, clock=clock), Painter(caps.color), clock)` for an interactive stream with no `verbose` or `steps`.
  - `tests/conftest.py`: the `server` fixture state gains `delay` (seconds, default `0.0`), slept before each response.
  - `run_on_pty(args, *, columns=80, env=None, interrupt_when=None) -> SimpleNamespace(returncode, terminal, stdout)` in `tests/conftest.py`: runs `python -m convolute` with stderr on a pseudo-terminal of the given width (stdout a pipe, stdin null). The child's environment is a copy of `os.environ` without `NO_COLOR`, with `TERM=xterm-256color` and `PYTHONUTF8=1`, then updated with `env` (extra variables only). `terminal` is the decoded stderr bytes with `\r\n` normalized to `\n`. When `interrupt_when` is a substring, send `SIGINT` once `strip_ansi(terminal)` contains it. Imports `pty`, `termios`, and `fcntl` inside the function.

- [ ] **Step 1: Write the failing display tests.** In `tests/test_display.py` add `FakeClock` (callable returning `.now`) and `make(cls, settings, width=80, color=False, **kw)` returning `(out, clock, region, display)` built on `LiveRegion(out, width=lambda: width, clock=clock, threaded=False)`.

```python
def test_spinner_line_shows_progress_then_a_summary():
    out,clock,region,display = make(SpinnerDisplay,LONG)
    display.begin(LONG,37); display.hop_started(1,3,'de','ja'); clock.now = 1.2; region.tick()
    screen = strip_ansi(out.getvalue())
    assert 'de → ja' in screen and 'hop 3/5' in screen and '1.2s' in screen
    clock.now = 10.4; display.end(RESULT_LONG)
    assert strip_ansi(out.getvalue()).endswith('✔ 5 translations · 10.4s\n')

def test_spinner_shows_pass_when_repeating_and_no_summary_on_failure():
    repeated = resolve_settings(Namespace(preset='short',repeat=2),{})
    out,clock,region,display = make(SpinnerDisplay,repeated)
    display.begin(repeated,5); display.hop_started(2,1,'en','fr'); region.tick()
    assert 'pass 2/2 · hop 1/2' in strip_ansi(out.getvalue())
    display.end(FAILED); assert '✔' not in strip_ansi(out.getvalue())

def test_make_display_gives_interactive_default_a_spinner():
    display = make_display(quiet=False,verbose=False,steps=False,stream=FakeStream(True),environ={'TERM':'xterm'})
    assert type(display) is SpinnerDisplay; display.close()
```

- [ ] **Step 2: Write the failing terminal tests** in `tests/test_cli_terminal.py` (start with `pytest.importorskip('pty')`; each uses `--endpoint server.endpoint --preset short`):

```python
def test_default_run_animates_clears_and_leaves_only_the_translation(server):
    server.delay = 0.3
    result = run_on_pty(['--endpoint',server.endpoint,'--preset','short','x'])
    screen = strip_ansi(result.terminal)
    assert result.returncode == 0 and result.stdout == b'translated\n'
    assert 'en → fr' in screen and '✔ 2 translations' in screen
    assert result.terminal.rstrip().endswith('\x1b[?25h')

def test_failure_clears_the_spinner_before_the_error_and_restores_the_cursor(server):
    server.responses.extend([(200,completion('partial'),{}),(401,{'error':'x'},{})]); server.delay = 0.2
    result = run_on_pty(['--endpoint',server.endpoint,'--preset','short','x'])
    assert result.returncode == 1 and result.stdout == b'' and 'convolute: pass 1, step 2: fr -> en' in result.terminal
    assert '✔ 2 translations' not in result.terminal
    assert result.terminal.rfind('\x1b[?25h') > result.terminal.rfind('\x1b[?25l')

def test_ctrl_c_mid_hop_exits_130_with_the_cursor_restored(server):
    server.delay = 5
    result = run_on_pty(['--endpoint',server.endpoint,'--preset','short','x'],interrupt_when='en → fr')
    assert result.returncode == 130 and result.stdout == b'' and 'interrupted' in result.terminal
    assert result.terminal.rfind('\x1b[?25h') > result.terminal.rfind('\x1b[?25l')

def test_quiet_no_color_and_dumb_terminals(server):
    server.delay = 0.2
    base = ['--endpoint',server.endpoint,'--preset','short']
    quiet = run_on_pty([*base,'--quiet','x'])
    assert quiet.terminal == '' and quiet.stdout == b'translated\n'
    plain = run_on_pty(base+['x'],env={'NO_COLOR':'1'})
    assert '\x1b[?25l' in plain.terminal and not re.search(r'\x1b\[[0-9;]*m',plain.terminal)
    assert '\x1b' not in run_on_pty(base+['x'],env={'TERM':'dumb'}).terminal
```
  (Write the first test's assertions plainly: returncode 0, stdout exact, `'en → fr'` and `'✔ 2 translations'` in the stripped screen, and the terminal ends with the show-cursor sequence.)
- [ ] **Step 3: Run them.** Expected: FAIL (`SpinnerDisplay` missing; `server.delay` unsupported).
- [ ] **Step 4: Implement.** Add `delay` to the fixture (`time.sleep` before responding) and `run_on_pty` to `tests/conftest.py`; add `progress` and `SpinnerDisplay` and the interactive branch of `make_display`. Setting the pty window size to `(24, columns)` is part of `run_on_pty`.
- [ ] **Step 5: Run the full suite.** Expected: all PASS.
- [ ] **Step 6: Commit.** `git add src/convolute/display.py tests/conftest.py tests/test_display.py tests/test_cli_terminal.py && git commit -m "feat: show a spinner while translating on interactive terminals"`

### Task 7: Verbose log and chain log

**Files:**
- Modify: `src/convolute/display.py`
- Test: `tests/test_display.py`

**Interfaces:**
- Consumes: `LiveRegion` (including `columns()` for `is_revealable`), `Painter`, `header_rows`, `progress` (Task 6), `FakeClock`/`make` test helpers.
- Produces:
  - `step_tag(settings, pass_number, step_number) -> str`: `[3/5]`, or `[p2 3/5]` when `repeat > 1`.
  - `reveal_count(length: int, elapsed: float) -> int`: characters shown after `elapsed` seconds, completing in `min(1.0, length / 60)` seconds.
  - `is_revealable(text: str, width: int) -> bool`: single line and `visible_width(text) + 2 <= width - 1`.
  - `LogDisplay(region, painter, clock, *, steps: bool)`. `begin` prints the header (`header_rows` with `arrow='→'`, `sep=' · '`, tree glyphs `├`/`└`, dim labels) and a blank line through `region.print_above`, then starts the region. The pending line is `{step_tag} {src} → {tgt}  {spinner} {elapsed:.1f}s`. `hop_finished` commits `{step_tag} {src} → {tgt}  ✔ {duration:.1f}s  {prev} → {new} chars` via `print_above`. With `steps`, the text follows with a bar `┃ ` in the target language's color on every line. A revealable text is typed in the live block (above the pending line) and committed in full at the next `hop_finished`, at `end`, or at `close`; any other text is committed immediately and whole. `end` on success calls `region.finish([...])` with `✔ done in {elapsed:.1f}s · {hops} hops`; on failure `region.finish()`.
  - `make_display` returns `LogDisplay(..., steps=steps)` for an interactive stream with `verbose`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_reveal_helpers():
    assert reveal_count(300,0.5) == 150 and reveal_count(30,0.25) == 15 and reveal_count(30,9) == 30
    assert is_revealable('Hello there.',80) and not is_revealable('a\nb',80)
    assert not is_revealable('x'*200,80) and not is_revealable('会'*30,40)

def test_verbose_log_commits_each_hop_with_time_and_character_counts():
    out,clock,region,display = make(LogDisplay,LONG,steps=False)
    display.begin(LONG,37); display.hop_started(1,1,'en','fr'); clock.now = 2.1
    display.hop_finished(Step(1,1,'en','fr','La réunion a été déplacée à vendredi.',2.1))
    screen = strip_ansi(out.getvalue())
    assert '├ model' in screen and '└ mode' in screen and '[1/5] en → fr  ✔ 2.1s  37 → 37 chars' in screen
    assert 'La réunion' not in screen
    display.end(RESULT_LONG); assert 'done in' in strip_ansi(out.getvalue())

def test_chain_log_reveals_short_text_gradually_then_commits_it():
    out,clock,region,display = make(LogDisplay,LONG,steps=True)
    display.begin(LONG,37); display.hop_started(1,2,'fr','de')
    text = 'Das Treffen wurde auf Freitag verschoben.'
    display.hop_finished(Step(1,2,'fr','de',text,1.0)); clock.now = 0.3; region.tick()
    partial = strip_ansi(out.getvalue())
    assert '┃ Das T' in partial and text not in partial
    clock.now = 3; region.tick(); display.end(RESULT_LONG)
    assert text in strip_ansi(out.getvalue())

def test_chain_log_prints_long_multiparagraph_text_whole_and_immediately():
    text = 'Erster Absatz.\n\n' + 'Zweiter Absatz. ' * 300
    out,clock,region,display = make(LogDisplay,LONG,steps=True)
    display.begin(LONG,37); display.hop_started(1,1,'en','fr')
    display.hop_finished(Step(1,1,'en','fr',text,1.0))
    screen = strip_ansi(out.getvalue())
    assert all(line in screen for line in text.split('\n')) and screen.count('┃ ') >= 3
```

- [ ] **Step 2: Run them.** Expected: FAIL (`LogDisplay`, `reveal_count` missing).
- [ ] **Step 3: Implement** to the interfaces above. Keep state changes under `region.lock`.
- [ ] **Step 4: Run the full suite.** Expected: all PASS.
- [ ] **Step 5: Commit.** `git add src/convolute/display.py tests/test_display.py && git commit -m "feat: add colored verbose log and chain log displays"`

### Task 8: Live rail

**Files:**
- Modify: `src/convolute/display.py`
- Test: `tests/test_display.py`, `tests/test_cli_terminal.py`

**Interfaces:**
- Consumes: `LiveRegion` (`columns()` supplies `width` for `rail_text` and `is_revealable`), `Painter`, `FRAMES`, `progress`, `reveal_count`, `is_revealable`.
- Produces:
  - `rail_text(chain: Sequence[str], current: int, painter: Painter, *, phase: int, done: bool, width: int) -> str`. `current` is the index of the hop's source language in `chain`. Reached languages are bold in their color, the target shows `FRAMES[phase % 10]` after its label, upcoming ones are dim. Completed segments are solid `━` in the target's color; the active one cycles `━╌╌╌` frames every other phase; upcoming ones are dim `╌`. `done` fills every segment and drops the spinner. Segments are four columns wide, then shrink to two, one, and zero until `visible_width <= width - 1`; if the labels alone are still too wide, show a window of languages around `current` with `…` at the cut sides. The return value has no trailing spaces.
  - `preview(text: str) -> str`: whitespace runs, newlines included, collapsed to single spaces.
  - `RailDisplay(region, painter, clock)`: three live rows: the rail, `{spinner} {src} → {tgt}  {progress} · {elapsed:.1f}s`, and, once a hop has finished, `┃ {preview of the latest translation}` in the target's color, revealed gradually when `is_revealable`. `hop_started` resets to the hop's position, so the rail restarts each pass. `end` on success calls `region.finish([filled rail, '✔ done · {hops} hops · {elapsed:.1f}s'])`; on failure `region.finish()`.
  - `make_display` returns `RailDisplay` for an interactive stream with `steps` and not `verbose`.

- [ ] **Step 1: Write the failing tests.**

```python
EXTENDED = resolve_settings(Namespace(preset='extended'),{}).chain

@pytest.mark.parametrize('width',[80,60,40,20])
@pytest.mark.parametrize('current',range(9))
def test_rail_never_reaches_the_terminal_width(width,current):
    line = rail_text(EXTENDED,current,Painter(True),phase=3,done=False,width=width)
    assert visible_width(line) <= width - 1

def test_rail_marks_progress_and_fills_when_done():
    line = strip_ansi(rail_text(LONG.chain,2,Painter(True),phase=0,done=False,width=120))
    assert line.startswith('EN ━━━━ FR ━━━━ DE') and 'JA⠋' in line and '╌' in line
    assert '╌' not in rail_text(LONG.chain,4,Painter(False),phase=0,done=True,width=120)

def test_preview_collapses_paragraphs_to_one_row():
    assert preview('Eins.\n\nZwei.  Drei.') == 'Eins. Zwei. Drei.'

def test_rail_display_replaces_text_each_hop_and_resets_per_pass():
    repeated = resolve_settings(Namespace(preset='short',repeat=2),{})
    out,clock,region,display = make(RailDisplay,repeated)
    display.begin(repeated,5); display.hop_started(1,1,'en','fr'); display.hop_finished(Step(1,1,'en','fr','Bonjour',1.0))
    display.hop_started(1,2,'fr','en'); clock.now = 2; region.tick()
    assert '┃ Bonjour' in strip_ansi(out.getvalue())
    display.hop_started(2,1,'en','fr'); region.tick()
    assert 'pass 2/2 · hop 1/2' in strip_ansi(out.getvalue())

def test_rail_display_clips_long_double_width_text_and_leaves_a_receipt():
    out,clock,region,display = make(RailDisplay,LONG,width=40)
    display.begin(LONG,5); display.hop_started(1,1,'en','ja')
    display.hop_finished(Step(1,1,'en','ja','会議は金曜日に変更されました。'*10,1.0))
    display.hop_started(1,2,'ja','es'); clock.now = 5; region.tick()
    rows = strip_ansi(out.getvalue()).replace('\r','').split('\n')
    assert max(visible_width(row) for row in rows) <= 39
    clock.now = 10.4; display.end(RESULT_LONG)
    assert strip_ansi(out.getvalue()).endswith('✔ done · 5 hops · 10.4s\n')
```
  In `tests/test_cli_terminal.py` add a pty test that runs `--preset extended --show-steps` with `columns=60` and `server.delay = 0.2`, then asserts that every row of the stripped terminal text that contains `━` or `╌` has `visible_width <= 59`, and that the exit code is 0 with `stdout == b'translated\n'`.
- [ ] **Step 2: Run them.** Expected: FAIL (`rail_text` missing).
- [ ] **Step 3: Implement** to the interfaces above.
- [ ] **Step 4: Run the full suite.** Expected: all PASS.
- [ ] **Step 5: Commit.** `git add src/convolute/display.py tests/test_display.py tests/test_cli_terminal.py && git commit -m "feat: add live rail for interactive --show-steps"`

### Task 9: Clipboard module

**Files:**
- Create: `src/convolute/clipboard.py`
- Test: `tests/test_clipboard.py`

**Interfaces:**
- Produces:
  - `class ClipboardError(Exception)`: its message is safe to print.
  - `copy_text(text: str, *, platform: str = sys.platform, environ: Mapping[str, str] = os.environ, which=shutil.which, run=subprocess.run) -> None`. It sends exactly `text` (no added newline) to the first available tool and calls `run(cmd, input=data, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, env=env, check=False)`. `DEVNULL` matters: a forked `xclip` would hold inherited pipes open.
  - Tool choice: `darwin` → `pbcopy`, `data = text.encode()`, `env = {**environ, 'LC_CTYPE': 'UTF-8'}`. `win32` → `clip`, with `data = ('﻿' + text).encode('utf-16-le')`. Otherwise the first found of: `wl-copy` (only when `WAYLAND_DISPLAY` is set), `xclip -selection clipboard`, `xsel --clipboard --input`, `clip.exe` (WSL, same UTF-16 data); all but `darwin` use `env = dict(environ)` and `data = text.encode()`, except the two `clip` cases.
  - Errors: no tool found, a nonzero exit, `subprocess.TimeoutExpired`, or `OSError` raise `ClipboardError`.

- [ ] **Step 1: Write the failing tests** with `fake_run(calls, returncode=0)` (records `(cmd, kwargs)`, returns `CompletedProcess`) and `which=lambda name: '/usr/bin/' + name` (or a set-restricted variant):

```python
JAPANESE = '会議は金曜日に変更されました。'

def test_macos_sends_exact_utf8_bytes_with_a_utf8_locale():
    calls = []
    copy_text(JAPANESE,platform='darwin',environ={},which=everything,run=fake_run(calls))
    cmd,kwargs = calls[0]
    assert cmd == ['/usr/bin/pbcopy'] and kwargs['input'] == JAPANESE.encode()
    assert kwargs['env']['LC_CTYPE'] == 'UTF-8'
    assert kwargs['stdout'] is subprocess.DEVNULL and kwargs['stderr'] is subprocess.DEVNULL

def test_windows_sends_utf16_with_a_byte_order_mark():
    calls = []
    copy_text(JAPANESE,platform='win32',environ={},which=everything,run=fake_run(calls))
    assert calls[0][1]['input'] == ('﻿'+JAPANESE).encode('utf-16-le')

@pytest.mark.parametrize('environ,available,expected',[
    ({'WAYLAND_DISPLAY':'wayland-0'},{'wl-copy','xclip','xsel'},['/usr/bin/wl-copy']),
    ({},{'wl-copy','xclip','xsel'},['/usr/bin/xclip','-selection','clipboard']),
    ({},{'xsel'},['/usr/bin/xsel','--clipboard','--input']),
])
def test_linux_tool_preference(environ,available,expected):
    calls = []
    copy_text('x',platform='linux',environ=environ,which=lambda n: '/usr/bin/'+n if n in available else None,run=fake_run(calls))
    assert calls[0][0] == expected and calls[0][1]['input'] == b'x'

def test_failures_raise_clipboard_error():
    with pytest.raises(ClipboardError,match='no clipboard tool'):
        copy_text('x',platform='linux',environ={},which=lambda n: None,run=fake_run([]))
    with pytest.raises(ClipboardError):
        copy_text('x',platform='darwin',environ={},which=everything,run=fake_run([],returncode=3))
    for failure in (subprocess.TimeoutExpired('pbcopy',5),OSError('gone')):
        def run(*_,**__):
            raise failure
        with pytest.raises(ClipboardError):
            copy_text('x',platform='darwin',environ={},which=everything,run=run)
```

- [ ] **Step 2: Run them.** Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `clipboard.py` to the interface above.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit.** `git add src/convolute/clipboard.py tests/test_clipboard.py && git commit -m "feat: add system clipboard access"`

### Task 10: Clipboard wiring

**Files:**
- Modify: `src/convolute/cli.py`, `tests/conftest.py` (`fake_clipboard`)
- Test: `tests/test_cli.py`, `tests/test_cli_terminal.py`

**Interfaces:**
- Consumes: `copy_text`, `ClipboardError` (Task 9), `detect_capabilities`, `Painter`.
- Produces: after a successful run and after stdout is written, `--clipboard` copies `result.output`. A `ClipboardError` prints `convolute: warning: could not copy to the clipboard: {error}` to stderr and the exit code stays `0`, even with `--quiet`. When stderr is interactive and `--quiet` is absent, print a dim `✔ copied to clipboard` to stderr after a successful copy. A failed run copies nothing.

- [ ] **Step 1: Write the failing tests.** In `tests/conftest.py` add `fake_clipboard(tmp_path, exit_code=0) -> dict`: writes an executable `#!/bin/sh` script named `pbcopy` on macOS and `xclip` elsewhere, containing `/bin/cat > "$CLIP_OUT"` and `exit {exit_code}` (absolute `cat`, because `PATH` will not include the system directories), and returns only the extra variables `{'PATH': str(tmp_path), 'CLIP_OUT': str(tmp_path/'clip.out')}`. CLI tests pass `env={**os.environ, **clip}` to `invoke`; pty tests pass `env=clip` to `run_on_pty`. Skip these tests on `win32`.

```python
def test_clipboard_gets_the_final_translation_only(server,tmp_path):
    env = {**os.environ,**fake_clipboard(tmp_path)}
    server.responses.extend([(200,completion('intermediate'),{}),(200,completion('final 你好'),{})])
    result = invoke(['--endpoint',server.endpoint,'--preset','short','--clipboard','x'],env=env)
    assert result.returncode == 0 and result.stdout == 'final 你好\n'.encode() and result.stderr == b''
    assert (tmp_path/'clip.out').read_bytes() == 'final 你好'.encode()

def test_clipboard_with_json_copies_the_output_text(server,tmp_path):
    env = {**os.environ,**fake_clipboard(tmp_path)}
    result = invoke(['--endpoint',server.endpoint,'--preset','short','--json','--clipboard','x'],env=env)
    assert json.loads(result.stdout)['output'] == 'translated'
    assert (tmp_path/'clip.out').read_bytes() == b'translated'

def test_failed_run_copies_nothing(server,tmp_path):
    env = {**os.environ,**fake_clipboard(tmp_path)}
    server.responses.extend([(200,completion('partial'),{}),(401,{'error':'x'},{})])
    result = invoke(['--endpoint',server.endpoint,'--preset','short','--clipboard','x'],env=env)
    assert result.returncode == 1 and not (tmp_path/'clip.out').exists()

@pytest.mark.parametrize('broken',['missing','nonzero'])
def test_clipboard_failure_warns_but_keeps_the_result_and_exit_code(server,tmp_path,broken):
    extra = fake_clipboard(tmp_path,exit_code=3) if broken == 'nonzero' else {'PATH':str(tmp_path)}
    result = invoke(['--endpoint',server.endpoint,'--preset','short','--quiet','--clipboard','x'],env={**os.environ,**extra})
    assert result.returncode == 0 and result.stdout == b'translated\n'
    assert b'warning' in result.stderr and b'clipboard' in result.stderr
```
  In `tests/test_cli_terminal.py` add:

```python
def test_confirmation_appears_on_a_terminal_unless_quiet(server,tmp_path):
    clip = fake_clipboard(tmp_path)
    base = ['--endpoint',server.endpoint,'--preset','short','--clipboard']
    shown = run_on_pty([*base,'x'],env=clip)
    assert '✔ copied to clipboard' in strip_ansi(shown.terminal)
    assert (tmp_path/'clip.out').read_bytes() == b'translated'
    (tmp_path/'clip.out').unlink()
    quiet = run_on_pty([*base,'--quiet','x'],env=clip)
    assert quiet.terminal == '' and (tmp_path/'clip.out').read_bytes() == b'translated'
```
- [ ] **Step 2: Run them.** Expected: FAIL (nothing is copied).
- [ ] **Step 3: Implement** the copy step in `_execute`, after output is written and the error branch has returned.
- [ ] **Step 4: Run the full suite.** Expected: all PASS.
- [ ] **Step 5: Commit.** `git add src/convolute/cli.py tests/conftest.py tests/test_cli.py tests/test_cli_terminal.py && git commit -m "feat: copy the final translation with --clipboard"`

### Task 11: Documentation and final verification

**Files:**
- Modify: `README.md`, `src/convolute/cli.py` (epilog)

- [ ] **Step 1: README.** Add examples for `--verbose`, `--show-steps --verbose`, `--clipboard`, and `--quiet`. Add a "Terminal display" section with the flag table from the spec (interactive versus non-interactive), the definition of interactive, `NO_COLOR` and `TERM=dumb`, and the clipboard tools and fallback warning. Update the `--dry-run` sentence to include `--verbose` and `--clipboard`, and note that `--quiet` cannot be combined with `--verbose` or `--show-steps`. Leave the stdout, JSON, and exit-code sections unchanged.
- [ ] **Step 2: Epilog.** Add one sentence to the `build_parser` epilog: progress output appears only on an interactive stderr and `--quiet` removes it.
- [ ] **Step 3: Automated check.** Run `python -m pytest -q` and `python -m build`. Expected: all tests PASS and both distributions build.
- [ ] **Step 4: Manual check** in a real terminal (macOS Terminal or iTerm) with a live endpoint or a throwaway local stub: each of the four display flag combinations; `--preset extended --show-steps` in a narrow window; a long multi-paragraph file with `--show-steps --verbose`; Ctrl-C mid-hop (the cursor must reappear); a Japanese text run with `--clipboard` and pasted back. Record any problem rather than adjusting the tests to hide it.
- [ ] **Step 5: Commit.** `git add README.md src/convolute/cli.py && git commit -m "docs: document terminal display, --quiet and --clipboard"`
