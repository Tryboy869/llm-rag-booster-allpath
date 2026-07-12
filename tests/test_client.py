import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from ragbooster.client import RAGBooster, RAGBoosterError


class _FakeResponse:
    def __init__(self, json_data, status=200):
        self._json = json_data
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.exceptions.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._json


def _patch_post(monkeypatch, responses):
    """responses: list of return values (or Exception instances) consumed in order."""
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "json": json})
        item = responses[len(calls) - 1]
        if isinstance(item, Exception):
            raise item
        return _FakeResponse(item)

    monkeypatch.setattr("ragbooster.client.requests.post", fake_post)
    return calls


def test_ask_uses_retrieved_context_and_returns_sources(monkeypatch):
    calls = _patch_post(monkeypatch, [
        {"choices": [{"message": {"content": "Guido van Rossum."}}]},
    ])
    b = RAGBooster(api_url="https://api.groq.com/openai/v1/chat/completions", model="m")
    b.load_document("Python was created by Guido van Rossum in 1991.", chunk_size=5, overlap=1)

    result = b.ask("Who created Python?", top_k=3)
    assert result["answer"] == "Guido van Rossum."
    assert result["chunks_used"] >= 1
    assert "Guido" in calls[0]["json"]["messages"][-1]["content"]


def test_conversation_history_accumulates(monkeypatch):
    _patch_post(monkeypatch, [
        {"choices": [{"message": {"content": "First answer."}}]},
        {"choices": [{"message": {"content": "Second answer."}}]},
    ])
    b = RAGBooster(api_url="https://api.groq.com/openai/v1/chat/completions", model="m")
    b.ask("Question one?")
    assert len(b.history) == 2
    b.ask("Question two?")
    assert len(b.history) == 4
    assert b.history[0]["content"] == "Question one?"
    assert b.history[-1]["content"] == "Second answer."


def test_use_history_false_does_not_grow_history(monkeypatch):
    _patch_post(monkeypatch, [{"choices": [{"message": {"content": "ok"}}]}])
    b = RAGBooster(api_url="https://api.groq.com/openai/v1/chat/completions", model="m")
    b.ask("hi", use_history=False)
    assert b.history == []


def test_retries_then_succeeds(monkeypatch):
    import requests
    calls = _patch_post(monkeypatch, [
        requests.exceptions.ConnectionError("boom"),
        {"choices": [{"message": {"content": "recovered"}}]},
    ])
    monkeypatch.setattr("ragbooster.client.time.sleep", lambda s: None)  # skip real backoff delay
    b = RAGBooster(api_url="https://api.groq.com/openai/v1/chat/completions", model="m")
    result = b.ask("hi", retries=1)
    assert result["answer"] == "recovered"
    assert len(calls) == 2  # first failed, second succeeded


def test_retry_exhaustion_raises_ragbooster_error(monkeypatch):
    import requests
    _patch_post(monkeypatch, [
        requests.exceptions.ConnectionError("boom"),
        requests.exceptions.ConnectionError("boom again"),
    ])
    monkeypatch.setattr("ragbooster.client.time.sleep", lambda s: None)
    b = RAGBooster(api_url="https://api.groq.com/openai/v1/chat/completions", model="m")
    with pytest.raises(RAGBoosterError):
        b.ask("hi", retries=1)


def test_save_and_load_preserves_config_history_and_index(tmp_path, monkeypatch):
    _patch_post(monkeypatch, [{"choices": [{"message": {"content": "42"}}]}])
    b = RAGBooster(api_url="https://api.groq.com/openai/v1/chat/completions",
                    api_key="sk-test", model="m")
    b.load_document("The answer to everything is 42.", chunk_size=6, overlap=1)
    b.ask("What is the answer?")

    path = str(tmp_path / "session.json")
    b.save(path)

    # Simulate a brand new process: fresh instance, load from disk only.
    restored = RAGBooster.load_from(path)
    assert restored.api_key == "sk-test"
    assert restored.model == "m"
    assert len(restored.history) == 2
    assert restored.get_stats()["total_chunks"] == b.get_stats()["total_chunks"]
