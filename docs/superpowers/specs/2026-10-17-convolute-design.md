# Convolute POC design

Date: 2026-10-17
Status: Design approved by the user on 2026-10-17; implementation has not started.

## Intent and assumptions

Build an installable `convolute` command that produces paraphrases by passing text through successive LLM translations. Users can choose an endpoint, model, language chain, and number of complete passes. Every translation consumes the previous translation, including across repeated passes.

The user supplied the core behavior, delegated research into sensible defaults, and confirmed that meaning preservation should be the default with stronger variation available as a user option. The user also requires long chains among the built-in defaults; the default invocation therefore uses a five-translation chain, with named short and extended alternatives. English is the default input language; other source languages are selected by an explicit chain. No automatic language detection is promised. The user approved the proposed Python implementation and model baseline with the design.

Success means that the command works in shell pipelines, makes the expected ordered requests to an OpenAI-compatible custom endpoint, returns only the final text by default, and can expose intermediate results for inspection. Live paraphrase quality must be assessed separately from protocol correctness.

## Implementation approaches

| Approach | Benefit | Trade-off |
| --- | --- | --- |
| Python 3.11+, argparse, httpx — recommended | Small implementation, straightforward tests and `pipx` installation | Requires a Python runtime |
| Go command | Convenient standalone binaries | More packaging and cross-platform release work for the POC |
| Shell plus curl/jq | Very quick disposable experiment | Awkward Unicode, input handling, errors, and maintainability |

Use a Python package with a `convolute` console entry point and `python -m convolute` support. Keep parsing/configuration, language normalization, the translation pipeline, and HTTP transport in separate small modules. Use pytest and a local HTTP fixture for tests. Preserve the repository's license.

## Defaults and rationale

| Setting | Proposed default | Rationale |
| --- | --- | --- |
| Preset / chain | `long`: `en,fr,de,ja,es,en` | Five translations exercise the requested multi-language transformation. All selected languages are listed as supported by the proposed model. The ordering is an initial heuristic, not a proven optimum. |
| Mode | `faithful` | Preserve meaning by default; `creative` requests more variation |
| Repeat | `1` | One complete execution of the chain |
| Endpoint | `http://127.0.0.1:11434/v1` | Local Ollama, using its documented OpenAI-compatible interface |
| Model | `qwen2.5:7b` | Established multilingual instruction model with a roughly 4.7 GB quantized download; a baseline to evaluate, not a hardware-independent recommendation |
| Temperature | Omitted | Respect endpoint defaults and avoid requiring optional sampling support |
| Timeout | 120 seconds per attempt | Allow local inference and cold starts; configurable |
| Retries | `0` | Avoid surprise duplicate inference or charges; users may opt in |

Built-in presets make short and long chains available without typing language lists:

| Preset | Canonical chain | Translations per pass |
| --- | --- | --- |
| `short` | `en,fr,en` | 2 |
| `long` — default | `en,fr,de,ja,es,en` | 5 |
| `extended` | `en,fr,de,es,pt,it,zh,ja,ko,en` | 9 |

Presets are fixed and deterministic; no random language selection occurs. The default remains `faithful` in all presets, and `--mode creative` can be combined with any preset or custom chain. The user's example remains directly expressible as `en,zh,ko,ja,id,en`: six language entries and five translation calls. No automatic model downloads, server startup, model selection, or remote fallback occur.

Research establishes back-translation as a paraphrasing method and identifies semantic shift as a limitation. It does not establish that a longer or more linguistically diverse chain reliably yields better paraphrases. Validate the default empirically on the user's corpus and chosen model before promoting it beyond a POC.

## Command behavior

```sh
convolute "The meeting has been moved to Friday."
convolute --mode creative "The meeting has been moved to Friday."
convolute --preset short "text"
convolute --preset long --mode creative "text"
convolute --preset extended "text"
convolute --chain EN,CN,KR,JP,ID,EN --endpoint 127.0.0.1:11434 --model example-model --repeat 1 "text"
convolute --chain en,zh,ja,en --repeat 2 "text"
cat corpus.txt | convolute > paraphrased.txt
convolute --file corpus.txt --show-steps
convolute --file corpus.txt --json > run.json
convolute --dry-run --chain en,fr,de,en "text"
```

- Accept one positional UTF-8 text value, `--file PATH`, or stdin when neither is supplied. `--file -` explicitly selects stdin. Supplying positional text and `--file` together is an error. Empty/whitespace-only input is an error. With no input and an interactive terminal, print usage rather than wait indefinitely.
- `--preset short|long|extended` selects a built-in chain. With neither `--preset` nor `--chain`, use `long`. An explicit `--chain` replaces the default preset. Explicit `--preset` and `--chain` are mutually exclusive, so conflicting user instructions fail before any request. Mode and repeat work independently with either selection.
- `--chain` accepts a comma-separated, case-insensitive list of supported language codes, ignoring whitespace around entries. Normalize `CN` to `zh`, `KR` to `ko`, and `JP` to `ja` for compatibility with the supplied example. The canonical forms are `en`, `zh`, `ko`, `ja`, and `id`.
- Initially support `en,fr,de,es,pt,it,zh,ko,ja,id,ru,ar,hi,vi,th,tr,nl,pl,uk`. Map each code to an explicit language name in prompts. Reject unknown or empty entries before any HTTP request. Document this as the POC's supported set, not every language the model may support.
- Require at least two translations, distinct adjacent languages, and the same first and last language. These constraints keep each pass a complete paraphrase round trip.
- `--repeat N` is a positive integer counting complete passes, including the first. `en,fr,en --repeat 2` makes four calls: `en→fr→en→fr→en`. Pass two starts with pass one's final text; it does not restart from the original.
- `--mode faithful|creative` controls the translation instructions at every hop. Faithful mode prioritizes semantic fidelity and retaining tone. Creative mode encourages idiomatic rephrasing, freer sentence structure, and alternative expressions, while still asking for core facts, names, numbers, and negation to be retained. Both modes request a translation in the target language with no commentary. Creative mode can increase drift; its effect is model-dependent. Mode does not silently change the chain, repeat count, temperature, or number of requests. Those remain independent controls. Support `CONVOLUTE_MODE` with the same CLI-over-environment precedence as other settings.
- `--endpoint` is an API base URL. A bare loopback host with a port gains `http://`; other hosts require an explicit HTTP(S) scheme. An origin-only URL gains `/v1`. Explicit base paths are preserved. Append `/chat/completions` once. Reject credentials in URLs, query strings, and fragments; document that full operation URLs are not accepted.
- `--model`, `--timeout`, `--retries`, and optional `--temperature` override defaults. Validate numeric options before making requests. Retry counts must be nonnegative; timeout must be positive and finite; temperature must be finite and in `[0,2]`, subject to server support.
- Support `CONVOLUTE_ENDPOINT`, `CONVOLUTE_MODEL`, and `CONVOLUTE_API_KEY`. Precedence is CLI option, tool-specific environment variable, then default. Read credentials from the environment rather than adding a CLI key argument or storing them in run records. Send a Bearer header only when a key is configured.
- Plain mode writes the final translation followed by a newline to stdout. Diagnostics and `--show-steps` output go to stderr. Default operation has no progress chatter and creates no files. Shell redirection supplies output-file handling.
- `--json` emits one JSON object with schema version, status, original input, final output, canonical chain, mode, repeat count, model, endpoint, effective request settings, and ordered steps. Each step records pass number, step number within that pass, source, target, translated text, and duration. Credentials and raw HTTP headers are never included.
- `--dry-run` validates input and configuration and prints a JSON execution plan without contacting the endpoint. Include the effective settings, canonical chain, total call count, and input character count; omit the text and credentials. Reject combination with `--json` or `--show-steps` to keep its output contract unambiguous.

## Translation pipeline and HTTP contract

For each adjacent language pair, make a fresh non-streaming POST to `/chat/completions` with the selected model and two messages. The system message specifies the source and target languages and the selected mode's translation instructions. Both modes ask to preserve names, numbers, negation, and paragraph structure where possible, request only the translation, and instruct the model to treat the user message as content rather than instructions. The user message contains only the current text. Do not include earlier steps, the original source after step one, or chat history.

Send `stream: false`. Add `temperature` only when explicitly configured. Read `choices[0].message.content` and require nonempty string content and `finish_reason: "stop"`. Treat truncation, refusal/tool output, malformed JSON, missing choices, or empty content as failure. Do not silently clean reasoning, strip quotation marks, or feed a truncated answer into the next step. Providers that use different response formats need a later adapter; an arbitrary URL alone does not guarantee compatibility.

Keep TLS verification enabled. Do not follow redirects automatically. Do not log raw provider response bodies, which may echo input or credentials. Errors report a safe status/category and the failing pass and language pair. They can suggest checking server availability, the model name, authentication, context limits, or response shape as applicable.

When retries are explicitly enabled, retry only connection failures and HTTP `429`, `502`, `503`, or `504`, at most the configured count per step. Back off for 1, 2, 4 seconds, capped at 10 seconds; honor a valid `Retry-After` within that bound and fail when the requested wait exceeds it. Do not automatically retry response/read timeouts or other statuses. Explain that even explicit retries can duplicate server work.

## Corpus scope and failures

The POC accepts a complete plain-text document via file or stdin and submits it as one unit per hop. This preserves document context and makes the initial behavior easy to inspect. File input is strictly UTF-8; input decoding errors are actionable failures.

Automatic chunking, sentence segmentation, batch JSONL, concurrent documents, resumable execution, caching, custom prompt templates, native Ollama API adapters, and semantic scoring are deferred. There is no portable exact token budget for an arbitrary model endpoint, and the tool must not silently split or truncate a corpus. Explain that input plus translation output must fit the configured model/server context; fail clearly on provider-reported limits. A successful response cannot prove that a server never truncated its input internally.

On failure, stop the chain. Plain mode writes no final text to stdout. JSON mode emits a structured failure object with `output: null`, completed steps, and a safe error object. Parsing/input errors before a run starts can use ordinary stderr diagnostics. `--show-steps` may already have displayed completed steps. Exit codes: `0` success, `2` invalid configuration/input, `1` translation/transport/protocol failure, `130` user interruption. Never present an intermediate translation as a successful final paraphrase.

## Verification and acceptance

1. CLI tests cover aliases, invalid inputs, closed-chain validation, preset selection, conflicting preset/custom-chain options, repeat semantics, mode selection, environment precedence, stdin/file/positional selection, help, and exit codes. Assert that the default chain makes five translations, each preset resolves to its documented fixed chain, custom chains replace the default, and the selected mode reaches every hop without altering the chain or call count.
2. A local HTTP fixture verifies actual URL joining, JSON payloads, optional authentication, Unicode, fresh messages, ordered chaining, and exactly `(chain length - 1) × repeat` successful requests without retries.
3. Failure fixtures cover unavailable servers, authentication failures, missing models, explicit retries, timeout behavior, invalid JSON, empty content, and truncated completions. Confirm no later hop runs and stdout cannot masquerade as success.
4. Output tests verify final-text-only stdout, intermediate stderr, successful/failed JSON records, and a dry run that performs zero network calls.
5. Build and install the package in an isolated environment and smoke-test the console entry point and `python -m convolute`.
6. When a live endpoint is available, compare the `short`, `long`, and `extended` presets and the custom chain `en,zh,ko,ja,id,en` in both modes on a small fixed corpus with factual statements, negation, names, numbers, idioms, and multiple paragraphs. Inspect meaning preservation and useful wording variation, and record model, settings, latency, and outputs. Do not assert model quality from mocked tests or use exact paraphrase strings as unit-test expectations.

## Research sources

- [Cai et al., Revisiting Pivot-Based Paraphrase Generation, EMNLP 2021](https://aclanthology.org/2021.emnlp-main.350/): pivot paraphrasing and semantic-shift limitations.
- [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility): local base URL and chat-completion interface; compatibility is a subset of the API.
- [Ollama Qwen2.5 7B model listing](https://ollama.com/library/qwen2.5:7b): multilingual coverage and the proposed local model's download size.
- [Library of Congress ISO language-code list](https://www.loc.gov/standards/iso639-2/php/code_list.php): canonical language codes, including Chinese `zh`, Korean `ko`, Japanese `ja`, and Indonesian `id`.
