from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete, select

from backend import main
from backend.ingest import ingest_paths
from backend.rag import evidence_prompt, retrieve


def write_episode(path: Path, *, title: str, guest: str, url: str, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ntitle: {title}\nguest: {guest}\nyoutube_url: {url}\n---\n\n{text}\n",
        encoding="utf-8",
    )


def cleanup_sources(identities: set[str]) -> None:
    with main.SessionLocal() as db:
        db.execute(delete(main.SourceDocumentChunk).where(main.SourceDocumentChunk.source_identity.in_(identities)))
        db.execute(delete(main.TranscriptSource).where(main.TranscriptSource.source_identity.in_(identities)))
        db.commit()


def test_ingestion_deduplicates_and_refreshes_changed_transcript(tmp_path):
    main.ensure_rag_schema()
    root = tmp_path.parent
    folder = tmp_path / f"rag-{uuid4().hex}"
    path = folder / "episode.md"
    identity = path.resolve().relative_to(root.resolve()).as_posix()
    unrelated_identity = f"{folder.name}/other-source.md"
    write_episode(path, title="Episode One", guest="Guest One", url="https://example.test/one",
                  text="Original retention advice. " * 120)
    try:
        first = ingest_paths([path], root)
        assert first.processed_files == 1
        assert first.processed_chunks > 1

        with main.SessionLocal() as db:
            original_rows = db.scalars(select(main.SourceDocumentChunk).where(
                main.SourceDocumentChunk.source_identity == identity)).all()
            assert original_rows
            assert original_rows[0].title == "Episode One"
            assert original_rows[0].guest_name == "Guest One"
            assert original_rows[0].url == "https://example.test/one"
            assert original_rows[0].embedding == []
            db.add(main.SourceDocumentChunk(title="Unrelated", filename="other.md", guest_name=None,
                source_identity=unrelated_identity, url=None, chunk_index=0, content="unrelated document",
                embedding=[], content_hash=f"unrelated-{uuid4().hex}"))
            db.commit()

        second = ingest_paths([path], root)
        assert second.skipped_files == 1
        assert second.skipped_chunks == first.processed_chunks

        write_episode(path, title="Episode One Updated", guest="Guest One", url="https://example.test/updated",
                      text="Changed onboarding advice. " * 130)
        refreshed = ingest_paths([path], root)
        assert refreshed.updated_files == 1
        assert refreshed.updated_chunks > 0
        with main.SessionLocal() as db:
            rows = db.scalars(select(main.SourceDocumentChunk).where(
                main.SourceDocumentChunk.source_identity == identity)).all()
            assert rows
            assert all(row.title == "Episode One Updated" for row in rows)
            assert all(row.url == "https://example.test/updated" for row in rows)
            assert all("Changed onboarding advice" in row.content for row in rows)
            assert db.scalar(select(main.SourceDocumentChunk.id).where(
                main.SourceDocumentChunk.source_identity == unrelated_identity)) is not None
    finally:
        cleanup_sources({identity, unrelated_identity})


def test_postgres_full_text_rank_citations_and_unsupported_question(tmp_path):
    main.ensure_rag_schema()
    root = tmp_path.parent
    folder = tmp_path / f"fts-{uuid4().hex}"
    high_path = folder / "high.md"
    low_path = folder / "low.md"
    high_id = high_path.resolve().relative_to(root.resolve()).as_posix()
    low_id = low_path.resolve().relative_to(root.resolve()).as_posix()
    write_episode(high_path, title="Retention Playbook", guest="High Signal Guest",
                  url="https://example.test/high", text=("zephyrretention " * 35) + "cohort onboarding lessons")
    write_episode(low_path, title="General Interview", guest="Low Signal Guest",
                  url="https://example.test/low", text="zephyrretention matters in this case")
    try:
        stats = ingest_paths([high_path, low_path], root)
        assert stats.processed_files == 2
        with main.SessionLocal() as db:
            results = retrieve(db, "zephyrretention", limit=5)
            assert len(results) >= 2
            assert results[0][0].source_identity == high_id
            row, rank = results[0]
            assert rank > 0
            prompt = evidence_prompt("What does the episode say about retention?", [results[0]])
            assert row.guest_name in prompt
            assert row.url in prompt
            assert row.content in prompt
            assert retrieve(db, "quasar zxqv no-match", limit=5) == []
    finally:
        cleanup_sources({high_id, low_id})


def test_query_formatting_does_not_block_topic_retrieval_or_remove_meaningful_key(tmp_path):
    main.ensure_rag_schema()
    root = tmp_path.parent
    folder = tmp_path / f"rag-query-{uuid4().hex}"
    path = folder / "pmf.md"
    metrics_path = folder / "metrics.md"
    identity = path.resolve().relative_to(root.resolve()).as_posix()
    metrics_identity = metrics_path.resolve().relative_to(root.resolve()).as_posix()
    write_episode(path, title="Finding Product-Market Fit", guest="Test Founder",
                  url="https://example.test/pmf", text="Building products that solve customer problems is how teams find product market fit. " * 8)
    write_episode(metrics_path, title="Key Activation Metrics", guest="Metrics Guest",
                  url="https://example.test/metrics", text="Key activation metrics show whether new users reach value and continue using the product. " * 8)
    try:
        assert ingest_paths([path, metrics_path], root).processed_files == 2
        with main.SessionLocal() as db:
            results = retrieve(db, "What are the key lessons about building products from the indexed Lenny podcast transcripts? Give me a concise answer with citations.")
            match = next((row for row, _ in results if row.source_identity == identity), None)
            assert match is not None
            assert match.guest_name == "Test Founder"
            assert match.url == "https://example.test/pmf"
            assert "Building products" in match.content
            key_results = retrieve(db, "What are key activation metrics?")
            key_match = next((row for row, _ in key_results if row.source_identity == metrics_identity), None)
            assert key_match is not None
            assert "Key activation metrics" in key_match.content
            citations = evidence_prompt("What are the key lessons about building products?", [results[0]])
            assert "file=pmf.md" in citations
            assert "https://example.test/pmf" in citations
            assert retrieve(db, "Who won an unrelated award?") == []
    finally:
        cleanup_sources({identity, metrics_identity})


def test_multi_lesson_evidence_instructions_retrieve_product_building_passages(tmp_path):
    main.ensure_rag_schema()
    root = tmp_path.parent
    path = tmp_path / f"rag-followup-{uuid4().hex}" / "building.md"
    identity = path.resolve().relative_to(root.resolve()).as_posix()
    write_episode(path, title="Product Building Lessons", guest="Product Guest",
                  url="https://example.test/building",
                  text="A product-building lesson is to observe customer behavior and improve the product through focused iteration. " * 8)
    question = (
        "Based only on the retrieved podcast passages, summarize three specific product-building lessons. "
        "For each lesson, explain the supporting evidence and cite the relevant episode. "
        "If the evidence doesn't support a lesson, say so."
    )
    try:
        assert ingest_paths([path], root).processed_files == 1
        with main.SessionLocal() as db:
            detailed = retrieve(db, question)
            concise = retrieve(db, "building products")
            match = next((row for row, _ in detailed if row.source_identity == identity), None)
            assert match is not None
            assert any(row.source_identity == identity for row, _ in concise)
            detailed_score = next(score for row, score in detailed if row.source_identity == identity)
            assert detailed_score >= 0.01
            citation_prompt = evidence_prompt(question, [(match, detailed_score)])
            assert "file=building.md" in citation_prompt
            assert "https://example.test/building" in citation_prompt
            assert retrieve(db, "Who won an unrelated award?") == []
    finally:
        cleanup_sources({identity})
