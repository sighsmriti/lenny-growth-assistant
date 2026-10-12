# Architecture: Lenny Growth Assistant

## Runtime topology

```text
Browser
  ├─ /viewer and /viewer-assets/* (static artifact UI)
  └─ /api/* (FastAPI)
       ├─ PostgreSQL (sessions, messages, transcript chunks/manifests, artifacts)
       ├─ Ollama /api/chat (grounded chat; qwen2.5:3b)
       └─ Node Pi runner (essay skill) ── Ollama-compatible local model

CLI: python -m backend.ingest ── Markdown files under data/sources/ ── PostgreSQL
Docker Compose currently starts PostgreSQL only.
```

## Database schema

SQLAlchemy models in `backend/main.py`:

| Table | Key fields and relationships |
|---|---|
| `chat_sessions` | UUID primary key; created/updated timestamps; one-to-many messages with delete cascade |
| `chat_messages` | Integer key; session UUID foreign key; role, text content, timestamp; indexed session FK |
| `source_document_chunks` | Integer key; episode title, filename, optional URL/guest/source identity, chunk index, content, legacy JSON embedding field, unique content hash. GIN expression index covers English `to_tsvector(title, guest, content)`; filename/source identity/content hash also indexed. |
| `transcript_sources` | Relative source identity primary key; filename, file SHA-256, chunk count, update timestamp |
| `artifacts` | UUID key; title, format (`markdown`, `html`, `css`), content and creation timestamp; format/time indexed |

At startup, additive schema setup creates tables, adds guest/source identity columns if absent and creates indexes. There is no migration framework. Session user metadata is not implemented.

## API surface

FastAPI exposes OpenAPI docs at `/docs`.

| Method and path | Purpose |
|---|---|
| `GET /health` | API liveness |
| `GET /health/db` | PostgreSQL connectivity check |
| `POST /api/sessions` | Create a session |
| `GET /api/sessions` | List sessions |
| `GET /api/sessions/{session_id}/messages` | Read ordered messages for a session |
| `GET /api/config` | Report the selected LLM provider, model and readiness without exposing secrets |
| `POST /api/chat` | Persist user message, retrieve evidence, call the selected provider, persist answer; returns citations |
| `GET /api/agent/skills` | Discover project Pi skills |
| `POST /api/agent/skills/{skill_name}/run` | Execute a known skill; save generated Markdown artifact |
| `POST /api/artifacts` | Create an artifact |
| `GET /api/artifacts` | List artifact metadata, newest first |
| `GET /api/artifacts/{artifact_id}` | Read artifact and sanitized Markdown HTML when applicable |
| `GET /viewer` | Serve the static viewer |

Pydantic validates non-empty messages/tasks and artifact title, format and content size. FastAPI supplies standard validation responses. Missing session/artifact IDs return 404. Chat model failures return 502; the agent bridge maps known Pi errors to 503. There is no API authentication or per-user authorization.

## Ingestion and retrieval

`python -m backend.ingest` recursively enumerates `.md` under `RAG_SOURCE_DIR` (default `data/sources`). Transcript parsing reads YAML front matter for title, guest and URL aliases. Source identity is the path relative to the root. Text is normalized and split into 1,000-character chunks with 150-character overlap by default. Per-file SHA-256 manifest entries allow unchanged files to be skipped; changed chunks and manifest update commit in one transaction. Failures are counted and reported while prior indexed version is preserved.

Retrieval uses PostgreSQL English full-text search (`plainto_tsquery`, `ts_rank_cd`, GIN index), removes common question-framing terms, applies `RAG_FTS_MIN_RANK` (default `0.01`) and returns up to five passages. There are no transcript embeddings in this retrieval path. The JSON `embedding` field remains for compatibility and new chunks store `[]`. Retrieved passages are put in the current user prompt as evidence; conversation history is context only. No results cause a fixed refusal without an Ollama generation request. Citation entries correspond to retrieved passages and include exact excerpts and metadata. A file removed from disk is not automatically removed from the index.

## Pi agent and skill routing

`backend.agent` discovers `.pi/skills/*/SKILL.md` files with valid YAML front matter. It validates the skill name against discovered skills, then launches `agent-service/run-skill.mjs` using `PI_NODE_EXECUTABLE` (default `node`), JSON over stdin/stdout, and a 300-second timeout. The Node runner initializes Pi Coding Agent SDK with an in-memory credential store, local model configuration from `agent-service/models.json`, no tools, and an in-memory session; it prompts `/skill:<name> <task>`. The current essay skill is `ship-30-for-30-essay`. Successful output is saved as a Markdown artifact. This skill endpoint is independent of `/api/chat` and does not automatically ground essay claims in a RAG query.

## Model configuration

`LLM_PROVIDER` selects `ollama` (default) or `openai`. Chat uses `OLLAMA_URL`/`OLLAMA_MODEL` for local inference and the official OpenAI Python SDK with `OPENAI_API_KEY`/`OPENAI_MODEL` for cloud inference. The key is read only from the process environment and is not included in API output or error text. `GET /api/config` returns provider, model and a readiness boolean. Invalid providers or a missing OpenAI key return a sanitized 503; provider outages return 502; request timeouts return 504. There is no automatic fallback.

Pi reads the same `LLM_PROVIDER`. `agent-service/models.json` defines both Ollama and OpenAI, with the OpenAI credential referenced as `$OPENAI_API_KEY` for Pi's documented environment interpolation; the key is inherited by the child process and is not written into the file. The included Pi OpenAI model is `gpt-4o-mini`; another Pi model must first be registered there. Pi returns a 503 on configuration or execution failure. Pi's essay prompt is still a separate workflow and does not automatically retrieve RAG evidence.

## Security and privacy

No credentials are required for the default local configuration. OpenAI mode requires `OPENAI_API_KEY`; it must be provided as a process environment variable and is never returned by the configuration endpoint. Do not expose the unauthenticated API publicly. SQLAlchemy parameterization is used for query construction. Chat and transcript data persist in PostgreSQL. Markdown HTML is disabled and output is allowlisted via `bleach`. Markup artifacts are rendered in a sandboxed iframe with restrictive CSP; scripts, network, forms, nested frames and objects are disabled, while inline styles and data images are permitted. The viewer is not a production isolation boundary. No structured redaction, authentication, authorization or retention policy is implemented.

## Deployment and operations

`compose.yaml` provides PostgreSQL 17 on host port 5433 with a named data volume and health check. FastAPI, Ollama and Pi run outside Compose. `/health` is liveness only; `/health/db` checks the database. Chat uses a 180-second HTTP timeout and Pi has a 300-second process timeout. Ingestion reports per-file progress and totals. Structured logs, metrics, tracing, alerts, automatic restart policies for application services and cloud deployment configuration are absent.
