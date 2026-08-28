"""
Stage A (README §41.3, §41.3.1): deterministic bucket classification.

Every MatchResult in a reconciled batch lands in exactly one forecast
bucket -- CONFIRMED, EXPECTED, AT_RISK, or UNCLASSIFIABLE. Reuses the
existing exception taxonomy (app/exceptions/taxonomy.py); no new
exception categories are invented here, and reconciliation tables are
only ever read, never written.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.db import ExceptionResolution, MatchResult, TransactionRow, loads
from app.forecast.lag_estimator import lookup_lag

# README §41.3.1 -- direction of the implied cash movement per legacy
# exception_type (the same short strings app/exceptions/taxonomy.py's
# LEGACY_TYPE_TO_CATEGORY maps from).
EXCEPTION_DIRECTION = {
    "refund_missing_from_bank": "outflow",
    "partially_paid": "inflow",
    "overpaid": "outflow",
    "unidentified_cash": "inflow",
}
# Already landed, dated "as of" -- not projected forward in time.
NOT_PROJECTED_FORWARD = {"unidentified_cash"}


def _resolved_match_ids(db: Session, batch_id: str) -> set:
    rows = db.query(ExceptionResolution.match_id).filter(
        ExceptionResolution.batch_id == batch_id,
        ExceptionResolution.action == "resolved",
    ).all()
    return {r[0] for r in rows}


def _txn_map(db: Session, batch_id: str) -> Dict[tuple, TransactionRow]:
    # Keyed by (source, source_record_id) -- MatchResult.left_txn_ids_json /
    # right_txn_ids_json store source_record_id strings, not the internal
    # TransactionRow.id primary key (see app/main.py's
    # `accounted.add((u["left_source"], tid))` pattern).
    rows = db.query(TransactionRow).filter(TransactionRow.batch_id == batch_id).all()
    return {(r.source, r.source_record_id): r for r in rows}


def _side_amount_currency(txn_map: Dict[tuple, TransactionRow], source: Optional[str], ids: List[str]):
    amounts, currency = [], None
    for tid in ids:
        t = txn_map.get((source, tid))
        if t is None:
            continue
        if t.amount is not None:
            amounts.append(abs(t.amount))
        currency = currency or t.currency
    return (sum(amounts) if amounts else None), currency


def _side_date(txn_map: Dict[tuple, TransactionRow], source: Optional[str], ids: List[str]) -> Optional[date]:
    for tid in ids:
        t = txn_map.get((source, tid))
        if t is None:
            continue
        d = t.value_date or t.transaction_date
        if d:
            return d
    return None


def build_forecast_lines(
    db: Session,
    batch_id: str,
    as_of_date: date,
    lag_stats: Dict[Any, Any],
) -> List[Dict[str, Any]]:
    """
    Returns a list of plain dicts, one per forecast line, ready to persist
    as CashForecastLine rows. Deterministic and side-effect free (does not
    write to MatchResult/TransactionRow).
    """
    txn_map = _txn_map(db, batch_id)
    resolved_ids = _resolved_match_ids(db, batch_id)
    matches = db.query(MatchResult).filter(MatchResult.batch_id == batch_id).all()

    lines: List[Dict[str, Any]] = []

    for m in matches:
        left_ids = loads(m.left_txn_ids_json) or []
        right_ids = loads(m.right_txn_ids_json) or []

        if m.state == "RECONCILED":
            line = _classify_reconciled(m, txn_map, as_of_date, lag_stats, left_ids, right_ids)
            if line is not None:
                lines.append(line)
            continue

        if m.status == "exception" and m.exception_lifecycle == "OPEN" and m.match_id not in resolved_ids:
            line = _classify_exception(m, txn_map, as_of_date, lag_stats, left_ids, right_ids)
            if line is not None:
                lines.append(line)

    return lines


def _classify_reconciled(m, txn_map, as_of_date, lag_stats, left_ids, right_ids) -> Optional[Dict[str, Any]]:
    if left_ids:
        amount, currency = _side_amount_currency(txn_map, m.left_source, left_ids)
    else:
        amount, currency = _side_amount_currency(txn_map, m.right_source, right_ids)
    if amount is None:
        return None

    left_date = _side_date(txn_map, m.left_source, left_ids)
    right_date = _side_date(txn_map, m.right_source, right_ids)
    lag = lookup_lag(lag_stats, m.left_source, m.right_source, m.match_stage)

    settle_date = right_date or left_date
    if settle_date and settle_date > as_of_date:
        bucket_date = settle_date
        category = "EXPECTED"
    elif not settle_date and left_date:
        bucket_date = left_date + timedelta(days=int(round(lag["median_lag_days"])))
        category = "EXPECTED" if bucket_date > as_of_date else "CONFIRMED"
    else:
        bucket_date = settle_date or as_of_date
        category = "CONFIRMED"

    return {
        "bucket_date": bucket_date,
        "category": category,
        # Direction assumption: this reconciliation tool's confirmed
        # matches are predominantly receivables (processor/ERP settling
        # into bank) -- documented here rather than silently hard-coded.
        "direction": "inflow",
        "amount": amount,
        "currency": currency or "INR",
        "confidence": "high" if category == "CONFIRMED" else (
            "medium" if lag["lag_source"] == "observed" else "low"
        ),
        "lag_source": lag["lag_source"] if category == "EXPECTED" else None,
        "source_match_ids": [m.match_id],
        "evidence": {
            "reason": "confirmed reconciled match" if category == "CONFIRMED"
                      else "matched, projected settlement date",
            "match_stage": m.match_stage,
            "left_source": m.left_source,
            "right_source": m.right_source,
            "lag_median_days": lag["median_lag_days"],
            "lag_sample_size": lag["sample_size"],
            "direction_basis": "assumed_inflow (bank-receiving convention; see README §41)",
        },
        "ai_used": False,
        "ai_eligible": False,
    }


def _classify_exception(m, txn_map, as_of_date, lag_stats, left_ids, right_ids) -> Optional[Dict[str, Any]]:
    if left_ids:
        amount, currency = _side_amount_currency(txn_map, m.left_source, left_ids)
    else:
        amount, currency = _side_amount_currency(txn_map, m.right_source, right_ids)
    if not amount:
        return None

    etype = (m.exception_type or "").lower()

    if etype in EXCEPTION_DIRECTION:
        direction = EXCEPTION_DIRECTION[etype]
        anchor_date = (
            _side_date(txn_map, m.left_source, left_ids)
            or _side_date(txn_map, m.right_source, right_ids)
            or as_of_date
        )

        if etype in NOT_PROJECTED_FORWARD:
            bucket_date = as_of_date
            lag_source = None
        else:
            lag = lookup_lag(lag_stats, m.left_source, m.right_source, m.match_stage)
            bucket_date = anchor_date + timedelta(days=int(round(lag["median_lag_days"])))
            lag_source = lag["lag_source"]

        # A rule-based direction is known, but if there's no observed
        # historical lag data for it, this is a candidate for the
        # optional AI stage (§41.5) to bound more tightly.
        ai_eligible = lag_source == "default" and etype not in NOT_PROJECTED_FORWARD

        return {
            "bucket_date": bucket_date,
            "category": "AT_RISK",
            "direction": direction,
            "amount": amount,
            "currency": currency or "INR",
            "confidence": "low",
            "lag_source": lag_source,
            "source_match_ids": [m.match_id],
            "evidence": {
                "reason": f"open exception '{etype}' implies a probable {direction}",
                "exception_type": etype,
                "exception_lifecycle": m.exception_lifecycle,
            },
            "ai_used": False,
            "ai_eligible": ai_eligible,
        }

    # No reliable direction without further review -> UNCLASSIFIABLE
    # (§41.3.1: duplicate, duplicate_refund, ambiguous, invalid,
    # currency_mismatch, timing_difference, amount_mismatch,
    # missing_counterpart, plus anything else not in the mapping above).
    return {
        "bucket_date": None,
        "category": "UNCLASSIFIABLE",
        "direction": None,
        "amount": amount,
        "currency": currency or "INR",
        "confidence": "low",
        "lag_source": None,
        "source_match_ids": [m.match_id],
        "evidence": {
            "reason": "exception type has no reliable direction without manual review",
            "exception_type": etype or m.decision,
        },
        "ai_used": False,
        "ai_eligible": False,
    }
