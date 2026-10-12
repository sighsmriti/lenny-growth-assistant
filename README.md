# Lenny Growth Assistant

A local FastAPI service for grounded Q&A over a local copy of Lenny's Podcast Markdown transcripts, plus a Pi Coding Agent essay skill and a separate artifact viewer. This is a take-home prototype; the current app uses local Ollama only and does not include an integrated chat frontend.

## Architecture at a glance

- FastAPI provides session, chat, agent-skill and artifact APIs.
- PostgreSQL stores sessions, messages, transcript chunks/source manifests and artifacts.
- Transcript search uses PostgreSQL English full-text search and a GIN index. It does not create embeddings.
- Ollama serves `qwen2.5:3b` for chat and, by default, the Pi skill workflow.
- `/viewer` is a static artifact browser. It is separate from chat and skill invocation.
- See [docs/architecture.md](docs/architecture.md), [docs/PRD.md](docs/PRD.md), [docs/design.md](docs/design.md), and [docs/rag.md](docs/rag.md).

## Prerequisites

- Windows PowerShell examples below; equivalent Python, Docker and npm commands work on other platforms.
- Python 3.11+ and Docker Desktop with Compose.
- Ollama installed and running; pull `qwen2.5:3b` for chat and the essay skill.
- Node.js 22.19+ and npm for the Pi skill.
- A local Markdown transcript collection. This project does not fetch or package Lenny's transcripts.
- For viewer tests: install agent-service npm dependencies. For the browser-level viewer test: Google Chrome at the default Windows path, or set `CHROME_PATH`.

## Setup

From the repository root in PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# Start PostgreSQL; Compose reads its own local values from compose.yaml.
docker compose up -d db
ollama pull qwen2.5:3b
# Install Pi SDK and viewer test dependencies.
Push-Location agent-service
npm.cmd install
Pop-Location
```

The default database URL and Ollama URL are safe local development values. The application reads configuration from process environment variables; it does not load `.env` itself, and Compose currently does not use that file. To override a value in PowerShell, set it in the shell before starting the process, for example:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://lenny_user:local_dev_password@127.0.0.1:5433/lenny_assistant"
$env:OLLAMA_URL = "http://localhost:11434"
```

`DATABASE_URL` defaults to the same local PostgreSQL service configured by Compose. Change the Compose database credentials and URL together if you use different local credentials. `.env.example` documents supported variables; it contains no real secrets.

## Add and index transcripts

Copy the transcript repository's Markdown files, including YAML front matter where available, into `data/sources/`. Then run:

```powershell
.\.venv\Scripts\python.exe -m backend.ingest
```

Ingestion recursively reads `.md` files, extracts title/guest/source URL metadata, chunks with overlap, and incrementally skips unchanged files. It stores each file's relative identity and SHA-256 manifest in PostgreSQL. Removed files are not automatically deleted from the index. See [docs/rag.md](docs/rag.md) for the details.

## Run the API and viewer

In one PowerShell window:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload
```

Then open:

- API docs: http://127.0.0.1:8000/docs
- Liveness: http://127.0.0.1:8000/health
- Database health: http://127.0.0.1:8000/health/db
- Artifact viewer: http://127.0.0.1:8000/viewer

Create a session with `POST /api/sessions`, then submit `session_id` and `message` to `POST /api/chat`. Responses include a `citations` list with source excerpt and metadata, or an explicit unsupported answer when no passage meets the retrieval threshold.

### Pi essay skill

The skill endpoint is separate from `/api/chat`. List available skills with `GET /api/agent/skills`, then run `POST /api/agent/skills/ship-30-for-30-essay/run` with JSON such as:

```json
{"task":"Write an essay arguing that customer interviews should start with recent behavior. Do not invent personal anecdotes."}
```

The runner uses Pi Coding Agent SDK, local Ollama and `.pi/skills/ship-30-for-30-essay/SKILL.md`; it saves successful output as a Markdown artifact. Ollama and Node.js must be available. No Anthropic key is used or required.

### Artifact viewer and API

The viewer lists artifacts saved through `POST /api/artifacts` or the Pi skill endpoint. Use **Refresh list** to reload. Markdown is rendered as allowlisted CommonMark with raw HTML disabled. HTML/CSS is displayed in an iframe with an empty sandbox and restrictive CSP; inline styles and data images are allowed. The sample buttons show unsaved local examples. This is a local development safeguard, not a production security boundary.

Supported artifact formats are `markdown`, `html`, and `css`. The viewer is a separate page: the current app has no chat composer, no automatic chat-to-artifact action, and no inline skill controls.

## Model configuration

Chat and the Pi essay skill support `ollama` and `openai`. `LLM_PROVIDER` selects the provider and defaults to `ollama`; Ollama remains available without a cloud key. Ollama uses `OLLAMA_URL` and `OLLAMA_MODEL` (default `qwen2.5:3b`). OpenAI uses the official Python SDK, `OPENAI_API_KEY`, and `OPENAI_MODEL` (default `gpt-4o-mini`). Set environment variables in the shell before starting the app; `.env` is not loaded automatically.

For OpenAI in PowerShell:

```powershell
$env:LLM_PROVIDER = "openai"
$env:OPENAI_API_KEY = "your-key"
# Optional: $env:OPENAI_MODEL = "gpt-4o-mini"
```

Restart the API after changing shell configuration. `GET /api/config` reports the selected provider, model and whether its configuration is ready; it never returns the key. Chat responses also identify provider and model. The Pi runner uses the same selected provider; its OpenAI model must be registered in `agent-service/models.json` (the included model is `gpt-4o-mini`). Missing keys return a configuration error, provider failures return 502, and timeouts return 504. There is no automatic fallback to another provider. For the local demo, set `LLM_PROVIDER=ollama` or leave it unset. See [docs/architecture.md](docs/architecture.md) for details.

To switch back to local Ollama, set `$env:LLM_PROVIDER = "ollama"` and start the API from that shell. OpenAI mode sends retrieved transcript excerpts and prompts to OpenAI; choose it only when that data handling is acceptable.

## Tests and manual UI check

Run the Python suite (PostgreSQL must be running and configured):

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Run the Node agent and viewer checks after installing agent-service dependencies:

```powershell
Push-Location agent-service
npm.cmd run agent:check
npm.cmd run viewer:check
npm.cmd run test:viewer
npm.cmd run test:viewer:browser
Pop-Location
```

The browser check requires Chrome. Manual UI check: open `/viewer`; refresh the list; select a saved artifact; switch Preview/Source; try both local samples; verify the HTML sample cannot change the parent page; resize to a narrow viewport; and keyboard through the controls. The automated UI checks cover viewer state and sandbox/CSP behavior, not a full accessibility or responsive audit.

## Troubleshooting

- **Database connection refused:** run `docker compose up -d db`; check `docker compose ps` and `GET /health/db`. Default host port is 5433.
- **No transcripts indexed:** confirm Markdown files exist under `data/sources/` (or set `RAG_SOURCE_DIR` before starting ingestion), then rerun `python -m backend.ingest`.
- **No answer/citations:** retrieval is PostgreSQL full-text search, not semantic embedding search. Check indexed terms and `RAG_FTS_MIN_RANK`; lower values admit weaker matches.
- **Ollama unavailable/model missing:** start Ollama, verify `OLLAMA_URL`, and run `ollama pull qwen2.5:3b`.
- **Pi skill fails:** verify Node.js is available, run `npm.cmd install` in `agent-service`, and confirm the local model is installed. `PI_NODE_EXECUTABLE` can point to a non-default Node executable.
- **Viewer list fails:** ensure FastAPI and PostgreSQL are available. Inspect the browser alert and API response.
- **Browser viewer test cannot start:** install Chrome or set `CHROME_PATH`; set `ARTIFACT_VIEWER_URL` if the API is not at its default address.

## Known limitations and assignment handoff gaps

- No integrated chat UI or chat-driven artifact generation; chat and Pi skills are API workflows and the viewer is separate.
- No authentication, user metadata, or per-user authorization.
- No structured logs, metrics, tracing, or production deployment configuration.
- Compose starts PostgreSQL only; Ollama, FastAPI and Node/Pi run on the host.
- Full-text search can miss semantically related passages; generated answer quality is not automatically evaluated.
- No automatic cleanup for transcript files removed from the source directory.
- The repository snapshot has no genuine coding-agent transcripts; see [docs/agent-transcripts/README.md](docs/agent-transcripts/README.md) for how to add original logs.
- The assignment requires a camera-on 2–3 minute demo video upload and public repository submission. These are external candidate actions and are not represented as complete here.
