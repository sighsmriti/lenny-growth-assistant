"""Small bridge from FastAPI to the Pi Coding Agent SDK service."""
import asyncio
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = PROJECT_ROOT / ".pi" / "skills"
PI_RUNNER = PROJECT_ROOT / "agent-service" / "run-skill.mjs"
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RUN_TIMEOUT_SECONDS = 300


class PiAgentError(RuntimeError):
    pass


async def _run_process(command: list[str], payload: bytes) -> subprocess.CompletedProcess[bytes]:
    """Run Pi outside the event-loop thread for Windows SelectorEventLoop compatibility.

    Uvicorn uses SelectorEventLoop for Windows reload/workers, and that loop
    does not implement asyncio subprocess transports. subprocess.run executes
    in a worker thread, so the FastAPI event loop remains responsive. A list
    argument vector and stdin JSON keep user task text out of the shell.
    """
    return await asyncio.to_thread(
        subprocess.run,
        command,
        cwd=PROJECT_ROOT,
        input=payload,
        capture_output=True,
        timeout=RUN_TIMEOUT_SECONDS,
        check=False,
        shell=False,
    )


def discover_skills() -> list[dict[str, str]]:
    """Return Pi-discoverable project skills that have valid frontmatter."""
    skills = []
    for path in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        try:
            raw = path.read_text(encoding="utf-8")
            match = re.match(r"\A---\s*\r?\n(.*?)\r?\n---\s*(?:\r?\n|\Z)", raw, re.S)
            metadata = yaml.safe_load(match.group(1)) if match else None
            name = metadata.get("name") if isinstance(metadata, dict) else None
            description = metadata.get("description") if isinstance(metadata, dict) else None
            if isinstance(name, str) and isinstance(description, str) and name and description:
                skills.append({"name": name, "description": description})
        except (OSError, yaml.YAMLError):
            continue
    return skills


async def run_skill(name: str, task: str) -> str:
    if not SKILL_NAME_RE.fullmatch(name) or not any(s["name"] == name for s in discover_skills()):
        raise PiAgentError("The requested agent skill is not available.")

    command = [os.getenv("PI_NODE_EXECUTABLE", "node"), str(PI_RUNNER)]
    payload = json.dumps({"skill": name, "task": task}).encode("utf-8")
    try:
        process = await _run_process(command, payload)
    except FileNotFoundError as exc:
        raise PiAgentError("Node.js is required to run the Pi Coding Agent. Install Node.js and agent-service dependencies.") from exc
    except subprocess.TimeoutExpired as exc:
        raise PiAgentError(f"The local Pi agent timed out after {RUN_TIMEOUT_SECONDS} seconds. Check the selected model provider and try again.") from exc
    except (NotImplementedError, OSError) as exc:
        raise PiAgentError(f"Could not start the Pi Coding Agent process: {exc}") from exc

    if process.returncode != 0:
        stderr = (process.stderr or b"").decode("utf-8", errors="replace").strip()
        stdout = (process.stdout or b"").decode("utf-8", errors="replace").strip()
        detail = stderr or stdout
        if "Cannot find package" in detail or "ERR_MODULE_NOT_FOUND" in detail:
            raise PiAgentError("Pi Coding Agent dependencies are missing. Run npm install in agent-service.")
        raise PiAgentError(f"The Pi agent failed: {detail[-1000:] or 'no error details returned'}")

    try:
        result: Any = json.loads(process.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PiAgentError("The Pi agent returned malformed output.") from exc
    reply = result.get("reply") if isinstance(result, dict) else None
    if not isinstance(reply, str) or not reply.strip():
        raise PiAgentError("The Pi agent returned an empty response.")
    return reply.strip()
