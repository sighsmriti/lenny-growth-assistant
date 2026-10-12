"""Small bridge from FastAPI to the Pi Coding Agent SDK service."""
import asyncio
import json
import os
import re
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

    try:
        process = await asyncio.create_subprocess_exec(
            os.getenv("PI_NODE_EXECUTABLE", "node"), str(PI_RUNNER),
            cwd=PROJECT_ROOT,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise PiAgentError("Node.js is required to run the Pi Coding Agent. Install Node.js and agent-service dependencies.") from exc

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(json.dumps({"skill": name, "task": task}).encode("utf-8")),
            timeout=RUN_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise PiAgentError("The local Pi agent timed out. Check the selected model provider and try again.") from exc

    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        if "Cannot find package" in detail or "ERR_MODULE_NOT_FOUND" in detail:
            raise PiAgentError("Pi Coding Agent dependencies are missing. Run npm install in agent-service.")
        raise PiAgentError(f"The Pi agent failed: {detail[-1000:] or 'no error details returned'}")

    try:
        result: Any = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PiAgentError("The Pi agent returned malformed output.") from exc
    reply = result.get("reply") if isinstance(result, dict) else None
    if not isinstance(reply, str) or not reply.strip():
        raise PiAgentError("The Pi agent returned an empty response.")
    return reply.strip()
