"""Tests for autodev.llm.client and autodev.llm.prompts (HTTP fully mocked)."""

import httpx
import pytest

from autodev.llm import client as llm_client
from autodev.llm import prompts
from autodev.llm.client import (
    AnthropicClient,
    LLMError,
    MockLLMClient,
    OllamaClient,
    OpenAIClient,
    create_client,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def patch_post(monkeypatch, responses):
    """Replace httpx.post with a fake returning queued responses (or raising)."""
    calls = []

    def fake_post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(llm_client.httpx, "post", fake_post)
    return calls


def test_anthropic_generate_parses_content(monkeypatch):
    payload = {"content": [{"type": "text", "text": "def f():"}, {"type": "text", "text": " pass"}]}
    calls = patch_post(monkeypatch, [FakeResponse(payload=payload)])
    client = AnthropicClient(api_key="k", retry_wait=0)
    assert client.generate("hi", system="sys") == "def f(): pass"
    assert calls[0]["url"].endswith("/v1/messages")
    assert calls[0]["headers"]["x-api-key"] == "k"
    assert calls[0]["json"]["system"] == "sys"


def test_openai_generate_parses_choices(monkeypatch):
    payload = {"choices": [{"message": {"content": "result"}}]}
    calls = patch_post(monkeypatch, [FakeResponse(payload=payload)])
    client = OpenAIClient(api_key="k", retry_wait=0)
    assert client.generate("hi") == "result"
    assert calls[0]["url"].endswith("/chat/completions")
    assert calls[0]["headers"]["Authorization"] == "Bearer k"


def test_ollama_generate_parses_message(monkeypatch):
    payload = {"message": {"content": "ollama says"}}
    calls = patch_post(monkeypatch, [FakeResponse(payload=payload)])
    client = OllamaClient(retry_wait=0)
    assert client.generate("hi") == "ollama says"
    assert calls[0]["url"].endswith("/api/chat")
    assert calls[0]["json"]["stream"] is False


def test_retry_on_server_error_then_success(monkeypatch):
    payload = {"message": {"content": "recovered"}}
    patch_post(monkeypatch, [FakeResponse(status_code=500, text="boom"),
                             FakeResponse(status_code=429, text="slow down"),
                             FakeResponse(payload=payload)])
    client = OllamaClient(retry_wait=0)
    assert client.generate("hi") == "recovered"


def test_connection_error_exhausts_retries(monkeypatch):
    patch_post(monkeypatch, [httpx.ConnectError("refused")] * 4)
    client = OllamaClient(retry_wait=0, max_retries=3)
    with pytest.raises(LLMError, match="Start Ollama"):
        client.generate("hi")


def test_client_error_is_not_retried(monkeypatch):
    calls = patch_post(monkeypatch, [FakeResponse(status_code=401, text="bad key")])
    client = AnthropicClient(api_key="wrong", retry_wait=0)
    with pytest.raises(LLMError, match="HTTP 401"):
        client.generate("hi")
    assert len(calls) == 1


def test_missing_api_key_raises():
    with pytest.raises(LLMError, match="AUTODEV_API_KEY"):
        AnthropicClient(api_key="")
    with pytest.raises(LLMError, match="AUTODEV_API_KEY"):
        OpenAIClient(api_key="")


def test_create_client_dispatch():
    assert isinstance(create_client("anthropic", api_key="k"), AnthropicClient)
    assert isinstance(create_client("openai", api_key="k"), OpenAIClient)
    assert isinstance(create_client("ollama"), OllamaClient)
    assert isinstance(create_client("mock"), MockLLMClient)


def test_create_client_applies_model_and_base_url():
    client = create_client("ollama", model="llama3.2", base_url="http://box:11434/")
    assert client.model == "llama3.2"
    assert client.base_url == "http://box:11434"


def test_create_client_unknown_provider():
    with pytest.raises(LLMError, match="Unknown provider"):
        create_client("skynet")


def test_mock_client_replays_and_records():
    client = MockLLMClient(responses=["one", "two"])
    assert client.generate("p1") == "one"
    assert client.generate("p2", system="s") == "two"
    assert "no canned output" in client.generate("p3")
    assert client.calls[1]["system"] == "s"


def test_build_prompt_variants():
    prompt = prompts.build_prompt("add_tests", "def f(): pass", module_name="pkg.mod")
    assert "pkg.mod" in prompt and "def f(): pass" in prompt

    retry = prompts.build_prompt("refactor", "code", error="AssertionError: nope")
    assert "AssertionError: nope" in retry

    doc = prompts.build_prompt("add_docstrings", "code")
    assert "Google-style" in doc

    with pytest.raises(KeyError):
        prompts.build_prompt("unknown_job", "code")
