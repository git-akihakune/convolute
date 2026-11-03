# Development

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
