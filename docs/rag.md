# Transcript ingestion and retrieval

The assistant indexes a local transcript repository copied into `data/sources/` (or the directory configured by `RAG_SOURCE_DIR`). It recursively reads `.md` files and YAML front matter such as `title`, optional `guest`, and optional `youtube_url`/source URL. The relative source filename is retained as source identity. A URL is cited only when present in transcript metadata.

## Setup

1. Start PostgreSQL with `docker compose up -d db`.
2. Install Python dependencies from `requirements.txt`.
3. Set `DATABASE_URL` if needed; its default is `postgresql+psycopg://lenny_user:local_dev_password@127.0.0.1:5433/lenny_assistant`.
4. Copy transcript Markdown files into the source directory.
5. Run `python -m backend.ingest`.

Transcript indexing and chat retrieval do not call an embedding model. Ollama `qwen2.5:3b` is used for answer generation after passages are retrieved.

## Chunking and indexing

Transcripts are split into overlapping 1,000-character sections with 150 characters of overlap by default. Each chunk retains episode title, guest when available, source filename and relative identity, original URL when available, chunk index, and a content hash. Chunks are indexed by a PostgreSQL GIN expression index using English full-text search over title, guest and chunk text. No embeddings are generated for the transcript collection; the legacy JSON embedding field is retained for schema compatibility and new transcript rows store an empty array.

The first run creates the manifest table, adds metadata columns to `source_document_chunks` if missing, and creates indexes without dropping existing rows. This setup is additive but is not managed by a migration framework.

## Resume and refresh

The manifest stores a SHA-256 hash and indexed chunk count per relative source identity. Each file is committed separately. Unchanged files are skipped; if a file changes, only its chunks are replaced, with the manifest update in the same transaction. Parse or indexing failures are counted per file and leave the prior successfully indexed version intact. Progress is printed every 25 files and at completion. To refresh, replace local Markdown files and rerun ingestion. Files removed from disk are not automatically removed from the database.

## Grounded chat and citations

`POST /api/chat` uses `plainto_tsquery`/PostgreSQL full-text rank with the GIN index to retrieve up to five passages. The default minimum rank is `0.01`; change it with `RAG_FTS_MIN_RANK`. Retrieved excerpts are supplied to the provider selected by `LLM_PROVIDER` as evidence for factual transcript answers. If no passage meets the threshold, the API refuses without calling the model.

The response includes `reply`, selected `provider`, `model` and `citations`. Each citation contains episode title, guest, filename, relative source identity, original URL when present, chunk index, relevance rank, and the exact excerpt used. Conversation history remains in PostgreSQL; previous turns provide context and are explicitly excluded as evidence for source-collection facts.

## Run and verify

Start the API with `uvicorn backend.main:app --reload`. The Python tests require the configured PostgreSQL database. On Windows, run `python -m pytest -q -p no:cacheprovider` from the project virtual environment. See the root README for full setup and test commands.
