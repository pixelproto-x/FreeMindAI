from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .config import get_database_url


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(120), default="新對話", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan", passive_deletes=True)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    conversation: Mapped[Conversation] = relationship(back_populates="messages")


def _make_engine() -> Engine:
    url = get_database_url()
    connect_args: dict[str, Any] = {}
    if url.startswith("sqlite:"):
        # Ensure the default data directory exists before SQLite opens the database.
        if url in ("sqlite:///./data/freemind.db", "sqlite:///data/freemind.db"):
            Path("data").mkdir(parents=True, exist_ok=True)
        connect_args = {"check_same_thread": False, "timeout": 15}
    engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
    if url.startswith("sqlite:"):
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=15000")
            cursor.close()
    return engine


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class ChatStore:
    def create_conversation(self, title: str = "新對話") -> dict[str, Any]:
        conversation = Conversation(id=str(uuid4()), title=(title or "新對話")[:120])
        with SessionLocal.begin() as session:
            session.add(conversation)
        return self._conversation_dict(conversation)

    def list_conversations(self) -> list[dict[str, Any]]:
        with SessionLocal() as session:
            rows = session.scalars(select(Conversation).order_by(Conversation.updated_at.desc())).all()
            return [self._conversation_dict(row) for row in rows]

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        with SessionLocal() as session:
            row = session.get(Conversation, conversation_id)
            return self._conversation_dict(row) if row else None

    def get_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        with SessionLocal() as session:
            if not session.get(Conversation, conversation_id):
                return []
            rows = session.scalars(
                select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id.asc())
            ).all()
            return [self._message_dict(row) for row in rows]

    def append_turn(self, conversation_id: str, user_content: str, assistant_content: str, provider: str, model: str) -> None:
        now = datetime.now(timezone.utc)
        with SessionLocal.begin() as session:
            conversation = session.get(Conversation, conversation_id)
            if not conversation:
                raise KeyError("conversation_not_found")
            # First successful turn gets a useful title. Keep it plain text and bounded.
            if conversation.title == "新對話":
                conversation.title = " ".join(user_content.split())[:54] or "新對話"
            conversation.updated_at = now
            session.add_all([
                Message(conversation_id=conversation_id, role="user", content=user_content, created_at=now),
                Message(conversation_id=conversation_id, role="assistant", content=assistant_content,
                        provider=provider, model=model, created_at=now),
            ])

    def delete_conversation(self, conversation_id: str) -> bool:
        with SessionLocal.begin() as session:
            row = session.get(Conversation, conversation_id)
            if not row:
                return False
            session.delete(row)
            return True

    @staticmethod
    def _conversation_dict(row: Conversation) -> dict[str, Any]:
        return {"id": row.id, "title": row.title, "created_at": _iso(row.created_at), "updated_at": _iso(row.updated_at)}

    @staticmethod
    def _message_dict(row: Message) -> dict[str, Any]:
        return {"id": row.id, "role": row.role, "content": row.content, "provider": row.provider,
                "model": row.model, "created_at": _iso(row.created_at)}
