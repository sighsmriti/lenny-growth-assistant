"""Small, local-first retrieval pipeline for source documents."""
import hashlib
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx
import yaml
from sqlalchemy import func, literal_column, select

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
SOURCE_DIR = Path(os.getenv("RAG_SOURCE_DIR", "data/sources"))
CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "1000"))
CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "150"))
SIMILARITY_THRESHOLD = float(os.getenv("RAG_SIMILARITY_THRESHOLD", "0.25"))
FTS_MIN_RANK = float(os.getenv("RAG_FTS_MIN_RANK", "0.01"))
FTS_QUESTION_FRAMING = {
    "advice", "lenny", "podcast", "give", "find", "finding", "tell", "explain", "talk",
    "say", "ask", "discuss", "recommend", "suggest", "opinion", "think",
    "know", "share", "summarize", "describe", "answer", "question",
}


class EmbeddingError(RuntimeError):
    pass


@dataclass
class SourceChunk:
    title: str
    filename: str
    url: str | None
    chunk_index: int
    content: str
    embedding: list[float]
    content_hash: str
    guest_name: str | None = None
    source_identity: str | None = None


@dataclass
class IngestStats:
    processed_files: int = 0
    skipped_files: int = 0
    updated_files: int = 0
    failed_files: int = 0
    processed_chunks: int = 0
    skipped_chunks: int = 0
    updated_chunks: int = 0
    failed_chunks: int = 0


def parse_document(path: Path) -> tuple[str, str | None, str]:
    """Read UTF-8 text/Markdown. Optional first-line metadata: # Title, URL: ..."""
    try:
        raw = path.read_text(encoding="utf-8-sig").strip()
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"Could not read {path.name}: {exc}") from exc
    if not raw:
        raise ValueError(f"{path.name} is empty")
    title = path.stem.replace("_", " ").replace("-", " ").strip().title()
    url = None
    lines = raw.splitlines()
    if lines and lines[0].startswith("# "):
        title = lines.pop(0)[2:].strip() or title
    if lines and re.match(r"^URL:\s*", lines[0], re.I):
        url = re.sub(r"^URL:\s*", "", lines.pop(0), flags=re.I).strip() or None
    return title, url, "\n".join(lines).strip()


def split_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("chunk size must be positive and overlap between zero and size")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = text.rfind(" ", start, end)
            if boundary > start + size // 2:
                end = boundary
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/embed",
                json={"model": EMBED_MODEL, "input": texts},
            )
            response.raise_for_status()
        payload = response.json()
        vectors = payload.get("embeddings") if isinstance(payload, dict) else None
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise ValueError(f"expected one vector per input ({len(texts)}), received an invalid 'embeddings' array")
        checked = []
        for index, vector in enumerate(vectors):
            if (not isinstance(vector, list) or not vector
                    or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in vector)):
                raise ValueError(f"'embeddings[{index}]' must be a non-empty array of numbers")
            checked.append([float(value) for value in vector])
        return checked
    except httpx.TimeoutException as exc:
        raise EmbeddingError("Timed out waiting for Ollama /api/embed; check that Ollama is running and responsive") from exc
    except httpx.HTTPStatusError as exc:
        raise EmbeddingError(f"Ollama /api/embed returned HTTP {exc.response.status_code}; verify the embedding model is available") from exc
    except httpx.HTTPError as exc:
        raise EmbeddingError(f"Could not reach Ollama /api/embed: {exc}") from exc
    except (ValueError, TypeError, KeyError) as exc:
        raise EmbeddingError(f"Ollama /api/embed returned a malformed response: {exc}") from exc


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    denom = math.sqrt(sum(x*x for x in left)) * math.sqrt(sum(x*x for x in right))
    return sum(x*y for x, y in zip(left, right)) / denom if denom else 0.0


def source_files(directory: Path = SOURCE_DIR) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(p for p in directory.rglob("*") if p.is_file() and p.suffix.lower() == ".md")


def prepare_chunks(paths: list[Path]) -> list[SourceChunk]:
    """Parse source files and construct chunks without making embedding requests."""
    result = []
    for path in paths:
        title, url, body = parse_document(path)
        pieces = split_text(body)
        if not pieces:
            continue
        for index, content in enumerate(pieces):
            digest = hashlib.sha256((str(path.resolve()) + "\0" + str(index) + "\0" + content).encode()).hexdigest()
            result.append(SourceChunk(title, path.name, url, index, content, [], digest))
    return result


def parse_transcript(path: Path) -> tuple[str, str | None, str | None, str]:
    """Read the repository's YAML-front-matter transcript format."""
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"Could not read {path.name}: {exc}") from exc
    title = path.stem.replace("_", " ").replace("-", " ").strip().title()
    guest = None
    url = None
    body = raw.strip()
    if body.startswith("---"):
        match = re.match(r"\A---\s*\r?\n(.*?)\r?\n---\s*(?:\r?\n|\Z)", body, re.S)
        if not match:
            raise ValueError(f"{path.name} has malformed YAML front matter")
        try:
            metadata = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"{path.name} has malformed YAML front matter: {exc}") from exc
        if not isinstance(metadata, dict):
            raise ValueError(f"{path.name} front matter must be a YAML mapping")
        title = str(metadata.get("title") or title).strip()
        guest_value = metadata.get("guest") or metadata.get("guest_name")
        guest = str(guest_value).strip() if guest_value else None
        url_value = metadata.get("original_source_url") or metadata.get("source_url") or metadata.get("youtube_url") or metadata.get("url")
        url = str(url_value).strip() if url_value else None
        body = body[match.end():].strip()
    if not body:
        raise ValueError(f"{path.name} contains no transcript text")
    return title, guest, url, body


def prepare_transcript_chunks(path: Path, source_identity: str) -> tuple[list[SourceChunk], str]:
    title, guest, url, body = parse_transcript(path)
    file_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    pieces = split_text(body)
    chunks = []
    for index, content in enumerate(pieces):
        digest = hashlib.sha256(f"{source_identity}\0{index}\0{content}".encode("utf-8")).hexdigest()
        chunks.append(SourceChunk(title, path.name, url, index, content, [], digest, guest, source_identity))
    if not chunks:
        raise ValueError(f"{path.name} contains no transcript chunks")
    return chunks, file_digest


def retrieve(db: Any, query: str, limit: int = 5, min_rank: float = FTS_MIN_RANK) -> list[tuple[Any, float]]:
    """Rank transcript passages with PostgreSQL full-text search and the matching GIN index."""
    from backend.main import SourceDocumentChunk

    empty = literal_column("''")
    space = literal_column("' '")
    document_text = (
        func.coalesce(SourceDocumentChunk.title, empty) + space
        + func.coalesce(SourceDocumentChunk.guest_name, empty) + space
        + func.coalesce(SourceDocumentChunk.content, empty)
    )
    config = literal_column("'english'")
    vector = func.to_tsvector(config, document_text)
    # Remove request framing and punctuation, then let PostgreSQL's English
    # dictionary normalize the remaining content terms exactly once.
    raw_terms = re.findall(r"[^\W_]+", query.lower(), re.UNICODE)
    terms = [term for term in raw_terms if term not in FTS_QUESTION_FRAMING]
    if not terms:
        return []
    tsquery = func.plainto_tsquery(config, " ".join(terms))
    rank = func.ts_rank_cd(vector, tsquery)
    statement = (
        select(SourceDocumentChunk, rank.label("rank"))
        .where(SourceDocumentChunk.source_identity.is_not(None), vector.op("@@")(tsquery), rank >= min_rank)
        .order_by(rank.desc(), SourceDocumentChunk.filename, SourceDocumentChunk.chunk_index)
        .limit(limit)
    )
    return [(row, float(score)) for row, score in db.execute(statement).all()]


async def embed_chunks(
    chunks: list[SourceChunk], batch_size: int = 16,
    progress_callback: Callable[[int, int], None] | None = None,
    processed: int = 0, total: int | None = None,
) -> list[SourceChunk]:
    if batch_size <= 0:
        raise ValueError("embedding batch size must be positive")
    if total is None:
        total = processed + len(chunks)
    embedded = []
    for offset in range(0, len(chunks), batch_size):
        batch = chunks[offset:offset + batch_size]
        vectors = await embed_texts([chunk.content for chunk in batch])
        embedded.extend(
            SourceChunk(chunk.title, chunk.filename, chunk.url, chunk.chunk_index,
                        chunk.content, vector, chunk.content_hash)
            for chunk, vector in zip(batch, vectors)
        )
        processed += len(batch)
        if progress_callback:
            progress_callback(processed, total)
    if not chunks and progress_callback:
        progress_callback(processed, total)
    return embedded


async def build_chunks(paths: list[Path], batch_size: int = 16) -> list[SourceChunk]:
    """Convenience pipeline for callers that do not need database duplicate filtering."""
    return await embed_chunks(prepare_chunks(paths), batch_size=batch_size)


def evidence_prompt(question: str, chunks: list[tuple[Any, float]]) -> str:
    evidence = "\n\n".join(
        f"[Source {i}: episode={row.title}; guest={row.guest_name or 'not specified'}; "
        f"file={row.filename}; url={row.url or 'not available'}; chunk={row.chunk_index}]\n{row.content}"
        for i, (row, _) in enumerate(chunks, 1)
    )
    return ("Use only these retrieved transcript excerpts as evidence for factual claims about the source collection. "
            "If they do not support an answer, clearly say the available transcripts do not support an answer. "
            "Do not invent episode titles, guests, URLs, quotations, or citations.\n\n"
            f"SOURCE EXCERPTS:\n{evidence or '(No relevant source excerpts found.)'}\n\nQUESTION:\n{question}")
