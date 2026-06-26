from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str | None] = mapped_column(String(128), unique=True)
    password: Mapped[str | None] = mapped_column(String(128))
    google_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512))
    create_time: Mapped[datetime | None] = mapped_column(DateTime)
    update_time: Mapped[datetime | None] = mapped_column(DateTime)


class ResearchSession(Base):
    __tablename__ = "research_session"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(32))
    create_time: Mapped[datetime | None] = mapped_column(DateTime)
    start_time: Mapped[datetime | None] = mapped_column(DateTime)
    update_time: Mapped[datetime | None] = mapped_column(DateTime)
    complete_time: Mapped[datetime | None] = mapped_column(DateTime)
    model_id: Mapped[str | None] = mapped_column(String(256))
    budget: Mapped[str | None] = mapped_column(String(16))
    title: Mapped[str | None] = mapped_column(String(256))
    total_input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    total_output_tokens: Mapped[int | None] = mapped_column(BigInteger)


class Model(Base):
    __tablename__ = "model"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    type: Mapped[str] = mapped_column(String(16))
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    name: Mapped[str] = mapped_column(String(128))
    model: Mapped[str] = mapped_column(String(128))
    base_url: Mapped[str] = mapped_column(String(256))
    api_key: Mapped[str | None] = mapped_column(String(256))
    create_time: Mapped[datetime | None] = mapped_column(DateTime)
    update_time: Mapped[datetime | None] = mapped_column(DateTime)


class ChatMessage(Base):
    __tablename__ = "chat_message"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    research_id: Mapped[str] = mapped_column(String(32))
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    sequence_no: Mapped[int] = mapped_column(Integer)
    create_time: Mapped[datetime | None] = mapped_column(DateTime)


class WorkflowEvent(Base):
    __tablename__ = "workflow_event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    research_id: Mapped[str] = mapped_column(String(32))
    type: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(512))
    content: Mapped[str | None] = mapped_column(Text)
    parent_event_id: Mapped[int | None] = mapped_column(BigInteger)
    sequence_no: Mapped[int] = mapped_column(Integer)
    create_time: Mapped[datetime | None] = mapped_column(DateTime)
