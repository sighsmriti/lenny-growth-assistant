import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, create_engine, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://lenny_user:local_dev_password@127.0.0.1:5433/lenny_assistant",
)
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(9))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    session: Mapped[ChatSession] = relationship(back_populates="messages")


class SourceDocumentChunk(Base):
    __tablename__ = "source_document_chunks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500))
    filename: Mapped[str] = mapped_column(String(500), index=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    guest_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_identity: Mapped[str | None] = mapped_column(String(1000), nullable=True, index=True)
    chunk_index: Mapped[int] = mapped_column()
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)


class TranscriptSource(Base):
    __tablename__ = "transcript_sources"

    source_identity: Mapped[str] = mapped_column(String(1000), primary_key=True)
    filename: Mapped[str] = mapped_column(String(1000))
    content_hash: Mapped[str] = mapped_column(String(64))
    chunk_count: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(300))
    format: Mapped[str] = mapped_column(String(20), index=True)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


def ensure_rag_schema() -> None:
    """Create new RAG tables and add the FTS index without dropping existing rows."""
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE source_document_chunks ADD COLUMN IF NOT EXISTS guest_name VARCHAR(500)"))
        connection.execute(text("ALTER TABLE source_document_chunks ADD COLUMN IF NOT EXISTS source_identity VARCHAR(1000)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_source_document_chunks_source_identity ON source_document_chunks (source_identity)"))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_source_document_chunks_fts "
            "ON source_document_chunks USING GIN "
            "(to_tsvector('english', coalesce(title, '') || ' ' || coalesce(guest_name, '') || ' ' || coalesce(content, '')))"
        ))


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_rag_schema()
    yield


app = FastAPI(title="The Lenny Growth Assistant", lifespan=lifespan)


class ChatRequest(BaseModel):
    session_id: UUID
    message: str = Field(min_length=1, max_length=20000)


class AgentSkillRequest(BaseModel):
    task: str = Field(min_length=1, max_length=20000)


class ArtifactRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    format: str = Field(pattern="^(markdown|html|css)$")
    content: str = Field(min_length=1, max_length=500000)


class MessageResponse(BaseModel):
    id: int
    session_id: UUID
    role: str
    content: str
    created_at: datetime


def get_session_or_404(db, session_id: UUID) -> ChatSession:
    chat_session = db.get(ChatSession, session_id)
    if chat_session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return chat_session


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/config")
def public_app_config():
    from backend.llm import LLMConfigurationError, public_config

    try:
        return {"llm": public_config()}
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get("/api/agent/skills")
def list_agent_skills():
    """List Pi skills available to the app's agent workflow."""
    from backend.agent import discover_skills

    return {"framework": "pi-coding-agent", "skills": discover_skills()}


@app.post("/api/agent/skills/{skill_name}/run")
async def run_agent_skill(skill_name: str, request: AgentSkillRequest):
    """Run a discovered Pi skill using the configured model provider."""
    from backend.agent import PiAgentError, run_skill

    try:
        reply = await run_skill(skill_name, request.task)
    except PiAgentError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    title = next((line.strip().removeprefix("#").strip() for line in reply.splitlines() if line.strip()), "Generated essay")
    with SessionLocal() as db:
        artifact = Artifact(title=title[:300], format="markdown", content=reply)
        db.add(artifact)
        db.commit()
        db.refresh(artifact)
    return {
        "reply": reply,
        "framework": "pi-coding-agent",
        "provider": os.getenv("LLM_PROVIDER", "ollama").strip().lower(),
        "model": (os.getenv("OPENAI_MODEL", "gpt-4o-mini") if os.getenv("LLM_PROVIDER", "ollama").strip().lower() == "openai"
                  else os.getenv("OLLAMA_MODEL", MODEL)),
        "skill": skill_name,
        "artifact_id": str(artifact.id),
    }


@app.post("/api/artifacts", status_code=201)
def create_artifact(request: ArtifactRequest):
    with SessionLocal() as db:
        artifact = Artifact(title=request.title.strip(), format=request.format, content=request.content)
        db.add(artifact)
        db.commit()
        db.refresh(artifact)
        return {"id": str(artifact.id), "title": artifact.title, "format": artifact.format,
                "created_at": artifact.created_at}


@app.get("/api/artifacts")
def list_artifacts():
    with SessionLocal() as db:
        rows = db.scalars(select(Artifact).order_by(Artifact.created_at.desc(), Artifact.id.desc())).all()
        return [{"id": str(row.id), "title": row.title, "format": row.format,
                 "created_at": row.created_at} for row in rows]


@app.get("/api/artifacts/{artifact_id}")
def get_artifact(artifact_id: UUID):
    from backend.artifacts import render_markdown

    with SessionLocal() as db:
        artifact = db.get(Artifact, artifact_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail="Artifact not found")
        return {"id": str(artifact.id), "title": artifact.title, "format": artifact.format,
                "content": artifact.content,
                "rendered_html": render_markdown(artifact.content) if artifact.format == "markdown" else None,
                "created_at": artifact.created_at}


@app.get("/health/db")
def database_health():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"database": "connected"}
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="Database is unavailable")


@app.post("/api/sessions", status_code=201)
def create_chat_session():
    with SessionLocal() as db:
        chat_session = ChatSession()
        db.add(chat_session)
        db.commit()
        db.refresh(chat_session)
        return {"id": str(chat_session.id), "created_at": chat_session.created_at, "updated_at": chat_session.updated_at}


@app.get("/api/sessions")
def list_chat_sessions():
    with SessionLocal() as db:
        sessions = db.scalars(select(ChatSession).order_by(ChatSession.created_at.desc())).all()
        return [{"id": str(item.id), "created_at": item.created_at, "updated_at": item.updated_at} for item in sessions]


@app.get("/api/sessions/{session_id}/messages", response_model=list[MessageResponse])
def get_messages(session_id: UUID):
    with SessionLocal() as db:
        get_session_or_404(db, session_id)
        return db.scalars(select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at, ChatMessage.id)).all()


@app.post("/api/chat")
async def chat(request: ChatRequest):
    from backend.llm import LLMConfigurationError, LLMError, get_config, generate

    try:
        provider_config = get_config()
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    with SessionLocal() as db:
        chat_session = get_session_or_404(db, request.session_id)
        user_message = ChatMessage(session_id=request.session_id, role="user", content=request.message)
        db.add(user_message)
        chat_session.updated_at = datetime.now(timezone.utc)
        db.commit()

        history = db.scalars(select(ChatMessage).where(ChatMessage.session_id == request.session_id).order_by(ChatMessage.created_at, ChatMessage.id)).all()
        messages = [{"role": item.role, "content": item.content} for item in history]

        from backend.rag import evidence_prompt, retrieve
        relevant = retrieve(db, request.message)
        if not relevant:
            reply = "The available transcripts do not support an answer to this question."
            db.add(ChatMessage(session_id=request.session_id, role="assistant", content=reply))
            chat_session.updated_at = datetime.now(timezone.utc)
            db.commit()
            return {"reply": reply, "provider": provider_config.provider, "model": provider_config.model, "citations": []}
        # Keep session context, while stating that only current retrieved passages support facts.
        messages.insert(0, {"role": "system", "content":
            "For factual claims about the transcript collection, use only the source excerpts in the latest user message. "
            "Conversation history is context, not evidence. Do not invent titles, URLs, quotations, or citations. "
            "If the excerpts do not support the answer, say the available transcripts do not support an answer."})
        messages[-1] = {"role": "user", "content": evidence_prompt(request.message, relevant)}

        try:
            reply = await generate(messages)
        except LLMError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

        db.add(ChatMessage(session_id=request.session_id, role="assistant", content=reply))
        chat_session.updated_at = datetime.now(timezone.utc)
        db.commit()
        citations = [{"title": row.title, "guest_name": row.guest_name, "filename": row.filename,
                      "source_identity": row.source_identity, "url": row.url,
                      "chunk_index": row.chunk_index, "excerpt": row.content,
                      "relevance": round(score, 6)} for row, score in relevant]
        return {"reply": reply, "provider": provider_config.provider, "model": provider_config.model, "citations": citations}


FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"


@app.get("/viewer", include_in_schema=False)
def artifact_viewer():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/", include_in_schema=False)
def chat_app():
    return FileResponse(FRONTEND_DIR / "chat.html")


app.mount("/viewer-assets", StaticFiles(directory=FRONTEND_DIR), name="viewer-assets")
app.mount("/chat-assets", StaticFiles(directory=FRONTEND_DIR), name="chat-assets")
