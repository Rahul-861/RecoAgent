"""
Generic pairwise matching engine, shared by the bank<->processor
(settlement) pass and the bank<->erp (ledger) pass (README §9-11).

Kept source-agnostic: callers supply an `amount_fn` that extracts the
amount to compare for each side (e.g. processor.net_amount vs
bank.amount), so the same exact/fuzzy/semantic code powers every pair in
the pipeline instead of being duplicated per source pair.
"""
from __future__ import annotations
from datetime import date as date_type
from typing import List, Dict, Any, Tuple, Callable, Optional

from app.config import settings
from app.llm.embeddings import get_embedding, cosine_similarity
from app.pipeline.identity import amount_close, identities_overlap, text_similarity
from app.pipeline.scoring import currencies_compatible, margin_ok
from app.rules.reference_rules import references_match

Row = Dict[str, Any]
AmountFn = Callable[[Row], Optional[float]]


def _ref_match(row_a, row_b) -> bool:
    if identities_overlap(row_a, row_b):
        return True
    return references_match(
        row_a.get("reference") if isinstance(row_a, dict) else row_a,
        row_b.get("reference") if isinstance(row_b, dict) else row_b,
        row_a.get("reference_normalized") if isinstance(row_a, dict) else None,
        row_b.get("reference_normalized") if isinstance(row_b, dict) else None,
    )


def _amount_match(a: Optional[float], b: Optional[float], tolerance: float) -> bool:
    return amount_close(a, b, tolerance)


def _date_within(a: date_type, b: date_type, tolerance_days: int) -> bool:
    if a is None or b is None:
        return True  # don't over-constrain on missing dates
    return abs((a - b).days) <= tolerance_days


def run_exact_match(
    left: List[Row], right: List[Row],
    left_amount_fn: AmountFn, right_amount_fn: AmountFn,
    amount_tolerance: float, timing_tolerance_days: int,
    stage_name: str = "exact",
) -> Tuple[List[Dict[str, Any]], List[Row], List[Row]]:
    """Match on (amount within tolerance) + (date within tolerance) + (reference)."""
    matches = []
    used_right_ids = set()
    remaining_left = []
    right_sorted = sorted(right, key=lambda r: str(r.get("source_record_id") or ""))

    for l in left:
        found = []
        l_amt = left_amount_fn(l)
        for r in right_sorted:
            rid = r["source_record_id"]
            if rid in used_right_ids:
                continue
            if not currencies_compatible(l.get("currency"), r.get("currency")):
                continue
            r_amt = right_amount_fn(r)
            if not _amount_match(l_amt, r_amt, amount_tolerance):
                continue
            if not _date_within(l["transaction_date"], r["transaction_date"], timing_tolerance_days):
                continue
            if not _ref_match(l, r):
                continue
            found.append(r)

        if len(found) == 1:
            hit = found[0]
            used_right_ids.add(hit["source_record_id"])
            fee_note = ""
            if l.get("fee_amount") or l.get("refund_amount"):
                fee_note = (
                    f" (gross {l.get('gross_amount')} - fee {l.get('fee_amount') or 0}"
                    f" - refund {l.get('refund_amount') or 0} = net {l_amt})"
                )
            effective_stage = "fee_aware" if fee_note else stage_name
            matches.append({
                "left": l, "right": hit, "match_stage": effective_stage,
                "confidence": 1.0 if not fee_note else 0.98,
                "reason": (
                    f"{'Fee-aware' if fee_note else 'Exact'} match on amount ({l_amt}) "
                    f"and reference '{l['reference']}'{fee_note}."
                ),
                "candidates_shown": None, "provider_used": None,
                "evidence": {
                    "amount": "exact_after_fee" if fee_note else "exact",
                    "currency": "exact",
                    "reference": "strong_match",
                    "date": "within_window",
                },
                "contradictions": [],
                "candidate_ids": [hit["source_record_id"]],
                "top_score": 1.0, "second_score": None, "score_margin": 1.0,
                "rule_id": "R003" if fee_note else "R001",
            })
        elif len(found) > 1:
            remaining_left.append(l)
            # Leave for duplicate / ambiguous handling rather than first-wins.
        else:
            remaining_left.append(l)

    remaining_right = [r for r in right if r["source_record_id"] not in used_right_ids]
    return matches, remaining_left, remaining_right


def run_fuzzy_semantic_match(
    remaining_left: List[Row], remaining_right: List[Row],
    left_amount_fn: AmountFn, right_amount_fn: AmountFn,
    fuzzy_threshold: float, semantic_threshold: float,
    amount_tolerance: float, timing_tolerance_days: int,
    stage_prefix: str = "",
) -> Tuple[List[Dict[str, Any]], List[Row], List[Row], Dict[str, List[Dict[str, Any]]]]:
    """
    Returns (matches, still_remaining_left, still_remaining_right, multi_candidate_map).
    multi_candidate_map: left_source_record_id -> [{"row": right_row, "score", "stage"}]
    for every left row with MORE THAN ONE candidate clearing threshold (-> duplicate check).
    """
    matches = []
    used_right_ids = set()
    still_remaining_left = []
    multi_candidate_map: Dict[str, List[Dict[str, Any]]] = {}
    min_margin = settings.MIN_CANDIDATE_MARGIN
    right_sorted = sorted(remaining_right, key=lambda r: str(r.get("source_record_id") or ""))

    for l in remaining_left:
        l_amt = left_amount_fn(l)
        candidates = []
        for r in right_sorted:
            rid = r["source_record_id"]
            if rid in used_right_ids:
                continue
            if not currencies_compatible(l.get("currency"), r.get("currency")):
                continue
            r_amt = right_amount_fn(r)
            if not _amount_match(l_amt, r_amt, amount_tolerance):
                continue
            if not _date_within(l["transaction_date"], r["transaction_date"], timing_tolerance_days):
                continue
            fuzzy_score = text_similarity(l, r)
            candidates.append((r, fuzzy_score, "fuzzy"))

        candidates.sort(key=lambda c: (-c[1], c[0]["source_record_id"]))
        fuzzy_hits = [c for c in candidates if c[1] >= fuzzy_threshold]

        semantic_hits = []
        if not fuzzy_hits and candidates:
            emb_l = get_embedding(
                " ".join(filter(None, [l.get("counterparty"), l.get("description"), l.get("reference")]))
            )
            for r, score, _ in candidates:
                emb_r = get_embedding(
                    " ".join(filter(None, [r.get("counterparty"), r.get("description"), r.get("reference")]))
                )
                sim = cosine_similarity(emb_l, emb_r)
                if sim >= semantic_threshold:
                    semantic_hits.append((r, sim, "semantic"))
            semantic_hits.sort(key=lambda c: (-c[1], c[0]["source_record_id"]))

        hits = fuzzy_hits or semantic_hits
        if len(hits) > 1:
            top = hits[0][1]
            second = hits[1][1]
            # Fuzzy scores are 0-100; semantic and margin threshold are 0-1.
            if hits[0][2] == "fuzzy":
                top_n, second_n = top / 100.0, second / 100.0
                threshold_n = fuzzy_threshold / 100.0
            else:
                top_n, second_n, threshold_n = top, second, semantic_threshold
            if margin_ok(top_n, second_n, threshold_n, min_margin):
                hits = [hits[0]]
                l["_score_margin"] = round(top_n - second_n, 4)
                l["_second_score"] = round(second_n, 4)
            else:
                l["_score_margin"] = round(top_n - second_n, 4)
                l["_top_score"] = round(top_n, 4)
                l["_second_score"] = round(second_n, 4)

        if len(hits) == 0:
            still_remaining_left.append(l)
        elif len(hits) == 1:
            r, score, stage = hits[0]
            used_right_ids.add(r["source_record_id"])
            confidence = round(min(score / 100.0, 0.99) if stage == "fuzzy" else min(score, 0.99), 3)
            matches.append({
                "left": l, "right": r, "match_stage": stage,
                "confidence": confidence,
                "reason": (
                    f"{'String' if stage == 'fuzzy' else 'Semantic'} similarity match "
                    f"(score={round(score, 2)}) with matching amount ({l_amt})."
                ),
                "candidates_shown": None, "provider_used": None,
                "evidence": {
                    "amount": "exact",
                    "currency": "exact",
                    "counterparty": "fuzzy_match" if stage == "fuzzy" else "semantic_match",
                    "date": "within_window",
                },
                "contradictions": [],
                "candidate_ids": [r["source_record_id"]],
                "top_score": confidence,
                "second_score": l.get("_second_score"),
                "score_margin": l.get("_score_margin"),
                "rule_id": "R004",
            })
        else:
            multi_candidate_map[l["source_record_id"]] = [
                {"row": r, "score": score, "stage": stage} for r, score, stage in hits
            ]
            still_remaining_left.append(l)

    still_remaining_right = [r for r in remaining_right if r["source_record_id"] not in used_right_ids]
    return matches, still_remaining_left, still_remaining_right, multi_candidate_map
