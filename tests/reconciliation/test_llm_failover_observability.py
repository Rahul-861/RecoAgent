"""Regression: LLM adjudication tier must be observable even when every
provider is unreachable (README Bug 1).

Before the fix, a silently-unreachable Groq/Gemini key fell back to the
offline heuristic with NO logging and NO failover count, so the dashboard
reported "LLM: 0 calls / no failover needed" while the offline heuristic had
actually adjudicated the rows. This test locks in that a provider failure is
(a) counted as a failover and (b) logged.
"""
from datetime import date

import pytest

from app.pipeline.llm_adjudicate import run_llm_adjudication


def _row(rid, amount, counterparty, ref, d=date(2024, 1, 1)):
    return {
        "source_record_id": rid, "amount": amount, "transaction_date": d,
        "counterparty": counterparty, "reference": ref, "currency": "INR",
        "description": counterparty,
    }


def _amt(r):
    return r.get("amount") or 0


def test_provider_failures_are_counted_and_logged(monkeypatch, caplog):
    import app.pipeline.llm_adjudicate as mod

    def boom(*a, **k):
        raise RuntimeError("simulated provider outage")

    monkeypatch.setattr(mod.groq_client, "adjudicate_batch", boom)
    monkeypatch.setattr(mod.gemini_fallback, "adjudicate_batch", boom)

    left = [_row("P1", 100, "Vendor A", "REF1"), _row("P2", 200, "Vendor B", "REF2")]
    right = [_row("B1", 100, "Vendor A", "REF1"), _row("B2", 200, "Vendor B", "REF2")]

    with caplog.at_level("WARNING", logger="reconagent.llm_adjudicate"):
        results, exceptions, llm_calls, batched, failovers = run_llm_adjudication(
            left, right, _amt, _amt, "processor", "bank",
            batch_size=4, confidence_threshold=0.75,
        )

    # Both providers failed -> the offline heuristic took over, and that is
    # reported as a real failover rather than being silently swallowed.
    assert failovers == 1
    assert llm_calls == 0
    # Every row routed through the LLM tier carries the heuristic provider tag.
    tagged = results + exceptions
    assert tagged, "rows must still be adjudicated (by the heuristic fallback)"
    assert {m["provider_used"] for m in tagged} == {"heuristic"}
    joined = "\n".join(rec.message for rec in caplog.records)
    assert "Groq" in joined and "Gemini" in joined


def test_successful_groq_counts_call_and_no_failover(monkeypatch):
    import app.pipeline.llm_adjudicate as mod

    def ok(prompt):
        # One entry per left row, all confidently matched.
        return [
            {"left_id": "P1", "decision": "MATCH", "candidate_id": "B1",
             "confidence": 0.9, "reason": "ok", "evidence": [], "contradictions": []},
            {"left_id": "P2", "decision": "MATCH", "candidate_id": "B2",
             "confidence": 0.9, "reason": "ok", "evidence": [], "contradictions": []},
        ]

    monkeypatch.setattr(mod.groq_client, "adjudicate_batch", ok)
    monkeypatch.setattr(mod.gemini_fallback, "adjudicate_batch", ok)

    left = [_row("P1", 100, "Vendor A", "REF1"), _row("P2", 200, "Vendor B", "REF2")]
    right = [_row("B1", 100, "Vendor A", "REF1"), _row("B2", 200, "Vendor B", "REF2")]

    results, exceptions, llm_calls, batched, failovers = run_llm_adjudication(
        left, right, _amt, _amt, "processor", "bank",
        batch_size=4, confidence_threshold=0.75,
    )

    assert llm_calls == 1
    assert failovers == 0
    assert len(results) == 2
    assert {m["match_stage"] for m in results} == {"llm"}
    assert {m["provider_used"] for m in results} == {"groq"}
