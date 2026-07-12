"""
client.py — the public RAGBooster class.

Instance-based on purpose: the old booster.py used a single module-level
global (`_booster`) as its only state. That's what made the CLI unusable
across process boundaries (each `python3 booster.py <fn>` call is a fresh
interpreter, so the global was always empty again) and it would also
leak one user's documents/API key into another user's session in any
server context. Here, state lives on the instance, so a server can hold
one RAGBooster per session_id safely.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional

import requests

from .providers import LLMRequest, Provider, get_provider
from .retriever import BM25Retriever


class RAGBoosterError(Exception):
    pass


class RAGBooster:
    def __init__(self, api_url: str, api_key: str = "", model: str = "",
                 provider: Optional[str] = None, timeout: float = 30.0,
                 k1: float = 1.5, b: float = 0.75):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.provider: Provider = get_provider(provider, api_url)
        self.retriever = BM25Retriever(k1=k1, b=b)
        self.history: List[Dict[str, str]] = []

    # ------------------------------------------------------------- ingest

    def load_document(self, text: str, chunk_size: int = 200, overlap: int = 50,
                       source: Optional[str] = None) -> Dict:
        t0 = time.time()
        result = self.retriever.add_document(text, chunk_size=chunk_size,
                                              overlap=overlap, source=source)
        result["elapsed_seconds"] = round(time.time() - t0, 4)
        result["source_chars"] = len(text)
        return result

    # ---------------------------------------------------------------- ask

    def ask(self, question: str, top_k: int = 8, use_history: bool = True,
             system: Optional[str] = None, temperature: float = 0.3,
             max_tokens: int = 800, retries: int = 2) -> Dict:
        """
        Retrieve relevant chunks, call the LLM, and (optionally) remember
        the exchange so a follow-up question like "and the second one?"
        has something to refer back to. Returns a dict with the answer
        AND which chunks were used, so results are auditable — the old
        ask() returned only a string with no way to trace the source.
        """
        hits = self.retriever.search(question, top_k=top_k)
        context = "\n\n".join(self.retriever.chunks[cid].text for cid, _ in hits)

        prompt = (
            f"Context:\n{context}\n\nQuestion: {question}\n\nAnswer using the context above."
            if context else question
        )

        messages = list(self.history) if use_history else []
        messages.append({"role": "user", "content": prompt})

        answer = self._call_llm(messages, system=system, temperature=temperature,
                                  max_tokens=max_tokens, retries=retries)

        if use_history:
            self.history.append({"role": "user", "content": question})
            self.history.append({"role": "assistant", "content": answer})

        return {
            "answer": answer,
            "sources": [{"chunk_id": cid, "score": round(score, 4)} for cid, score in hits],
            "chunks_used": len(hits),
        }

    def _call_llm(self, messages, *, system, temperature, max_tokens, retries) -> str:
        req: LLMRequest = self.provider.build_request(
            api_key=self.api_key, model=self.model, messages=messages,
            system=system, temperature=temperature, max_tokens=max_tokens,
        )
        last_error = None
        for attempt in range(retries + 1):
            try:
                resp = requests.post(self.api_url, headers=req.headers,
                                      json=req.json_body, timeout=self.timeout)
                resp.raise_for_status()
                return self.provider.parse_response(resp.json())
            except requests.exceptions.RequestException as e:
                last_error = e
                if attempt < retries:
                    time.sleep(0.5 * (2 ** attempt))  # backoff: 0.5s, 1s, 2s...
        raise RAGBoosterError(f"LLM call failed after {retries + 1} attempts: {last_error}")

    # -------------------------------------------------------------- misc

    def clear_history(self) -> None:
        self.history.clear()

    def get_stats(self) -> Dict:
        stats = self.retriever.get_stats()
        stats["provider"] = self.provider.name
        stats["model"] = self.model
        stats["history_turns"] = len(self.history) // 2
        return stats

    # ---------------------------------------------------------- persist

    def save(self, path: str) -> None:
        """
        Persist the full session (connection config + index + chat
        history) to a single JSON file. This is what makes the CLI work
        across separate process invocations: `ragbooster load` and
        `ragbooster ask` are two different OS processes, so without this
        the retriever and history would vanish between commands exactly
        like the old global-variable design did.

        Note: this writes api_key to disk in plain text, same as any
        CLI tool that takes a key as an argument. Keep state files out
        of source control (see .gitignore) and prefer env vars for the
        key in shared/CI environments.
        """
        import json
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "config": {
                    "api_url": self.api_url, "api_key": self.api_key,
                    "model": self.model, "provider": self.provider.name,
                },
                "history": self.history,
                "retriever": self.retriever.to_dict(),
            }, f)

    @classmethod
    def load_from(cls, path: str) -> "RAGBooster":
        import json
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cfg = data["config"]
        booster = cls(api_url=cfg["api_url"], api_key=cfg["api_key"],
                       model=cfg["model"], provider=cfg.get("provider"))
        booster.history = data.get("history", [])
        booster.retriever = BM25Retriever.from_dict(data["retriever"])
        return booster

    def load(self, path: str) -> None:
        """Load retriever+history from a state file into this instance."""
        restored = RAGBooster.load_from(path)
        self.retriever = restored.retriever
        self.history = restored.history
