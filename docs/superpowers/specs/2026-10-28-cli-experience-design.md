# Convolute CLI experience design

Date: 2026-10-28
Status: Design approved by the user on 2026-10-28, including a `--quiet` flag the user asked for. Implementation plan: `docs/superpowers/plans/2026-10-28-cli-experience.md`.

## Intent and why

The CLI works but feels inert. A run can take minutes on a local 7B model, and during that time nothing on screen moves. `--show-steps` prints plain blocks after each hop. Copying the result means selecting it by hand. The user wants a more pleasant terminal experience: motion while the tool is working, color when asked for detail, an animated and colorful `--show-steps`, and a flag that puts the final result on the clipboard.

This is a presentation layer. Translation behavior, the stdout contract, the JSON schema, exit codes, and configuration are unchanged.

## Goals, non-goals, anti-goals

Goals:
- A spinner during every run on an interactive terminal, with no flag needed.
- A new `--verbose` flag that prints a colored log of settings and per-hop results.
- An animated, colored `--show-steps`, in two styles chosen by whether `--verbose` is also passed.
- A new `--clipboard` flag that copies the final translation to the system clipboard.
- A new `--quiet` flag that switches off the spinner and all other stderr decoration.
- Plain, script-safe output whenever stderr is not an interactive terminal.

Non-goals:
- Streaming tokens from the model. The client stays non-streaming, so any typing effect is a cosmetic reveal after a hop finishes.
- New runtime dependencies. Use hand-written ANSI escape sequences and the system's own clipboard tools.
- Changes to the `--json` schema, `--dry-run` output, exit codes, or settings precedence.
- Retry visibility. The client retries internally and does not report attempts, so no retry counts are shown.
- A configuration file, run history, diffing of input against output, or a full-screen interface.
- Bumping the version or publishing a release.

Anti-goals (a failure even if the features work):
- Anything that can corrupt stdout or a pipe, or that makes `convolute ... | other` behave differently from today.
- Leaving the terminal in a bad state after Ctrl-C, an error, or a closed pipe: a hidden cursor, a half-drawn line, or stray escape codes.
- Animation that delays results. The final text must not wait on a visual effect for more than a fraction of a second.

## Behavior

All decoration goes to stderr. "Interactive" means stderr is a TTY, `TERM` is not `dumb`, and (on Windows) the terminal is known to understand ANSI sequences. Stdout being piped does not matter: `convolute "x" | pbcopy` still shows the spinner.

| Flags | Interactive stderr | Non-interactive stderr |
| --- | --- | --- |
| none | Spinner line, replaced at the end by a dim one-line summary | Nothing, as today |
| `--verbose` | Colored log: settings header, one line per hop, summary | The same log as plain text, no color or animation |
| `--show-steps` | Live rail | Today's plain blocks, byte-compatible: `pass P, step S: src -> tgt`, then the text |
| `--show-steps --verbose` | Chain log | Plain log in the `--verbose` format, with each hop's text under its line and the `pass P, step S` label kept |
| `--quiet` | Nothing | Nothing |

`NO_COLOR` removes color but keeps animation. `TERM=dumb` and non-interactive stderr remove both. `--quiet` removes all decoration whatever the terminal.

### Spinner (no flags)

One line that is redrawn in place while a hop runs, for example `⠹ fr → de  hop 2/5 · 1.2s`. Language codes are colored. When `--repeat` is above 1, the line also carries `pass N/M`. On success the line is replaced by a dim `✔ 5 translations · 10.4s`; then the final text goes to stdout. On failure the line is cleared before the existing error message is printed.

### `--verbose`

A header, then one line per hop as it completes, then a summary:

```text
convolute 0.1.0
├ model     qwen2.5:7b
├ endpoint  http://127.0.0.1:11434/v1
├ chain     en → fr → de → ja → es → en
└ mode      faithful · 5 hops · 37 chars in

[1/5] en → fr  ✔ 2.1s  37 → 37 chars
[2/5] fr → de  ✔ 1.8s  37 → 41 chars
...
✔ done in 10.4s · 5 hops
```

The pending hop shows a spinner on its line. The header never shows an API key or any credential. Colors: dim for labels, a distinct color per language, green for success, yellow for times.

### `--show-steps`: live rail (default style)

A progress line redrawn in place, with the latest completed translation under it. Each new translation replaces the previous one on screen, so only the final answer remains afterwards:

```text
EN ━━━━ FR ━━━━ DE ╌╌╌╌ JA ╌╌╌╌ ES ╌╌╌╌ EN
⠹ de → ja  hop 3/5 · 1.2s
┃ Das Treffen wurde auf Freitag verschoben.
```

Reached languages are bold and colored, the active segment animates, and upcoming ones are dim. When the run finishes the rail is all filled and the status line becomes `✔ done · 5 hops · 10.4s`.

### `--show-steps --verbose`: chain log

Every hop stays in the scrollback, as a language-chip line followed by its text behind a colored bar, with the spinner on the hop in progress. The verbose header comes first and the summary last:

```text
✔ EN → FR  2.1s
  ┃ La réunion a été déplacée à vendredi.
✔ FR → DE  1.8s
  ┃ Das Treffen wurde auf Freitag verschoben.
⠹ DE → JA  1.2s
```

### `--clipboard`

After a successful run, copy the final translation to the system clipboard. Stdout still prints the result as before. On an interactive terminal a short `✔ copied to clipboard` line goes to stderr. If the run fails, nothing is copied.

- With `--json`, the copied text is the `output` field, not the JSON.
- The copy uses the system's own tool, not a new dependency: `pbcopy` on macOS; `wl-copy`, `xclip`, or `xsel` on Linux; the Windows and WSL equivalent.
- If no tool is found or the copy fails, print a warning to stderr. The translation still prints and the exit code stays 0, because the run itself succeeded.
- Non-English text must reach the clipboard intact, which is not automatic on every platform (see Verification).

### `--quiet`

Turns off the spinner and all other stderr decoration on any terminal: no spinner, no one-line success summary, and no `✔ copied to clipboard` confirmation. Stdout is unchanged. Errors and warnings are not decoration and still print: a failed translation's message, the clipboard-failure warning, and usage errors. With `--clipboard` the copy still happens, silently.

`--quiet` cannot be combined with `--verbose` or `--show-steps`, because they ask for exactly the output `--quiet` removes. That is a usage error with exit code 2 before any request is made. It is allowed with `--json`, `--clipboard`, and `--dry-run`, where it changes nothing visible.

## Constraints

- One owner for stderr. While any animation is active, nothing else writes to stderr. The error message and the final text are written only after the animation has stopped and its last line is cleared.
- Always restore the terminal: show the cursor and clear any partial line on success, failure, `KeyboardInterrupt`, and a closed pipe. The existing exit codes (0, 1, 2, 130) and the clean broken-pipe handling are preserved. An animation thread that hits `BrokenPipeError` stops quietly and prints no traceback.
- Long text must not break redrawing. Terminal rows that wrap break in-place redraws, so the live rail shows the latest translation truncated to one terminal row with an ellipsis, and the chain log is append-only. The full text is still available in the chain log, in `--json`, and in the plain output.
- Reveal (typing) effects have a time cap of about one second per hop, whatever the text length, so large documents never wait on animation.
- Colors must work on a basic 16-color terminal, be readable on both light and dark backgrounds, and cover all 19 supported language codes.
- The existing tests must keep passing as they are. They rely on non-interactive stderr being empty by default and on the `pass 2, step 5: id -> en` text from `--show-steps`.

## Decisions made on the user's behalf

These are my calls. The user did not discuss them, so please check them while reading.

1. `--verbose` and `--clipboard` are rejected together with `--dry-run`, as `--json` and `--show-steps` already are.
2. No short flags. `-v` would be confused with `--version`.
3. The one-line success summary stays after the spinner, as the approved mockup showed.
4. The copied text is the translation without the extra newline that stdout appends. Pasting then does not add a stray line break.
5. When `--repeat` is above 1, the spinner, the rail, and the log show `pass N/M`. The rail resets at the start of each pass.
6. On Windows, animate only when the terminal is known to support ANSI, otherwise fall back to plain output.
7. The approved mockups showed `0 retries` in a summary. Retry counts are not observable, so the summary omits them.
8. A language-to-color table lives in a new small module, with a neutral fallback color.
9. `--quiet` removes only decoration. Errors and warnings keep printing, so a quiet run never fails silently.
10. `--quiet` together with `--verbose` or `--show-steps` is a usage error, rather than one silently winning.
11. `--quiet` has no environment variable and no short flag, matching decision 2.

## Left to the builder

- Module layout, for example one module for terminal rendering and one for clipboard access.
- How `run()` tells the CLI that a hop has started. Today it reports only completed steps; the spinner needs a hop-start signal as well. Keep the result and JSON schema unchanged.
- The render thread design, frame rate, and exact glyphs, within the constraints above.
- The mechanism for each platform's clipboard tool, and how tests substitute a fake one.
- Wording of warnings and `--help` text, and the README update.

## Verification

1. Existing tests pass unchanged.
2. Unit tests for the renderer with a fake stream and clock: frames, in-place clearing, truncation, the reveal cap, plain fallbacks, and `NO_COLOR`.
3. Pseudo-terminal tests (Unix, skipped on Windows) run the real CLI against the local fixture server. They assert that a spinner appears and is cleared, that the cursor is restored after success, failure, and interrupt, and that stdout contains only the translation. They also check that `--quiet` leaves stderr empty on success on a terminal, still prints errors and the clipboard warning, and is rejected with `--verbose` or `--show-steps`.
4. Clipboard tests use a fake tool on `PATH` and never touch the real clipboard. They cover success, no tool, a tool that exits non-zero, a failed run copying nothing, `--json`, and non-ASCII text arriving byte-intact.
5. Manual check in a real terminal: all four flag combinations, a narrow window, a long multi-paragraph document, Ctrl-C mid-hop, and a Japanese text copied and pasted back. On macOS `pbcopy` depends on the locale to decode UTF-8, and Windows `clip` expects UTF-16, so Unicode round-tripping is a real risk.
6. README, `--help`, and the epilog describe the new flags and the interactive and non-interactive behavior.
