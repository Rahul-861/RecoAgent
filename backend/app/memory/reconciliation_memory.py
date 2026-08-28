"""Reconciliation memory + exception-to-rule learning (README §7/§8).

Records the reusable knowledge a human creates when they resolve an
exception: by confirming "this processor record corresponds to that ERP
record", the reviewer approves the counterparty/reference pairing those two
records carry. That approval is stored as:

  * a `MemoryMapping`  -- raw value → canonical value, with an approval
    count, status, rule source and last-used information (README §7), and
  * a `LearnedRule`    -- rule ID, name, version and approval status
    (README §8).

Nothing here is ever fabricated: every value of a mapping comes from real
`TransactionRow` columns that were part of the content of the resolved match, and
a mapping is only recorded when a human explicitly resolved the exception. A
resolved standalone row that has no counterpart on the far side (missing
counterpart / unidentified cash) stores nothing unless the row itself carries an
identity (its own counterparty text plus a reference) -- in which case the one
self-pairing the resolution affirms is recorded. A genuinely blank or
self-identical standalone row still records nothing.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.db import AuditEvent, LearnedRule, MemoryMapping, TransactionRow, dumps, loads


def _clean(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    v = str(value).strip()
    return v or None


def _same(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b:
        return False
    return a.casefold() == b.casefold()


def _candidate_rows(db: Session, match) -> List[TransactionRow]:
    """
    Exceptions produced by the pipeline (duplicate, amount_mismatch, ...) are
    usually persisted with only a left side -- the near-candidate counterpart(s)
    they presented to the human live in `candidates_shown` / `candidate_ids`
    rather than `right_txn_ids`. When a reviewer resolves such a row we still
    want to approve the counterparty/reference pairing it carries, so fall back
    to looking up those candidate rows directly.
    """
    if not getattr(match, "batch_id", None):
        return []
    ids = loads(getattr(match, "candidate_ids_json", None)) or []
    if not ids:
        return []
    return (
        db.query(TransactionRow)
        .filter(
            TransactionRow.batch_id == match.batch_id,
            TransactionRow.source != match.left_source,
            TransactionRow.source_record_id.in_(ids),
        )
        .all()
    )


def extract_mapping_pairs(db: Session, match) -> List[Tuple[str, str, str, Optional[str], Optional[str]]]:
    """
    Extract (kind, raw_value, canonical_value, source_txn_id, target_txn_id)
    pairs from a resolved match's own transactions.

    Cross-source pairs are learnable only when both sides exist and genuinely
    differ -- identical values carry no mapping information. A resolved match
    with no counterpart on the far side falls back to its candidate rows, or
    -- when it has none -- to the single row's own identity (see
    `_single_side_pairs`), which knows how to emit nothing for genuinely blank
    or self-identical rows.
    """
    left_ids = loads(match.left_txn_ids_json) or []
    if not left_ids:
        return []
    right_ids = loads(match.right_txn_ids_json) or []
    right_rows = []
    kind_allow = None  # None => no extra restriction (explicit right side)
    if right_ids:
        right_rows = (
            db.query(TransactionRow)
            .filter(TransactionRow.source == match.right_source, TransactionRow.source_record_id.in_(right_ids))
            .all()
        )
    else:
        # Did the human explicitly pick the correct counterpart in the UI?
        # That pick IS the approval -- pair the left row against exactly that
        # record, no ambiguity guard needed (both kinds are learnable).
        chosen = getattr(match, "chosen_candidate_id", None)
        if chosen:
            right_rows = (
                db.query(TransactionRow)
                .filter(
                    TransactionRow.batch_id == match.batch_id,
                    TransactionRow.source != match.left_source,
                    TransactionRow.source_record_id == chosen,
                )
                .all()
            )
            kind_allow = None
        if not right_rows:
            # No explicit pick recorded: fall back to the candidate rows the
            # row actually presented to the human.
            # Storing a genuinely multi-entity candidate list without a pick
            # is ambiguous. We learn a kind only when the candidates are
            # unanimous for that kind (e.g. a duplicate for a single vendor
            # shares one counterparty even if their references differ).
            right_rows = _candidate_rows(db, match)
            kind_allow = {
                "counterparty": len({_clean(r.counterparty) for r in right_rows if _clean(r.counterparty)}) <= 1,
                "reference": len({_clean(r.reference) for r in right_rows if _clean(r.reference)}) <= 1,
            }

    left_rows = (
        db.query(TransactionRow)
        .filter(TransactionRow.source == match.left_source, TransactionRow.source_record_id.in_(left_ids))
        .all()
    )

    if not right_rows:
        # No explicit right counterpart and no candidates. This is the standalone
        # single-source exception (missing counterpart / unidentified cash) --
        # there is nothing on the other side to pair it against. But a row that
        # carries its own identity (a real counterparty text and its own
        # reference) still encodes a pairing the reviewer just affirmed by
        # resolving it; record exactly that one self-pair and nothing more.
        return _single_side_pairs(match, left_rows)

    pairs: List[Tuple[str, str, str, Optional[str], Optional[str]]] = []
    seen = set()
    for l in left_rows:
        for r in right_rows:
            for kind, lv, rv in (
                ("counterparty", _clean(l.counterparty), _clean(r.counterparty)),
                ("reference", _clean(l.reference), _clean(r.reference)),
            ):
                if not lv or not rv or _same(lv, rv):
                    continue
                if kind_allow is not None and not kind_allow[kind]:
                    continue
                key = (kind, lv.casefold(), rv.casefold())
                if key in seen:
                    continue
                seen.add(key)
                pairs.append((kind, lv, rv, l.id, r.id))
    return pairs


def _single_side_pairs(match, left_rows) -> List[Tuple[str, str, str, Optional[str], Optional[str]]]:
    """
    Standalone single-source exception (missing_counterpart / unidentified
    cash): no counterpart on the far side and no candidate rows, so there is
    no cross-source pairing to learn. When the resolved row still carries its
    own identity -- a real counterparty/description text AND its own reference
    -- resolving it affirms that association, so we record that one pair and
    nothing more (kind = reference: the reference value is the canonical
    identity the counterparty text belongs to, exactly the "NET SETTLEMENT
    PAY2047 -> BANK3047" style mapping from the task's reproduction).

    A row that is blank or whose body text equals its reference carries no
    information and yields nothing. A multi-row left side is also skipped --
    we never guess which row the resolution refers to.
    """
    left_ids = loads(match.left_txn_ids_json) or []
    if len(left_ids) != 1 or not left_rows:
        return []
    row = left_rows[0]
    body = _clean(row.counterparty) or _clean(row.description)
    ref = _clean(row.reference)
    if not body or not ref or _same(body, ref):
        return []
    # Source and target are the same row -- the resolution affirms the
    # row's own counterparty-text -> reference pairing.
    return [("reference", body, ref, row.id, row.id)]

def _upsert_rule(db: Session, match, kind: str, raw: str, canonical: str) -> Tuple[LearnedRule, bool]:
    kind_name = f"{kind}_mapping"
    rules = db.query(LearnedRule).filter(LearnedRule.kind == kind_name).all()
    rule = None
    for r in rules:
        pattern = loads(r.pattern_json) or {}
        if _same(pattern.get("raw"), raw) and _same(pattern.get("canonical"), canonical):
            rule = r
            break

    if rule is not None:
        # Same pattern re-approved by a human: bump version + approval count.
        rule.version = (rule.version or 1) + 1
        rule.times_approved = (rule.times_approved or 1) + 1
        rule.updated_at = datetime.utcnow()
        return rule, False

    pretty = kind.replace("_", " ")
    return LearnedRule(
        name=f"{pretty.capitalize()}: {raw} → {canonical}",
        kind=kind_name,
        pattern_json=dumps({"raw": raw, "canonical": canonical}),
        version=1,
        approval_status="human_approved",
        origin_match_id=match.match_id,
        origin_batch_id=match.batch_id,
        exception_type=match.exception_type,
        times_approved=1,
        ), True


def _upsert_mapping(
    db: Session, match, kind: str, raw: str, canonical: str, rule_id: str,
    source_txn_id: Optional[str] = None, target_txn_id: Optional[str] = None,
) -> Tuple[MemoryMapping, bool]:
    mappings = (
        db.query(MemoryMapping).filter(MemoryMapping.mapping_kind == kind).all()
    )
    existing = None
    for m in mappings:
        if _same(m.raw_value, raw) and _same(m.canonical_value, canonical):
            existing = m
            break

    if existing is not None:
        existing.approval_count = (existing.approval_count or 1) + 1
        existing.last_approved_at = datetime.utcnow()
        existing.last_batch_id = match.batch_id
        existing.rule_source = rule_id
        if source_txn_id:
            existing.source_transaction_id = source_txn_id
        if target_txn_id:
            existing.target_transaction_id = target_txn_id
        if match.resolved_by:
            existing.reviewer = match.resolved_by
        return existing, False

    return MemoryMapping(
        mapping_kind=kind,
        raw_value=raw,
        canonical_value=canonical,
        approval_count=1,
        status="active",
        rule_source=rule_id,
        origin_match_id=match.match_id,
        origin_batch_id=match.batch_id,
        exception_type=match.exception_type,
        first_approved_at=datetime.utcnow(),
        last_approved_at=datetime.utcnow(),
        last_batch_id=match.batch_id,
        source_transaction_id=source_txn_id,
        target_transaction_id=target_txn_id,
        reviewer=match.resolved_by,
    ), True


def _record_audit(
    db: Session, event_type: str, match, reviewer: Optional[str], details: Optional[dict] = None
) -> AuditEvent:
    """Append an immutable audit event for a memory-lifecycle action (README section 16)."""
    evt = AuditEvent(
        event_type=event_type,
        match_id=match.match_id if hasattr(match, "match_id") else None,
        batch_id=getattr(match, "batch_id", None),
        reviewer=reviewer,
        details_json=dumps(details) if details else None,
    )
    db.add(evt)
    return evt


def record_resolution_memory(db: Session, match) -> List[str]:
    """
    Record reconciliation memory + learned rules for a human-resolved match.
    Called only for action == "resolved" -- a rejection or escalation approves
    nothing. Returns the rule IDs touched (possibly empty).
    """
    if (match.review_status or "").lower() != "resolved":
        return []

    touched: List[str] = []
    reviewer = match.resolved_by
    for kind, raw, canonical, src_id, tgt_id in extract_mapping_pairs(db, match):
        _record_audit(db, "MAPPING_APPROVED", match, reviewer, {
            "mapping_kind": kind, "raw_value": raw, "canonical_value": canonical,
            "source_transaction_id": src_id, "target_transaction_id": tgt_id,
        })

        rule, rule_is_new = _upsert_rule(db, match, kind, raw, canonical)
        db.add(rule)
        db.flush()  # materialize rule.rule_id before audit / linking the mapping
        if rule_is_new:
            _record_audit(db, "RULE_CREATED", match, reviewer, {
                "rule_id": rule.rule_id, "kind": rule.kind,
                "times_approved": rule.times_approved,
            })

        mapping, mapping_is_new = _upsert_mapping(
            db, match, kind, raw, canonical, rule.rule_id, src_id, tgt_id
        )
        db.add(mapping)
        db.flush()  # materialize mapping.id for the audit event
        if mapping_is_new:
            _record_audit(db, "MEMORY_CREATED", match, reviewer, {
                "mapping_kind": kind, "mapping_id": mapping.id,
                "rule_source": rule.rule_id,
            })
        touched.append(rule.rule_id)
    return touched
