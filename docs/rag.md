# Transcript ingestion and retrieval

The assistant indexes the local Lenny's Podcast transcript repository copied into `data/sources/`. It recursively reads `.md` transcript files and their YAML front matter (`title`, optional `guest`, and optional `youtube_url`/source URL). The exact source filename and relative source identity are retained. A URL is only cited when it exists in the transcript metadata.

## Setup

1. Start PostgreSQL with `docker compose up -d db`.
2. Activate `.venv` and install dependencies with `python -m pip install -r requirements.txt`.
3. Set `DATABASE_URL` if needed. The default is `postgresql+psycopg://lenny_user:local_dev_password@127.0.0.1:5433/lenny_assistant`.
4. Copy or clone the transcript Markdown files into `data/sources/`.

No embedding model is needed for transcript ingestion or question retrieval. The existing Ollama `qwen2.5:3b` chat model is used only after relevant passages have been retrieved.

## Chunking and indexing

Run `python -m backend.ingest`. Transcripts are split into overlapping 1,000-character sections with 150 characters of overlap. Each chunk retains episode title, guest when available, source filename and identity, original URL when available, chunk index, and a content hash. Chunks are indexed by a PostgreSQL GIN expression index using English full-text search over title, guest, and chunk text. No embeddings are generated for the transcript collection.

The first run adds a `transcript_sources` manifest table, metadata columns on `source_document_chunks`, and the GIN index. These are additive changes; existing rows and unrelated database tables are preserved. The old JSON embedding field remains for compatibility and new transcript chunks store an empty array there.

## Resume and refresh

The manifest stores the SHA-256 hash and indexed chunk count for each relative source identity. Each file is committed separately. An unchanged file is skipped before chunking; an interrupted run resumes from completed files. If a file changes, only chunks with that source identity are replaced, and the manifest is updated in the same transaction. Parse or indexing failures are counted per file, reported, and leave the previous successfully indexed version intact.

Progress is printed every 25 files and at completion. The final summary reports processed, skipped, updated, and failed file and chunk counts. Updated chunk counts represent the new chunks committed for changed files. To refresh, replace the local Markdown transcript and rerun `python -m backend.ingest`.

## Grounded chat and citations

`POST /api/chat` uses `websearch_to_tsquery`, `ts_rank_cd`, and the GIN index to retrieve the highest-ranking passages. The default minimum rank is `0.01`; change it with `RAG_FTS_MIN_RANK`. Retrieved excerpts are supplied to Ollama as the evidence for factual transcript answers. If no passage meets the threshold, the API refuses and says that the available transcripts do not support an answer.

The existing `reply`, `provider`, and `model` fields remain. The response's `citations` array contains episode title, guest, filename, relative source identity, original URL when present, chunk index, relevance rank, and the exact excerpt used. Conversation history remains in PostgreSQL; previous turns are context and are explicitly excluded as evidence for source-collection facts.

## Run and test

Start the API with `uvicorn backend.main:app --reload`. Run tests with `python -m pytest -q` (the session and transcript integration tests use the configured PostgreSQL database). On Windows, run `python -m pytest -q -p no:cacheprovider` from the activated `.venv`.
