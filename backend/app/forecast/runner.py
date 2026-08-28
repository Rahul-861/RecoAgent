"""
Orchestrates a single forecast run (README §41.7, §41.12 build order
steps 2-4): Stage A bucketing -> Stage B lag stats (used inside Stage A)
-> Stage C optional AI -> persist CashForecastRun/CashForecastLine.

Idempotent per (batch_id, as_of_date, horizon_days) unless force=True,
the same pattern POST /api/reconcile uses for Batch.reconciliation_run_id.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.db import Batch, CashForecastLine, CashForecastRun, dumps, loads, new_id
from app.forecast.ai_estimator import apply_ai_stage
from app.forecast.bucketing import build_forecast_lines
from app.forecast.lag_estimator import compute_lag_stats


class BatchNotReconciledError(ValueError):
    pass


class BatchNotFoundError(ValueError):
    pass


def _find_existing_run(db: Session, batch_id: str, as_of_date: date, horizon_days: int) -> Optional[CashForecastRun]:
    return (
        db.query(CashForecastRun)
        .filter(
            CashForecastRun.batch_id == batch_id,
            CashForecastRun.as_of_date == as_of_date,
            CashForecastRun.horizon_days == horizon_days,
        )
        .order_by(CashForecastRun.created_at.desc())
        .first()
    )


def run_forecast(
    db: Session,
    batch_id: str,
    horizon_days: Optional[int] = None,
    opening_balance: Optional[float] = None,
    as_of: Optional[date] = None,
    force: bool = False,
) -> CashForecastRun:
    batch = db.get(Batch, batch_id)
    if not batch:
        raise BatchNotFoundError(f"Batch {batch_id} not found")
    if batch.status not in ("done", "VALIDATION_FAILED"):
        # Mirrors README §41.2: reject rather than forecast off incomplete data.
        raise BatchNotReconciledError(
            f"Batch {batch_id} has not been reconciled yet (status={batch.status}); "
            "run POST /api/reconcile/{batch_id} first."
        )

    horizon_days = horizon_days if horizon_days is not None else settings.FORECAST_HORIZON_DAYS
    as_of_date = as_of or date.today()

    existing = _find_existing_run(db, batch_id, as_of_date, horizon_days)
    if existing and not force:
        return existing

    if existing and force:
        db.query(CashForecastLine).filter(CashForecastLine.run_id == existing.run_id).delete()
        db.delete(existing)
        db.flush()

    lag_stats = compute_lag_stats(db, batch_id)
    lines = build_forecast_lines(db, batch_id, as_of_date, lag_stats)
    lines, llm_calls, failovers = apply_ai_stage(lines)

    run = CashForecastRun(
        run_id=new_id("fcst"),
        batch_id=batch_id,
        as_of_date=as_of_date,
        horizon_days=horizon_days,
        opening_balance=opening_balance,
        forecast_version=settings.FORECAST_VERSION,
        lag_model_version=settings.LAG_MODEL_VERSION,
        forecast_llm_call_count=llm_calls,
        forecast_failover_count=failovers,
    )
    db.add(run)
    db.flush()

    for line in lines:
        db.add(CashForecastLine(
            line_id=new_id("fcln"),
            run_id=run.run_id,
            batch_id=batch_id,
            bucket_date=line.get("bucket_date"),
            category=line["category"],
            direction=line.get("direction"),
            amount=line.get("amount"),
            currency=line.get("currency"),
            confidence=line.get("confidence"),
            lag_source=line.get("lag_source"),
            source_match_ids_json=dumps(line.get("source_match_ids") or []),
            evidence_json=dumps(line.get("evidence") or {}),
            ai_used=bool(line.get("ai_used")),
        ))
    db.commit()
    db.refresh(run)
    return run


def _line_to_dict(l: CashForecastLine) -> Dict[str, Any]:
    return {
        "line_id": l.line_id,
        "run_id": l.run_id,
        "batch_id": l.batch_id,
        "bucket_date": l.bucket_date.isoformat() if l.bucket_date else None,
        "category": l.category,
        "direction": l.direction,
        "amount": l.amount,
        "currency": l.currency,
        "confidence": l.confidence,
        "lag_source": l.lag_source,
        "source_match_ids": loads(l.source_match_ids_json) or [],
        "evidence": loads(l.evidence_json) or {},
        "ai_used": l.ai_used,
    }


def get_latest_run(db: Session, batch_id: str) -> Optional[CashForecastRun]:
    return (
        db.query(CashForecastRun)
        .filter(CashForecastRun.batch_id == batch_id)
        .order_by(CashForecastRun.created_at.desc())
        .first()
    )


def forecast_response(db: Session, batch_id: str) -> Optional[Dict[str, Any]]:
    run = get_latest_run(db, batch_id)
    if not run:
        return None
    lines = db.query(CashForecastLine).filter(CashForecastLine.run_id == run.run_id).all()

    horizon_end = run.as_of_date + timedelta(days=run.horizon_days)
    by_date: Dict[str, Dict[str, float]] = defaultdict(lambda: {
        "confirmed": 0.0, "expected": 0.0, "at_risk": 0.0,
    })
    unclassifiable_total = 0.0
    totals = {"confirmed": 0.0, "expected": 0.0, "at_risk": 0.0, "unclassifiable": 0.0}

    for l in lines:
        if l.category == "UNCLASSIFIABLE" or l.bucket_date is None:
            unclassifiable_total += l.amount or 0.0
            totals["unclassifiable"] += l.amount or 0.0
            continue
        if l.bucket_date < run.as_of_date or l.bucket_date > horizon_end:
            # Outside the requested horizon -- still stored for
            # traceability but excluded from the plotted curve.
            continue
        bucket_key = l.bucket_date.isoformat()
        signed = (l.amount or 0.0) * (1 if l.direction != "outflow" else -1)
        if l.category == "CONFIRMED":
            by_date[bucket_key]["confirmed"] += signed
            totals["confirmed"] += signed
        elif l.category == "EXPECTED":
            by_date[bucket_key]["expected"] += signed
            totals["expected"] += signed
        elif l.category == "AT_RISK":
            by_date[bucket_key]["at_risk"] += signed
            totals["at_risk"] += signed

    curve = []
    running_balance = run.opening_balance
    for bucket_key in sorted(by_date.keys()):
        row = by_date[bucket_key]
        entry = {
            "date": bucket_key,
            "confirmed": round(row["confirmed"], 2),
            "expected": round(row["expected"], 2),
            "at_risk": round(row["at_risk"], 2),
        }
        if running_balance is not None:
            running_balance += row["expected"] + row["at_risk"]
            entry["running_balance"] = round(running_balance, 2)
        curve.append(entry)

    return {
        "batch_id": batch_id,
        "run_id": run.run_id,
        "as_of_date": run.as_of_date.isoformat(),
        "horizon_days": run.horizon_days,
        "opening_balance": run.opening_balance,
        "forecast_version": run.forecast_version,
        "lag_model_version": run.lag_model_version,
        "forecast_llm_call_count": run.forecast_llm_call_count,
        "forecast_failover_count": run.forecast_failover_count,
        "curve": curve,
        "totals": {k: round(v, 2) for k, v in totals.items()},
        "line_count": len(lines),
    }


def line_response(db: Session, line_id: str) -> Optional[Dict[str, Any]]:
    line = db.get(CashForecastLine, line_id)
    if not line:
        return None
    return _line_to_dict(line)
