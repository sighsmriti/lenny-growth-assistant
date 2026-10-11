# Lenny Growth Assistant

A local FastAPI chat assistant with PostgreSQL-backed sessions and grounded search over a local copy of Lenny's Podcast Markdown transcripts.

## Start

1. Start PostgreSQL: `docker compose up -d db`
2. Install dependencies in the virtual environment: `python -m pip install -r requirements.txt`
3. Copy transcript `.md` files into `data/sources/` and index them: `python -m backend.ingest`
4. Start the API: `uvicorn backend.main:app --reload`

The API uses local Ollama `qwen2.5:3b` for chat. Transcript indexing and retrieval use PostgreSQL full-text search and do not embed every transcript chunk.

See [docs/rag.md](docs/rag.md) for transcript metadata, chunking, indexing, incremental refresh, grounding, citations, and test commands.

## Pi agent and Ship 30 for 30 essay skill

The assignment-approved Pi Coding Agent SDK is integrated through `/api/agent/skills` and `/api/agent/skills/ship-30-for-30-essay/run`. It uses the local Ollama `qwen2.5:3b` model through Ollama's OpenAI-compatible `/v1` endpoint. This workflow is separate from `/api/chat`; the existing PostgreSQL chat sessions and grounded RAG response are unchanged.

One-time setup on Windows (Node.js 22.19+ is required by the current Pi release):

```powershell
cd agent-service
npm.cmd install --ignore-scripts
cd ..
```

Start FastAPI as usual. In Swagger, list skills with `GET /api/agent/skills`, then call `POST /api/agent/skills/ship-30-for-30-essay/run` with `{"task":"Write an essay arguing that customer interviews should start with recent behavior. Use no invented personal anecdotes."}`. The skill is stored at `.pi/skills/ship-30-for-30-essay/SKILL.md` and targets a 1,250-word essay. Ollama must be running with `qwen2.5:3b` available. No Anthropic API key is needed.

Run the test suite with:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

## Artifact viewer

The artifact viewer is a small static UI served by FastAPI at `http://127.0.0.1:8000/viewer`. After starting PostgreSQL and the backend as above, open that URL in a browser. No frontend build step is required. On a Windows development setup, start the API with:

```powershell
docker compose up -d db
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload
```

The Ship 30 skill endpoint saves its generated Markdown as a PostgreSQL artifact and returns `artifact_id`; the viewer lists it after **Refresh list**. Artifacts can also be created using `POST /api/artifacts` with `title`, `format` (`markdown`, `html`, or `css`), and `content`. Browse `GET /api/artifacts` and `GET /api/artifacts/{id}` for the API. The two sample buttons load clearly marked, unsaved examples, including HTML that tries to execute script and reach the parent window.

Markdown is rendered as CommonMark with raw HTML disabled and the resulting tags, attributes, and URL schemes allowlisted. HTML and CSS source is never inserted into the application DOM; preview runs in an iframe with an empty `sandbox` attribute and CSP that disables scripts, network connections, forms, embedded frames, and objects. The preview permits inline styles, and data images, so supplied CSS can render. This is a local development viewer, not a complete content moderation or production isolation boundary.

Run the viewer interaction checks after npm setup in `agent-service`:

```powershell
npm.cmd run test:viewer
npm.cmd run viewer:check
npm.cmd run agent:check
```

With FastAPI running on port 8000 and Google Chrome installed at its default Windows path, run the browser-level check:

```powershell
npm.cmd run test:viewer:browser
```

Set `$env:ARTIFACT_VIEWER_URL` to use another viewer URL, or `$env:CHROME_PATH` if Chrome is installed elsewhere.

The UI tests verify Markdown preview, source/preview switching, empty state, and sandbox/CSP attributes. The Chromium check exercises the served viewer, loads the local samples, clicks the sample's script handler, and verifies it cannot set `window.parent.__artifactViewerPwned` or read the parent document. No transcript files or database exports are included in these samples.
