"""
Stage B (README §41.4): deterministic settlement-lag statistics.

For every (left_source, right_source, match_stage) combination observed
among this batch's own confirmed (RECONCILED) matches, compute the
median and p90 number of days between the left and right transaction
dates. Pure arithmetic over data already in the database -- no AI, no
network calls, fully deterministic and reproducible.

Below MIN_LAG_SAMPLES_FOR_STATS observations, fall back to the
configured DEFAULT_LAG_DAYS and mark lag_source="default" so the
fallback is visible in each line's evidence rather than hidden.
"""
from __future__ import annotations

import statistics
from datetime import date
from typing import Any, Dict, List, Tuple

from sqlalchemy.orm import Session

from app.config import settings
from app.db import MatchResult, TransactionRow, loads

LagKey = Tuple[str, str, str]


def _txn_date_map(db: Session, batch_id: str) -> Dict[tuple, date]:
    # MatchResult.left_txn_ids_json / right_txn_ids_json store
    # (source, source_record_id) pairs, not the internal TransactionRow.id
    # primary key -- key this map the same way (see app/main.py's own
    # `accounted.add((u["left_source"], tid))` pattern).
    rows = db.query(TransactionRow).filter(TransactionRow.batch_id == batch_id).all()
    out: Dict[tuple, date] = {}
    for r in rows:
        d = r.value_date or r.transaction_date
        if d:
            out[(r.source, r.source_record_id)] = d
    return out


def _percentile(sorted_values: List[int], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    idx = pct * (len(sorted_values) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = idx - lo
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


def compute_lag_stats(db: Session, batch_id: str) -> Dict[LagKey, Dict[str, Any]]:
    """
    Returns {(left_source, right_source, match_stage): {median_lag_days,
    p90_lag_days, sample_size, lag_source}} computed only from this
    batch's own RECONCILED, clean 1:1 matches (aggregated many-to-one /
    one-to-many relationships are excluded -- they don't have a single
    unambiguous lag).
    """
    dates = _txn_date_map(db, batch_id)
    matches = db.query(MatchResult).filter(
        MatchResult.batch_id == batch_id,
        MatchResult.state == "RECONCILED",
    ).all()

    samples: Dict[LagKey, List[int]] = {}
    for m in matches:
        left_ids = loads(m.left_txn_ids_json) or []
        right_ids = loads(m.right_txn_ids_json) or []
        if len(left_ids) != 1 or len(right_ids) != 1:
            continue
        left_date = dates.get((m.left_source, left_ids[0]))
        right_date = dates.get((m.right_source, right_ids[0]))
        if not left_date or not right_date:
            continue
        key = (m.left_source, m.right_source, m.match_stage)
        samples.setdefault(key, []).append((right_date - left_date).days)

    stats: Dict[LagKey, Dict[str, Any]] = {}
    for key, values in samples.items():
        values_sorted = sorted(values)
        n = len(values_sorted)
        if n >= settings.MIN_LAG_SAMPLES_FOR_STATS:
            stats[key] = {
                "median_lag_days": statistics.median(values_sorted),
                "p90_lag_days": _percentile(values_sorted, 0.90),
                "sample_size": n,
                "lag_source": "observed",
            }
        else:
            stats[key] = {
                "median_lag_days": float(settings.DEFAULT_LAG_DAYS),
                "p90_lag_days": float(settings.DEFAULT_LAG_DAYS),
                "sample_size": n,
                "lag_source": "default",
            }
    return stats


def lookup_lag(stats: Dict[LagKey, Dict[str, Any]], left_source, right_source, match_stage) -> Dict[str, Any]:
    key = (left_source, right_source, match_stage)
    if key in stats:
        return stats[key]
    return {
        "median_lag_days": float(settings.DEFAULT_LAG_DAYS),
        "p90_lag_days": float(settings.DEFAULT_LAG_DAYS),
        "sample_size": 0,
        "lag_source": "default",
    }
