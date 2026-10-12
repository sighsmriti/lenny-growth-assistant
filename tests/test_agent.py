import asyncio
import json
from pathlib import Path
import subprocess
import sys

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

    def fake_subprocess_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        captured["input"] = json.loads(kwargs["input"])
        return subprocess.CompletedProcess(command, 0, b'{"reply":"A grounded essay draft."}', b"")

    monkeypatch.setattr(agent.subprocess, "run", fake_subprocess_run)
    reply = asyncio.run(agent.run_skill("ship-30-for-30-essay", "Write about customer interviews."))
    assert reply == "A grounded essay draft."
    assert captured["input"] == {"skill": "ship-30-for-30-essay", "task": "Write about customer interviews."}
    assert captured["command"] == ["node", str(agent.PI_RUNNER)]
    assert Path(captured["command"][1]) == agent.PI_RUNNER
    assert captured["kwargs"]["shell"] is False
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["cwd"] == agent.PROJECT_ROOT


def test_run_skill_rejects_unavailable_skill_before_starting_process(monkeypatch):
    def should_not_start(*args, **kwargs):
        raise AssertionError("unknown skills must not launch Pi")

    monkeypatch.setattr(agent.subprocess, "run", should_not_start)
    with pytest.raises(agent.PiAgentError, match="skill is not available"):
        asyncio.run(agent.run_skill("read-files", "do something"))


def test_run_skill_reports_missing_node_or_pi_dependency(monkeypatch):
    def missing_node(*args, **kwargs):
        raise FileNotFoundError("node")

    monkeypatch.setattr(agent.subprocess, "run", missing_node)
    with pytest.raises(agent.PiAgentError, match="Node.js is required"):
        asyncio.run(agent.run_skill("ship-30-for-30-essay", "write an essay"))


def test_run_skill_reports_agent_failure_usefully(monkeypatch):
    def fake_subprocess_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, b"", b"Ollama connection refused")

    monkeypatch.setattr(agent.subprocess, "run", fake_subprocess_run)
    with pytest.raises(agent.PiAgentError, match="Ollama connection refused"):
        asyncio.run(agent.run_skill("ship-30-for-30-essay", "write an essay"))


def test_run_skill_reports_timeout_and_process_start_errors(monkeypatch):
    def timed_out(command, **kwargs):
        raise subprocess.TimeoutExpired(command, timeout=agent.RUN_TIMEOUT_SECONDS)

    monkeypatch.setattr(agent.subprocess, "run", timed_out)
    with pytest.raises(agent.PiAgentError, match="timed out after 300 seconds"):
        asyncio.run(agent.run_skill("ship-30-for-30-essay", "write an essay"))

    def loop_unsupported(command, **kwargs):
        raise NotImplementedError("subprocess support is unavailable")

    monkeypatch.setattr(agent.subprocess, "run", loop_unsupported)
    with pytest.raises(agent.PiAgentError, match="Could not start.*subprocess support is unavailable"):
        asyncio.run(agent.run_skill("ship-30-for-30-essay", "write an essay"))


def test_worker_thread_process_runs_under_selector_event_loop():
    async def run():
        return await agent._run_process(
            [sys.executable, "-c", "import sys; data=sys.stdin.buffer.read(); sys.stdout.buffer.write(data); sys.stderr.write('captured stderr')"],
            b"task text; this remains stdin data",
        )

    loop = asyncio.SelectorEventLoop()
    try:
        completed = loop.run_until_complete(run())
    finally:
        loop.close()
    assert completed.returncode == 0
    assert completed.stdout == b"task text; this remains stdin data"
    assert completed.stderr == b"captured stderr"


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


def test_agent_api_returns_useful_subprocess_start_failure(monkeypatch):
    from fastapi.testclient import TestClient

    async def failed_run_skill(name, task):
        raise agent.PiAgentError("Could not start the Pi Coding Agent process: access denied")

    monkeypatch.setattr(agent, "run_skill", failed_run_skill)
    with TestClient(main.app) as client:
        response = client.post("/api/agent/skills/ship-30-for-30-essay/run", json={"task": "Write about interviews"})
    assert response.status_code == 503
    assert response.json()["detail"] == "Could not start the Pi Coding Agent process: access denied"
