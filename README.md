<h1 align="center">convolute</h1>

<p align="center">
  Paraphrase text by translating it through a chain of languages with an LLM.
</p>

<p align="center">
  <a href="https://pypi.org/project/convolute/"><img alt="PyPI" src="https://img.shields.io/pypi/v/convolute?color=blue"></a>
  <a href="https://pypi.org/project/convolute/"><img alt="Python" src="https://img.shields.io/pypi/pyversions/convolute"></a>
  <a href="https://github.com/git-akihakune/convolute/actions/workflows/publish.yml"><img alt="Publish" src="https://github.com/git-akihakune/convolute/actions/workflows/publish.yml/badge.svg"></a>
  <a href="https://github.com/git-akihakune/convolute/blob/main/LICENSE"><img alt="License: GPL-3.0" src="https://img.shields.io/pypi/l/convolute"></a>
  <a href="https://ollama.com/"><img alt="Works with Ollama" src="https://img.shields.io/badge/works%20with-Ollama-black"></a>
</p>

<p align="center">
  <img alt="convolute translating a sentence through five languages" src="https://raw.githubusercontent.com/git-akihakune/convolute/main/docs/demo.gif" width="760">
</p>

Each translation feeds the next, and the last one lands back in your language. The
default chain makes **five translations**:

```text
English → French → German → Japanese → Spanish → English
```

The result keeps the meaning but not the wording. It runs against any
OpenAI-compatible endpoint, and a local [Ollama](https://ollama.com/) is the default,
so your text stays on your machine.

## Install

```sh
pipx install convolute
```

Requires Python 3.11+. Upgrade with `pipx upgrade convolute`.

## Quick start

Convolute talks to an OpenAI-compatible chat endpoint. For a local setup with Ollama:

```sh
ollama pull qwen2.5:7b          # ~4.7 GB, the default model
convolute "The meeting has been moved to Friday."
```

Convolute never downloads models, starts servers, or falls back to another provider.
Preview a run without contacting anything:

```sh
convolute --dry-run "The meeting has been moved to Friday."
```

## Usage

```sh
convolute --show-steps "Watch every hop live."         # see each translation
convolute --mode creative "Ask for freer phrasing."    # faithful (default) or creative
convolute --preset extended "Nine translations."       # short, long (default), extended
convolute --chain en,ja,ko,en "Pick your own chain."   # closed chain of language codes
convolute --repeat 2 "Run the whole chain twice."
convolute --file notes.txt --json > run.json           # structured output with every step
cat corpus.txt | convolute > paraphrased.txt           # plain text on stdout, so pipes work
convolute --clipboard "Copy the result."
```

| Preset | Chain | Translations |
| --- | --- | ---: |
| `short` | `en,fr,en` | 2 |
| **`long`** (default) | `en,fr,de,ja,es,en` | **5** |
| `extended` | `en,fr,de,es,pt,it,zh,ja,ko,en` | 9 |

Settings come from flags or environment variables:

| Setting | Flag | Environment variable | Default |
| --- | --- | --- | --- |
| Endpoint | `--endpoint` | `CONVOLUTE_ENDPOINT` | `http://127.0.0.1:11434/v1` |
| Model | `--model` | `CONVOLUTE_MODEL` | `qwen2.5:7b` |
| Mode | `--mode` | `CONVOLUTE_MODE` | `faithful` |
| API key | — | `CONVOLUTE_API_KEY` | none |

To use a hosted endpoint, pass a base URL and set the key in your environment:

```sh
export CONVOLUTE_API_KEY=...
convolute --endpoint https://llm.example.org/v1 --model my-model "text"
```

[TranslateGemma](https://ollama.com/library/translategemma) models are detected and get
their documented prompt format automatically.

## Good to know

- **It's a proof of concept.** Translation chains drift. Faithful mode is an instruction
  to the model, not a guarantee, and small models drift a lot. Check the output
  before you rely on it, especially names, numbers, and negation.
- **The whole document goes in every hop.** There is no chunking, so input plus output
  must fit the model's context.
- **Nothing is written to disk.** Intermediate text lives in memory unless you ask for
  `--json` or `--show-steps`.

## Documentation

- [Reference](https://github.com/git-akihakune/convolute/blob/main/docs/reference.md):
  every option, output format, exit codes, retries, terminal display, and data handling
- [Development](https://github.com/git-akihakune/convolute/blob/main/docs/development.md):
  running the tests and evaluating paraphrase quality
- [Releasing](https://github.com/git-akihakune/convolute/blob/main/docs/releasing.md):
  how maintainers publish to PyPI

## Build from source

```sh
git clone https://github.com/git-akihakune/convolute.git
cd convolute
pipx install .
```

For development, use an editable install with the test extras:

```sh
python3 -m venv .venv && . .venv/bin/activate
python -m pip install -e '.[test]'
python -m pytest -q
```

## License

[GPL-3.0-only](https://github.com/git-akihakune/convolute/blob/main/LICENSE)
