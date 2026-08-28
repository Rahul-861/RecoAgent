"""
ReconAgent FastAPI backend -- multi-source AI Finance Controller.
Implements the endpoints in README §... (see root README "API surface").
"""
from __future__ import annotations
import time
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import pandas as pd

from app.config import settings
from app.db import (
    init_db, get_session, Batch, TransactionRow, MatchResult, AnswerKeyRow,
        ExceptionResolution, MemoryMapping, LearnedRule, AuditEvent, dumps, loads,
)
from app.memory.reconciliation_memory import record_resolution_memory
from app.models import (
    UploadResponse, ReconcileResponse, StageBreakdown, ResultsResponse, MatchOut,
    ResolveRequest, AccuracyReport, GraphResponse, EventChain, GraphNode, GraphEdge,
    QARequest, QAResponse,
)
from app.pipeline.normalize import normalize_bank_csv, normalize_processor_csv, normalize_erp_csv
from app.pipeline.matching_core import run_exact_match, run_fuzzy_semantic_match
from app.pipeline.identity import settlement_amount
from app.pipeline.settlement_match import (
    run_many_to_one_settlement, run_many_to_one_fallback_subset_sum, run_one_to_many_invoice,
)
from app.pipeline.refund_match import run_refund_check
from app.pipeline.duplicate_check import run_duplicate_check
from app.pipeline.llm_adjudicate import run_llm_adjudication
from app.pipeline.event_graph import build_event_graph
from app.pipeline.qa import answer_question
from app.accuracy.validate_against_key import compute_accuracy
from app.pipeline.validate import validate_rows
from app.pipeline.rule_engine import enrich_decision
from app.pipeline.final_validation import validate_batch
from app.contract.reconciliation_contract import get_contract
from app.audit.audit_trail import decision_audit_record, audit_completeness
from app.exceptions.lifecycle import apply_resolution
from app.forecast.runner import (
    BatchNotFoundError, BatchNotReconciledError, forecast_response, line_response, run_forecast,
)

app = FastAPI(title="ReconAgent API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/api/health")
def health():
    return {"status": "ok"}


# --------------------------------------------------------------------------
# Upload
# --------------------------------------------------------------------------

def _store_transactions(db: Session, batch_id: str, rows: List[Dict[str, Any]]):
    for r in rows:
        db.add(TransactionRow(
            batch_id=batch_id, source=r["source"], source_record_id=r["source_record_id"],
            transaction_type=r["transaction_type"], transaction_date=r["transaction_date"],
            value_date=r.get("value_date"), amount=r["amount"], gross_amount=r.get("gross_amount"),
            fee_amount=r.get("fee_amount"), refund_amount=r.get("refund_amount"),
            net_amount=r.get("net_amount"), currency=r["currency"], reference=r["reference"],
            invoice_id=r.get("invoice_id"), order_id=r.get("order_id"), payment_id=r.get("payment_id"),
            settlement_id=r.get("settlement_id"), counterparty=r.get("counterparty"),
            description=r.get("description"), status=r.get("status"),
            tax_amount=r.get("tax_amount"), chargeback_amount=r.get("chargeback_amount"),
            parent_transaction_id=r.get("parent_transaction_id"),
            raw_row_json=dumps(r["raw_row"]),
            original_amount=r.get("original_amount"),
            reference_normalized=r.get("reference_normalized"),
            counterparty_normalized=r.get("counterparty_normalized"),
            description_normalized=r.get("description_normalized"),
            normalization_version=r.get("normalization_version") or settings.NORMALIZATION_VERSION,
            recon_state=r.get("recon_state") or "NORMALIZED",
            is_valid=bool(r.get("is_valid", True)),
            validation_errors_json=dumps(r.get("validation_errors") or []),
        ))


@app.post("/api/upload", response_model=UploadResponse)
async def upload(
    bank_file: UploadFile = File(...),
    processor_file: UploadFile = File(...),
    erp_file: UploadFile = File(...),
    answer_key_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_session),
):
    try:
        bank_rows = normalize_bank_csv(await bank_file.read())
        processor_rows = normalize_processor_csv(await processor_file.read())
        erp_rows = normalize_erp_csv(await erp_file.read())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    bank_rows = validate_rows(bank_rows)
    processor_rows = validate_rows(processor_rows)
    erp_rows = validate_rows(erp_rows)
    invalid_count = sum(1 for r in bank_rows + processor_rows + erp_rows if not r.get("is_valid", True))

    batch = Batch(
        bank_count=len(bank_rows), processor_count=len(processor_rows), erp_count=len(erp_rows),
        has_answer_key=answer_key_file is not None, status="uploaded",
        invalid_count=invalid_count,
        pipeline_version=settings.PIPELINE_VERSION,
        normalization_version=settings.NORMALIZATION_VERSION,
        rule_set_version=settings.RULE_SET_VERSION,
        configuration_version=settings.CONFIGURATION_VERSION,
    )
    db.add(batch)
    db.flush()

    _store_transactions(db, batch.batch_id, bank_rows)
    _store_transactions(db, batch.batch_id, processor_rows)
    _store_transactions(db, batch.batch_id, erp_rows)

    if answer_key_file is not None:
        ak_bytes = await answer_key_file.read()
        ak_df = pd.read_csv(pd.io.common.BytesIO(ak_bytes))
        ak_df.columns = [c.strip() for c in ak_df.columns]
        for _, row in ak_df.iterrows():
            expected_ids = row.get("expected_match_ids")
            ids_list = (
                [x.strip() for x in str(expected_ids).split(";") if x.strip()]
                if pd.notna(expected_ids) else []
            )
            db.add(AnswerKeyRow(
                batch_id=batch.batch_id,
                source=str(row.get("source")),
                transaction_id=str(row.get("transaction_id")),
                expected_match_source=(str(row.get("expected_match_source"))
                                        if pd.notna(row.get("expected_match_source")) else None),
                expected_match_ids_json=dumps(ids_list),
                expected_exception_type=(str(row.get("expected_exception_type"))
                                          if pd.notna(row.get("expected_exception_type")) else None),
            ))

    db.commit()
    return UploadResponse(
        batch_id=batch.batch_id, bank_count=batch.bank_count,
        processor_count=batch.processor_count, erp_count=batch.erp_count,
        has_answer_key=batch.has_answer_key,
    )


def _row_from_db(t: TransactionRow) -> Dict[str, Any]:
    return {
        "source": t.source, "source_record_id": t.source_record_id,
        "transaction_type": t.transaction_type, "transaction_date": t.transaction_date,
        "value_date": t.value_date, "amount": t.amount, "gross_amount": t.gross_amount,
        "fee_amount": t.fee_amount, "refund_amount": t.refund_amount, "net_amount": t.net_amount,
        "currency": t.currency, "reference": t.reference, "invoice_id": t.invoice_id,
        "order_id": t.order_id, "payment_id": t.payment_id, "settlement_id": t.settlement_id,
        "counterparty": t.counterparty, "description": t.description, "status": t.status,
        "tax_amount": getattr(t, "tax_amount", None),
        "chargeback_amount": getattr(t, "chargeback_amount", None),
        "parent_transaction_id": getattr(t, "parent_transaction_id", None),
        "raw_row": loads(t.raw_row_json),
        "original_amount": getattr(t, "original_amount", None),
        "reference_normalized": getattr(t, "reference_normalized", None),
        "counterparty_normalized": getattr(t, "counterparty_normalized", None),
        "description_normalized": getattr(t, "description_normalized", None),
        "normalization_version": getattr(t, "normalization_version", None),
        "is_valid": bool(getattr(t, "is_valid", True)),
        "validation_errors": loads(getattr(t, "validation_errors_json", None)) or [],
        "recon_state": getattr(t, "recon_state", None),
    }



# --------------------------------------------------------------------------
# Reconcile -- the core pipeline
# --------------------------------------------------------------------------

def _uniform(d: Dict[str, Any]) -> Dict[str, Any]:
    """Adapts the varied per-stage output shapes into one persistence-ready dict."""
    if "left_rows" in d:
        left_rows = d["left_rows"]
        left_source = left_rows[0]["source"] if left_rows else None
        left_ids = [r["source_record_id"] for r in left_rows]
    elif d.get("left") is not None:
        left_source = d["left"]["source"]
        left_ids = [d["left"]["source_record_id"]]
    elif "left_txn_id" in d:
        left_source = d.get("left_source")
        left_ids = [d["left_txn_id"]]
    else:
        left_source, left_ids = d.get("left_source"), []

    if d.get("right") is not None:
        right_source = d["right"]["source"]
        right_ids = [d["right"]["source_record_id"]]
    elif "right_rows" in d and d["right_rows"]:
        right_rows = d["right_rows"]
        right_source = right_rows[0]["source"]
        right_ids = [r["source_record_id"] for r in right_rows]
    else:
        right_source, right_ids = d.get("right_source"), []

    return {
        "left_source": left_source, "left_txn_ids": left_ids,
        "right_source": right_source, "right_txn_ids": right_ids,
        "match_stage": d["match_stage"], "confidence": d.get("confidence", 0.0),
        "reason": d.get("reason", ""), "candidates_shown": d.get("candidates_shown"),
        "provider_used": d.get("provider_used"), "status": d.get("status", "matched"),
        "exception_type": d.get("exception_type"), "severity": d.get("severity"),
        "evidence": d.get("evidence"), "contradictions": d.get("contradictions") or [],
        "candidate_ids": d.get("candidate_ids"), "decision": d.get("decision"),
        "rule_id": d.get("rule_id"), "top_score": d.get("top_score"),
        "second_score": d.get("second_score"), "score_margin": d.get("score_margin"),
    }


def _model_dump(model) -> dict:
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


def _response_from_existing(db: Session, batch: Batch) -> ReconcileResponse:
    stage = loads(batch.stage_breakdown_json) or {}
    try:
        stage_counts = StageBreakdown(**stage)
    except Exception:
        stage_counts = StageBreakdown()
    total_records = (batch.bank_count or 0) + (batch.processor_count or 0) + (batch.erp_count or 0)
    exception_count = db.query(MatchResult).filter(
        MatchResult.batch_id == batch.batch_id, MatchResult.status == "exception"
    ).count()
    accuracy = compute_accuracy(db, batch.batch_id)
    return ReconcileResponse(
        batch_id=batch.batch_id, total_records=total_records, match_rate=batch.match_rate or 0,
        stage_breakdown=stage_counts, exception_count=exception_count,
        manual_review_reduction=batch.manual_review_reduction or 0,
        llm_call_count=batch.llm_call_count or 0, llm_batched_call_count=batch.llm_batched_call_count or 0,
        failover_count=batch.failover_count or 0, throughput_per_sec=batch.throughput_per_sec or 0,
        processing_ms=batch.processing_ms or 0, settlement_variance=batch.settlement_variance,
        accuracy=AccuracyReport(**accuracy),
        validation_status=batch.validation_status,
        control_totals=loads(batch.control_totals_json),
        pipeline_version=batch.pipeline_version,
        rule_set_version=batch.rule_set_version,
        normalization_version=batch.normalization_version,
        audit_completeness=batch.audit_completeness,
        invalid_count=batch.invalid_count or 0,
        reused_existing_run=True,
    )


@app.post("/api/reconcile/{batch_id}", response_model=ReconcileResponse)
def reconcile(batch_id: str, force: bool = Query(False), db: Session = Depends(get_session)):
    start = time.perf_counter()
    batch = db.get(Batch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    existing = db.query(MatchResult).filter(MatchResult.batch_id == batch_id).count()
    if existing and batch.status in ("done", "VALIDATION_FAILED") and not force:
        return _response_from_existing(db, batch)

    db.query(MatchResult).filter(MatchResult.batch_id == batch_id).delete()
    db.commit()

    txns = db.query(TransactionRow).filter(TransactionRow.batch_id == batch_id).all()
    bank = [_row_from_db(t) for t in txns if t.source == "bank"]
    processor = [_row_from_db(t) for t in txns if t.source == "processor"]
    erp = [_row_from_db(t) for t in txns if t.source == "erp"]
    all_records = bank + processor + erp
    invalid_rows = [r for r in all_records if not r.get("is_valid", True)]
    bank = sorted([r for r in bank if r.get("is_valid", True)], key=lambda r: r["source_record_id"])
    processor = sorted([r for r in processor if r.get("is_valid", True)], key=lambda r: r["source_record_id"])
    erp = sorted([r for r in erp if r.get("is_valid", True)], key=lambda r: r["source_record_id"])

    all_uniform: List[Dict[str, Any]] = []
    for r in invalid_rows:
        all_uniform.append({
            "left_source": r["source"], "left_txn_ids": [r["source_record_id"]],
            "right_source": None, "right_txn_ids": [],
            "match_stage": "unresolved", "confidence": 0.0, "status": "exception",
            "exception_type": "invalid", "severity": "high",
            "decision": "INVALID",
            "reason": "; ".join(r.get("validation_errors") or ["Invalid record"]),
            "candidates_shown": None, "provider_used": None,
            "evidence": {"validation_errors": r.get("validation_errors")},
            "contradictions": r.get("validation_errors") or [],
        })

    # --- Stage: refunds (processor <-> bank debits) -------------------------
    # Refunds consume bank *debits* only. The processor payment stays in the
    # settlement pool so its net payout can still match a bank credit.
    refund_results, processor_payments, bank_remaining = run_refund_check(
        processor, bank, settings.AMOUNT_TOLERANCE, settings.TIMING_TOLERANCE_DAYS,
    )
    all_uniform += [_uniform(r) for r in refund_results]

    bank_credits = [b for b in bank_remaining if (b["amount"] or 0) >= 0]
    # ERP matching uses the full credit pool independently of processor-bank
    # consumption so a bank deposit can close both the processor and the ledger.
    bank_credits_for_erp = list(bank_credits)

    def _proc_amt(r):
        return settlement_amount(r)

    def _bank_amt(r):
        return r.get("amount")

    def _erp_amt(r):
        return r.get("amount")

    # --- Stage: many-to-one settlement batches (processor <-> bank) --------
    m2o_matches, processor_payments, bank_credits = run_many_to_one_settlement(
        processor_payments, bank_credits, settings.SETTLEMENT_SUM_TOLERANCE,
        settings.TIMING_TOLERANCE_DAYS, settings.MAX_GROUP_SIZE,
    )
    all_uniform += [_uniform(m) for m in m2o_matches]

    # --- Stage: exact / fee-aware (processor <-> bank) ----------------------
    exact_matches, processor_payments, bank_credits = run_exact_match(
        processor_payments, bank_credits,
        left_amount_fn=_proc_amt,
        right_amount_fn=_bank_amt,
        amount_tolerance=settings.AMOUNT_TOLERANCE, timing_tolerance_days=settings.TIMING_TOLERANCE_DAYS,
    )
    all_uniform += [_uniform(m) for m in exact_matches]

    # --- Stage: fuzzy / semantic (processor <-> bank) -----------------------
    fs_matches, processor_payments, bank_credits, multi_map_pb = run_fuzzy_semantic_match(
        processor_payments, bank_credits,
        left_amount_fn=_proc_amt,
        right_amount_fn=_bank_amt,
        fuzzy_threshold=settings.FUZZY_MATCH_THRESHOLD, semantic_threshold=settings.SEMANTIC_MATCH_THRESHOLD,
        amount_tolerance=settings.AMOUNT_TOLERANCE, timing_tolerance_days=settings.TIMING_TOLERANCE_DAYS,
    )
    all_uniform += [_uniform(m) for m in fs_matches]

    dup_exceptions_pb = run_duplicate_check(multi_map_pb, "processor")
    all_uniform += [_uniform(m) for m in dup_exceptions_pb]
    dup_ids_pb = set(multi_map_pb.keys())
    processor_payments = [p for p in processor_payments if p["source_record_id"] not in dup_ids_pb]

    pending_left = []
    ready_for_llm = []
    for p in processor_payments:
        if str(p.get("status") or "").lower().startswith("pending"):
            pending_left.append({
                "left": p, "right": None, "match_stage": "unresolved",
                "confidence": 0.0, "status": "exception", "exception_type": "missing_counterpart",
                "severity": "medium",
                "reason": (
                    f"Processor payment {p['source_record_id']} is {p.get('status')} — "
                    "no bank counterpart is expected until settlement posts."
                ),
                "candidates_shown": None, "provider_used": None,
            })
        else:
            ready_for_llm.append(p)
    all_uniform += [_uniform(m) for m in pending_left]
    processor_payments = ready_for_llm

    # --- Stage: LLM adjudication (processor <-> bank) -----------------------
    llm_pb_matches, llm_pb_exceptions, llm_calls_1, llm_batched_1, failover_1 = run_llm_adjudication(
        processor_payments, bank_credits,
        left_amount_fn=_proc_amt,
        right_amount_fn=_bank_amt,
        left_source="processor", right_source="bank",
        batch_size=settings.LLM_BATCH_SIZE, confidence_threshold=settings.LLM_CONFIDENCE_THRESHOLD,
    )
    all_uniform += [_uniform(m) for m in llm_pb_matches]
    all_uniform += [_uniform(m) for m in llm_pb_exceptions]

    matched_bank_ids = {m["right"]["source_record_id"] for m in llm_pb_matches if m.get("right")}
    bank_credits = [b for b in bank_credits if b["source_record_id"] not in matched_bank_ids]
    # Every processor row entering the LLM stage leaves it either matched or
    # turned into an exception -- none should be reconsidered downstream.
    resolved_processor_ids = {m["left"]["source_record_id"] for m in llm_pb_matches} | \
        {m["left"]["source_record_id"] for m in llm_pb_exceptions}
    processor_payments = [p for p in processor_payments if p["source_record_id"] not in resolved_processor_ids]

    # --- Stage: many-to-one fallback (no settlement_id), on the now-small
    #     residual pool only -- see settlement_match.py for why this must
    #     run last rather than before 1:1 matching. ---------------------------
    m2o_fallback_matches, processor_payments, bank_credits = run_many_to_one_fallback_subset_sum(
        processor_payments, bank_credits, settings.SETTLEMENT_SUM_TOLERANCE,
        settings.TIMING_TOLERANCE_DAYS, settings.MAX_GROUP_SIZE,
    )
    all_uniform += [_uniform(m) for m in m2o_fallback_matches]

    # --- Stage: one-to-many partial payments (bank <-> erp invoices) -------
    o2m_matches, erp, bank_credits_erp = run_one_to_many_invoice(
        erp, bank_credits_for_erp, settings.SETTLEMENT_SUM_TOLERANCE,
        settings.TIMING_TOLERANCE_DAYS, settings.MAX_GROUP_SIZE,
    )
    all_uniform += [_uniform(m) for m in o2m_matches]

    # --- Stage: exact + fuzzy/semantic (bank <-> erp ledger) -----------------
    erp_exact, erp, bank_credits_erp = run_exact_match(
        erp, bank_credits_erp,
        left_amount_fn=_erp_amt, right_amount_fn=_bank_amt,
        amount_tolerance=settings.AMOUNT_TOLERANCE, timing_tolerance_days=settings.TIMING_TOLERANCE_DAYS,
        stage_name="exact",
    )
    all_uniform += [_uniform(m) for m in erp_exact]

    erp_fs, erp, bank_credits_erp, multi_map_eb = run_fuzzy_semantic_match(
        erp, bank_credits_erp,
        left_amount_fn=_erp_amt, right_amount_fn=_bank_amt,
        fuzzy_threshold=settings.FUZZY_MATCH_THRESHOLD, semantic_threshold=settings.SEMANTIC_MATCH_THRESHOLD,
        amount_tolerance=settings.AMOUNT_TOLERANCE, timing_tolerance_days=settings.TIMING_TOLERANCE_DAYS,
    )
    all_uniform += [_uniform(m) for m in erp_fs]

    dup_exceptions_eb = run_duplicate_check(multi_map_eb, "erp")
    all_uniform += [_uniform(m) for m in dup_exceptions_eb]
    dup_ids_eb = set(multi_map_eb.keys())
    erp = [e for e in erp if e["source_record_id"] not in dup_ids_eb]

    llm_eb_matches, llm_eb_exceptions, llm_calls_2, llm_batched_2, failover_2 = run_llm_adjudication(
        erp, bank_credits_erp,
        left_amount_fn=_erp_amt, right_amount_fn=_bank_amt,
        left_source="erp", right_source="bank",
        batch_size=settings.LLM_BATCH_SIZE, confidence_threshold=settings.LLM_CONFIDENCE_THRESHOLD,
    )
    all_uniform += [_uniform(m) for m in llm_eb_matches]
    all_uniform += [_uniform(m) for m in llm_eb_exceptions]

    # --- Final sweep: nothing gets silently dropped (README §49) -----------
    accounted: set = set()
    for u in all_uniform:
        for tid in u["left_txn_ids"]:
            accounted.add((u["left_source"], tid))
        for tid in u["right_txn_ids"]:
            accounted.add((u["right_source"], tid))

    for src_rows, src_name, kind in ((bank, "bank", "unidentified_cash"),
                                      (processor, "processor", "missing_counterpart"),
                                      (erp, "erp", "missing_counterpart")):
        for r in src_rows:
            if (src_name, r["source_record_id"]) not in accounted:
                all_uniform.append({
                    "left_source": src_name, "left_txn_ids": [r["source_record_id"]],
                    "right_source": None, "right_txn_ids": [],
                    "match_stage": "unresolved", "confidence": 0.0, "status": "exception",
                    "exception_type": kind, "severity": "medium",
                    "reason": (
                        f"No counterpart found in any other source for {src_name} record "
                        f"{r['source_record_id']} after all matching stages."
                    ),
                    "candidates_shown": None, "provider_used": None,
                })
                accounted.add((src_name, r["source_record_id"]))

    all_uniform = [enrich_decision(u) for u in all_uniform]
    validation = validate_batch(all_records, all_uniform)

    # --- Persist -------------------------------------------------------------
    stage_counts = StageBreakdown()
    stage_field_map = {
        "exact": "exact", "fee_aware": "fee_aware", "many_to_one": "many_to_one",
        "one_to_many": "one_to_many", "fuzzy": "fuzzy", "semantic": "semantic",
        "refund": "refund", "llm": "llm", "unresolved": "unresolved",
    }

    for u in all_uniform:
        db.add(MatchResult(
            batch_id=batch_id,
            left_source=u["left_source"], left_txn_ids_json=dumps(u["left_txn_ids"]),
            right_source=u["right_source"], right_txn_ids_json=dumps(u["right_txn_ids"]),
            match_stage=u["match_stage"], confidence=u["confidence"], reason=u["reason"],
            candidates_shown_json=dumps(u["candidates_shown"]), provider_used=u["provider_used"],
            status=u["status"], exception_type=u["exception_type"], severity=u["severity"],
            decision=u.get("decision"), state=u.get("state"),
            decision_stage=u.get("decision_stage"), rule_id=u.get("rule_id"),
            rule_set_version=u.get("rule_set_version"),
            pipeline_version=u.get("pipeline_version"),
            normalization_version=u.get("normalization_version"),
            evidence_json=dumps(u.get("evidence")),
            contradictions_json=dumps(u.get("contradictions")),
            candidate_ids_json=dumps(u.get("candidate_ids")),
            top_score=u.get("top_score"), second_score=u.get("second_score"),
            score_margin=u.get("score_margin"),
            relationship_type=u.get("relationship_type"),
            exception_category=u.get("exception_category"),
            exception_lifecycle="OPEN" if u.get("status") == "exception" else None,
            ai_used=bool(u.get("ai_used")),
        ))
        field = stage_field_map.get(u["match_stage"], "unresolved") if u["status"] == "matched" else "unresolved"
        setattr(stage_counts, field, getattr(stage_counts, field) + 1)

    total_records = batch.bank_count + batch.processor_count + batch.erp_count
    matched_ids = set()
    exception_ids = set()
    for u in all_uniform:
        keys = [(u["left_source"], tid) for tid in u["left_txn_ids"]]
        keys += [(u["right_source"], tid) for tid in u["right_txn_ids"] if u.get("right_source")]
        if u["status"] == "matched":
            matched_ids.update(keys)
        else:
            exception_ids.update(keys)
    # A record that is matched on one pair and excepted on another still counts as matched.
    match_rate = round(len(matched_ids) / total_records, 4) if total_records else 0.0
    review_ids = exception_ids - matched_ids
    manual_review_reduction = round(1 - (len(review_ids) / total_records), 4) if total_records else 0.0

    settlement_variance = round(sum(
        abs((u.get("candidates_shown") or [{}])[0].get("amount", 0) or 0) if isinstance(u.get("candidates_shown"), list)
        else 0
        for u in all_uniform if u["status"] == "exception" and u["exception_type"] == "amount_mismatch"
    ), 2)

    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    throughput = round(total_records / (elapsed_ms / 1000), 2) if elapsed_ms > 0 else float(total_records)

    audit_rows = [
        {
            "decision": u.get("decision"), "decision_stage": u.get("decision_stage"),
            "evidence": u.get("evidence"), "pipeline_version": u.get("pipeline_version"),
        }
        for u in all_uniform
    ]
    completeness = audit_completeness(audit_rows)

    batch.status = "done" if validation["validation_status"] == "PASSED" else "VALIDATION_FAILED"
    batch.match_rate = match_rate
    batch.manual_review_reduction = manual_review_reduction
    batch.stage_breakdown_json = dumps(_model_dump(stage_counts))
    batch.llm_call_count = llm_calls_1 + llm_calls_2
    batch.llm_batched_call_count = llm_batched_1 + llm_batched_2
    batch.failover_count = failover_1 + failover_2
    batch.processing_ms = elapsed_ms
    batch.throughput_per_sec = throughput
    batch.settlement_variance = settlement_variance
    batch.validation_status = validation["validation_status"]
    batch.control_totals_json = dumps(validation["control_totals"])
    batch.pipeline_version = settings.PIPELINE_VERSION
    batch.normalization_version = settings.NORMALIZATION_VERSION
    batch.rule_set_version = settings.RULE_SET_VERSION
    batch.configuration_version = settings.CONFIGURATION_VERSION
    batch.audit_completeness = completeness
    batch.reconciliation_run_id = f"{batch_id}:{settings.PIPELINE_VERSION}:{settings.RULE_SET_VERSION}"
    db.commit()

    accuracy = compute_accuracy(db, batch_id)

    return ReconcileResponse(
        batch_id=batch_id, total_records=total_records, match_rate=match_rate,
        stage_breakdown=stage_counts, exception_count=sum(1 for u in all_uniform if u["status"] == "exception"),
        manual_review_reduction=manual_review_reduction,
        llm_call_count=batch.llm_call_count, llm_batched_call_count=batch.llm_batched_call_count,
        failover_count=batch.failover_count, throughput_per_sec=throughput, processing_ms=elapsed_ms,
        settlement_variance=settlement_variance, accuracy=AccuracyReport(**accuracy),
        validation_status=batch.validation_status,
        control_totals=validation["control_totals"],
        pipeline_version=batch.pipeline_version,
        rule_set_version=batch.rule_set_version,
        normalization_version=batch.normalization_version,
        audit_completeness=completeness,
        invalid_count=len(invalid_rows),
        reused_existing_run=False,
    )


# --------------------------------------------------------------------------
# Results / exceptions / resolve / accuracy / batch
# --------------------------------------------------------------------------

def _match_to_out(m: MatchResult) -> MatchOut:
    return MatchOut(
        match_id=m.match_id, left_source=m.left_source, left_txn_ids=loads(m.left_txn_ids_json) or [],
        right_source=m.right_source, right_txn_ids=loads(m.right_txn_ids_json) or [],
        match_stage=m.match_stage, confidence=m.confidence, reason=m.reason,
        candidates_shown=loads(m.candidates_shown_json), provider_used=m.provider_used,
        status=m.status, exception_type=m.exception_type, severity=m.severity,
        review_status=m.review_status,
        decision=getattr(m, "decision", None),
        state=getattr(m, "state", None),
        decision_stage=getattr(m, "decision_stage", None),
        rule_id=getattr(m, "rule_id", None),
        evidence=loads(getattr(m, "evidence_json", None)),
        contradictions=loads(getattr(m, "contradictions_json", None)),
        candidate_ids=loads(getattr(m, "candidate_ids_json", None)),
        exception_category=getattr(m, "exception_category", None),
        exception_lifecycle=getattr(m, "exception_lifecycle", None),
        relationship_type=getattr(m, "relationship_type", None),
        top_score=getattr(m, "top_score", None),
        second_score=getattr(m, "second_score", None),
        score_margin=getattr(m, "score_margin", None),
        ai_used=getattr(m, "ai_used", None),
        pipeline_version=getattr(m, "pipeline_version", None),
    )


@app.get("/api/results/{batch_id}", response_model=ResultsResponse)
def get_results(batch_id: str, db: Session = Depends(get_session)):
    if not db.get(Batch, batch_id):
        raise HTTPException(status_code=404, detail="Batch not found")
    matches = db.query(MatchResult).filter(MatchResult.batch_id == batch_id).all()
    return ResultsResponse(batch_id=batch_id, matches=[_match_to_out(m) for m in matches])


@app.get("/api/exceptions/{batch_id}", response_model=ResultsResponse)
def get_exceptions(batch_id: str, db: Session = Depends(get_session)):
    if not db.get(Batch, batch_id):
        raise HTTPException(status_code=404, detail="Batch not found")
    matches = (
        db.query(MatchResult)
        .filter(MatchResult.batch_id == batch_id, MatchResult.status == "exception")
        .order_by(MatchResult.confidence.asc())
        .all()
    )
    return ResultsResponse(batch_id=batch_id, matches=[_match_to_out(m) for m in matches])


@app.post("/api/exceptions/{match_id}/resolve")
def resolve_exception(match_id: str, req: ResolveRequest, db: Session = Depends(get_session)):
    match = db.get(MatchResult, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if req.action not in ("resolved", "rejected", "escalated", "in_review"):
        raise HTTPException(status_code=400, detail="action must be resolved, rejected, escalated, or in_review")
    apply_resolution(match, req.action, req.note, req.resolved_by or "reviewer", db=db)
    if req.action == "resolved" and req.chosen_candidate_id:
        # The candidate the human explicitly picked as the correct counterpart
        # in the UI. record_resolution_memory pairs the left row against this
        # specific record -- that is what makes ambiguous multi-candidate
        # exceptions (e.g. amount_mismatch) learnable.
        match.chosen_candidate_id = req.chosen_candidate_id
    # Reconciliation memory (README §7/§8): a human resolution approves the
    # counterparty/reference pairing the two sides carry. Recorded only on
    # "resolved" -- rejections and escalations approve nothing.
    learned_rule_ids: list[str] = []
    if req.action == "resolved":
        learned_rule_ids = record_resolution_memory(db, match)
    db.commit()
    return {
        "match_id": match_id,
        "review_status": match.review_status,
        "exception_lifecycle": match.exception_lifecycle,
        "resolution_note": match.resolution_note,
        "learned_rule_ids": learned_rule_ids,
    }


@app.get("/api/exceptions/{match_id}/history")
def get_resolution_history(match_id: str, db: Session = Depends(get_session)):
    """Full, append-only resolution history for one match (never deleted)."""
    match = db.get(MatchResult, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    rows = (
        db.query(ExceptionResolution)
        .filter(ExceptionResolution.match_id == match_id)
        .order_by(ExceptionResolution.created_at.asc())
        .all()
    )
    return {
        "match_id": match_id,
        "current_review_status": match.review_status,
        "current_exception_lifecycle": match.exception_lifecycle,
        "history": [
            {
                "id": r.id,
                "action": r.action,
                "previous_lifecycle": r.previous_lifecycle,
                "new_lifecycle": r.new_lifecycle,
                "note": r.note,
                "resolved_by": r.resolved_by,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


# --------------------------------------------------------------------------
# Reconciliation memory (README §7) + exception -> rule learning (README §8)
# --------------------------------------------------------------------------

@app.get("/api/memory/{batch_id}")
def get_memory(batch_id: str, db: Session = Depends(get_session)):
    """
    Human-approved reconciliation memory: counterparty/reference mappings
    recorded when a reviewer resolved an exception, plus the learned rules
    that encode them. Memory is cross-batch by nature -- each row carries its
    origin batch so the UI can distinguish "approved in this batch" from
    knowledge carried over from earlier batches.
    """
    if not db.get(Batch, batch_id):
        raise HTTPException(status_code=404, detail="Batch not found")

    mappings = (
        db.query(MemoryMapping)
        .order_by(MemoryMapping.last_approved_at.desc())
        .all()
    )
    rules = db.query(LearnedRule).order_by(LearnedRule.updated_at.desc()).all()

    # Enrich mappings with the actual transaction display identifiers and
    # amounts in a single lookup (README section 6: "reference actual
    # transaction IDs/records whenever possible"; section 12 needs Source /
    # Target / Amount / Difference / Approved by).
    txn_ids = []
    for m in mappings:
        if m.source_transaction_id and m.source_transaction_id not in txn_ids:
            txn_ids.append(m.source_transaction_id)
        if m.target_transaction_id and m.target_transaction_id not in txn_ids:
            txn_ids.append(m.target_transaction_id)
    txn_lookup = {}
    if txn_ids:
        for t in db.query(TransactionRow).filter(TransactionRow.id.in_(txn_ids)).all():
            txn_lookup[t.id] = t

    return {
        "batch_id": batch_id,
        "mappings": [
            {
                "id": m.id,
                "mapping_kind": m.mapping_kind,
                "raw_value": m.raw_value,
                "canonical_value": m.canonical_value,
                "approval_count": m.approval_count,
                "status": m.status,
                "rule_source": m.rule_source,
                "origin_match_id": m.origin_match_id,
                "origin_batch_id": m.origin_batch_id,
                "exception_type": m.exception_type,
                "first_approved_at": m.first_approved_at.isoformat() if m.first_approved_at else None,
                "last_approved_at": m.last_approved_at.isoformat() if m.last_approved_at else None,
                "last_batch_id": m.last_batch_id,
                "source_transaction_id": m.source_transaction_id,
                "target_transaction_id": m.target_transaction_id,
                "source_record_id": (txn_lookup[m.source_transaction_id].source_record_id
                                     if m.source_transaction_id and m.source_transaction_id in txn_lookup else None),
                "target_record_id": (txn_lookup[m.target_transaction_id].source_record_id
                                     if m.target_transaction_id and m.target_transaction_id in txn_lookup else None),
                "source_amount": (txn_lookup[m.source_transaction_id].amount
                                  if m.source_transaction_id and m.source_transaction_id in txn_lookup else None),
                "target_amount": (txn_lookup[m.target_transaction_id].amount
                                  if m.target_transaction_id and m.target_transaction_id in txn_lookup else None),
                "reviewer": m.reviewer,
            }
            for m in mappings
        ],
        "rules": [
            {
                "rule_id": r.rule_id,
                "name": r.name,
                "kind": r.kind,
                "version": r.version,
                "approval_status": r.approval_status,
                "times_approved": r.times_approved,
                "origin_match_id": r.origin_match_id,
                "origin_batch_id": r.origin_batch_id,
                "exception_type": r.exception_type,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rules
        ],
        "totals": {
            "mappings": len(mappings),
            "rules": len(rules),
            "approvals": sum((m.approval_count or 0) for m in mappings),
            "from_this_batch": sum(
                1 for m in mappings
                if m.origin_batch_id == batch_id or m.last_batch_id == batch_id
            ),
        },
    }

@app.get("/api/memory/{batch_id}/audit")
def get_memory_audit(batch_id: str, db: Session = Depends(get_session)):
    """Structured audit trail of memory lifecycle actions for a batch (README section 16).

    Returns MAPPING_APPROVED, MEMORY_CREATED and RULE_CREATED events
    in chronological order, so a reviewer can see exactly which human
    resolution produced each mapping and learned rule.
    """
    if not db.get(Batch, batch_id):
        raise HTTPException(status_code=404, detail="Batch not found")
    events = (
        db.query(AuditEvent)
        .filter(AuditEvent.batch_id == batch_id)
        .order_by(AuditEvent.created_at.asc())
        .all()
    )
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "match_id": e.match_id,
            "batch_id": e.batch_id,
            "reviewer": e.reviewer,
            "details": loads(e.details_json),
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in events
    ]


# --------------------------------------------------------------------------
# Data quality layer (README §15): records that failed source validation.
# These are data-quality problems, not reconciliation failures -- they were
# excluded from matching and their values were never modified.
# --------------------------------------------------------------------------

@app.get("/api/data-quality/{batch_id}")
def get_data_quality(batch_id: str, db: Session = Depends(get_session)):
    if not db.get(Batch, batch_id):
        raise HTTPException(status_code=404, detail="Batch not found")

    rows = (
        db.query(TransactionRow)
        .filter(TransactionRow.batch_id == batch_id, TransactionRow.is_valid.is_(False))
        .all()
    )
    records = []
    for r in rows:
        records.append({
            "transaction_id": r.id,
            "source": r.source,
            "source_record_id": r.source_record_id,
            "transaction_type": r.transaction_type,
            "amount": r.amount,
            "currency": r.currency,
            "reference": r.reference,
            "transaction_date": r.transaction_date.isoformat() if r.transaction_date else None,
            "validation_errors": loads(r.validation_errors_json) or [],
        })

    return {
        "batch_id": batch_id,
        "invalid_count": len(records),
        "records": records,
    }


@app.get("/api/accuracy/{batch_id}", response_model=AccuracyReport)
def get_accuracy(batch_id: str, db: Session = Depends(get_session)):
    if not db.get(Batch, batch_id):
        raise HTTPException(status_code=404, detail="Batch not found")
    return AccuracyReport(**compute_accuracy(db, batch_id))


@app.get("/api/batch/{batch_id}")
def get_batch(batch_id: str, db: Session = Depends(get_session)):
    batch = db.get(Batch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    return {
        "batch_id": batch.batch_id, "status": batch.status,
        "bank_count": batch.bank_count, "processor_count": batch.processor_count, "erp_count": batch.erp_count,
        "has_answer_key": batch.has_answer_key, "match_rate": batch.match_rate,
        "manual_review_reduction": batch.manual_review_reduction,
        "stage_breakdown": loads(batch.stage_breakdown_json),
        "llm_call_count": batch.llm_call_count, "llm_batched_call_count": batch.llm_batched_call_count,
        "failover_count": batch.failover_count, "processing_ms": batch.processing_ms,
        "throughput_per_sec": batch.throughput_per_sec, "settlement_variance": batch.settlement_variance,
        "validation_status": batch.validation_status,
        "control_totals": loads(batch.control_totals_json),
        "pipeline_version": batch.pipeline_version,
        "normalization_version": batch.normalization_version,
        "rule_set_version": batch.rule_set_version,
        "configuration_version": batch.configuration_version,
        "audit_completeness": batch.audit_completeness,
        "invalid_count": batch.invalid_count,
    }


@app.get("/api/contract")
def get_reconciliation_contract():
    contract = get_contract().to_dict()
    contract["forecast"] = {
        "status": "implemented",
        "horizon_limits": {"default_days": settings.FORECAST_HORIZON_DAYS, "min_days": 1, "max_days": 365},
        "buckets": ["CONFIRMED", "EXPECTED", "AT_RISK", "UNCLASSIFIABLE"],
        "bucket_definitions": {
            "CONFIRMED": "Already-reconciled (RECONCILED) transactions; context only, not projected forward.",
            "EXPECTED": "Matched but not yet settled; amount known exactly, date = observed/default settlement lag.",
            "AT_RISK": "Open exception with a directional cash implication; amount known, arrival not confirmed.",
            "UNCLASSIFIABLE": "No reliable direction or date; excluded from the point-forecast curve.",
        },
        "lag_model": {
            "description": "Median/p90 days between matched left/right transaction dates, "
                            "computed per (left_source, right_source, match_stage) from this "
                            "batch's own RECONCILED matches.",
            "min_samples_for_observed_stats": settings.MIN_LAG_SAMPLES_FOR_STATS,
            "default_lag_days": settings.DEFAULT_LAG_DAYS,
            "version": settings.LAG_MODEL_VERSION,
        },
        "ai_stage": {
            "enabled": settings.FORECAST_AI_ENABLED,
            "fail_safe_behavior": "No key configured, a failed call, or an unparseable response "
                                   "demotes the line to UNCLASSIFIABLE -- never a fabricated number.",
        },
        "requires_reconciled_batch": True,
        "version": settings.FORECAST_VERSION,
    }
    return contract


@app.get("/api/audit/{batch_id}")
def get_audit(batch_id: str, db: Session = Depends(get_session)):
    if not db.get(Batch, batch_id):
        raise HTTPException(status_code=404, detail="Batch not found")
    matches = db.query(MatchResult).filter(MatchResult.batch_id == batch_id).all()
    records = [decision_audit_record(m) for m in matches]
    return {
        "batch_id": batch_id,
        "count": len(records),
        "audit_completeness": audit_completeness(records),
        "records": records,
    }


@app.get("/api/reconciliation/{match_id}")
def get_reconciliation(match_id: str, db: Session = Depends(get_session)):
    match = db.get(MatchResult, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return decision_audit_record(match)


# --------------------------------------------------------------------------
# Forward Cash Forecaster (README §41) -- additive: reads reconciliation
# output only, never writes to Batch/TransactionRow/MatchResult.
# --------------------------------------------------------------------------

@app.post("/api/forecast/{batch_id}")
def forecast(
    batch_id: str,
    horizon_days: Optional[int] = Query(None),
    opening_balance: Optional[float] = Query(None),
    force: bool = Query(False),
    db: Session = Depends(get_session),
):
    try:
        run_forecast(db, batch_id, horizon_days=horizon_days, opening_balance=opening_balance, force=force)
    except BatchNotFoundError:
        raise HTTPException(status_code=404, detail="Batch not found")
    except BatchNotReconciledError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return forecast_response(db, batch_id)


@app.get("/api/forecast/{batch_id}")
def get_forecast(batch_id: str, db: Session = Depends(get_session)):
    if not db.get(Batch, batch_id):
        raise HTTPException(status_code=404, detail="Batch not found")
    result = forecast_response(db, batch_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No forecast run yet for this batch; POST /api/forecast/{batch_id} first")
    return result


@app.get("/api/forecast/{batch_id}/line/{line_id}")
def get_forecast_line(batch_id: str, line_id: str, db: Session = Depends(get_session)):
    result = line_response(db, line_id)
    if result is None or result["batch_id"] != batch_id:
        raise HTTPException(status_code=404, detail="Forecast line not found")
    return result


# --------------------------------------------------------------------------
# Financial event graph + Q&A  (README §7, §29)
# --------------------------------------------------------------------------

@app.get("/api/graph/{batch_id}", response_model=GraphResponse)
def get_graph(batch_id: str, db: Session = Depends(get_session)):
    if not db.get(Batch, batch_id):
        raise HTTPException(status_code=404, detail="Batch not found")
    chains = build_event_graph(db, batch_id)
    return GraphResponse(batch_id=batch_id, chains=[
        EventChain(
            chain_id=c["chain_id"],
            nodes=[GraphNode(**n) for n in c["nodes"]],
            edges=[GraphEdge(**e) for e in c["edges"]],
            status=c["status"],
        ) for c in chains
    ])


@app.post("/api/qa/{batch_id}", response_model=QAResponse)
def qa(batch_id: str, req: QARequest, db: Session = Depends(get_session)):
    if not db.get(Batch, batch_id):
        raise HTTPException(status_code=404, detail="Batch not found")
    result = answer_question(db, batch_id, req.question)
    return QAResponse(question=req.question, answer=result["answer"], data=result.get("data"))
