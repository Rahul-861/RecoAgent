"""
Stage C (README §41.5): optional AI-bounded estimation for AT_RISK lines
where the rule-based direction is known but timing confidence is still
low (no historical lag data). Strictly additive and off by default when
nothing is configured.

Non-negotiable fail-safe (mirrors README §17/§37 for reconciliation): if
no GROQ_API_KEY/GEMINI_API_KEY is configured, the LLM call fails, or the
response can't be parsed into a bounded date range, the line MUST fall
back to UNCLASSIFIABLE -- never silently keep the rule-only estimate
relabeled as AI-confirmed, and never fabricate a number.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.config import settings
from app.llm import gemini_fallback, groq_client


def apply_ai_stage(lines: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int, int]:
    """
    Returns (lines, llm_call_count, failover_count). Every line with
    ai_eligible=True is either upgraded with a bounded AI estimate or
    demoted to UNCLASSIFIABLE -- there is no other outcome.
    """
    llm_calls = 0
    failovers = 0
    out: List[Dict[str, Any]] = []

    for line in lines:
        if not line.get("ai_eligible") or not settings.FORECAST_AI_ENABLED:
            out.append(line)
            continue

        if not settings.GROQ_API_KEY and not settings.GEMINI_API_KEY:
            out.append(_demote_to_unclassifiable(line, "no LLM key configured"))
            continue

        prompt = _build_prompt(line)
        result = None
        try:
            llm_calls += 1
            result = groq_client.adjudicate_batch(prompt)
        except groq_client.GroqError:
            failovers += 1
            try:
                result = gemini_fallback.adjudicate_batch(prompt)
            except Exception:
                result = None
        except Exception:
            result = None

        bounded = _parse_bounded_estimate(result)
        if bounded is None:
            out.append(_demote_to_unclassifiable(line, "AI response could not be parsed into a bounded range"))
        else:
            new_line = dict(line)
            new_line["lag_source"] = "ai_estimated"
            new_line["confidence"] = bounded.get("confidence", "low")
            new_line["ai_used"] = True
            new_line["evidence"] = {**line.get("evidence", {}), "ai_range_days": bounded.get("range_days")}
            out.append(new_line)

    return out, llm_calls, failovers


def _demote_to_unclassifiable(line: Dict[str, Any], reason: str) -> Dict[str, Any]:
    new_line = dict(line)
    new_line["category"] = "UNCLASSIFIABLE"
    new_line["bucket_date"] = None
    new_line["confidence"] = "low"
    new_line["lag_source"] = None
    new_line["evidence"] = {**line.get("evidence", {}), "ai_fallback_reason": reason}
    return new_line


def _build_prompt(line: Dict[str, Any]) -> str:
    reason = line.get("evidence", {}).get("reason")
    return (
        "Given this open financial exception, estimate a bounded date range "
        "(min_days, max_days from today) for when the implied cash movement "
        "will occur, and a qualitative confidence (low|medium|high). "
        "Respond ONLY as a JSON array with one object: "
        '[{"min_days": <int>, "max_days": <int>, "confidence": "<low|medium|high>"}]. '
        f"Exception: {reason}. Direction: {line.get('direction')}. "
        f"Amount: {line.get('amount')} {line.get('currency')}."
    )


def _parse_bounded_estimate(result: Any):
    if not result or not isinstance(result, list) or not result:
        return None
    item = result[0]
    if not isinstance(item, dict):
        return None
    lo, hi = item.get("min_days"), item.get("max_days")
    if not isinstance(lo, (int, float)) or not isinstance(hi, (int, float)):
        return None
    if lo > hi:
        return None
    return {"range_days": [lo, hi], "confidence": item.get("confidence", "low")}
