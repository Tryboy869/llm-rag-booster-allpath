"""
retriever.py — Sparse lexical retrieval (Okapi BM25).

This replaces the old "GravitationalMemory" / "GravitationalBit" classes.
Those stored the raw text in plain dict fields anyway and built an unused,
1240-object-per-chunk decorative structure alongside it — no compression
ever happened. This module does the one thing that repo actually needs:
rank chunks of text against a query, using a well-known, well-understood
algorithm (BM25) instead of raw keyword-overlap counting.

No external dependencies. Pure stdlib (math, re, collections).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")


def tokenize(text: str) -> List[str]:
    """Lowercase word tokenizer. Deliberately simple and dependency-free."""
    return _TOKEN_RE.findall(text.lower())


def chunk_text(text: str, chunk_size: int = 200, overlap: int = 0) -> List[str]:
    """
    Split text into word-count windows.

    overlap > 0 means consecutive chunks share `overlap` words at the
    boundary, so a fact that straddles a cut point still appears intact
    in at least one chunk. The original implementation always used
    overlap=0, which can silently sever a sentence at exactly the
    chunk_size'th word.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    words = text.split()
    if not words:
        return []

    step = chunk_size - overlap
    chunks = []
    i = 0
    while i < len(words):
        window = words[i : i + chunk_size]
        if window:
            chunks.append(" ".join(window))
        if i + chunk_size >= len(words):
            break
        i += step
    return chunks


@dataclass
class Chunk:
    chunk_id: str
    text: str
    source: Optional[str] = None
    token_counts: Counter = field(default_factory=Counter)
    length: int = 0


class BM25Retriever:
    """
    Okapi BM25 index over text chunks.

    k1 controls term-frequency saturation (how much repeating a word in
    the same chunk keeps adding score — diminishing returns past k1).
    b controls length normalization (0 = ignore chunk length, 1 = fully
    penalize long chunks). Defaults (1.5, 0.75) are the standard values
    used by Lucene/Elasticsearch and most BM25 references.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.chunks: Dict[str, Chunk] = {}
        self.doc_freq: Counter = Counter()   # token -> number of chunks containing it
        self._avg_len: float = 0.0
        self._order: List[str] = []          # insertion order, for stable fallback

    # ---------------------------------------------------------------- index

    def add_chunk(self, text: str, source: Optional[str] = None, chunk_id: Optional[str] = None) -> str:
        """Index a single chunk of text. Returns its chunk_id."""
        if chunk_id is None:
            chunk_id = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]

        tokens = tokenize(text)
        counts = Counter(tokens)

        if chunk_id in self.chunks:
            # Replace: remove old doc frequencies first so re-adding the
            # same id (e.g. re-loading a document) doesn't double-count.
            self._remove_doc_freqs(self.chunks[chunk_id])
        else:
            self._order.append(chunk_id)

        self.chunks[chunk_id] = Chunk(
            chunk_id=chunk_id, text=text, source=source,
            token_counts=counts, length=len(tokens),
        )
        for token in counts:
            self.doc_freq[token] += 1

        self._recompute_avg_len()
        return chunk_id

    def add_document(self, text: str, chunk_size: int = 200, overlap: int = 50,
                      source: Optional[str] = None) -> Dict:
        """Chunk a document and index every chunk. Returns summary stats."""
        pieces = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
        ids = [self.add_chunk(p, source=source) for p in pieces]
        return {
            "chunks_added": len(ids),
            "chunk_ids": ids,
            "total_chunks": len(self.chunks),
            "indexed_terms": len(self.doc_freq),
        }

    def _remove_doc_freqs(self, chunk: Chunk) -> None:
        for token in chunk.token_counts:
            self.doc_freq[token] -= 1
            if self.doc_freq[token] <= 0:
                del self.doc_freq[token]

    def _recompute_avg_len(self) -> None:
        if not self.chunks:
            self._avg_len = 0.0
        else:
            self._avg_len = sum(c.length for c in self.chunks.values()) / len(self.chunks)

    # ------------------------------------------------------------- scoring

    def _idf(self, token: str) -> float:
        n = len(self.chunks)
        df = self.doc_freq.get(token, 0)
        # BM25+ style IDF, always non-negative (classic Robertson-Sparck
        # Jones IDF can go negative for terms in >50% of chunks).
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def score(self, query: str, chunk_id: str) -> float:
        chunk = self.chunks[chunk_id]
        if self._avg_len == 0:
            return 0.0
        total = 0.0
        for token in set(tokenize(query)):
            f = chunk.token_counts.get(token, 0)
            if f == 0:
                continue
            idf = self._idf(token)
            denom = f + self.k1 * (1 - self.b + self.b * chunk.length / self._avg_len)
            total += idf * (f * (self.k1 + 1)) / denom
        return total

    def search(self, query: str, top_k: int = 8) -> List[Tuple[str, float]]:
        """Return [(chunk_id, score), ...] sorted by descending score."""
        if not self.chunks:
            return []
        query_tokens = set(tokenize(query))
        candidates = set()
        for token in query_tokens:
            # Only chunks that actually contain at least one query token
            # are scored — this is why BM25/TF-IDF indices are called
            # "sparse": we never touch chunks with zero overlap.
            for chunk_id, chunk in self.chunks.items():
                if token in chunk.token_counts:
                    candidates.add(chunk_id)

        if not candidates:
            # No lexical overlap at all: fall back to the most recently
            # added chunks rather than returning nothing.
            return [(cid, 0.0) for cid in self._order[-top_k:]]

        scored = [(cid, self.score(query, cid)) for cid in candidates]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def retrieve_context(self, query: str, top_k: int = 8, separator: str = "\n\n") -> str:
        hits = self.search(query, top_k=top_k)
        return separator.join(self.chunks[cid].text for cid, _ in hits)

    # ---------------------------------------------------------------- misc

    def get_stats(self) -> Dict:
        return {
            "total_chunks": len(self.chunks),
            "indexed_terms": len(self.doc_freq),
            "avg_chunk_length_tokens": round(self._avg_len, 1),
        }

    def clear(self) -> None:
        self.chunks.clear()
        self.doc_freq.clear()
        self._order.clear()
        self._avg_len = 0.0

    # ----------------------------------------------------------- persist

    def to_dict(self) -> Dict:
        return {
            "k1": self.k1,
            "b": self.b,
            "order": self._order,
            "chunks": {
                cid: {"text": c.text, "source": c.source}
                for cid, c in self.chunks.items()
            },
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "BM25Retriever":
        retriever = cls(k1=data.get("k1", 1.5), b=data.get("b", 0.75))
        for cid in data.get("order", data.get("chunks", {}).keys()):
            entry = data["chunks"][cid]
            retriever.add_chunk(entry["text"], source=entry.get("source"), chunk_id=cid)
        return retriever

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f)

    @classmethod
    def load(cls, path: str) -> "BM25Retriever":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
