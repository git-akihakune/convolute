# convolute

Paraphrase text by translating it through a chain of languages with an LLM.
Each translation consumes the previous result. The default is **five translations**
with instructions to preserve meaning:

```text
English → French → German → Japanese → Spanish → English
```

This is a proof of concept. Translation chains can change meaning, and faithful
mode is an instruction to the model, not a guarantee. Creative mode asks for more
variation while still asking to retain facts, names, numbers, and negation.

## Install and run

Requires Python 3.11+ and an OpenAI-compatible chat-completion endpoint.
From this repository:

```sh
pipx install .
```

Install remotely from PyPI without cloning:

```sh
pipx install convolute
pipx upgrade convolute
pipx uninstall convolute
```

For the default local setup, install [Ollama](https://ollama.com/), start its server
if it is not already running, and download the baseline model:

```sh
ollama serve                      # run in another terminal if needed
ollama pull qwen2.5:7b
convolute "The meeting has been moved to Friday."
```

The quantized model download is roughly 4.7 GB; inference needs additional memory.
You can use a different multilingual model with `--model`. Convolute does not
download models, start servers, or send input to a fallback provider.

Inspect the configuration without contacting any endpoint:

```sh
convolute --dry-run "The meeting has been moved to Friday."
```

## Examples

```sh
convolute --mode creative "The meeting has been moved to Friday."
convolute --preset short "A quick round trip."
convolute --preset extended --mode creative "A longer transformation."
convolute --chain EN,CN,KR,JP,ID,EN --endpoint 127.0.0.1:11434 --model example-model --repeat 1 "text"
convolute --preset long --repeat 2 "Ten translations in total."
convolute --chain en,fr,en --temperature 0.7 "Use a sampling override."
cat corpus.txt | convolute > paraphrased.txt
convolute --file corpus.txt --show-steps
convolute --verbose "Log settings and per-hop timings."
convolute --show-steps --verbose --file corpus.txt
convolute --clipboard "Copy the final translation."
convolute --quiet "No spinner or other decoration."
convolute --file corpus.txt --json > run.json
convolute --dry-run --preset extended --repeat 2 "Inspect eighteen calls."
convolute -- "-text beginning with a dash"
python -m convolute --help
```

## Chains and modes

| Preset | Languages | Translations per pass |
| --- | --- | ---: |
| `short` | `en,fr,en` | 2 |
| **`long` (default)** | `en,fr,de,ja,es,en` | **5** |
| `extended` | `en,fr,de,es,pt,it,zh,ja,ko,en` | 9 |

Presets are fixed, with no random language selection. `--chain` replaces the
default preset; explicit `--preset` and `--chain` cannot be combined. Custom chains
must contain at least two translations, have different adjacent languages, and
end in the same language they start in. Non-English source text needs an explicit
chain starting in its language; language detection is not automatic.

Codes are case-insensitive. Supported codes: `en fr de es pt it zh ko ja id ru ar
hi vi th tr nl pl uk`. Aliases `CN`, `KR`, and `JP` normalize to `zh`, `ko`, and
`ja`. The model must support every language in the selected chain.

`--mode faithful` prioritizes meaning and tone; `--mode creative` requests freer
sentence structure and expression. Mode does not change the chain, repeat count,
or temperature. `--repeat N` counts complete passes including the first, with
each pass consuming the previous pass's final text. For example,
`--chain en,fr,en --repeat 2` makes four calls, not two independent paraphrases.

## Endpoints and settings

The default base URL is `http://127.0.0.1:11434/v1`. Convolute appends
`/chat/completions`. Supply a base URL, not a full operation URL:

```sh
convolute --endpoint https://llm.example.org/v1 --model my-model "text"
```

A bare loopback address with a port, such as `127.0.0.1:11434`, `localhost:11434`,
or `[::1]:11434`, gains `http://`. Other hosts require `http://` or `https://`.
Origin-only URLs gain `/v1`; explicit base paths are preserved. URLs containing
credentials, query strings, or fragments are rejected. TLS verification remains
enabled and redirects are not followed. Standard HTTP proxy/CA environment
configuration is honored; ensure loopback hosts are covered by `NO_PROXY` if
your environment uses a proxy.

### TranslateGemma

Convolute automatically selects [TranslateGemma's documented prompt format](https://ollama.com/library/translategemma)
for models named `translategemma` (including tags such as `:latest` and `:4b`)
or `translategemma-*`, with optional namespace prefixes such as `google/`.
Each hop sends one user message containing the source/target language names and
codes, translation instructions, two blank lines, and the unmodified input text.
The chain's `zh` code is sent as `zh-Hans` (Simplified Chinese).

Faithful mode uses the documented prompt verbatim. Creative mode adds rephrasing
and fact-preservation instructions before the text separator; this extension's
effect is model-dependent.

```sh
ollama pull translategemma:4b
convolute --model translategemma:4b "What's the matter? You don't look so good?"
```

### Settings

| Setting | CLI flag | Environment variable | Default |
| --- | --- | --- | --- |
| Endpoint | `--endpoint` | `CONVOLUTE_ENDPOINT` | `http://127.0.0.1:11434/v1` |
| Model | `--model` | `CONVOLUTE_MODEL` | `qwen2.5:7b` |
| Mode | `--mode` | `CONVOLUTE_MODE` | `faithful` |
| Authentication | — | `CONVOLUTE_API_KEY` | No Authorization header |
| Passes | `--repeat` | — | `1` |
| HTTP timeout | `--timeout` | — | `120` seconds |
| Retries per translation | `--retries` | — | `0` |
| Sampling temperature | `--temperature` | — | Omitted; endpoint default |

CLI flags override tool-specific environment variables, which override defaults.
Set `CONVOLUTE_API_KEY` in your shell environment or secret manager for endpoints
that require Bearer authentication. Keys are not accepted as command arguments.

Timeout controls HTTP connect/read/write/pool waits, not an overall deadline for
the entire chain. Explicit retries apply only to connection failures and HTTP
`429`, `502`, `503`, and `504`. Read/write timeouts, malformed completions, and
other HTTP statuses are not retried. Backoff is 1, 2, 4, 8, then at most 10 seconds.
A valid `Retry-After` above 10 seconds fails rather than sleeping indefinitely.
Retries can duplicate server work or charges; the default disables them.

## Input, output, and failures

Provide one quoted text argument, `--file PATH`, or UTF-8 stdin. `--file -` explicitly
reads stdin. Files and stdin must be valid UTF-8; empty input is rejected.

Plain stdout contains only the final translation, ending in a newline. Diagnostic
messages and `--show-steps` output go to stderr, keeping shell redirection useful.
No final text is written on failure. The chain stops at the failing hop.

`--json` writes one JSON object with:

- `schema_version: 1`, `status`, original `input`, final `output`, and `error`.
- Canonical `chain`, selected `preset` (null for a custom chain), `mode`, `repeat`,
  `model`, `endpoint`, and public `request_settings`.
- Ordered `steps`, each with `pass_number`, `step_number`, `source`, `target`,
  translated `text`, and `duration_seconds`. Step numbers start at one within each pass.

On translation failure, `status` is `error`, `output` is null, and completed steps
remain available. The error contains a safe `code`/`message` and the failing
pass, step, source, and target. Invalid configuration/input can fail before a run
record exists and uses stderr instead. Missing, empty, refused, tool-call, and
truncated completions fail rather than becoming inputs to later hops.

`--dry-run` emits a JSON execution plan with the canonical chain, mode, effective
settings, `total_calls`, and `input_characters`. It includes neither input text nor
credentials, and makes no network calls. It cannot be combined with `--json`,
`--show-steps`, `--verbose`, or `--clipboard`.

Exit codes: `0` success, `1` translation/transport/protocol or output-pipe failure,
`2` invalid configuration/input, `130` interruption.

## Terminal display

Everything decorative goes to stderr; stdout and `--json` are unchanged. A terminal is
"interactive" when stderr is a TTY, `TERM` is not `dumb`, stderr uses UTF-8, and, on
Windows, `WT_SESSION` is set (Windows Terminal). Anything else gets plain ASCII text
with no color or animation.

| Flags | Interactive stderr | Otherwise |
| --- | --- | --- |
| none | A spinner line, replaced by a one-line summary | Nothing |
| `--verbose` | Colored log: settings, one line per hop, summary | The same log as plain text |
| `--show-steps` | Live rail: a progress line redrawn in place, with the latest translation under it | The `pass P, step S: src -> tgt` blocks, unchanged |
| `--show-steps --verbose` | Chain log: every hop and its text stays in the scrollback | Plain log with each hop's text |
| `--quiet` | Nothing | Nothing |

`NO_COLOR` removes color but keeps the animation. `--quiet` removes the spinner, the
summary, and the clipboard confirmation; errors and warnings still print. It cannot be
combined with `--verbose` or `--show-steps`. Translations arrive whole, so the typing
effect after each hop is cosmetic: single-line text is typed out in at most a second,
and longer or multi-line text appears at once.

### Clipboard

`--clipboard` copies the final translation to the system clipboard after a successful
run, without the trailing newline that stdout adds. It uses the system's own tool:
`pbcopy` on macOS; `wl-copy` (when `WAYLAND_DISPLAY` is set), `xclip`, `xsel`, or WSL's
`clip.exe` on Linux; and `System32\clip.exe` on Windows. Stdout still prints the
result, and with `--json` the copied text is the `output` field. On an interactive
terminal a `✔ copied to clipboard` line follows. If no tool is available or the copy
fails, a warning goes to stderr and the exit code stays `0`, since the run succeeded.
A failed run copies nothing. `--clipboard` cannot be combined with `--dry-run`.

## Scope and data handling

Each hop sends the **whole document** to the configured endpoint. There is no
automatic chunking or silent truncation. Input plus generated translation must
fit the model/server context; long corpora may require a larger context or manual
preparation. Server-side silent input truncation cannot be reliably detected.

Intermediate text is held in memory. `--json` includes the original and every
translation; `--show-steps` displays intermediate text. Convolute creates no run
files by default; redirected output and provider-side logging remain under your
control. API keys and raw response bodies are excluded from error diagnostics.

This POC supports OpenAI-compatible text chat completions. Native provider APIs,
batch JSONL, concurrent documents, caching, resumable runs, and automatic semantic
scoring are outside its current scope. A custom endpoint must support this wire
format and provide a usable non-streaming completion with `finish_reason: stop`.

## Development and validation

```sh
python3 -m venv work/venv
. work/venv/bin/activate
python -m pip install -e '.[test]'
python -m pytest -q
python -m build
```

Tests exercise configuration, actual HTTP requests to a local fixture server,
request ordering, repeats, CLI subprocesses, retries, failure records, terminal
rendering on a pseudo-terminal (skipped on Windows), and a fake clipboard tool without
requiring an LLM or paid API. Test runs need permission to bind a loopback socket.

Protocol tests do not establish paraphrase quality. Before adopting a default for
your corpus, compare all three presets and both modes on a fixed set of sentences
containing names, numbers, negation, idioms, and multiple paragraphs. Record the
model/settings, latency, wording variation, and factual changes. The initial
language ordering is a heuristic, not a proven optimum.

Background: [pivot-based paraphrasing and semantic shift](https://aclanthology.org/2021.emnlp-main.350/),
[Ollama API compatibility](https://docs.ollama.com/api/openai-compatibility),
[model baseline](https://ollama.com/library/qwen2.5:7b), and
[standard language codes](https://www.loc.gov/standards/iso639-2/php/code_list.php).

Licensed under GPL-3.0-only; see [LICENSE](LICENSE).

## Publishing releases

The `publish.yml` GitHub Actions workflow tests, builds, validates, and publishes
the package when a GitHub release is published. Uploading uses PyPI Trusted
Publishing, with no API token stored in the repository.

One-time setup:

1. Create a PyPI account, verify its email address, and enable two-factor
   authentication.
2. Create the `pypi` environment in this repository's GitHub settings.
3. At <https://pypi.org/manage/account/publishing/>, register a pending publisher:

   | Field | Value |
   | --- | --- |
   | PyPI project name | `convolute` |
   | Owner | `git-akihakune` |
   | Repository | `convolute` |
   | Workflow filename | `publish.yml` |
   | Environment | `pypi` |

For each release, update both `pyproject.toml` and `src/convolute/__init__.py`
to the same version, commit and push the changes, then publish a GitHub release
with a matching tag such as `v0.1.0`. The workflow rejects mismatched versions
before building. The first successful upload creates the PyPI project; a pending
publisher does not reserve its name. Subsequent releases need a new version.
