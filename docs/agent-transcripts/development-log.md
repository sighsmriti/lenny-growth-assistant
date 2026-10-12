# Reconstructed development log

> This is a concise development summary, not a verbatim transcript. It is based on the repository, its Git history, and results visible in the prior development conversation. No original coding-agent exports are available in the repository.

## Development journey

### Environment and PostgreSQL setup

**Objective and implementation.** Establish a repeatable local database and a clear connection check. `compose.yaml` runs PostgreSQL 17 on host port 5433, persists data in a named volume, and uses `pg_isready` as its health check. FastAPI creates its SQLAlchemy engine from `DATABASE_URL` and exposes `/health/db`.

**Debugging and verification.** The source and history contain no specific PostgreSQL failure-and-fix record. The initial application commit includes the Compose configuration and database-backed application.

### FastAPI sessions and persistence

**Objective and implementation.** Preserve independent conversation history. `ChatSession` and `ChatMessage` store session IDs, roles, content, and timestamps in PostgreSQL. The API creates and lists sessions, reads ordered messages, validates the session on chat requests, and persists user messages and successful assistant replies.

**Verification.** `tests/test_sessions.py` covers session creation, message history, citations through chat, and invalid session IDs. The code and tests are part of the initial application commit.

### Transcript ingestion and RAG

**Objective and implementation.** Make transcript answers traceable to source material. `backend/ingest.py` reads Markdown transcripts, records relative source identities and content hashes, skips unchanged files, and replaces changed chunks and manifest entries transactionally. `backend/rag.py` chunks text and uses PostgreSQL English full-text search with `plainto_tsquery`, `ts_rank_cd`, and a GIN index. Chat supplies retrieved excerpts as evidence, returns citation metadata, and refuses unsupported questions without calling a model when retrieval is empty. Transcript retrieval does not generate embeddings; the legacy embedding column is retained with empty arrays for these chunks.

**Verification.** `tests/test_transcript_rag.py` covers incremental ingestion, ranking, citations, and empty retrieval. `tests/test_rag_embeddings.py` also covers retained embedding helpers. These tests were included in the initial application commit.

### Pi Coding Agent and Ship 30 for 30 skill

**Objective and implementation.** Provide a reusable essay workflow through the Pi Coding Agent SDK. `backend/agent.py` discovers valid skill files and starts `agent-service/run-skill.mjs`; the runner loads the Ship 30 for 30 skill, uses an in-memory session, disables tools, and enforces a 300-second process timeout. Successful essays are saved as Markdown artifacts. The skill is invoked through its API route, separately from chat.

**Verification.** `tests/test_agent.py` covers skill discovery, runner behavior, errors, and the API route. A model configuration check reported `model-found true` and `model openai gpt-4o-mini openai-completions`; this verifies Pi can load the configured model, not that it can complete a live OpenAI request.

### Artifact viewer and security

**Objective and implementation.** Let users inspect generated artifacts while treating markup as untrusted. The standalone `/viewer` page lists saved artifacts and offers Preview/Source modes plus local samples. Markdown is rendered as CommonMark with raw HTML disabled and output sanitized through an allowlist. HTML/CSS preview runs in an iframe with an empty sandbox and restrictive CSP.

**Verification.** `tests/test_artifacts.py` covers Markdown sanitization and artifact APIs. The Node viewer tests cover empty state, preview/source switching, and sandbox configuration; a Chromium test checks that sample scripts cannot reach the parent page. The viewer is not integrated into a chat composer.

### Ollama/OpenAI provider configuration

**Objective and implementation.** Keep the local demo as the default while allowing cloud selection through environment configuration. `LLM_PROVIDER` selects Ollama (default) or OpenAI. Chat uses the official `AsyncOpenAI` client when OpenAI is selected; `OPENAI_API_KEY` is read from the environment and is not returned by `/api/config`. Chat and Pi use the selected provider. Missing configuration, provider failures, and timeouts produce sanitized errors; no automatic fallback is implemented. Pi's OpenAI model is registered in `agent-service/models.json` using an environment-variable reference.

**Verification.** `tests/test_llm.py` covers provider selection, missing keys, provider errors, timeouts, public configuration, and Pi credential configuration. Commit `fb3030c15476a21a2a7817b284926d242765c2ba` adds the provider implementation and related tests and documentation.

## Testing, debugging, and verification

The available prior conversation records these results; they were not rerun for this documentation edit, and no standalone run logs are checked in:

- Python suite: `31 passed in 2.66s`.
- Node viewer suite: 4 tests passed; Chromium viewer test: 1 test passed. Agent and viewer syntax checks completed without reported errors.
- During one browser run, the test reported `page.goto: net::ERR_CONNECTION_REFUSED at http://127.0.0.1:8000/viewer`. The rerun started FastAPI for the test and passed.
- A provider test initially failed with `FakeClient.__init__() got an unexpected keyword argument 'max_retries'`. The mock was updated to accept the SDK option, after which the reported Python suite passed.
- The Pi model check above loaded configuration only. No live OpenAI inference was run.

Git history records the delivered changes, not the intermediate development process:

- `1d68753ae5a21a95d929a099693340be0c83bd2c` — `Build Lenny Growth Assistant` (application, tests, Pi skill, and viewer).
- `fb3030c15476a21a2a7817b284926d242765c2ba` — `Add configurable cloud and local LLM providers`.

## Current limitations

- No original agent transcript exports are available; this file is a summary, not a substitute for them.
- The artifact viewer is a separate page, not an integrated chat/artifact workspace.
- Essay generation does not automatically retrieve RAG evidence.
- OpenAI is configured but live inference has not been verified with a real key.
- The UI has no provider selector; provider selection is through environment variables.
