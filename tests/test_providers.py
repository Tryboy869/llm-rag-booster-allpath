import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ragbooster.providers import (
    AnthropicProvider, OpenAICompatibleProvider, OllamaChatProvider,
    OllamaGenerateProvider, detect_provider,
)

MSGS = [{"role": "user", "content": "hi"}]


def test_anthropic_uses_x_api_key_not_bearer():
    """
    This is the exact test that would have caught the original bug:
    the old code sent `Authorization: Bearer <key>` to every provider,
    including Anthropic, which rejects that and requires x-api-key +
    anthropic-version instead.
    """
    req = AnthropicProvider().build_request(
        api_key="sk-ant-xxx", model="claude-sonnet-4-6", messages=MSGS,
        system=None, temperature=0.3, max_tokens=100,
    )
    assert req.headers["x-api-key"] == "sk-ant-xxx"
    assert "anthropic-version" in req.headers
    assert "Authorization" not in req.headers


def test_openai_compatible_uses_bearer():
    req = OpenAICompatibleProvider().build_request(
        api_key="sk-xxx", model="gpt-4", messages=MSGS,
        system=None, temperature=0.3, max_tokens=100,
    )
    assert req.headers["Authorization"] == "Bearer sk-xxx"


def test_ollama_chat_works_without_api_key():
    req = OllamaChatProvider().build_request(
        api_key="", model="llama3", messages=MSGS,
        system=None, temperature=0.3, max_tokens=100,
    )
    assert "Authorization" not in req.headers
    assert req.json_body["messages"] == MSGS


def test_system_prompt_injected_correctly_per_provider():
    a = AnthropicProvider().build_request(api_key="k", model="m", messages=MSGS,
                                            system="be concise", temperature=0.3, max_tokens=10)
    assert a.json_body["system"] == "be concise"  # top-level field for Anthropic

    o = OpenAICompatibleProvider().build_request(api_key="k", model="m", messages=MSGS,
                                                   system="be concise", temperature=0.3, max_tokens=10)
    assert o.json_body["messages"][0] == {"role": "system", "content": "be concise"}  # prepended message


def test_response_parsing_openai():
    data = {"choices": [{"message": {"content": "hello"}}]}
    assert OpenAICompatibleProvider().parse_response(data) == "hello"


def test_response_parsing_anthropic_joins_text_blocks():
    data = {"content": [{"type": "text", "text": "hel"}, {"type": "text", "text": "lo"}]}
    assert AnthropicProvider().parse_response(data) == "hello"


def test_response_parsing_ollama_chat():
    data = {"message": {"role": "assistant", "content": "hi"}}
    assert OllamaChatProvider().parse_response(data) == "hi"


def test_response_parsing_ollama_generate():
    data = {"response": "hi there"}
    assert OllamaGenerateProvider().parse_response(data) == "hi there"


def test_malformed_response_raises_clear_error_not_keyerror():
    try:
        OpenAICompatibleProvider().parse_response({"unexpected": "shape"})
        assert False, "should have raised"
    except ValueError as e:
        assert "Unexpected" in str(e)


def test_auto_detect_provider_from_url():
    assert detect_provider("https://api.anthropic.com/v1/messages").name == "anthropic"
    assert detect_provider("http://localhost:11434/api/chat").name == "ollama-chat"
    assert detect_provider("http://localhost:11434/api/generate").name == "ollama-generate"
    assert detect_provider("https://api.groq.com/openai/v1/chat/completions").name == "openai-compatible"
