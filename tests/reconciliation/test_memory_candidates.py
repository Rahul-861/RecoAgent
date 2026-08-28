"""Regression: resolving an in-pipeline exception populates reconciliation
memory via its candidate rows (README Bug 2).

The common in-pipeline exception shape (duplicate / duplicate_refund /
amount_mismatch) is persisted with only a left side -- the near-candidate
counterpart(s) live in `candidate_ids` rather than `right_txn_ids`. Before
the fix, resolving such a row recorded nothing, so Memory stayed at 0. These
tests lock in the candidate-fallback extraction and its ambiguity guard.
"""
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, Batch, MatchResult, MemoryMapping, TransactionRow
from app.exceptions.lifecycle import apply_resolution
from app.memory.reconciliation_memory import record_resolution_memory


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _txn(db, batch_id, source, record_id, counterparty=None, reference=None):
    row = TransactionRow(
        batch_id=batch_id, source=source, source_record_id=record_id,
        currency="INR", amount=50000, counterparty=counterparty, reference=reference,
    )
    db.add(row)
    db.flush()
    return row


def _leftonly_match(db, batch_id, left_ids, candidate_ids, exception_type="duplicate"):
    match = MatchResult(
        batch_id=batch_id,
        left_source="processor",
        left_txn_ids_json=json.dumps(left_ids),
        right_source=None,
        right_txn_ids_json=json.dumps([]),
        candidate_ids_json=json.dumps(candidate_ids),
        match_stage="unresolved",
        status="exception",
        exception_type=exception_type,
        severity="high",
    )
    db.add(match)
    db.flush()
    return match


def test_duplicate_same_vendor_records_counterparty_mapping():
    db = _session()
    db.add(Batch(batch_id="batch_1"))
    db.flush()
    left = _txn(db, "batch_1", "processor", "PAY1", counterparty="ACME TRADERS")
    # Two candidate bank rows, same vendor (but a different spelling than the
    # left side) and distinct references.
    _txn(db, "batch_1", "bank", "B1", counterparty="Acme Traders Pvt Ltd", reference="UTR-1")
    _txn(db, "batch_1", "bank", "B2", counterparty="Acme Traders Pvt Ltd", reference="UTR-2")

    match = _leftonly_match(db, "batch_1", [left.source_record_id], ["B1", "B2"])
    apply_resolution(match, "resolved", note=None, resolved_by="reviewer", db=db)
    touched = record_resolution_memory(db, match)
    db.commit()

    assert touched
    mappings = db.query(MemoryMapping).all()
    assert any(m.mapping_kind == "counterparty" for m in mappings)


def test_multi_entity_candidates_are_not_fabricated():
    db = _session()
    db.add(Batch(batch_id="batch_1"))
    db.flush()
    left = _txn(db, "batch_1", "processor", "PAY1", counterparty="ACME TRADERS")
    _txn(db, "batch_1", "bank", "B1", counterparty="BLUEWAVE LOGISTICS")
    _txn(db, "batch_1", "bank", "B2", counterparty="CRESTLINE FOODS")

    match = _leftonly_match(db, "batch_1", [left.source_record_id], ["B1", "B2"])
    apply_resolution(match, "resolved", note=None, resolved_by="reviewer", db=db)
    touched = record_resolution_memory(db, match)
    db.commit()

    # Two different candidate counterparties with no recorded pick is
    # ambiguous -- we must not invent an approval for either.
    assert touched == []
    assert db.query(MemoryMapping).count() == 0


def test_chosen_candidate_records_exact_pairing():
    """The human picked the correct counterpart in the UI: the approval
    attaches to that specific record, so the ambiguous multi-candidate case
    (amount_mismatch with many different vendors) becomes learnable."""
    db = _session()
    db.add(Batch(batch_id="batch_1"))
    db.flush()
    left = _txn(db, "batch_1", "processor", "JNL1", counterparty="Indigo Health", reference="PAY2037")
    _txn(db, "batch_1", "bank", "B1", counterparty="NET SETTLEMENT PAY2033", reference="PAY2033")
    chosen = _txn(db, "batch_1", "bank", "B2", counterparty="NET SETTLEMENT PAY2037", reference="PAY2037")
    _txn(db, "batch_1", "bank", "B3", counterparty="PAYOUT PAY2095 ADJUSTED", reference="PAY2095")

    match = _leftonly_match(
        db, "batch_1", [left.source_record_id], ["B1", "B2", "B3"], exception_type="amount_mismatch"
    )
    match.chosen_candidate_id = "B2"
    apply_resolution(match, "resolved", note=None, resolved_by="reviewer", db=db)
    touched = record_resolution_memory(db, match)
    db.commit()

    assert touched
    mappings = db.query(MemoryMapping).all()
    # The reference is identical on both sides (PAY2037 == PAY2037), so only
    # the counterparty pairing carries information -- exactly that one pair,
    # tied to the specific record the human picked.
    assert [m.mapping_kind for m in mappings] == ["counterparty"]
    m = mappings[0]
    assert m.raw_value == "Indigo Health"
    assert m.canonical_value == "NET SETTLEMENT PAY2037"
    assert m.source_transaction_id == left.id
    assert m.target_transaction_id == chosen.id
    assert m.reviewer == "reviewer"


def test_chosen_candidate_with_different_reference_learns_both_kinds():
    db = _session()
    db.add(Batch(batch_id="batch_1"))
    db.flush()
    left = _txn(db, "batch_1", "processor", "JNL1", counterparty="Indigo Health", reference="JNL-REF-1")
    chosen = _txn(db, "batch_1", "bank", "B2", counterparty="NET SETTLEMENT PAY2037", reference="PAY2037")
    _txn(db, "batch_1", "bank", "B1", counterparty="BLUEWAVE LOGISTICS", reference="PAY2033")

    match = _leftonly_match(db, "batch_1", [left.source_record_id], ["B1", "B2"], exception_type="amount_mismatch")
    match.chosen_candidate_id = "B2"
    apply_resolution(match, "resolved", note=None, resolved_by="alice", db=db)
    touched = record_resolution_memory(db, match)
    db.commit()

    mappings = db.query(MemoryMapping).all()
    assert sorted(m.mapping_kind for m in mappings) == ["counterparty", "reference"]
    ref = [m for m in mappings if m.mapping_kind == "reference"][0]
    assert (ref.raw_value, ref.canonical_value) == ("JNL-REF-1", "PAY2037")
    assert ref.reviewer == "alice"
    assert len(touched) == 2


def test_unknown_chosen_candidate_still_guarded():
    """A pick that matches no real row must not crash or fabricate -- the
    ambiguity guard still applies when no valid pick was recorded."""
    db = _session()
    db.add(Batch(batch_id="batch_1"))
    db.flush()
    left = _txn(db, "batch_1", "processor", "PAY1", counterparty="ACME TRADERS")
    _txn(db, "batch_1", "bank", "B1", counterparty="BLUEWAVE LOGISTICS")
    _txn(db, "batch_1", "bank", "B2", counterparty="CRESTLINE FOODS")

    match = _leftonly_match(db, "batch_1", [left.source_record_id], ["B1", "B2"])
    match.chosen_candidate_id = "GHOST-ID"  # not a real transaction row
    apply_resolution(match, "resolved", note=None, resolved_by="reviewer", db=db)
    touched = record_resolution_memory(db, match)
    db.commit()

    assert touched == []
    assert db.query(MemoryMapping).count() == 0


def test_missing_candidate_ids_still_learns_nothing():
    db = _session()
    db.add(Batch(batch_id="batch_1"))
    db.flush()
    left = _txn(db, "batch_1", "processor", "PAY1", counterparty="ACME TRADERS")
    match = _leftonly_match(db, "batch_1", [left.source_record_id], [])
    apply_resolution(match, "resolved", note=None, resolved_by="reviewer", db=db)
    assert record_resolution_memory(db, match) == []
    db.commit()
    assert db.query(MemoryMapping).count() == 0
