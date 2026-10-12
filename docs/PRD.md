# Product requirements: Lenny Growth Assistant

## Discovery brief

### User and problem
The primary user is a product or growth practitioner who wants to turn lessons from Lenny's Podcast transcripts into a practical answer or a reusable written draft. Today they must search long transcripts manually, judge which passages support an idea, and then organize the result. The assistant is intended to make that workflow faster while keeping source evidence visible.

### Success metric
For an evaluation set of questions with known transcript evidence, target at least 80% of answers to include a citation whose excerpt supports the answer, and 100% of questions with no retrieved passage to return the explicit unsupported-answer response without calling the model. Measure manually for this take-home; the repository does not yet contain an evaluation harness or telemetry.

### Assumptions
- The user has a local copy of the Lenny transcript repository and may place Markdown files under `data/sources/`; the project does not download or redistribute transcripts.
- The first demo is a single-machine, single-team local application. PostgreSQL is the durable store; authentication and multi-tenant controls are outside this implementation.
- Ollama with `qwen2.5:3b` is the supported chat and Pi model. The essay skill is a separate agent workflow, not a chat mode.
- Transcript content is treated as the source of truth for factual answers. Conversation history supplies context but is not evidence.
- A lightweight artifact viewer and explicit skill endpoint are sufficient for demonstrating generated artifacts; full chat-to-artifact orchestration is outside current scope.

### Scope choices
Included: FastAPI endpoints for sessions, chat, artifacts and Pi skills; PostgreSQL persistence; Markdown transcript ingestion with incremental refresh; PostgreSQL full-text retrieval and citations; selectable local Ollama or OpenAI generation; a Ship 30 for 30 essay skill; a static artifact viewer with source/preview modes and isolated HTML/CSS rendering.

Excluded: authentication, authorization and user metadata; transcript acquisition; a polished integrated chat composer that routes requests to artifact generation; production deployment, automated quality evaluation, streaming, deletion/retention controls, and production observability. These remain material gaps against the assignment.

## User flows

1. Start PostgreSQL, Ollama and the API; create a session with `POST /api/sessions`.
2. Put transcript Markdown files in `data/sources/`, run `python -m backend.ingest`, then send a question to `POST /api/chat` with the session ID. The reply includes citations or an unsupported response.
3. Continue in the same session; prior turns are passed as context while new factual claims are grounded in newly retrieved passages.
4. List the available Pi skills, then run `ship-30-for-30-essay` with a task. The generated essay is also saved as a Markdown artifact.
5. Open `/viewer`, refresh the artifact list, and inspect a saved artifact in preview or source mode. Local sample artifacts can be previewed without saving.
6. Create or retrieve Markdown, HTML or CSS artifacts through the artifact API.

## Acceptance criteria

- A session has a UUID and timestamps; messages are persisted and scoped to it. Unknown session and artifact IDs return 404; invalid request data is rejected by FastAPI validation.
- Transcript ingestion parses front matter, splits text into overlapping chunks, and stores source identity, title, guest, URL, file hash and chunk index. An unchanged file is skipped; a changed file is replaced transactionally.
- Chat retrieves up to five transcript chunks using PostgreSQL English full-text search, returns source metadata and excerpts, and refuses when no result meets the minimum rank. The selected Ollama or OpenAI chat provider receives retrieved passages as source evidence.
- Pi skill discovery returns valid project skills. Running the essay skill uses Pi with the selected provider (Ollama by default), has a five-minute timeout, and stores the answer as an artifact.
- Artifact preview distinguishes Markdown from HTML/CSS. Markdown rendering disables raw HTML and allowlists output. HTML/CSS runs in a sandboxed iframe with CSP restrictions; source mode displays text.
- `/health` reports API liveness and `/health/db` checks PostgreSQL connectivity.
- Existing automated tests pass when the PostgreSQL service and agent-service dependencies required by the test environment are available.

## Risks and trade-offs

| Risk | Current handling | Remaining trade-off |
|---|---|---|
| Unsupported or fabricated answers | Full-text retrieval, evidence-only prompt, citations, explicit empty-result refusal | Retrieval can miss relevant passages; generated prose can still misstate evidence. No automated grounding evaluation exists. |
| Latency | Local Ollama avoids per-request cloud charges; chat timeout is 180 seconds and agent timeout is 300 seconds | Small local model quality and speed depend on hardware; no streaming or cancellation. |
| Cost and data leakage | Ollama is the default; OpenAI is opt-in through `LLM_PROVIDER` | In OpenAI mode, retrieved transcript excerpts and prompts leave the machine; usage may incur provider charges. No authentication or access controls exist. |
| Unsafe artifacts | Sanitized CommonMark and isolated iframe/CSP for HTML/CSS | Local viewer is not a production isolation or moderation boundary; CSS and data images are allowed. |
| Ingestion errors | Per-file transactions, manifest hashes, resumable indexing and error counts | No scheduled refresh, source deletion reconciliation, or admin UI. |
| Operability | Health endpoints and user-facing dependency errors | Structured logs, metrics, tracing, alerting and broad dependency-failure tests are not implemented. |

## Implementation plan and remaining requirements

1. Complete and verify the local demo and handoff documentation (current work).
2. Add a chat UI that connects sessions, grounded chat and artifact generation/viewing in one workflow; current viewer is a separate static page.
3. Add structured operational logs and a fresh-clone setup path; current Compose file starts PostgreSQL only.
4. Record a genuine 2–3 minute camera-on demo and upload it; this must be done by the candidate.
5. Publish the repository and submit the form; neither is performed by this local codebase.
