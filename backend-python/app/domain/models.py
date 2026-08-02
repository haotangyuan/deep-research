from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Date, DateTime, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import MEDIUMTEXT
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
    content: Mapped[str] = mapped_column(MEDIUMTEXT)
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
    content: Mapped[str | None] = mapped_column(MEDIUMTEXT)
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


# ---------------------------------------------------------------------------
# Eval MVP v2 — 落库链路（Commit 1）
# 见 docs/deep-research-eval-mvp-v2-tier-mechanism.md §6。
# 核心 Eval 读取 research_run / research_artifact / research_llm_call /
# research_claim_manifest；research_stage_usage 仅是业务聚合投影。
# ---------------------------------------------------------------------------


class ResearchRun(Base):
    """单次连续后台执行（一次 _run_now）。retry/resume 新建一行。"""

    __tablename__ = "research_run"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    research_id: Mapped[str] = mapped_column(String(32), index=True)
    attempt_no: Mapped[int] = mapped_column(Integer)
    trigger_type: Mapped[str] = mapped_column(String(32))
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str | None] = mapped_column(String(32))
    outcome: Mapped[str | None] = mapped_column(String(32))
    workflow_mode: Mapped[str | None] = mapped_column(String(32))
    budget_level: Mapped[str | None] = mapped_column(String(16))
    request_model: Mapped[str | None] = mapped_column(String(256))
    response_model: Mapped[str | None] = mapped_column(String(256))
    workflow_commit_sha: Mapped[str | None] = mapped_column(String(64))
    workflow_dirty: Mapped[int | None] = mapped_column(Integer)
    prompt_version_json: Mapped[str | None] = mapped_column(Text)
    prompt_hash_json: Mapped[str | None] = mapped_column(Text)
    template_version: Mapped[str | None] = mapped_column(String(64))
    template_sha256: Mapped[str | None] = mapped_column(String(64))
    evaluator_version: Mapped[str | None] = mapped_column(String(64))
    judge_model: Mapped[str | None] = mapped_column(String(256))
    fallback_used: Mapped[int | None] = mapped_column(Integer)
    fallback_type: Mapped[str | None] = mapped_column(String(64))
    fallback_reason: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger)
    search_count: Mapped[int | None] = mapped_column(Integer)
    conduct_count: Mapped[int | None] = mapped_column(Integer)
    round_count: Mapped[int | None] = mapped_column(Integer)
    active_duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    wall_duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    start_time: Mapped[datetime | None] = mapped_column(DateTime)
    end_time: Mapped[datetime | None] = mapped_column(DateTime)
    config_json: Mapped[str | None] = mapped_column(Text)
    create_time: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        UniqueConstraint("research_id", "attempt_no", name="uniq_research_run_attempt"),
    )


class ResearchArtifact(Base):
    """研究产物落库（报告/证据/来源/决策/brief 等）。按幂等键去重。"""

    __tablename__ = "research_artifact"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), index=True)
    research_id: Mapped[str] = mapped_column(String(32), index=True)
    artifact_type: Mapped[str] = mapped_column(String(64), index=True)
    stage_name: Mapped[str | None] = mapped_column(String(128))
    agent_name: Mapped[str | None] = mapped_column(String(128))
    round_no: Mapped[int | None] = mapped_column(Integer)
    section_id: Mapped[str | None] = mapped_column(String(128))
    angle: Mapped[str | None] = mapped_column(String(64))
    content: Mapped[str | None] = mapped_column(MEDIUMTEXT)
    content_ref: Mapped[str | None] = mapped_column(String(512))
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    request_model: Mapped[str | None] = mapped_column(String(256))
    response_model: Mapped[str | None] = mapped_column(String(256))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    prompt_sha256: Mapped[str | None] = mapped_column(String(64))
    outcome: Mapped[str | None] = mapped_column(String(32))
    fallback_used: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[str | None] = mapped_column(Text)
    create_time: Mapped[datetime | None] = mapped_column(DateTime)
    update_time: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "artifact_type",
            "round_no",
            "section_id",
            "angle",
            "content_sha256",
            name="uniq_research_artifact_key",
        ),
    )


class ResearchLlmCall(Base):
    """单次逻辑 LLM 调用的 token 事实源。PK=llm_call_id 去重 replay。"""

    __tablename__ = "research_llm_call"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), index=True)
    research_id: Mapped[str] = mapped_column(String(32), index=True)
    stage_name: Mapped[str | None] = mapped_column(String(128), index=True)
    agent_name: Mapped[str | None] = mapped_column(String(128))
    round_no: Mapped[int | None] = mapped_column(Integer)
    report_phase: Mapped[str | None] = mapped_column(String(32))
    reviewer_lens: Mapped[str | None] = mapped_column(String(64))
    section_id: Mapped[str | None] = mapped_column(String(128))
    request_model: Mapped[str | None] = mapped_column(String(256))
    response_model: Mapped[str | None] = mapped_column(String(256))
    attempt_no: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    outcome: Mapped[str | None] = mapped_column(String(32))
    error_type: Mapped[str | None] = mapped_column(String(128))
    start_time: Mapped[datetime | None] = mapped_column(DateTime)
    end_time: Mapped[datetime | None] = mapped_column(DateTime)

class ResearchStageUsage(Base):
    """阶段级 token/调用投影，由 research_llm_call 聚合，不从 state.total_* 读。"""

    __tablename__ = "research_stage_usage"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(32), index=True)
    stage_name: Mapped[str | None] = mapped_column(String(128))
    agent_name: Mapped[str | None] = mapped_column(String(128))
    round_no: Mapped[int | None] = mapped_column(Integer)
    report_phase: Mapped[str | None] = mapped_column(String(32))
    reviewer_lens: Mapped[str | None] = mapped_column(String(64))
    section_id: Mapped[str | None] = mapped_column(String(128))
    request_count: Mapped[int | None] = mapped_column(Integer)
    retry_count: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    outcome: Mapped[str | None] = mapped_column(String(32))
    create_time: Mapped[datetime | None] = mapped_column(DateTime)
    update_time: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "stage_name",
            "agent_name",
            "round_no",
            "report_phase",
            "reviewer_lens",
            "section_id",
            name="uniq_research_stage_usage_key",
        ),
    )


class ResearchClaimManifest(Base):
    """claim-citation 级清单，按 (run_id, report_artifact_id, claim_id, citation_id) 幂等。"""

    __tablename__ = "research_claim_manifest"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), index=True)
    research_id: Mapped[str] = mapped_column(String(32), index=True)
    report_artifact_id: Mapped[str | None] = mapped_column(String(32), index=True)
    claim_id: Mapped[str | None] = mapped_column(String(128))
    claim_text: Mapped[str | None] = mapped_column(MEDIUMTEXT)
    section_id: Mapped[str | None] = mapped_column(String(128))
    importance: Mapped[str | None] = mapped_column(String(32))
    citation_id: Mapped[str | None] = mapped_column(String(128))
    citation_url: Mapped[str | None] = mapped_column(String(1024))
    citation_excerpt: Mapped[str | None] = mapped_column(Text)
    evidence_id: Mapped[str | None] = mapped_column(String(128))
    verifiable: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[str | None] = mapped_column(Text)
    create_time: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "report_artifact_id",
            "claim_id",
            "citation_id",
            name="uniq_research_claim_manifest_key",
        ),
    )


# === Eval MVP v2 — Commit 6：Eval 数据层（dataset / experiment / case_run / score） ===
# 无外键，按 ID 约定关联，与既有 eval 表一致。v2 §6.7-6.10。


class EvalDatasetItem(Base):
    """从日常研究冻结出的脱敏题目（v2 §6.7）。"""

    __tablename__ = "eval_dataset_item"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    dataset_name: Mapped[str] = mapped_column(String(128), index=True)
    dataset_version: Mapped[str] = mapped_column(String(64), index=True)
    source_research_id: Mapped[str | None] = mapped_column(String(32))
    source_run_id: Mapped[str | None] = mapped_column(String(32))
    query_snapshot: Mapped[str] = mapped_column(MEDIUMTEXT)
    query_sha256: Mapped[str] = mapped_column(String(64))
    task_type: Mapped[str | None] = mapped_column(String(64), index=True)
    language: Mapped[str | None] = mapped_column(String(16))
    as_of_date: Mapped[str | None] = mapped_column(Date)
    required_points_json: Mapped[str | None] = mapped_column(Text)
    reference_facts_json: Mapped[str | None] = mapped_column(Text)
    forbidden_claims_json: Mapped[str | None] = mapped_column(Text)
    source_policy_json: Mapped[str | None] = mapped_column(Text)
    evaluation_contract_json: Mapped[str | None] = mapped_column(Text)
    privacy_status: Mapped[str | None] = mapped_column(String(32))
    annotation_status: Mapped[str | None] = mapped_column(String(32))
    sample_reason: Mapped[str | None] = mapped_column(String(64))
    split_name: Mapped[str | None] = mapped_column(String(32), index=True)
    create_time: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        UniqueConstraint(
            "dataset_name",
            "dataset_version",
            "query_sha256",
            name="uniq_eval_dataset_item_query",
        ),
    )


class EvalExperiment(Base):
    """实验定义（v2 §6.8）：tier_comparison / *_ablation。"""

    __tablename__ = "eval_experiment"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    dataset_name: Mapped[str] = mapped_column(String(128), index=True)
    dataset_version: Mapped[str] = mapped_column(String(64))
    experiment_type: Mapped[str] = mapped_column(String(64), index=True)
    baseline_experiment_id: Mapped[str | None] = mapped_column(String(32))
    workflow_version: Mapped[str | None] = mapped_column(String(64))
    evaluator_version: Mapped[str | None] = mapped_column(String(64))
    judge_model: Mapped[str | None] = mapped_column(String(256))
    config_json: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(32), index=True)
    create_time: Mapped[datetime | None] = mapped_column(DateTime)
    complete_time: Mapped[datetime | None] = mapped_column(DateTime)


class EvalCaseRun(Base):
    """单次回放运行（v2 §6.9）：experiment × dataset_item × variant × repeat。"""

    __tablename__ = "eval_case_run"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(String(32), index=True)
    dataset_item_id: Mapped[str] = mapped_column(String(32), index=True)
    run_id: Mapped[str | None] = mapped_column(String(32), index=True)
    variant_name: Mapped[str] = mapped_column(String(128))
    repeat_no: Mapped[int] = mapped_column(Integer, default=0)
    gate_passed: Mapped[int | None] = mapped_column(Integer)
    failure_reasons_json: Mapped[str | None] = mapped_column(Text)
    total_score: Mapped[float | None] = mapped_column(Numeric(8, 4))
    estimated_cost: Mapped[float | None] = mapped_column(Numeric(12, 6))
    create_time: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        UniqueConstraint(
            "experiment_id",
            "dataset_item_id",
            "variant_name",
            "repeat_no",
            name="uniq_eval_case_run_key",
        ),
    )


class EvalScore(Base):
    """通用分数表（v2 §6.10）：case_run × metric × evaluator_version。"""

    __tablename__ = "eval_score"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    case_run_id: Mapped[str] = mapped_column(String(32), index=True)
    metric_name: Mapped[str] = mapped_column(String(128), index=True)
    metric_group: Mapped[str | None] = mapped_column(String(64))
    score_value: Mapped[float | None] = mapped_column(Numeric(10, 6))
    label_value: Mapped[str | None] = mapped_column(String(64))
    passed: Mapped[int | None] = mapped_column(Integer)
    evaluator_name: Mapped[str] = mapped_column(String(128))
    evaluator_version: Mapped[str] = mapped_column(String(64))
    judge_model: Mapped[str | None] = mapped_column(String(256))
    reason: Mapped[str | None] = mapped_column(Text)
    details_json: Mapped[str | None] = mapped_column(MEDIUMTEXT)
    create_time: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        UniqueConstraint(
            "case_run_id",
            "metric_name",
            "evaluator_version",
            name="uniq_eval_score_key",
        ),
    )
