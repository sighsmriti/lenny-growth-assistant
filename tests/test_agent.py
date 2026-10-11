import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from backend import agent
from backend import main


def test_ship30_skill_is_discoverable_and_targets_about_1250_words():
    skills = agent.discover_skills()
    skill = next(item for item in skills if item["name"] == "ship-30-for-30-essay")
    path = agent.SKILLS_DIR / skill["name"] / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    assert "1,250 words" in text
    assert "1,125–1,375 words" in text
    assert "Do not invent" in text
    assert "`/skill:name`" not in skill["description"]


def test_run_skill_calls_pi_runner_and_parses_response(monkeypatch):
    captured = {}

    class FakeProcess:
        returncode = 0

        async def communicate(self, input):
            captured["input"] = json.loads(input)
            return b'{"reply":"A grounded essay draft."}', b""

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(agent.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    reply = asyncio.run(agent.run_skill("ship-30-for-30-essay", "Write about customer interviews."))
    assert reply == "A grounded essay draft."
    assert captured["input"] == {"skill": "ship-30-for-30-essay", "task": "Write about customer interviews."}
    assert Path(captured["args"][1]) == agent.PI_RUNNER


def test_run_skill_rejects_unavailable_skill_before_starting_process(monkeypatch):
    async def should_not_start(*args, **kwargs):
        raise AssertionError("unknown skills must not launch Pi")

    monkeypatch.setattr(agent.asyncio, "create_subprocess_exec", should_not_start)
    with pytest.raises(agent.PiAgentError, match="skill is not available"):
        asyncio.run(agent.run_skill("read-files", "do something"))


def test_run_skill_reports_missing_node_or_pi_dependency(monkeypatch):
    async def missing_node(*args, **kwargs):
        raise FileNotFoundError("node")

    monkeypatch.setattr(agent.asyncio, "create_subprocess_exec", missing_node)
    with pytest.raises(agent.PiAgentError, match="Node.js is required"):
        asyncio.run(agent.run_skill("ship-30-for-30-essay", "write an essay"))


def test_run_skill_reports_agent_failure_usefully(monkeypatch):
    class FakeProcess:
        returncode = 1

        async def communicate(self, input):
            return b"", b"Ollama connection refused"

    async def fake_create_subprocess_exec(*args, **kwargs):
        return FakeProcess()

    monkeypatch.setattr(agent.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    with pytest.raises(agent.PiAgentError, match="Ollama connection refused"):
        asyncio.run(agent.run_skill("ship-30-for-30-essay", "write an essay"))


def test_agent_api_lists_and_runs_ship30_skill(monkeypatch):
    from fastapi.testclient import TestClient

    async def fake_run_skill(name, task):
        assert name == "ship-30-for-30-essay"
        assert task == "Write about interviews"
        return "test-agent-artifact\n\nDrafted essay"

    monkeypatch.setattr(agent, "run_skill", fake_run_skill)
    with TestClient(main.app) as client:
        listed = client.get("/api/agent/skills")
        assert listed.status_code == 200
        assert listed.json()["framework"] == "pi-coding-agent"
        assert any(skill["name"] == "ship-30-for-30-essay" for skill in listed.json()["skills"])

        response = client.post("/api/agent/skills/ship-30-for-30-essay/run",
                               json={"task": "Write about interviews"})
    assert response.status_code == 200
    assert response.json() == {
        "reply": "test-agent-artifact\n\nDrafted essay",
        "framework": "pi-coding-agent",
        "provider": "ollama",
        "model": "qwen2.5:3b",
        "skill": "ship-30-for-30-essay",
        "artifact_id": response.json()["artifact_id"],
    }
    with main.SessionLocal() as db:
        assert db.scalar(select(main.Artifact.id).where(main.Artifact.title == "test-agent-artifact")) is not None
        db.execute(delete(main.Artifact).where(main.Artifact.title.like("test-agent-%")))
        db.commit()
