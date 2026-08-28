"""
Ground-truth accuracy validation (README §22-26).

Computes precision/recall/F1 per match stage against an optional answer
key, false-match rate, missed-match rate, and confidence calibration for
LLM-adjudicated matches -- turning an asserted match rate into a measured
one. Generalized to the (source, transaction_id) keying used by the
multi-source pipeline, and to many-to-one/one-to-many groups (answer key
rows may list more than one expected id).
"""
from __future__ import annotations
from typing import List, Dict, Any, Tuple, Optional
from sqlalchemy.orm import Session

from app.db import MatchResult, AnswerKeyRow, loads

STAGES = ("exact", "fee_aware", "many_to_one", "one_to_many", "fuzzy", "semantic", "refund", "llm")


def _key(source, txn_id):
    return (source, txn_id)


def _side_confirms(ids, source, other_source, other_ids, answer_map) -> Optional[bool]:
    """True/False if every id on this side has a ground-truth row and they agree
    (or disagree) on the expected counterpart; None if ground truth doesn't cover
    this side at all (so the caller should try the other side instead)."""
    if not ids:
        return None
    for tid in ids:
        ak = answer_map.get(_key(source, tid))
        if ak is None:
            return None
        expected_ids = set(loads(ak.expected_match_ids_json) or [])
        if ak.expected_match_source != other_source or expected_ids != other_ids:
            return False
    return True


def _check_match_correct(m: MatchResult, answer_map: Dict[Tuple[str, str], AnswerKeyRow]) -> Optional[bool]:
    """
    A predicted match is checked against ground truth from whichever side has
    it: some records (e.g. a payment that both settles AND is later refunded)
    participate in more than one true relationship, so a record's answer-key
    row on one side may describe a *different* relationship than the one
    being checked here -- in that case we fall back to validating from the
    other side of the pair instead of reporting a false negative.
    """
    left_ids = loads(m.left_txn_ids_json) or []
    right_ids = loads(m.right_txn_ids_json) or []
    if not left_ids:
        return None

    left_result = _side_confirms(left_ids, m.left_source, m.right_source, set(right_ids), answer_map)
    if left_result is True:
        return True
    right_result = _side_confirms(right_ids, m.right_source, m.left_source, set(left_ids), answer_map)
    if right_result is True:
        return True
    if left_result is False and right_result in (False, None):
        return False
    if right_result is False and left_result in (False, None):
        return False
    return None


def _stage_precision_recall(matches: List[MatchResult], answer_map, stage: str):
    predicted_positive = [m for m in matches if m.match_stage == stage and m.status == "matched"]
    n_predicted = len(predicted_positive)

    correct = 0
    evaluated = 0
    for m in predicted_positive:
        is_correct = _check_match_correct(m, answer_map)
        m.correct_by_answer_key = is_correct
        if is_correct is not None:
            evaluated += 1
            if is_correct:
                correct += 1

    n_expected_here = sum(
        1 for ak in answer_map.values()
        if ak.expected_match_ids_json and _matches_stage_pool(matches, stage, ak)
    )

    precision = round(correct / evaluated, 3) if evaluated else None
    recall = round(correct / n_expected_here, 3) if n_expected_here else None
    return precision, recall, n_predicted, n_expected_here


def _matches_stage_pool(matches, stage, ak) -> bool:
    # Rough attribution: was this expected pair actually resolved (at any
    # stage) so it's countable in *some* stage's recall denominator? We
    # attribute it to `stage` only if a matched row at that stage covers it.
    return any(
        m.match_stage == stage and m.status == "matched"
        and ak.transaction_id in (loads(m.left_txn_ids_json) or [])
        for m in matches
    )


def compute_accuracy(db: Session, batch_id: str) -> Dict[str, Any]:
    answer_rows = db.query(AnswerKeyRow).filter(AnswerKeyRow.batch_id == batch_id).all()
    if not answer_rows:
        return {
            "available": False, "overall_precision": None, "overall_recall": None,
            "overall_f1": None, "false_match_rate": None, "missed_match_rate": None,
            "per_stage": [], "calibration": [],
        }

    answer_map = {_key(ak.source, ak.transaction_id): ak for ak in answer_rows}
    matches = db.query(MatchResult).filter(MatchResult.batch_id == batch_id).all()

    per_stage = []
    total_correct, total_evaluated = 0, 0
    for stage in STAGES:
        precision, recall, n_pred, n_exp = _stage_precision_recall(matches, answer_map, stage)
        per_stage.append({"stage": stage, "precision": precision, "recall": recall,
                           "n_predicted": n_pred, "n_expected": n_exp})
        if precision is not None and n_pred:
            total_correct += round(precision * n_pred)
            total_evaluated += n_pred

    overall_precision = round(total_correct / total_evaluated, 3) if total_evaluated else None
    total_expected_positive = sum(
        1 for ak in answer_map.values() if ak.expected_match_ids_json and loads(ak.expected_match_ids_json)
    )
    overall_recall = round(total_correct / total_expected_positive, 3) if total_expected_positive else None
    overall_f1 = None
    if overall_precision and overall_recall and (overall_precision + overall_recall) > 0:
        overall_f1 = round(2 * overall_precision * overall_recall / (overall_precision + overall_recall), 3)

    false_matches = sum(
        1 for m in matches if m.status == "matched" and m.correct_by_answer_key is False
    )
    total_matched = sum(1 for m in matches if m.status == "matched")
    false_match_rate = round(false_matches / total_matched, 3) if total_matched else None

    missed = sum(
        1 for ak in answer_map.values()
        if ak.expected_match_ids_json and loads(ak.expected_match_ids_json)
        and not any(
            ak.transaction_id in (loads(m.left_txn_ids_json) or []) and m.status == "matched"
            and m.correct_by_answer_key
            for m in matches
        )
    )
    missed_match_rate = round(missed / total_expected_positive, 3) if total_expected_positive else None

    # Confidence calibration for LLM-adjudicated matches only.
    llm_matches = [m for m in matches if m.match_stage == "llm" and m.status == "matched"]
    buckets = [("0.75-0.80", 0.75, 0.80), ("0.80-0.90", 0.80, 0.90), ("0.90-1.00", 0.90, 1.001)]
    calibration = []
    for label, lo, hi in buckets:
        bucket_matches = [m for m in llm_matches if lo <= m.confidence < hi]
        n = len(bucket_matches)
        n_correct = sum(1 for m in bucket_matches if m.correct_by_answer_key)
        calibration.append({
            "bucket": label, "n": n,
            "accuracy": round(n_correct / n, 3) if n else None,
        })

    db.commit()
    return {
        "available": True,
        "overall_precision": overall_precision,
        "overall_recall": overall_recall,
        "overall_f1": overall_f1,
        "false_match_rate": false_match_rate,
        "missed_match_rate": missed_match_rate,
        "per_stage": per_stage,
        "calibration": calibration,
    }
