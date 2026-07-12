# ragbooster

**A small, honest RAG library.** BM25 sparse retrieval + a universal LLM client
(OpenAI, Groq, Anthropic, Ollama) — usable as a Python import, a CLI, or an
HTTP service you can run with one Docker command.

No vector database. No embedding API costs. No proprietary file format.

---

## What this actually does

Given a document too large to paste into an LLM's context window, `ragbooster`
splits it into overlapping chunks, ranks those chunks against your question
using [Okapi BM25](https://en.wikipedia.org/wiki/Okapi_BM25), and sends only
the top-k relevant chunks to the LLM. That's it. That's the whole trick.

**What this does NOT do:** it does not change or "extend" the LLM's actual
context window. No RAG system — this one, a vector database, anything —
makes a 128k-token model accept more than 128k tokens. What RAG does is
*select a relevant subset of a larger corpus* so that subset fits inside the
window that already exists. Earlier versions of this project described this
as "gravitational compression" and "15-60× context extension" with a
"quantum-inspired" storage format. That framing measured nothing real: the
full source text was stored in plain text either way, an unused 1240-object
decorative structure sat alongside it, and independent verification showed
it used *more* memory than a plain dict, not less. See `CHANGELOG.md` for
the full account. This version says only what it can show.

## Install

```bash
pip install ragbooster                  # library only
pip install "ragbooster[server]"        # + HTTP API (FastAPI/uvicorn)
```

Or run it as a service, no Python setup required:

```bash
docker run -p 8000:8000 -v ragbooster-data:/data ghcr.io/tryboy869/ragbooster
curl http://localhost:8000/health
```

## Quick start — as a library

```python
from ragbooster import RAGBooster

booster = RAGBooster(
    api_url="https://api.groq.com/openai/v1/chat/completions",
    api_key="YOUR_GROQ_API_KEY",
    model="llama-3.3-70b-versatile",
)

booster.load_document(open("large_document.txt").read())
result = booster.ask("What is the main conclusion?")
print(result["answer"])
print(result["sources"])   # which chunks were actually used — auditable
```

Anthropic, OpenAI, and Ollama work the same way — just change `api_url`/
`api_key`/`model`; the provider is auto-detected from the URL (or set
`provider=` explicitly). Anthropic in particular needs correct `x-api-key`
+ `anthropic-version` headers, which this version sends correctly (the
original did not — see `CHANGELOG.md`).

## Quick start — as an HTTP service

```bash
docker compose up
```

```bash
SID=$(curl -s -X POST localhost:8000/sessions -H 'Content-Type: application/json' \
  -d '{"api_url":"https://api.groq.com/openai/v1/chat/completions","api_key":"...","model":"llama-3.3-70b-versatile"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['session_id'])")

curl -s -X POST localhost:8000/sessions/$SID/documents \
  -H 'Content-Type: application/json' -d '{"text":"..."}'

curl -s -X POST localhost:8000/sessions/$SID/ask \
  -H 'Content-Type: application/json' -d '{"question":"What is the main conclusion?"}'
```

Callable from any language that speaks HTTP — this is the intended answer to
"I want this usable everywhere, without a Python environment on the caller's
side."

## Quick start — CLI

```bash
ragbooster init --api-url https://api.groq.com/openai/v1/chat/completions \
                 --api-key $GROQ_API_KEY --model llama-3.3-70b-versatile
ragbooster load --file large_document.txt
ragbooster ask "What is the main conclusion?"
```

Each command is a separate process; state round-trips through
`.ragbooster/session.json` between calls (override with `--state` or
`$RAGBOOSTER_STATE`). Keep that file out of version control — it contains
your API key.

## Benchmark

Reproducible: `python3 benchmark/benchmark.py`. Compares this engine (BM25)
against the original "gravitational" engine on the same 15-fact / 15k-word
synthetic corpus, full methodology and questions in the script itself —
nothing held back.

| Metric | Old engine | New engine (BM25) |
|---|---|---|
| Retrieval precision@3 (10 labeled questions) | 70% | **90%** |
| Indexing time (~15k words) | 502 ms | **32 ms** (15.5× faster) |
| Traced memory (~15k words) | 14.9 MB | **0.95 MB** (15.7× less) |
| Self-reported "compression_ratio" | 5.42× (fictional — see above) | *(metric removed; it never measured real storage)* |

Numbers will vary by document and question set — that's why the script is
included rather than just the table.

## Provider support

| Provider | Auth | Notes |
|---|---|---|
| OpenAI / Groq / any OpenAI-compatible | `Authorization: Bearer` | default fallback if URL doesn't match a known pattern |
| Anthropic | `x-api-key` + `anthropic-version` | auto-detected from `anthropic.com` in the URL |
| Ollama `/api/chat` | none required | auto-detected from `/api/chat` in the URL |
| Ollama `/api/generate` | none required | auto-detected from `/api/generate` in the URL |

## Where this fits

BM25 is lexical: it matches words, not meaning. It's fast, needs no
embedding model or vector DB, costs nothing to run, and is fully
explainable (you can always see *why* a chunk scored the way it did). It
will miss a relevant chunk that uses different words than the question
(a known, demonstrated limitation — see the benchmark script's "DNA"
question). If you need meaning-level matching across large, diverse
corpora, pair this with an embeddings-based retriever; hybrid (lexical +
semantic) is on the roadmap as an optional, additive mode — never a
required dependency for the core library.

## Development

```bash
git clone https://github.com/Tryboy869/llm-rag-booster-allpath
cd llm-rag-booster-allpath
pip install -e ".[dev,server]"
pytest tests/ -v
```

## License

MIT — see `LICENSE`.
