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


class ResearchIntervention(Base):
    __tablename__ = "research_intervention"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    research_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    focus_sections_json: Mapped[str] = mapped_column(Text)
    reinforce_modes_json: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    replace_mode: Mapped[str | None] = mapped_column(String(32))
    requested_round_no: Mapped[int | None] = mapped_column(Integer)
    target_round_no: Mapped[int | None] = mapped_column(Integer)
    applied_round_no: Mapped[int | None] = mapped_column(Integer)
    superseded_by_id: Mapped[int | None] = mapped_column(BigInteger)
    apply_summary_json: Mapped[str | None] = mapped_column(Text)
    reject_code: Mapped[str | None] = mapped_column(String(64))
    reject_reason: Mapped[str | None] = mapped_column(Text)
    create_time: Mapped[datetime | None] = mapped_column(DateTime)
    update_time: Mapped[datetime | None] = mapped_column(DateTime)
    applied_time: Mapped[datetime | None] = mapped_column(DateTime)
    expired_time: Mapped[datetime | None] = mapped_column(DateTime)


class ResearchPlanningRound(Base):
    __tablename__ = "research_planning_round"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    research_id: Mapped[str] = mapped_column(String(32), index=True)
    round_no: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    round_goal: Mapped[str | None] = mapped_column(Text)
    intervention_id: Mapped[int | None] = mapped_column(BigInteger)
    planner_bias_json: Mapped[str | None] = mapped_column(Text)
    summary_json: Mapped[str | None] = mapped_column(Text)
    create_time: Mapped[datetime | None] = mapped_column(DateTime)
    update_time: Mapped[datetime | None] = mapped_column(DateTime)
    completed_time: Mapped[datetime | None] = mapped_column(DateTime)


class ResearchWorkItem(Base):
    __tablename__ = "research_work_item"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    research_id: Mapped[str] = mapped_column(String(32), index=True)
    round_id: Mapped[int] = mapped_column(BigInteger, index=True)
    round_no: Mapped[int] = mapped_column(Integer, index=True)
    task_key: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), index=True)
    result_summary: Mapped[str | None] = mapped_column(Text)
    verification_state: Mapped[str | None] = mapped_column(String(32))
    create_time: Mapped[datetime | None] = mapped_column(DateTime)
    update_time: Mapped[datetime | None] = mapped_column(DateTime)


class ResearchDecisionLog(Base):
    __tablename__ = "research_decision_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    research_id: Mapped[str] = mapped_column(String(32), index=True)
    round_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    round_no: Mapped[int | None] = mapped_column(Integer, index=True)
    decision_type: Mapped[str] = mapped_column(String(32), index=True)
    action: Mapped[str | None] = mapped_column(String(32))
    summary: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[str | None] = mapped_column(Text)
    create_time: Mapped[datetime | None] = mapped_column(DateTime)


class ResearchEvidenceLedger(Base):
    __tablename__ = "research_evidence_ledger"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    research_id: Mapped[str] = mapped_column(String(32), index=True)
    round_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    work_item_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    source_url: Mapped[str | None] = mapped_column(String(1024))
    source_title: Mapped[str | None] = mapped_column(String(512))
    source_type: Mapped[str] = mapped_column(String(32), index=True)
    strength_score: Mapped[str | None] = mapped_column(String(32))
    section_hint: Mapped[str | None] = mapped_column(String(256))
    snippet: Mapped[str | None] = mapped_column(Text)
    create_time: Mapped[datetime | None] = mapped_column(DateTime)


class ResearchContextNode(Base):
    __tablename__ = "research_context_node"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    research_id: Mapped[str] = mapped_column(String(32), index=True)
    path: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    node_type: Mapped[str] = mapped_column(String(64), index=True)
    level: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str | None] = mapped_column(String(512))
    content: Mapped[str | None] = mapped_column(Text)
    content_ref: Mapped[str | None] = mapped_column(String(512))
    parent_path: Mapped[str | None] = mapped_column(String(512), index=True)
    branch_index: Mapped[int | None] = mapped_column(Integer, index=True)
    round_no: Mapped[int | None] = mapped_column(Integer, index=True)
    token_estimate: Mapped[int | None] = mapped_column(Integer)
    char_count: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True)
    create_time: Mapped[datetime | None] = mapped_column(DateTime)
    update_time: Mapped[datetime | None] = mapped_column(DateTime)


class ResearchContextEdge(Base):
    __tablename__ = "research_context_edge"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    research_id: Mapped[str] = mapped_column(String(32), index=True)
    from_path: Mapped[str] = mapped_column(String(512), index=True)
    to_path: Mapped[str] = mapped_column(String(512), index=True)
    relation_type: Mapped[str] = mapped_column(String(64), index=True)
    metadata_json: Mapped[str | None] = mapped_column(Text)
    create_time: Mapped[datetime | None] = mapped_column(DateTime)
