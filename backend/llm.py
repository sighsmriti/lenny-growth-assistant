"""Runtime-selected chat model providers with sanitized failures."""
from dataclasses import dataclass
import os

import httpx


DEFAULT_OLLAMA_MODEL = "qwen2.5:3b"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
REQUEST_TIMEOUT_SECONDS = 180.0


class LLMError(RuntimeError):
    """Provider error safe to return to an API caller."""

    status_code = 502


class LLMConfigurationError(LLMError):
    status_code = 503


class LLMTimeoutError(LLMError):
    status_code = 504


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    model: str
    ready: bool


def get_config() -> ProviderConfig:
    provider = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
    if provider not in {"ollama", "openai"}:
        raise LLMConfigurationError("LLM_PROVIDER must be either 'ollama' or 'openai'.")
    if provider == "openai":
        return ProviderConfig(
            provider=provider,
            model=os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
            ready=bool(os.getenv("OPENAI_API_KEY", "").strip()),
        )
    return ProviderConfig(
        provider=provider,
        model=os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
        ready=True,
    )


def public_config() -> dict[str, str | bool]:
    """Configuration safe to expose; never returns provider credentials."""
    config = get_config()
    return {"provider": config.provider, "model": config.model, "ready": config.ready}


async def generate(messages: list[dict[str, str]]) -> str:
    config = get_config()
    if not config.ready:
        raise LLMConfigurationError(
            "OpenAI is selected but OPENAI_API_KEY is not configured. Set the key or select LLM_PROVIDER=ollama."
        )
    if config.provider == "ollama":
        return await _generate_ollama(config, messages)
    return await _generate_openai(config, messages)


async def _generate_ollama(config: ProviderConfig, messages: list[dict[str, str]]) -> str:
    base_url = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{base_url}/api/chat",
                json={"model": config.model, "messages": messages, "stream": False},
            )
            response.raise_for_status()
        reply = response.json()["message"]["content"]
    except httpx.TimeoutException as exc:
        raise LLMTimeoutError("The Ollama request timed out.") from exc
    except httpx.HTTPError as exc:
        raise LLMError("Ollama is unavailable or the model request failed.") from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise LLMError("Ollama returned an invalid model response.") from exc
    if not isinstance(reply, str):
        raise LLMError("Ollama returned an invalid model response.")
    return reply


async def _generate_openai(config: ProviderConfig, messages: list[dict[str, str]]) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise LLMConfigurationError(
            "OpenAI is selected but OPENAI_API_KEY is not configured. Set the key or select LLM_PROVIDER=ollama."
        )
    from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

    try:
        async with AsyncOpenAI(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS, max_retries=0) as client:
            response = await client.chat.completions.create(
                model=config.model,
                messages=messages,
            )
        reply = response.choices[0].message.content
    except APITimeoutError as exc:
        raise LLMTimeoutError("The OpenAI request timed out.") from exc
    except (APIConnectionError, APIStatusError) as exc:
        raise LLMError("OpenAI is unavailable or the model request failed.") from exc
    except (IndexError, AttributeError, TypeError) as exc:
        raise LLMError("OpenAI returned an invalid model response.") from exc
    if not isinstance(reply, str):
        raise LLMError("OpenAI returned an invalid model response.")
    return reply
