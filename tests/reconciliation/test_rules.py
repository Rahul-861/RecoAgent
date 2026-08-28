from app.rules.base import RULE_CATALOG, rule_for_stage
from app.pipeline.scoring import currencies_compatible, margin_ok, hard_constraint_failures
from app.pipeline.rule_engine import enrich_decision


def test_rules_have_ids_and_versions():
    assert RULE_CATALOG
    for r in RULE_CATALOG:
        assert r.rule_id.startswith("R")
        assert r.rule_version
        assert r.priority >= 1


def test_stage_maps_to_rule():
    assert rule_for_stage("exact").rule_id == "R001"
    assert rule_for_stage("fee_aware").rule_id == "R003"
    assert rule_for_stage("llm").rule_id == "R009"


def test_currency_hard_constraint():
    failures = hard_constraint_failures({"currency": "INR"}, {"currency": "USD"})
    assert "currency_mismatch" in failures
    assert currencies_compatible("INR", "inr")


def test_margin_policy():
    assert margin_ok(0.96, 0.54, 0.85, 0.10)
    assert not margin_ok(0.96, 0.94, 0.85, 0.10)


def test_enrich_adds_evidence_and_rule():
    u = enrich_decision({
        "left_source": "processor", "left_txn_ids": ["P1"],
        "right_source": "bank", "right_txn_ids": ["B1"],
        "match_stage": "exact", "status": "matched", "confidence": 1.0,
        "exception_type": None, "reason": "exact",
    })
    assert u["decision"] == "MATCH"
    assert u["rule_id"] == "R001"
    assert u["evidence"]
    assert u["pipeline_version"]
