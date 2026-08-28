"""Confidence calibration buckets (LLM matches)."""
from __future__ import annotations

from typing import Any, Dict, List


DEFAULT_BUCKETS = [("0.75-0.80", 0.75, 0.80), ("0.80-0.90", 0.80, 0.90), ("0.90-1.00", 0.90, 1.001)]


def calibration_buckets(matches: List[Any], buckets=DEFAULT_BUCKETS) -> List[Dict[str, Any]]:
    out = []
    for label, lo, hi in buckets:
        bucket = [m for m in matches if lo <= (m.confidence or 0) < hi]
        n = len(bucket)
        n_correct = sum(1 for m in bucket if getattr(m, "correct_by_answer_key", None))
        out.append({"bucket": label, "n": n, "accuracy": round(n_correct / n, 3) if n else None})
    return out
