"""
server.py — HTTP API around RAGBooster, for the "run once, call from any
language" use case (curl, JS, Go, Rust, whatever speaks HTTP).

This is where the old provider.json / CLI design actually becomes usable:
the earlier bug was that `provider.json` implied a runner calling
`python3 booster.py <fn> <args>` per function, and each of those calls
was a brand-new OS process, so the module-level `_booster` global was
always empty on the 2nd call onward. A FastAPI server is a single
long-running process, so state naturally survives between requests —
no subprocess re-spawning involved. Sessions are still explicit
(session_id) rather than one implicit global, so one container can
safely serve more than one document/user at a time.
"""

from __future__ import annotations

import os
import uuid
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .client import RAGBooster, RAGBoosterError

app = FastAPI(
    title="ragbooster",
    version="2.0.0",
    description="Lightweight LLM-agnostic RAG: BM25 retrieval + a universal LLM client, served over HTTP.",
)

_sessions: Dict[str, RAGBooster] = {}
_STATE_DIR = os.environ.get("RAGBOOSTER_STATE_DIR", "/data")


def _get_session(session_id: str) -> RAGBooster:
    booster = _sessions.get(session_id)
    if booster is None:
        raise HTTPException(status_code=404, detail=f"Unknown session_id '{session_id}'. Create one via POST /sessions.")
    return booster


# --------------------------------------------------------------- schemas

class CreateSessionRequest(BaseModel):
    api_url: str = Field(..., description="LLM endpoint, e.g. https://api.anthropic.com/v1/messages")
    api_key: str = ""
    model: str = ""
    provider: Optional[str] = Field(None, description="openai | anthropic | ollama-chat | ollama-generate. Leave unset to auto-detect from api_url.")
    k1: float = 1.5
    b: float = 0.75


class LoadDocumentRequest(BaseModel):
    text: str
    chunk_size: int = 200
    overlap: int = 50
    source: Optional[str] = None


class AskRequest(BaseModel):
    question: str
    top_k: int = 8
    use_history: bool = True
    system: Optional[str] = None
    temperature: float = 0.3
    max_tokens: int = 800


# ---------------------------------------------------------------- routes

@app.get("/health")
def health():
    return {"status": "ok", "active_sessions": len(_sessions)}


@app.post("/sessions")
def create_session(req: CreateSessionRequest):
    session_id = uuid.uuid4().hex[:12]
    try:
        booster = RAGBooster(
            api_url=req.api_url, api_key=req.api_key, model=req.model,
            provider=req.provider, k1=req.k1, b=req.b,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _sessions[session_id] = booster
    return {"session_id": session_id, "provider": booster.provider.name}


@app.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    _get_session(session_id)
    del _sessions[session_id]
    return {"deleted": session_id}


@app.post("/sessions/{session_id}/documents")
def load_document(session_id: str, req: LoadDocumentRequest):
    booster = _get_session(session_id)
    return booster.load_document(req.text, chunk_size=req.chunk_size,
                                  overlap=req.overlap, source=req.source)


@app.post("/sessions/{session_id}/ask")
def ask(session_id: str, req: AskRequest):
    booster = _get_session(session_id)
    try:
        return booster.ask(req.question, top_k=req.top_k, use_history=req.use_history,
                            system=req.system, temperature=req.temperature,
                            max_tokens=req.max_tokens)
    except RAGBoosterError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/sessions/{session_id}/stats")
def stats(session_id: str):
    return _get_session(session_id).get_stats()


@app.post("/sessions/{session_id}/save")
def save_session(session_id: str):
    booster = _get_session(session_id)
    os.makedirs(_STATE_DIR, exist_ok=True)
    path = os.path.join(_STATE_DIR, f"{session_id}.json")
    booster.save(path)
    return {"saved_to": path}


@app.post("/sessions/{session_id}/restore")
def restore_session(session_id: str):
    path = os.path.join(_STATE_DIR, f"{session_id}.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"No saved state at {path}")
    booster = _get_session(session_id)
    booster.load(path)
    return {"restored_from": path}
