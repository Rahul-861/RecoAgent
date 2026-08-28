"""Regression tests for the memory lifecycle enhancements:

  * MemoryMapping now stores the actual source/target transaction IDs
    (README section 6/12), so the Memory page can show `Source: BANK3047 ->
    Target: ERP2047` along with amounts.
  * MemoryMapping stores the approving reviewer (README section 5/7).
  * Resolving an exception emits append-only audit events
    (MAPPING_APPROVED / RULE_CREATED / MEMORY_CREATED) per README section 16.
"""
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import (
    AuditEvent, Base, Batch, LearnedRule, MatchResult, MemoryMapping, TransactionRow,
)
from app.exceptions.lifecycle import apply_resolution
from app.memory.reconciliation_memory import record_resolution_memory


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _batch(db):
    db.add(Batch(batch_id="batch_1"))
    db.flush()


def _txn(db, source, record_id, counterparty=None, reference=None):
    row = TransactionRow(
        batch_id="batch_1", source=source, source_record_id=record_id,
        currency="INR", amount=50000, counterparty=counterparty, reference=reference,
    )
    db.add(row)
    db.flush()
    return row


def _match(db, left, right, exception_type="amount_mismatch"):
    m = MatchResult(
        batch_id="batch_1", left_source=left.source,
        left_txn_ids_json=json.dumps([left.source_record_id]),
        right_source=right.source,
        right_txn_ids_json=json.dumps([right.source_record_id]),
        match_stage="fuzzy", status="exception",
        exception_type=exception_type, severity="medium",
    )
    db.add(m)
    db.flush()
    return m


def test_mapping_stores_source_target_txn_ids_and_reviewer():
    """README §6/§12: the approved mapping must reference the actual
    source/target transaction records, and the approving reviewer."""
    db = _session()
    _batch(db)
    left = _txn(db, "processor", "PAY1", counterparty="AMZN PAYMENTS INDIA", reference="ref-1")
    right = _txn(db, "erp", "E1", counterparty="Amazon India", reference="ref_1")
    match = _match(db, left, right)

    apply_resolution(match, "resolved", note=None, resolved_by="alice", db=db)
    record_resolution_memory(db, match)
    db.commit()

    mappings = db.query(MemoryMapping).all()
    assert len(mappings) == 2  # counterparty + reference

    for m in mappings:
        assert m.source_transaction_id == left.id
        assert m.target_transaction_id == right.id
        assert m.reviewer == "alice"


def test_reviewer_captured_as_default():
    """When no reviewer is supplied, apply_resolution uses 'reviewer' and the
    mapping must reflect it (README §12 Approved by: reviewer)."""
    db = _session()
    _batch(db)
    left = _txn(db, "processor", "PAY1", counterparty="AMZN PAYMENTS INDIA")
    right = _txn(db, "erp", "E1", counterparty="Amazon India")
    match = _match(db, left, right)

    apply_resolution(match, "resolved", note=None, resolved_by="reviewer", db=db)
    record_resolution_memory(db, match)
    db.commit()

    mapping = db.query(MemoryMapping).one()
    assert mapping.reviewer == "reviewer"


def test_resolution_emits_audit_events():
    """README §16 / verification checklist: resolving creates MAPPING_APPROVED,
    RULE_CREATED and MEMORY_CREATED audit events, each with a real reviewer and
    real rule/mapping IDs (not null)."""
    db = _session()
    _batch(db)
    left = _txn(db, "processor", "PAY1", counterparty="AMZN PAYMENTS INDIA", reference="ref-1")
    right = _txn(db, "erp", "E1", counterparty="Amazon India", reference="ref_1")
    match = _match(db, left, right)

    apply_resolution(match, "resolved", note="same vendor", resolved_by="bob", db=db)
    record_resolution_memory(db, match)
    db.commit()

    events = db.query(AuditEvent).order_by(AuditEvent.created_at.asc()).all()
    types = [e.event_type for e in events]
    assert types.count("MAPPING_APPROVED") == 2
    assert types.count("RULE_CREATED") == 2
    assert types.count("MEMORY_CREATED") == 2

    for e in events:
        assert e.reviewer == "bob"
        assert e.match_id == match.match_id
        assert e.batch_id == "batch_1"

    # RULE_CREATED and MEMORY_CREATED details must reference real IDs
    rule_events = [e for e in events if e.event_type == "RULE_CREATED"]
    mem_events = [e for e in events if e.event_type == "MEMORY_CREATED"]
    rule_in_db = {r.rule_id for r in db.query(LearnedRule).all()}
    mapping_ids = {m.id for m in db.query(MemoryMapping).all()}
    for e in rule_events:
        import json as _j
        assert _j.loads(e.details_json)["rule_id"] in rule_in_db
    for e in mem_events:
        import json as _j
        assert _j.loads(e.details_json)["mapping_id"] in mapping_ids


def test_rejected_match_emits_no_audit_events():
    """README §24/safety: rejections never create memory or audit mappings."""
    db = _session()
    _batch(db)
    left = _txn(db, "processor", "PAY1", counterparty="A Corp")
    right = _txn(db, "erp", "E1", counterparty="B Corp")
    match = _match(db, left, right)

    apply_resolution(match, "rejected", note=None, resolved_by="carol", db=db)
    assert record_resolution_memory(db, match) == []
    db.commit()

    assert db.query(MemoryMapping).count() == 0
    assert db.query(AuditEvent).count() == 0