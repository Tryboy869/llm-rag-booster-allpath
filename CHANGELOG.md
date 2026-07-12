# Changelog

## 2.0.0 — full rewrite

**Why:** an independent audit of 1.0.0 found that its core "gravitational
compression" mechanism did not compress anything, and several claims in
the README and `provider.json` did not hold up under direct testing.
Rather than patch around that, this release replaces the retrieval and
provider layers outright and changes what the project claims about itself.

### Removed
- `GravitationalBit` / `GravitationalMemory` (orbital-state encoding of an
  MD5 hash into 1240 unused Python objects per chunk). Measured against a
  plain dict storing the same chunked text on a 26,000-character document:
  4× more memory, 86× slower, for zero functional benefit — the retrieved
  context was always read from the plaintext copy, never from the
  "gravitational" structure.
- The `compression_ratio` metric. Its formula (`chunk_count × level²`) was
  disconnected from actual stored bytes, and — the opposite of the
  documented "higher level = more compression" — it went *down* as
  `compression_level` went up (21.7× at level 10, 9.6× at level 15, 3.5×
  at level 25).
- The "100% integrity guaranteed" claim. `verify_integrity()` could not
  fail by construction: `propagate()` only mutated a `.phase` field that
  `decode()` never reads, so the check passed regardless of input.
- The "15–60× context extension" framing. No RAG system extends a model's
  actual context window; it selects a relevant subset of a larger corpus.
  See the README's "What this does NOT do" section.

### Fixed
- **Anthropic auth**: the old client sent `Authorization: Bearer` to every
  provider, including Anthropic, which requires `x-api-key` +
  `anthropic-version` instead. The README's own Anthropic example did not
  work. `providers.py` now has one adapter per API shape, each with its
  own header logic and its own test.
- **CLI / provider.json state loss**: `booster.py`'s CLI used a
  module-level global (`_booster`) as its only state. Each CLI invocation
  is a separate OS process, so every call after `init` returned
  `"Not initialized"` — confirmed by running the original `test.py`
  directly, which crashed with `KeyError: 'chunks'`. State now persists to
  a JSON file between CLI calls.
- **Missing LICENSE**: the README and `provider.json` both declared MIT;
  no `LICENSE` file existed in the repository. Added.

### Added
- Real Okapi BM25 ranking (IDF-weighted) in place of raw keyword-overlap
  counting, so common words no longer score the same as rare, specific
  ones.
- Configurable chunk overlap (`overlap=`) so a fact isn't silently
  severed at a chunk boundary.
- Conversation history in `ask()` — follow-up questions now have context.
  `ask()` returns `sources` (which chunks were used) alongside the answer.
- Retry with exponential backoff on transient LLM API failures.
- An HTTP API (`ragbooster serve`, FastAPI) and a `Dockerfile` /
  `docker-compose.yml`, for callers that aren't Python.
- A real test suite (`tests/`) that checks retrieval actually returns the
  chunk containing the answer to a given question, that each provider
  sends the headers its API requires, and that save/load round-trips
  correctly across process boundaries — none of which the original
  `test.py` did, despite appearing to.
- A reproducible benchmark (`benchmark/benchmark.py`) comparing this
  engine against the 1.0.0 engine on the same corpus, with the full
  question set printed in the script.

## 1.0.0

Initial release.
