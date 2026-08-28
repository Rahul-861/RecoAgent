"""
Database layer. Uses SQLAlchemy so the same code works against the default
local SQLite file (zero-config demo) or a Supabase/Postgres URL in prod --
just swap DATABASE_URL in .env.

v2: generalized from a fixed "source A / source B" pair to N canonical
sources (bank / processor / erp) per README §6, plus the fields needed for
fee-aware, many-to-one/one-to-many, refund, and financial-event-graph
reconciliation (§7, §13-17).
"""
import json
import uuid
from datetime import datetime, date

from sqlalchemy import (
    create_engine, Column, String, Float, Integer, Boolean, Text, DateTime, Date
)
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Batch(Base):
    __tablename__ = "batches"
    batch_id = Column(String, primary_key=True, default=lambda: new_id("batch"))
    created_at = Column(DateTime, default=datetime.utcnow)

    bank_count = Column(Integer, default=0)
    processor_count = Column(Integer, default=0)
    erp_count = Column(Integer, default=0)
    has_answer_key = Column(Boolean, default=False)

    status = Column(String, default="uploaded")  # uploaded | running | done
    match_rate = Column(Float, nullable=True)
    manual_review_reduction = Column(Float, nullable=True)
    stage_breakdown_json = Column(Text, nullable=True)
    llm_call_count = Column(Integer, default=0)
    llm_batched_call_count = Column(Integer, default=0)
    failover_count = Column(Integer, default=0)
    processing_ms = Column(Float, nullable=True)
    throughput_per_sec = Column(Float, nullable=True)
    settlement_variance = Column(Float, nullable=True)
    pipeline_version = Column(String, nullable=True)
    normalization_version = Column(String, nullable=True)
    rule_set_version = Column(String, nullable=True)
    configuration_version = Column(String, nullable=True)
    validation_status = Column(String, nullable=True)
    control_totals_json = Column(Text, nullable=True)
    invalid_count = Column(Integer, default=0)
    reconciliation_run_id = Column(String, nullable=True)
    audit_completeness = Column(Float, nullable=True)


class TransactionRow(Base):
    """Canonical transaction record (README §6)."""
    __tablename__ = "transactions"
    id = Column(String, primary_key=True, default=lambda: new_id("txn"))
    batch_id = Column(String, index=True)

    source = Column(String)  # "bank" | "processor" | "erp"
    source_record_id = Column(String)  # original id from that system
    transaction_type = Column(String, nullable=True)  # payment|refund|fee|settlement|journal|credit|debit

    transaction_date = Column(Date, nullable=True)
    value_date = Column(Date, nullable=True)

    amount = Column(Float, nullable=True)          # the "headline" amount for this row
    gross_amount = Column(Float, nullable=True)
    fee_amount = Column(Float, nullable=True)
    refund_amount = Column(Float, nullable=True)
    net_amount = Column(Float, nullable=True)
    currency = Column(String, default="INR")

    # Optional canonical fields (README §4) -- only populated when the
    # source CSV actually has a matching column. Left NULL otherwise so we
    # never fabricate financial data.
    tax_amount = Column(Float, nullable=True)
    chargeback_amount = Column(Float, nullable=True)
    parent_transaction_id = Column(String, nullable=True)

    reference = Column(String, nullable=True)
    invoice_id = Column(String, nullable=True)
    order_id = Column(String, nullable=True)
    payment_id = Column(String, nullable=True)
    settlement_id = Column(String, nullable=True)

    counterparty = Column(String, nullable=True)
    description = Column(String, nullable=True)
    status = Column(String, nullable=True)

    embedding_json = Column(Text, nullable=True)
    raw_row_json = Column(Text, nullable=True)
    original_amount = Column(String, nullable=True)
    reference_normalized = Column(String, nullable=True)
    counterparty_normalized = Column(String, nullable=True)
    description_normalized = Column(String, nullable=True)
    normalization_version = Column(String, nullable=True)
    recon_state = Column(String, default="UNPROCESSED")
    is_valid = Column(Boolean, default=True)
    validation_errors_json = Column(Text, nullable=True)


class MatchResult(Base):
    """
    A resolved relationship (or exception) between two canonical records,
    or between a group of records and one counterpart (many-to-one /
    one-to-many). Generalized from the old source_a/source_b pair.
    """
    __tablename__ = "matches"
    match_id = Column(String, primary_key=True, default=lambda: new_id("match"))
    batch_id = Column(String, index=True)

    left_source = Column(String, nullable=True)
    left_txn_ids_json = Column(Text, nullable=True)   # list[str] -- supports many-to-one
    right_source = Column(String, nullable=True)
    right_txn_ids_json = Column(Text, nullable=True)  # list[str] -- supports one-to-many

    match_stage = Column(String)
    # exact | fee_aware | many_to_one | one_to_many | fuzzy | semantic |
    # llm | refund | unresolved
    confidence = Column(Float, default=0.0)
    reason = Column(Text, default="")
    candidates_shown_json = Column(Text, nullable=True)
    provider_used = Column(String, nullable=True)  # groq | gemini | heuristic | null

    status = Column(String, default="matched")  # matched | exception
    exception_type = Column(String, nullable=True)
    severity = Column(String, nullable=True)     # low | medium | high
    review_status = Column(String, default="open")  # open | resolved | rejected
    correct_by_answer_key = Column(Boolean, nullable=True)

    decision = Column(String, nullable=True)
    state = Column(String, nullable=True)
    decision_stage = Column(String, nullable=True)
    rule_id = Column(String, nullable=True)
    rule_set_version = Column(String, nullable=True)
    pipeline_version = Column(String, nullable=True)
    normalization_version = Column(String, nullable=True)
    evidence_json = Column(Text, nullable=True)
    contradictions_json = Column(Text, nullable=True)
    candidate_ids_json = Column(Text, nullable=True)
    top_score = Column(Float, nullable=True)
    second_score = Column(Float, nullable=True)
    score_margin = Column(Float, nullable=True)
    relationship_type = Column(String, nullable=True)
    exception_category = Column(String, nullable=True)
    exception_lifecycle = Column(String, default="OPEN")
    resolution_note = Column(Text, nullable=True)
    resolved_by = Column(String, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    # The candidate the human explicitly picked as the correct counterpart
    # when resolving (README §5/§7). Recorded at resolve time; makes an
    # ambiguous multi-candidate exception learnable because the approval is
    # attached to a specific record instead of guessed.
    chosen_candidate_id = Column(String, nullable=True)
    ai_used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ExceptionResolution(Base):
    """
    Append-only human-resolution history (README §17 / Definition of Done
    "resolution history is preserved"). One row per review action.

    `MatchResult` still carries the *current* review_status/resolution_note
    for cheap reads (dashboard, exception queue), but that is now a
    denormalized "latest" projection over this table -- nothing is ever
    deleted from here, so a match's full review history survives even if
    it is resolved, reopened, and resolved again.
    """
    __tablename__ = "exception_resolutions"
    id = Column(String, primary_key=True, default=lambda: new_id("res"))
    match_id = Column(String, index=True)
    batch_id = Column(String, index=True)

    action = Column(String)  # resolved | rejected | escalated | in_review
    previous_lifecycle = Column(String, nullable=True)
    new_lifecycle = Column(String, nullable=True)
    note = Column(Text, nullable=True)
    resolved_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class MemoryMapping(Base):
    """Reconciliation memory (README §7): a counterparty/reference mapping a
    human effectively approved by resolving an exception. Every row is derived
    from a real human resolution of a real match -- nothing is fabricated or
    seeded. Re-approval of the same pair increments `approval_count`."""
    __tablename__ = "memory_mappings"
    id = Column(String, primary_key=True, default=lambda: new_id("mem"))
    mapping_kind = Column(String)               # counterparty | reference
    raw_value = Column(String)                  # e.g. "AMZN PAYMENTS INDIA"
    canonical_value = Column(String)            # e.g. "AMAZON INDIA"
    approval_count = Column(Integer, default=1)
    status = Column(String, default="active")   # active | retired
    rule_source = Column(String, nullable=True)  # LearnedRule.rule_id that encodes it
    origin_match_id = Column(String, index=True, nullable=True)
    origin_batch_id = Column(String, index=True, nullable=True)
    exception_type = Column(String, nullable=True)
    first_approved_at = Column(DateTime, default=datetime.utcnow)
    last_approved_at = Column(DateTime, default=datetime.utcnow)
    last_batch_id = Column(String, nullable=True)
    # The actual transaction rows this mapping was derived from (README section 6).
    # For a source/target pairing these are the left/right TransactionRow ids;
    # for a standalone self-identity mapping both point to the same row.
    source_transaction_id = Column(String, index=True, nullable=True)
    target_transaction_id = Column(String, index=True, nullable=True)
    # The human who approved this mapping (README section 5/7) -- sourced from
    # match.resolved_by at resolution time, never fabricated.
    reviewer = Column(String, nullable=True)


class AuditEvent(Base):
    """Structured audit trail for the memory lifecycle (README section 16).

    One immutable row per meaningful memory action so every part of the
    human-decision, memory, learned rule, suggestion loop is
    auditable and append-only.
    """
    __tablename__ = "audit_events"
    id = Column(String, primary_key=True, default=lambda: new_id("aud"))
    event_type = Column(
        String, nullable=False
    )  # MAPPING_APPROVED | MEMORY_CREATED | RULE_CREATED | SUGGESTION_GENERATED
    match_id = Column(String, index=True, nullable=True)
    batch_id = Column(String, index=True, nullable=True)
    reviewer = Column(String, nullable=True)
    details_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class LearnedRule(Base):
    """Exception -> rule learning (README §8): a reusable pattern recorded when
    a human resolves an exception. Rule ID, name, version and approval status
    are real -- the rule exists only because a human approved the underlying
    mapping. Re-approval bumps `version` and `times_approved`."""
    __tablename__ = "learned_rules"
    rule_id = Column(String, primary_key=True, default=lambda: new_id("LR"))
    name = Column(String)
    kind = Column(String)                        # counterparty_mapping | reference_mapping
    pattern_json = Column(Text)                  # {"raw": ..., "canonical": ...}
    version = Column(Integer, default=1)
    approval_status = Column(String, default="human_approved")
    origin_match_id = Column(String, index=True, nullable=True)
    origin_batch_id = Column(String, index=True, nullable=True)
    exception_type = Column(String, nullable=True)
    times_approved = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class AnswerKeyRow(Base):
    """
    Ground-truth row: says what a given (source, txn id) SHOULD resolve to.
    expected_match_ids_json supports many-to-one/one-to-many ground truth
    (a list, usually length 1).
    """
    __tablename__ = "answer_key"
    id = Column(String, primary_key=True, default=lambda: new_id("ak"))
    batch_id = Column(String, index=True)
    source = Column(String)
    transaction_id = Column(String)
    expected_match_source = Column(String, nullable=True)
    expected_match_ids_json = Column(Text, nullable=True)
    expected_exception_type = Column(String, nullable=True)


class CashForecastRun(Base):
    """
    One forecast run over an already-reconciled batch (README §41.6).
    Additive table -- the forecaster only *reads* Batch/TransactionRow/
    MatchResult; nothing here changes the reconciliation schema above.
    Idempotent per (batch_id, as_of_date, horizon_days) unless ?force=true,
    mirroring Batch.reconciliation_run_id for POST /api/reconcile.
    """
    __tablename__ = "cash_forecast_runs"
    run_id = Column(String, primary_key=True, default=lambda: new_id("fcst"))
    batch_id = Column(String, index=True)
    as_of_date = Column(Date)
    horizon_days = Column(Integer)
    opening_balance = Column(Float, nullable=True)
    forecast_version = Column(String, nullable=True)
    lag_model_version = Column(String, nullable=True)
    forecast_llm_call_count = Column(Integer, default=0)
    forecast_failover_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class CashForecastLine(Base):
    """One bucketed line item within a CashForecastRun (README §41.6)."""
    __tablename__ = "cash_forecast_lines"
    line_id = Column(String, primary_key=True, default=lambda: new_id("fcln"))
    run_id = Column(String, index=True)
    batch_id = Column(String, index=True)

    bucket_date = Column(Date, nullable=True)
    category = Column(String)       # CONFIRMED | EXPECTED | AT_RISK | UNCLASSIFIABLE
    direction = Column(String, nullable=True)  # inflow | outflow
    amount = Column(Float)
    currency = Column(String, nullable=True)
    confidence = Column(String, nullable=True)  # high | medium | low
    lag_source = Column(String, nullable=True)   # observed | default | ai_estimated | null
    source_match_ids_json = Column(Text, nullable=True)
    evidence_json = Column(Text, nullable=True)
    ai_used = Column(Boolean, default=False)


def init_db():
    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_columns()


def _ensure_sqlite_columns():
    """Add columns introduced after the original schema so existing SQLite files keep working."""
    if not settings.DATABASE_URL.startswith("sqlite"):
        return
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    extras = {
        "batches": [
            ("pipeline_version", "VARCHAR"),
            ("normalization_version", "VARCHAR"),
            ("rule_set_version", "VARCHAR"),
            ("configuration_version", "VARCHAR"),
            ("validation_status", "VARCHAR"),
            ("control_totals_json", "TEXT"),
            ("invalid_count", "INTEGER"),
            ("reconciliation_run_id", "VARCHAR"),
            ("audit_completeness", "FLOAT"),
        ],
        "transactions": [
            ("tax_amount", "FLOAT"),
            ("chargeback_amount", "FLOAT"),
            ("parent_transaction_id", "VARCHAR"),
            ("original_amount", "VARCHAR"),
            ("reference_normalized", "VARCHAR"),
            ("counterparty_normalized", "VARCHAR"),
            ("description_normalized", "VARCHAR"),
            ("normalization_version", "VARCHAR"),
            ("recon_state", "VARCHAR"),
            ("is_valid", "BOOLEAN"),
            ("validation_errors_json", "TEXT"),
        ],
        "memory_mappings": [
            ("source_transaction_id", "VARCHAR"),
            ("target_transaction_id", "VARCHAR"),
            ("reviewer", "VARCHAR"),
        ],
        "matches": [
            ("decision", "VARCHAR"),
            ("state", "VARCHAR"),
            ("decision_stage", "VARCHAR"),
            ("rule_id", "VARCHAR"),
            ("rule_set_version", "VARCHAR"),
            ("pipeline_version", "VARCHAR"),
            ("normalization_version", "VARCHAR"),
            ("evidence_json", "TEXT"),
            ("contradictions_json", "TEXT"),
            ("candidate_ids_json", "TEXT"),
            ("top_score", "FLOAT"),
            ("second_score", "FLOAT"),
            ("score_margin", "FLOAT"),
            ("relationship_type", "VARCHAR"),
            ("exception_category", "VARCHAR"),
            ("exception_lifecycle", "VARCHAR"),
            ("resolution_note", "TEXT"),
            ("resolved_by", "VARCHAR"),
            ("resolved_at", "DATETIME"),
            ("ai_used", "BOOLEAN"),
            ("chosen_candidate_id", "VARCHAR"),
            ("created_at", "DATETIME"),
        ],
    }
    with engine.begin() as conn:
        for table, cols in extras.items():
            if table not in inspector.get_table_names():
                continue
            existing = {c["name"] for c in inspector.get_columns(table)}
            for name, coltype in cols:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {coltype}"))


def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def dumps(obj) -> str:
    return json.dumps(obj, default=str)


def loads(s):
    if not s:
        return None
    return json.loads(s)
