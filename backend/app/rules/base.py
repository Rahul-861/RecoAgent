"""Rule catalog: every matching rule has id, name, priority, version, decision."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.config import settings


@dataclass(frozen=True)
class Rule:
    rule_id: str
    rule_name: str
    priority: int
    enabled: bool
    source_pair: str
    conditions: List[str]
    decision: str
    explanation: str
    rule_version: str = settings.RULE_SET_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "priority": self.priority,
            "enabled": self.enabled,
            "source_pair": self.source_pair,
            "conditions": self.conditions,
            "decision": self.decision,
            "explanation": self.explanation,
            "rule_version": self.rule_version,
        }


RULE_CATALOG: List[Rule] = [
    Rule(
        rule_id="R001",
        rule_name="Exact identity",
        priority=10,
        enabled=True,
        source_pair="*",
        conditions=["reference exact or normalized-equal", "amount exact", "currency exact", "date within window"],
        decision="MATCH",
        explanation="Identity + amount + currency + date window.",
    ),
    Rule(
        rule_id="R002",
        rule_name="Settlement batch",
        priority=20,
        enabled=True,
        source_pair="processor-bank",
        conditions=["settlement_id exact", "sum(net_amount) matches bank amount", "settlement date within window"],
        decision="MATCH",
        explanation="Many processor payments settle as one bank deposit.",
    ),
    Rule(
        rule_id="R003",
        rule_name="Fee-adjusted",
        priority=15,
        enabled=True,
        source_pair="processor-bank",
        conditions=["gross - fee - refund = target amount", "currency exact", "date within tolerance"],
        decision="MATCH",
        explanation="Net proceeds after fees/refunds equal the bank credit.",
    ),
    Rule(
        rule_id="R004",
        rule_name="Strong candidate",
        priority=50,
        enabled=True,
        source_pair="*",
        conditions=["amount compatible", "date compatible", "no hard contradiction", "similarity above threshold", "score margin sufficient"],
        decision="MATCH",
        explanation="Soft signals rank a unique winner; close races stay AMBIGUOUS.",
    ),
    Rule(
        rule_id="R005",
        rule_name="Currency conflict",
        priority=5,
        enabled=True,
        source_pair="*",
        conditions=["currency mismatch", "no FX rule enabled"],
        decision="EXCEPTION",
        explanation="Hard constraint: never match across currencies without an FX rule.",
    ),
    Rule(
        rule_id="R006",
        rule_name="Consumed candidate",
        priority=1,
        enabled=True,
        source_pair="*",
        conditions=["candidate already consumed by an incompatible relationship"],
        decision="reject",
        explanation="A transaction cannot be consumed twice.",
    ),
    Rule(
        rule_id="R007",
        rule_name="Refund debit",
        priority=12,
        enabled=True,
        source_pair="processor-bank",
        conditions=["refund_amount > 0", "matching bank debit amount", "date within window"],
        decision="MATCH",
        explanation="Processor refund should appear as a bank debit.",
    ),
    Rule(
        rule_id="R008",
        rule_name="Invoice aggregation",
        priority=25,
        enabled=True,
        source_pair="erp-bank",
        conditions=["shared invoice/reference", "sum of bank credits vs invoice amount", "compatible dates"],
        decision="MATCH or PARTIAL_MATCH",
        explanation="One invoice may be paid by several bank credits.",
    ),
    Rule(
        rule_id="R009",
        rule_name="AI adjudication",
        priority=90,
        enabled=True,
        source_pair="*",
        conditions=["deterministic stages unresolved", "AI cannot invent candidates", "AI cannot override hard constraints"],
        decision="MATCH | AMBIGUOUS | UNMATCHED",
        explanation="AI interprets remaining semantic ambiguity only.",
    ),
]


RULES_BY_ID = {r.rule_id: r for r in RULE_CATALOG}


def rule_for_stage(match_stage: str, fee_note: bool = False) -> Optional[Rule]:
    if match_stage == "exact":
        return RULES_BY_ID["R001"]
    if match_stage == "fee_aware":
        return RULES_BY_ID["R003"]
    if match_stage == "many_to_one":
        return RULES_BY_ID["R002"]
    if match_stage == "one_to_many":
        return RULES_BY_ID["R008"]
    if match_stage in ("fuzzy", "semantic"):
        return RULES_BY_ID["R004"]
    if match_stage == "refund":
        return RULES_BY_ID["R007"]
    if match_stage == "llm":
        return RULES_BY_ID["R009"]
    return None
