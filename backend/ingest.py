"""Resumable transcript indexing command: python -m backend.ingest"""
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete

from backend.main import (
    SessionLocal, SourceDocumentChunk, TranscriptSource, ensure_rag_schema,
)
from backend.rag import IngestStats, SOURCE_DIR, prepare_transcript_chunks, source_files


def ingest_paths(paths: list[Path], source_root: Path = SOURCE_DIR) -> IngestStats:
    """Index each file transactionally; completed files are resumable by content hash."""
    stats = IngestStats()
    root = source_root.resolve()
    for path in paths:
        chunk_count = 0
        try:
            identity = path.resolve().relative_to(root).as_posix()
            source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            with SessionLocal() as db:
                manifest = db.get(TranscriptSource, identity)
                if manifest and manifest.content_hash == source_hash:
                    stats.skipped_files += 1
                    stats.skipped_chunks += manifest.chunk_count
                    db.rollback()
                    continue

            chunks, parsed_hash = prepare_transcript_chunks(path, identity)
            chunk_count = len(chunks)
            if parsed_hash != source_hash:
                raise ValueError(f"{path.name} changed while it was being read; retry ingestion")

            with SessionLocal() as db:
                manifest = db.get(TranscriptSource, identity)
                was_update = manifest is not None
                old_chunk_count = manifest.chunk_count if manifest else 0
                if was_update:
                    db.execute(delete(SourceDocumentChunk).where(SourceDocumentChunk.source_identity == identity))
                for chunk in chunks:
                    db.add(SourceDocumentChunk(
                        title=chunk.title, filename=chunk.filename, url=chunk.url,
                        guest_name=chunk.guest_name, source_identity=identity,
                        chunk_index=chunk.chunk_index, content=chunk.content,
                        embedding=[], content_hash=chunk.content_hash,
                    ))
                if manifest is None:
                    manifest = TranscriptSource(source_identity=identity, filename=path.name,
                                                content_hash=source_hash, chunk_count=len(chunks))
                    db.add(manifest)
                else:
                    manifest.filename = path.name
                    manifest.content_hash = source_hash
                    manifest.chunk_count = len(chunks)
                    manifest.updated_at = datetime.now(timezone.utc)
                db.commit()
            if was_update:
                stats.updated_files += 1
                stats.updated_chunks += chunk_count
            else:
                stats.processed_files += 1
                stats.processed_chunks += chunk_count
        except Exception as exc:
            stats.failed_files += 1
            stats.failed_chunks += chunk_count
            print(f"Failed {path}: {exc}")
        finally:
            completed = stats.processed_files + stats.skipped_files + stats.updated_files + stats.failed_files
            if completed % 25 == 0 or completed == len(paths):
                print(
                    f"Progress {completed}/{len(paths)} files | "
                    f"new {stats.processed_files}, skipped {stats.skipped_files}, "
                    f"updated {stats.updated_files}, failed {stats.failed_files}"
                )
    return stats


def main() -> IngestStats:
    ensure_rag_schema()
    paths = source_files(SOURCE_DIR)
    if not paths:
        print(f"No Markdown transcript files found in {SOURCE_DIR}.")
        return IngestStats()
    print(f"Indexing {len(paths)} transcript files with PostgreSQL full-text search; no embeddings will be generated.")
    stats = ingest_paths(paths)
    print(
        "Ingestion summary: "
        f"processed={stats.processed_files} files/{stats.processed_chunks} chunks, "
        f"skipped={stats.skipped_files} files/{stats.skipped_chunks} chunks, "
        f"updated={stats.updated_files} files/{stats.updated_chunks} chunks, "
        f"failed={stats.failed_files} files/{stats.failed_chunks} chunks"
    )
    return stats


if __name__ == "__main__":
    main()
