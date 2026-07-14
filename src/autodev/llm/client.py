"""Unified LLM client: Anthropic, OpenAI-compatible, Ollama, and offline Mock."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

import httpx

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5",
    "openai": "gpt-4o-mini",
    "ollama": "qwen2.5-coder:7b",
}


class LLMError(RuntimeError):
    """Raised when the LLM backend cannot produce a response."""


class _RetryableError(Exception):
    """Internal: transient failure (rate limit, 5xx, connection refused)."""


def _check_response(response: httpx.Response, provider: str) -> None:
    """Raise _RetryableError for transient statuses, LLMError for hard failures."""
    if response.status_code == 429 or response.status_code >= 500:
        raise _RetryableError(f"HTTP {response.status_code}: {response.text[:200]}")
    if response.status_code >= 400:
        raise LLMError(f"{provider} error HTTP {response.status_code}: {response.text[:500]}")


class LLMClient(ABC):
    """Base client: retry loop around a provider-specific `_call`."""

    provider = "base"
    unavailable_hint = "Check your AUTODEV_* environment variables."

    def __init__(
        self,
        model: str,
        max_tokens: int = 4096,
        timeout: float = 180.0,
        max_retries: int = 3,
        retry_wait: float = 60.0,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_wait = retry_wait

    def generate(self, prompt: str, system: str | None = None, temperature: float = 0.2) -> str:
        """Return the model's text response, retrying transient failures."""
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return self._call(prompt, system, temperature)
            except (httpx.TransportError, _RetryableError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(self.retry_wait)
        raise LLMError(
            f"{self.provider} request failed after {self.max_retries + 1} attempts"
            f" ({last_error}). {self.unavailable_hint}"
        )

    @abstractmethod
    def _call(self, prompt: str, system: str | None, temperature: float) -> str:
        """Perform one provider request; return the response text."""


class AnthropicClient(LLMClient):
    """Client for the Anthropic Messages API."""

    provider = "anthropic"
    unavailable_hint = "Verify AUTODEV_API_KEY and network access to api.anthropic.com."

    def __init__(self, api_key: str, model: str = DEFAULT_MODELS["anthropic"],
                 base_url: str = "https://api.anthropic.com", **kwargs: Any) -> None:
        if not api_key:
            raise LLMError("Anthropic provider requires an API key: set AUTODEV_API_KEY.")
        super().__init__(model=model, **kwargs)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def _call(self, prompt: str, system: str | None, temperature: float) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system
        response = httpx.post(
            f"{self.base_url}/v1/messages",
            headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
            json=payload,
            timeout=self.timeout,
        )
        _check_response(response, self.provider)
        blocks = response.json()["content"]
        return "".join(b["text"] for b in blocks if b.get("type") == "text")


class OpenAIClient(LLMClient):
    """Client for OpenAI and OpenAI-compatible chat-completions endpoints."""

    provider = "openai"
    unavailable_hint = "Verify AUTODEV_API_KEY (and AUTODEV_BASE_URL for compatible servers)."

    def __init__(self, api_key: str, model: str = DEFAULT_MODELS["openai"],
                 base_url: str = "https://api.openai.com/v1", **kwargs: Any) -> None:
        if not api_key:
            raise LLMError("OpenAI provider requires an API key: set AUTODEV_API_KEY.")
        super().__init__(model=model, **kwargs)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def _call(self, prompt: str, system: str | None, temperature: float) -> str:
        messages = ([{"role": "system", "content": system}] if system else [])
        messages.append({"role": "user", "content": prompt})
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": self.max_tokens,
            },
            timeout=self.timeout,
        )
        _check_response(response, self.provider)
        return response.json()["choices"][0]["message"]["content"]


class OllamaClient(LLMClient):
    """Client for a local Ollama server."""

    provider = "ollama"
    unavailable_hint = (
        "Start Ollama locally (`ollama serve`, default http://localhost:11434) or set"
        " AUTODEV_LLM_PROVIDER=anthropic|openai with AUTODEV_API_KEY for a hosted provider."
    )

    def __init__(self, model: str = DEFAULT_MODELS["ollama"],
                 base_url: str = "http://localhost:11434", **kwargs: Any) -> None:
        super().__init__(model=model, **kwargs)
        self.base_url = base_url.rstrip("/")

    def _call(self, prompt: str, system: str | None, temperature: float) -> str:
        messages = ([{"role": "system", "content": system}] if system else [])
        messages.append({"role": "user", "content": prompt})
        response = httpx.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": temperature, "num_predict": self.max_tokens},
            },
            timeout=self.timeout,
        )
        _check_response(response, self.provider)
        return response.json()["message"]["content"]


class MockLLMClient(LLMClient):
    """Offline client for tests and demos: replays queued canned responses."""

    provider = "mock"

    def __init__(self, responses: list[str] | None = None, **kwargs: Any) -> None:
        kwargs.setdefault("retry_wait", 0.0)
        super().__init__(model="mock", **kwargs)
        self.responses = list(responses or [])
        self.calls: list[dict[str, Any]] = []

    def _call(self, prompt: str, system: str | None, temperature: float) -> str:
        self.calls.append({"prompt": prompt, "system": system, "temperature": temperature})
        if self.responses:
            return self.responses.pop(0)
        return "# mock response: no canned output queued\n"


def create_client(
    provider: str,
    api_key: str = "",
    model: str = "",
    base_url: str = "",
    max_tokens: int = 4096,
    retry_wait: float = 60.0,
) -> LLMClient:
    """Build the right client for a provider name (anthropic|openai|ollama|mock)."""
    provider = provider.strip().lower()
    kwargs: dict[str, Any] = {"max_tokens": max_tokens, "retry_wait": retry_wait}
    if model:
        kwargs["model"] = model
    if provider == "mock":
        return MockLLMClient(max_tokens=max_tokens, retry_wait=retry_wait)
    if base_url:
        kwargs["base_url"] = base_url
    if provider == "anthropic":
        return AnthropicClient(api_key=api_key, **kwargs)
    if provider == "openai":
        return OpenAIClient(api_key=api_key, **kwargs)
    if provider == "ollama":
        return OllamaClient(**kwargs)
    raise LLMError(f"Unknown provider '{provider}'. Use anthropic, openai, ollama, or mock.")
