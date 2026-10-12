import asyncio
import json

import httpx
import pytest

from backend import llm


def test_provider_defaults_to_local_ollama_and_can_select_openai(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert llm.get_config() == llm.ProviderConfig("ollama", "qwen2.5:3b", True)

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    assert llm.get_config() == llm.ProviderConfig("openai", "test-model", True)
    assert llm.public_config() == {"provider": "openai", "model": "test-model", "ready": True}
    assert "test-secret" not in json.dumps(llm.public_config())


def test_openai_missing_key_fails_without_fallback(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(llm.LLMConfigurationError, match="OPENAI_API_KEY") as error:
        asyncio.run(llm.generate([{"role": "user", "content": "hello"}]))
    assert error.value.status_code == 503
    assert llm.public_config() == {"provider": "openai", "model": "gpt-4o-mini", "ready": False}


def test_config_api_reports_provider_without_exposing_key(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.main import app

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "never-return-this-secret")

    with TestClient(app) as client:
        response = client.get("/api/config")
    assert response.status_code == 200
    assert response.json() == {"llm": {"provider": "openai", "model": "gpt-4o-mini", "ready": True}}
    assert "never-return-this-secret" not in response.text


def test_openai_provider_uses_official_sdk_and_selected_model(monkeypatch):
    from openai import AsyncOpenAI

    captured = {}

    class FakeCompletions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return type("Response", (), {"choices": [type("Choice", (), {"message": type("Message", (), {"content": "Cloud answer"})()})()]})()

    class FakeClient:
        def __init__(self, *, api_key, timeout, max_retries):
            captured["api_key"] = api_key
            captured["timeout"] = timeout
            captured["max_retries"] = max_retries
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr("openai.AsyncOpenAI", FakeClient)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    messages = [{"role": "user", "content": "hello"}]

    assert asyncio.run(llm.generate(messages)) == "Cloud answer"
    assert captured["model"] == "test-model"
    assert captured["messages"] == messages
    assert captured["api_key"] == "test-secret"
    assert captured["max_retries"] == 0
    assert isinstance(AsyncOpenAI, type)


@pytest.mark.parametrize("failure,expected", [
    ("outage", llm.LLMError),
    ("timeout", llm.LLMTimeoutError),
])
def test_openai_outage_and_timeout_are_sanitized(monkeypatch, failure, expected):
    from openai import APIConnectionError, APITimeoutError

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")

    class FakeCompletions:
        async def create(self, **kwargs):
            if failure == "timeout":
                raise APITimeoutError(request=request)
            raise APIConnectionError(request=request)

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr("openai.AsyncOpenAI", FakeClient)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "never-return-this-secret")

    with pytest.raises(expected) as error:
        asyncio.run(llm.generate([{"role": "user", "content": "hello"}]))
    assert "never-return-this-secret" not in str(error.value)
    assert error.value.status_code == (504 if failure == "timeout" else 502)


def test_pi_models_config_uses_environment_credential_reference():
    from pathlib import Path

    config_path = Path(__file__).resolve().parents[1] / "agent-service" / "models.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    openai_provider = config["providers"]["openai"]
    assert openai_provider["apiKey"] == "$OPENAI_API_KEY"
    assert openai_provider["models"][0]["id"] == "gpt-4o-mini"
