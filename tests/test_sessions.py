import os
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://lenny_user:local_dev_password@127.0.0.1:5433/lenny_assistant")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from backend import main


@pytest.fixture
def client():
    # Clean only test-owned chunks so an interrupted prior run cannot affect ranking.
    with main.SessionLocal() as db:
        db.execute(delete(main.SourceDocumentChunk).where(main.SourceDocumentChunk.content_hash.like("test-%")))
        db.commit()
    with main.SessionLocal() as db:
        original_ids = set(db.scalars(select(main.ChatSession.id)).all())
    with TestClient(main.app) as test_client:
        yield test_client
    with main.SessionLocal() as db:
        db.execute(delete(main.SourceDocumentChunk).where(main.SourceDocumentChunk.content_hash.like("test-%")))
        db.commit()
        created_ids = set(db.scalars(select(main.ChatSession.id)).all()) - original_ids
        if created_ids:
            db.execute(delete(main.ChatMessage).where(main.ChatMessage.session_id.in_(created_ids)))
            db.execute(delete(main.ChatSession).where(main.ChatSession.id.in_(created_ids)))
            db.commit()


def test_chat_ui_and_assets_are_served(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "Lenny Growth Assistant" in page.text
    assert "/chat-assets/chat.js" in page.text
    assert client.get("/chat-assets/chat.js").status_code == 200
    assert client.get("/chat-assets/chat.css").status_code == 200
    assert client.get("/viewer").status_code == 200


def test_create_session_and_list(client):
    response = client.post("/api/sessions")
    assert response.status_code == 201
    session_id = response.json()["id"]
    assert response.json()["created_at"]
    assert response.json()["updated_at"]
    listed = client.get("/api/sessions")
    assert listed.status_code == 200
    assert any(item["id"] == session_id for item in listed.json())


def test_chat_persists_messages_and_history(client, monkeypatch):
    session_id = client.post("/api/sessions").json()["id"]
    source = main.SourceDocumentChunk(title="Greeting", filename="greeting.txt", source_identity="test-greeting.txt", chunk_index=0,
        content="qzxgreetingtoken", embedding=[1.0, 0.0], content_hash="test-greeting-hash")
    with main.SessionLocal() as db:
        db.add(source); db.commit()

    async def fake_generate(messages):
        assert messages[-1]["role"] == "user"
        assert "qzxgreetingtoken" in messages[-1]["content"]
        return "Hello back"

    monkeypatch.setattr("backend.llm.generate", fake_generate)
    async def fake_embed(texts):
        return [[1.0, 0.0] for _ in texts]
    monkeypatch.setattr("backend.rag.embed_texts", fake_embed)
    response = client.post("/api/chat", json={"session_id": session_id, "message": "qzxgreetingtoken"})
    assert response.status_code == 200
    assert response.json()["reply"] == "Hello back"
    assert response.json()["citations"][0]["filename"] == "greeting.txt"
    history = client.get(f"/api/sessions/{session_id}/messages")
    assert [(item["role"], item["content"]) for item in history.json()] == [
        ("user", "qzxgreetingtoken"), ("assistant", "Hello back")
    ]
    with main.SessionLocal() as db:
        db.delete(source); db.commit()


def test_chat_preserves_session_history(client, monkeypatch):
    session_id = client.post("/api/sessions").json()["id"]
    source = main.SourceDocumentChunk(title="Session", filename="session.txt", source_identity="test-session.txt", chunk_index=0,
        content="qzxfirsttoken qzxsecondtoken", embedding=[1.0, 0.0], content_hash="test-session-hash")
    with main.SessionLocal() as db:
        db.add(source); db.commit()
    calls = []

    async def fake_generate(messages):
        calls.append(messages)
        return "answer"

    monkeypatch.setattr("backend.llm.generate", fake_generate)
    assert client.post("/api/chat", json={"session_id": session_id, "message": "qzxfirsttoken"}).status_code == 200
    assert client.post("/api/chat", json={"session_id": session_id, "message": "qzxsecondtoken"}).status_code == 200
    assert [m["role"] for m in calls[1]] == ["system", "user", "assistant", "user"]
    assert calls[1][1]["content"].endswith("qzxfirsttoken")
    assert calls[1][2]["content"] == "answer"
    assert calls[1][3]["content"].endswith("qzxsecondtoken")
    with main.SessionLocal() as db:
        db.delete(source); db.commit()


def test_retrieval_and_citations(client, monkeypatch):
    from backend.rag import retrieve
    row = main.SourceDocumentChunk(title="Activation", guest_name="Ada Example", filename="activation.md",
                                   url="https://example.test/a", source_identity="test-activation.md",
                                   chunk_index=2, content="qzxactivationtoken qzxretentiontoken", embedding=[1.0, 0.0],
                                   content_hash="test-citation-hash")
    with main.SessionLocal() as db:
        db.add(row); db.commit()
        found = retrieve(db, "qzxactivationtoken qzxretentiontoken", min_rank=0.0)
        assert found and found[0][0].filename == "activation.md"

    async def fake_generate(messages):
        return "Retention is supported by the source."
    monkeypatch.setattr("backend.llm.generate", fake_generate)
    session_id = client.post("/api/sessions").json()["id"]
    response = client.post("/api/chat", json={"session_id": session_id, "message": "qzxactivationtoken qzxretentiontoken"})
    citation = response.json()["citations"][0]
    assert citation["title"] == "Activation"
    assert citation["guest_name"] == "Ada Example"
    assert citation["filename"] == "activation.md"
    assert citation["url"] == "https://example.test/a"
    assert citation["chunk_index"] == 2
    assert citation["excerpt"] == "qzxactivationtoken qzxretentiontoken"
    with main.SessionLocal() as db:
        db.delete(row); db.commit()


def test_chunking_and_document_metadata(tmp_path):
    from backend.rag import parse_document, split_text
    path = tmp_path / "source.md"
    path.write_text("# My Source\nURL: https://example.test\n\n" + ("alpha beta gamma " * 60), encoding="utf-8")
    title, url, body = parse_document(path)
    chunks = split_text(body, size=100, overlap=20)
    assert (title, url) == ("My Source", "https://example.test")
    assert len(chunks) > 1
    assert chunks[0][-15:] in chunks[1]


def test_unsupported_question_has_no_citations(client, monkeypatch):
    async def generation_must_not_run(messages):
        raise AssertionError("generation must not run without evidence")
    monkeypatch.setattr("backend.llm.generate", generation_must_not_run)
    session_id = client.post("/api/sessions").json()["id"]
    response = client.post("/api/chat", json={"session_id": session_id, "message": "Who won an unrelated award?"})
    assert response.status_code == 200
    assert response.json()["citations"] == []
    assert "available transcripts do not support an answer" in response.json()["reply"]


def test_invalid_session_ids(client):
    missing = str(uuid4())
    assert client.get(f"/api/sessions/{missing}/messages").status_code == 404
    assert client.post("/api/chat", json={"session_id": missing, "message": "Hi"}).status_code == 404
    assert client.get("/api/sessions/not-a-uuid/messages").status_code == 422
