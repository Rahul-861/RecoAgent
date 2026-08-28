"""
Stage: Batched LLM adjudication (README §21).

The LLM is the last-mile reasoning layer, not the primary matcher --
only records that survive exact, fee-aware, many-to-one/one-to-many,
fuzzy, and semantic matching reach here. Generalized to work on any
left/right source pair (bank<->processor or bank<->erp) with a
configurable amount extractor per side, so the batching/failover/
heuristic-fallback logic isn't duplicated per pair.
"""
from __future__ import annotations
import json
import logging
from typing import List, Dict, Any, Tuple, Callable, Optional

from app.config import settings
from app.llm import groq_client, gemini_fallback
from app.pipeline.identity import identities_overlap, text_similarity
from app.pipeline.scoring import currencies_compatible

logger = logging.getLogger("reconagent.llm_adjudicate")

CANDIDATES_PER_ROW = None  # filled from settings.MAX_CANDIDATES at call time
ALLOWED_AI_DECISIONS = ("MATCH", "NO_MATCH", "AMBIGUOUS")
Row = Dict[str, Any]
AmountFn = Callable[[Row], Optional[float]]


def _top_candidates(l: Row, remaining_right: List[Row], l_amt_fn: AmountFn, r_amt_fn: AmountFn) -> List[Row]:
    scored = []
    l_amt = l_amt_fn(l) or 0
    for r in remaining_right:
        amt_diff = abs(l_amt - (r_amt_fn(r) or 0))
        date_diff = 9999
        if l.get("transaction_date") and r.get("transaction_date"):
            date_diff = abs((l["transaction_date"] - r["transaction_date"]).days)
        text_score = text_similarity(l, r)
        id_bonus = -250 if identities_overlap(l, r) else 0
        proximity = amt_diff * 1000 - text_score + date_diff * 10 + id_bonus
        scored.append((proximity, r))
    scored.sort(key=lambda x: (x[0], x[1]["source_record_id"]))
    cap = min(settings.MAX_CANDIDATES, 20)
    return [r for _, r in scored[:cap]]


def _build_prompt(batch, l_amt_fn, r_amt_fn, left_source, right_source) -> str:
    payload = []
    for l, candidates in batch:
        payload.append({
            "left_id": l["source_record_id"],
            "left": {
                "source": left_source, "amount": l_amt_fn(l), "date": str(l.get("transaction_date")),
                "counterparty": l.get("counterparty"), "reference": l.get("reference"),
            },
            "candidates": [
                {
                    "right_id": c["source_record_id"], "amount": r_amt_fn(c),
                    "date": str(c.get("transaction_date")), "counterparty": c.get("counterparty"),
                    "reference": c.get("reference"),
                } for c in candidates
            ],
        })
    return (
        "You are the AI adjudication layer for financial reconciliation. "
        "You may interpret semantic ambiguity. You MUST NOT override hard financial facts "
        "(currency mismatch, impossible amounts, invented IDs).\n"
        f"Left source='{left_source}', right source='{right_source}'.\n"
        "For EACH item, choose exactly one allowed decision: MATCH, NO_MATCH, or AMBIGUOUS.\n"
        "MATCH requires candidate_id to be one of the provided candidate IDs.\n\n"
        f"Items:\n{json.dumps(payload, indent=2)}\n\n"
        "Respond with ONLY a JSON array:\n"
        '[{"left_id": "...", "decision": "MATCH"|"NO_MATCH"|"AMBIGUOUS", '
        '"candidate_id": "... or null", "confidence": 0.0, "evidence": [], "contradictions": [], '
        '"reason": "...", "exception_type": null}]\n'
        "Legacy keys match/matched_id are also accepted. exception_type if not matching must be one of: "
        '"amount_mismatch", "timing_difference", "missing_counterpart", "ambiguous".'
    )


def _heuristic_adjudicate(batch, l_amt_fn, r_amt_fn) -> List[Dict[str, Any]]:
    """Transparent, no-API-key fallback so the pipeline never silently dies."""
    results = []
    for l, candidates in batch:
        if not candidates:
            results.append({
                "left_id": l["source_record_id"], "match": False, "matched_id": None,
                "confidence": 0.0, "reason": "No candidate rows within amount/date proximity.",
            })
            continue
        best = candidates[0]
        text_score = text_similarity(l, best)
        amt_diff = abs((l_amt_fn(l) or 0) - (r_amt_fn(best) or 0))
        date_diff = (abs((l["transaction_date"] - best["transaction_date"]).days)
                     if l.get("transaction_date") and best.get("transaction_date") else 99)
        id_hit = identities_overlap(l, best)
        confidence = max(0.0, min(0.95, (text_score / 100.0) * 0.65 + (1 - min(date_diff, 10) / 10) * 0.35))
        if id_hit and amt_diff <= max(0.5, settings.AMOUNT_TOLERANCE):
            confidence = max(confidence, 0.92)
        if amt_diff > 0.5:
            confidence *= 0.3
        is_match = confidence >= settings.LLM_CONFIDENCE_THRESHOLD
        l_amt = abs(l_amt_fn(l) or 0) or 1
        rel = amt_diff / l_amt
        if is_match:
            exception_type = None
        elif id_hit and amt_diff > 0.5:
            exception_type = "amount_mismatch"
        elif amt_diff > 0.5 and rel <= 0.2:
            exception_type = "amount_mismatch"
        elif date_diff > settings.TIMING_TOLERANCE_DAYS and amt_diff <= 0.5:
            exception_type = "timing_difference"
        elif not id_hit and (text_score < 40 or rel > 0.2):
            exception_type = "missing_counterpart"
        else:
            exception_type = "ambiguous"
        results.append({
            "left_id": l["source_record_id"],
            "match": is_match,
            "matched_id": best["source_record_id"] if is_match else None,
            "confidence": round(confidence, 3),
            "exception_type": exception_type,
            "reason": (
                f"Heuristic fallback (no LLM API key configured): counterparty similarity "
                f"{round(text_score, 1)}, amount diff {round(amt_diff, 2)}, date diff {date_diff}d."
            ),
        })
    return results


def run_llm_adjudication(
    remaining_left: List[Row], remaining_right: List[Row],
    left_amount_fn: AmountFn, right_amount_fn: AmountFn,
    left_source: str, right_source: str,
    batch_size: int, confidence_threshold: float,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int, int, int]:
    """
    Returns (results, exceptions, llm_call_count, llm_batched_call_count, failover_count).
    """
    right_by_id = {r["source_record_id"]: r for r in remaining_right}

    batches: List[List[Tuple[Row, List[Row]]]] = []
    current: List[Tuple[Row, List[Row]]] = []
    for l in remaining_left:
        candidates = _top_candidates(l, remaining_right, left_amount_fn, right_amount_fn)
        current.append((l, candidates))
        if len(current) >= batch_size:
            batches.append(current)
            current = []
    if current:
        batches.append(current)

    results, exceptions = [], []
    llm_call_count = 0
    llm_batched_call_count = 0
    failover_count = 0

    for batch in batches:
        prompt = _build_prompt(batch, left_amount_fn, right_amount_fn, left_source, right_source)
        provider_used = None
        raw_results = None

        try:
            raw_results = groq_client.adjudicate_batch(prompt)
            provider_used = "groq"
            llm_call_count += 1
        except Exception as groq_err:
            # The primary provider failed for this batch. Count it as a failover
            # whether Gemini rescues it OR the offline heuristic takes over --
            # otherwise a silently-unreachable Groq key would report
            # "no failover, everything handled" when nothing was actually
            # handled by Groq (README Bug 1).
            failover_count += 1
            logger.warning(
                "LLM adjudication (%s->%s): Groq call failed for a batch of %d item(s) -- "
                "failing over. Reason: %r",
                left_source, right_source, len(batch), groq_err,
            )
            try:
                raw_results = gemini_fallback.adjudicate_batch(prompt)
                provider_used = "gemini"
                llm_call_count += 1
            except Exception as gem_err:
                logger.warning(
                    "LLM adjudication (%s->%s): Gemini failover also failed for the same batch "
                    "-- falling back to the offline heuristic adjudicator. Reason: %r",
                    left_source, right_source, gem_err,
                )
                raw_results = _heuristic_adjudicate(batch, left_amount_fn, right_amount_fn)
                provider_used = "heuristic"

        if provider_used:
            logger.info(
                "LLM adjudication tier invoked (%s->%s): %d item(s), %d candidate(s), provider=%s",
                left_source, right_source, len(batch), sum(len(cands) for _, cands in batch),
                provider_used,
            )

        if len(batch) > 1:
            llm_batched_call_count += 1

        raw_by_id = {item.get("left_id"): item for item in (raw_results or [])}
        for l, cands in batch:
            cand_ids = {c["source_record_id"] for c in cands}
            candidates_shown = [
                {
                    "transaction_id": c["source_record_id"], "amount": right_amount_fn(c),
                    "date": str(c.get("transaction_date")) if c.get("transaction_date") else None,
                    "counterparty": c.get("counterparty"), "reference": c.get("reference"),
                } for c in cands
            ]
            r = raw_by_id.get(l["source_record_id"])
            if r is None:
                exceptions.append({
                    "left": l, "right": None, "match_stage": "unresolved",
                    "confidence": 0.0, "status": "exception", "exception_type": "ambiguous",
                    "reason": "LLM did not return a decision for this row (missing from batch response).",
                    "candidates_shown": candidates_shown, "provider_used": provider_used,
                    "decision": "AMBIGUOUS", "candidate_ids": list(cand_ids),
                    "contradictions": ["invalid_or_missing_ai_output"],
                })
                continue

            confidence = float(r.get("confidence", 0) or 0)
            decision = str(r.get("decision") or "").upper()
            matched_id = r.get("candidate_id") or r.get("matched_id")
            if not decision:
                if r.get("match") and matched_id:
                    decision = "MATCH"
                elif r.get("exception_type") == "ambiguous":
                    decision = "AMBIGUOUS"
                else:
                    decision = "NO_MATCH"

            # AI cannot invent candidate IDs or override hard constraints.
            if decision == "MATCH":
                if not matched_id or matched_id not in cand_ids:
                    decision = "AMBIGUOUS"
                    r["reason"] = (r.get("reason") or "") + " AI proposed an unknown candidate_id; failed safe to review."
                    matched_id = None
                else:
                    target = right_by_id.get(matched_id)
                    if target is not None and not currencies_compatible(l.get("currency"), target.get("currency")):
                        decision = "NO_MATCH"
                        r["exception_type"] = "currency_mismatch"
                        r["reason"] = "Hard constraint: currency mismatch; AI match rejected."
                        matched_id = None
                    elif target is None:
                        decision = "AMBIGUOUS"
                        matched_id = None

            if decision not in ALLOWED_AI_DECISIONS:
                decision = "AMBIGUOUS"

            is_match = decision == "MATCH" and confidence >= confidence_threshold and matched_id
            reason = r.get("reason", "")

            if is_match:
                matched_right = right_by_id.get(matched_id)
                results.append({
                    "left": l, "right": matched_right, "match_stage": "llm",
                    "confidence": confidence, "status": "matched", "exception_type": None,
                    "reason": reason, "candidates_shown": candidates_shown, "provider_used": provider_used,
                    "decision": "MATCH", "candidate_ids": list(cand_ids),
                    "evidence": r.get("evidence") or {"stage": "llm"},
                    "contradictions": r.get("contradictions") or [],
                    "rule_id": "R009",
                })
            else:
                exception_type = r.get("exception_type")
                if decision == "AMBIGUOUS":
                    exception_type = "ambiguous"
                elif exception_type not in ("amount_mismatch", "timing_difference",
                                           "missing_counterpart", "ambiguous", "currency_mismatch"):
                    exception_type = "missing_counterpart" if not cands else "ambiguous"
                exceptions.append({
                    "left": l, "right": None, "match_stage": "unresolved",
                    "confidence": confidence, "status": "exception", "exception_type": exception_type,
                    "reason": reason or "Below confidence threshold; held for human review.",
                    "candidates_shown": candidates_shown, "provider_used": provider_used,
                    "decision": "AMBIGUOUS" if decision != "NO_MATCH" else "UNMATCHED",
                    "candidate_ids": list(cand_ids),
                    "contradictions": r.get("contradictions") or [],
                    "rule_id": "R009",
                })

    return results, exceptions, llm_call_count, llm_batched_call_count, failover_count
