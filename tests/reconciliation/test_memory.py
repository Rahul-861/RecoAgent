"""Reconciliation memory + learned rules (README §7/§8).

These tests exercise the real recording path used by
POST /api/exceptions/{match_id}/resolve: a human "resolved" action approves
the counterparty/reference pairing the two sides carry. Rejections record
nothing; matches without a counterpart record nothing; identical values carry
no mapping information.
"""
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, Batch, LearnedRule, MatchResult, MemoryMapping, TransactionRow
from app.exceptions.lifecycle import apply_resolution
from app.memory.reconciliation_memory import record_resolution_memory


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _txn(db, batch_id, source, record_id, counterparty=None, reference=None):
    row = TransactionRow(
        batch_id=batch_id,
        source=source,
        source_record_id=record_id,
        currency="INR",
        amount=50000,
        counterparty=counterparty,
        reference=reference,
    )
    db.add(row)
    db.flush()
    return row


def _match(db, batch_id, left_ids, right_ids, exception_type="amount_mismatch"):
    match = MatchResult(
        batch_id=batch_id,
        left_source="processor",
        left_txn_ids_json=json.dumps(left_ids),
        right_source="erp",
        right_txn_ids_json=json.dumps(right_ids),
        match_stage="fuzzy",
        status="exception",
        exception_type=exception_type,
        severity="medium",
    )
    db.add(match)
    db.flush()
    return match


def test_resolved_match_records_mapping_and_rule():
    db = _session()
    batch = Batch(batch_id="batch_1")
    db.add(batch)
    db.flush()
    left = _txn(db, "batch_1", "processor", "P1", counterparty="AMZN PAYMENTS INDIA")
    right = _txn(db, "batch_1", "erp", "E1", counterparty="Amazon India")
    match = _match(db, "batch_1", [left.source_record_id], [right.source_record_id])

    apply_resolution(match, "resolved", note="same vendor", resolved_by="reviewer", db=db)
    touched = record_resolution_memory(db, match)
    db.commit()

    assert len(touched) == 1
    mapping = db.query(MemoryMapping).one()
    assert mapping.mapping_kind == "counterparty"
    assert mapping.raw_value == "AMZN PAYMENTS INDIA"
    assert mapping.canonical_value == "Amazon India"
    assert mapping.approval_count == 1
    assert mapping.status == "active"
    assert mapping.rule_source == touched[0]
    assert mapping.last_batch_id == "batch_1"

    rule = db.query(LearnedRule).one()
    assert rule.rule_id == touched[0]
    assert rule.kind == "counterparty_mapping"
    assert rule.version == 1
    assert rule.approval_status == "human_approved"
    assert rule.times_approved == 1
    assert rule.origin_batch_id == "batch_1"


def test_repeat_approval_bumps_count_and_version():
    db = _session()
    db.add(Batch(batch_id="batch_1"))
    db.add(Batch(batch_id="batch_2"))
    db.flush()

    left1 = _txn(db, "batch_1", "processor", "P1", counterparty="AMZN PAYMENTS INDIA")
    right1 = _txn(db, "batch_1", "erp", "E1", counterparty="Amazon India")
    m1 = _match(db, "batch_1", [left1.source_record_id], [right1.source_record_id])
    apply_resolution(m1, "resolved", note=None, resolved_by="reviewer", db=db)
    record_resolution_memory(db, m1)
    db.commit()

    left2 = _txn(db, "batch_2", "processor", "P2", counterparty="AMZN PAYMENTS INDIA")
    right2 = _txn(db, "batch_2", "erp", "E2", counterparty="Amazon India")
    m2 = _match(db, "batch_2", [left2.source_record_id], [right2.source_record_id])
    apply_resolution(m2, "resolved", note=None, resolved_by="reviewer", db=db)
    record_resolution_memory(db, m2)
    db.commit()

    mapping = db.query(MemoryMapping).one()
    assert mapping.approval_count == 2
    assert mapping.last_batch_id == "batch_2"

    rule = db.query(LearnedRule).one()
    assert rule.version == 2
    assert rule.times_approved == 2


def test_rejected_match_records_nothing():
    db = _session()
    db.add(Batch(batch_id="batch_1"))
    db.flush()
    left = _txn(db, "batch_1", "processor", "P1", counterparty="A Corp")
    right = _txn(db, "batch_1", "erp", "E1", counterparty="B Corp")
    match = _match(db, "batch_1", [left.source_record_id], [right.source_record_id])

    apply_resolution(match, "rejected", note=None, resolved_by="reviewer", db=db)
    assert record_resolution_memory(db, match) == []
    db.commit()
    assert db.query(MemoryMapping).count() == 0
    assert db.query(LearnedRule).count() == 0


def test_missing_counterpart_records_nothing():
    db = _session()
    db.add(Batch(batch_id="batch_1"))
    db.flush()
    left = _txn(db, "batch_1", "processor", "P1", counterparty="Mystery Ltd")
    match = _match(
        db, "batch_1", [left.source_record_id], [], exception_type="missing_counterpart"
    )

    apply_resolution(match, "resolved", note=None, resolved_by="reviewer", db=db)
    assert record_resolution_memory(db, match) == []
    db.commit()
    assert db.query(MemoryMapping).count() == 0


def test_identical_values_are_not_learned():
    db = _session()
    db.add(Batch(batch_id="batch_1"))
    db.flush()
    # Same counterparty on both sides -> nothing learnable there; references
    # differ -> exactly one (reference) mapping is recorded.
    left = _txn(db, "batch_1", "processor", "P1", counterparty="Acme", reference="REF-1")
    right = _txn(db, "batch_1", "erp", "E1", counterparty="Acme", reference="ref_1")
    match = _match(db, "batch_1", [left.source_record_id], [right.source_record_id])

    apply_resolution(match, "resolved", note=None, resolved_by="reviewer", db=db)
    touched = record_resolution_memory(db, match)
    db.commit()

    assert len(touched) == 1
    mapping = db.query(MemoryMapping).one()
    assert mapping.mapping_kind == "reference"


def _leftonly_match(db, batch_id, left_ids, exception_type="missing_counterpart"):
    match = MatchResult(
        batch_id=batch_id,
        left_source="bank",
        left_txn_ids_json=json.dumps(left_ids),
        right_source=None,
        right_txn_ids_json=json.dumps([]),
        match_stage="unresolved",
        status="exception",
        exception_type=exception_type,
        severity="medium",
    )
    db.add(match)
    db.flush()
    return match


def test_standalone_resolved_row_with_identity_records_self_mapping():
    """Regression for the reported symptom: resolving a lone bank row (an
    `unidentified_cash` / `missing_counterpart` exception) used to record no
    reconciliation memory, so the Memory page stayed at 0 even after the
    resolution. A row that carries its own counterparty text plus its own
    reference must now produce exactly one approved mapping."""
    db = _session()
    db.add(Batch(batch_id="batch_1"))
    db.flush()
    # Mirrors the normalization of the repro bank row (BANK2047):
    # counter-text from the description, plus its own reference.
    _txn(db, "batch_1", "bank", "BANK2047", counterparty="NET SETTLEMENT PAY 2047",
         reference="PAY2047")
    match = _leftonly_match(db, "batch_1", ["BANK2047"], exception_type="unidentified_cash")

    apply_resolution(match, "resolved", note=None, resolved_by="reviewer", db=db)
    touched = record_resolution_memory(db, match)
    db.commit()

    assert len(touched) == 1
    mapping = db.query(MemoryMapping).one()
    assert mapping.mapping_kind == "reference"
    assert mapping.raw_value == "NET SETTLEMENT PAY 2047"
    assert mapping.canonical_value == "PAY2047"
    assert mapping.approval_count == 1
    assert mapping.origin_batch_id == "batch_1"

    rule = db.query(LearnedRule).one()
    assert rule.rule_id == touched[0]
    assert rule.times_approved == 1


def test_standalone_row_blank_or_self_identical_records_nothing():
    db = _session()
    db.add(Batch(batch_id="batch_1"))
    db.flush()
    # No reference at all  -> nothing learnable.
    _txn(db, "batch_1", "bank", "BANK1", counterparty="Mystery Ltd")
    m1 = _leftonly_match(db, "batch_1", ["BANK1"], exception_type="unidentified_cash")
    apply_resolution(m1, "resolved", note=None, resolved_by="reviewer", db=db)
    assert record_resolution_memory(db, m1) == []

    # Counterparty text identical to the reference carries no information.
    _txn(db, "batch_1", "bank", "BANK2", counterparty="PAY1002", reference="PAY1002")
    m2 = _leftonly_match(db, "batch_1", ["BANK2"], exception_type="unidentified_cash")
    apply_resolution(m2, "resolved", note=None, resolved_by="reviewer", db=db)
    assert record_resolution_memory(db, m2) == []

    db.commit()
    assert db.query(MemoryMapping).count() == 0
    assert db.query(LearnedRule).count() == 0


def test_re_resolving_same_exception_upserts_not_duplicates():
    """The reproduction's exception went RESOLVED -> ESCALATED -> RESOLVED.
    Recording must not create duplicate mappings for the same exception --
    it must upsert (bump the approval count) instead."""
    db = _session()
    db.add(Batch(batch_id="batch_1"))
    db.flush()
    _txn(db, "batch_1", "bank", "BANK3", counterparty="NET SETTLEMENT PAY2047",
         reference="PAY2047", )
    match = _leftonly_match(db, "batch_1", ["BANK3"], exception_type="unidentified_cash")

    apply_resolution(match, "resolved", note=None, resolved_by="reviewer", db=db)
    first = record_resolution_memory(db, match)
    apply_resolution(match, "escalated", note=None, resolved_by="reviewer", db=db)
    apply_resolution(match, "resolved", note=None, resolved_by="reviewer", db=db)
    second = record_resolution_memory(db, match)
    db.commit()

    assert set(first) == set(second)
    assert db.query(MemoryMapping).count() == 1
    mapping = db.query(MemoryMapping).one()
    assert mapping.approval_count == 2
    rule = db.query(LearnedRule).one()
    assert rule.times_approved == 2


def test_two_different_counterparties_produce_two_mappings():
    """README verification step 4: resolving a second exception for a
    *different* counterparty must add a second mapping -- not overwrite the
    first. Upsert is keyed on (kind, raw, canonical), so distinct
    counterparties coexist as separate rows."""
    db = _session()
    db.add(Batch(batch_id="batch_1"))
    db.flush()

    # First exception: AMZN PAYMENTS INDIA <-> Amazon India
    left1 = _txn(db, "batch_1", "processor", "P1", counterparty="AMZN PAYMENTS INDIA")
    right1 = _txn(db, "batch_1", "erp", "E1", counterparty="Amazon India")
    m1 = _match(db, "batch_1", [left1.source_record_id], [right1.source_record_id])
    apply_resolution(m1, "resolved", note=None, resolved_by="reviewer", db=db)
    record_resolution_memory(db, m1)
    db.commit()

    # Second exception: a different counterparty pair
    left2 = _txn(db, "batch_1", "processor", "P2", counterparty="CRESTLINE FOODS")
    right2 = _txn(db, "batch_1", "erp", "E2", counterparty="Crestline Foods Ltd")
    m2 = _match(db, "batch_1", [left2.source_record_id], [right2.source_record_id])
    apply_resolution(m2, "resolved", note=None, resolved_by="reviewer", db=db)
    record_resolution_memory(db, m2)
    db.commit()

    mappings = db.query(MemoryMapping).all()
    assert len(mappings) == 2
    raw_values = {m.raw_value for m in mappings}
    assert "AMZN PAYMENTS INDIA" in raw_values
    assert "CRESTLINE FOODS" in raw_values
    assert db.query(LearnedRule).count() == 2
