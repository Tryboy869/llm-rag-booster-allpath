"""
providers.py — one adapter per LLM API shape.

The old booster.py sent `Authorization: Bearer <key>` to every endpoint,
including Anthropic's. Anthropic's Messages API requires an `x-api-key`
header plus a required `anthropic-version` header; it does not accept
Authorization: Bearer for a plain API key. That made the README's own
"Example 3: Anthropic" call fail with a 401 in practice. Each provider
below builds its own headers/body and parses its own response shape, so
adding a fifth provider later doesn't risk breaking the other four.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class LLMRequest:
    headers: Dict[str, str]
    json_body: Dict[str, Any]


class Provider:
    """Base interface. Subclass and implement build_request/parse_response."""

    name = "generic"

    def build_request(self, *, api_key: str, model: str, messages: List[Dict[str, str]],
                       system: Optional[str], temperature: float, max_tokens: int) -> LLMRequest:
        raise NotImplementedError

    def parse_response(self, data: Dict[str, Any]) -> str:
        raise NotImplementedError


class OpenAICompatibleProvider(Provider):
    """OpenAI, Groq, and any other /chat/completions-compatible endpoint."""

    name = "openai-compatible"

    def build_request(self, *, api_key, model, messages, system, temperature, max_tokens):
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        msgs = list(messages)
        if system:
            msgs = [{"role": "system", "content": system}] + msgs
        body = {
            "model": model,
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        return LLMRequest(headers=headers, json_body=body)

    def parse_response(self, data):
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise ValueError(f"Unexpected OpenAI-compatible response shape: {data}") from e


class AnthropicProvider(Provider):
    """Anthropic Messages API (api.anthropic.com/v1/messages)."""

    name = "anthropic"
    ANTHROPIC_VERSION = "2023-06-01"

    def build_request(self, *, api_key, model, messages, system, temperature, max_tokens):
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": self.ANTHROPIC_VERSION,
        }
        if api_key:
            headers["x-api-key"] = api_key
        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if system:
            body["system"] = system
        return LLMRequest(headers=headers, json_body=body)

    def parse_response(self, data):
        try:
            blocks = data["content"]
            if isinstance(blocks, list):
                return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            return str(blocks)
        except (KeyError, TypeError) as e:
            raise ValueError(f"Unexpected Anthropic response shape: {data}") from e


class OllamaChatProvider(Provider):
    """Ollama /api/chat (local or remote). No API key required by default."""

    name = "ollama-chat"

    def build_request(self, *, api_key, model, messages, system, temperature, max_tokens):
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        msgs = list(messages)
        if system:
            msgs = [{"role": "system", "content": system}] + msgs
        body = {
            "model": model,
            "messages": msgs,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        return LLMRequest(headers=headers, json_body=body)

    def parse_response(self, data):
        try:
            return data["message"]["content"]
        except (KeyError, TypeError) as e:
            raise ValueError(f"Unexpected Ollama /api/chat response shape: {data}") from e


class OllamaGenerateProvider(Provider):
    """Ollama /api/generate (single prompt, no message history)."""

    name = "ollama-generate"

    def build_request(self, *, api_key, model, messages, system, temperature, max_tokens):
        headers = {"Content-Type": "application/json"}
        prompt = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
        if system:
            prompt = f"system: {system}\n{prompt}"
        body = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        return LLMRequest(headers=headers, json_body=body)

    def parse_response(self, data):
        try:
            return data["response"]
        except (KeyError, TypeError) as e:
            raise ValueError(f"Unexpected Ollama /api/generate response shape: {data}") from e


def detect_provider(api_url: str) -> Provider:
    """Best-effort auto-detection from the endpoint URL. Can be overridden explicitly."""
    url = api_url.lower()
    if "anthropic.com" in url:
        return AnthropicProvider()
    if "/api/chat" in url:
        return OllamaChatProvider()
    if "/api/generate" in url:
        return OllamaGenerateProvider()
    return OpenAICompatibleProvider()  # OpenAI, Groq, and most others


PROVIDERS = {
    # "openai-compatible" is the canonical key (matches Provider.name, so
    # RAGBooster.save()/load_from() round-trip correctly). "openai" and
    # "groq" are friendlier aliases for the CLI --provider flag.
    "openai-compatible": OpenAICompatibleProvider,
    "openai": OpenAICompatibleProvider,
    "groq": OpenAICompatibleProvider,
    "anthropic": AnthropicProvider,
    "ollama-chat": OllamaChatProvider,
    "ollama-generate": OllamaGenerateProvider,
}


def get_provider(name_or_none: Optional[str], api_url: str) -> Provider:
    if name_or_none is None:
        return detect_provider(api_url)
    if name_or_none not in PROVIDERS:
        raise ValueError(f"Unknown provider '{name_or_none}'. Choose from {list(PROVIDERS)} or leave unset for auto-detect.")
    return PROVIDERS[name_or_none]()
