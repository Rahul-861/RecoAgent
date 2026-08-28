"""Configurable matching policies per source pair."""
from __future__ import annotations

from typing import Dict, Any

SOURCE_PAIR_POLICIES: Dict[str, Dict[str, Any]] = {
    "processor-bank": {
        "strong_signals": ["settlement_id", "net_amount", "fee", "settlement_date", "processor_reference"],
        "left_amount_field": "net_amount",
        "right_amount_field": "amount",
        "allow_aggregation": True,
        "relationship": "MANY_TO_ONE",
    },
    "erp-bank": {
        "strong_signals": ["invoice_id", "erp_reference", "amount", "counterparty", "value_date", "transaction_type"],
        "left_amount_field": "amount",
        "right_amount_field": "amount",
        "allow_aggregation": True,
        "relationship": "ONE_TO_MANY",
    },
    "invoice-payment": {
        "strong_signals": ["invoice_id", "counterparty", "amount", "payment_date", "reference"],
        "left_amount_field": "amount",
        "right_amount_field": "amount",
        "allow_aggregation": True,
        "relationship": "ONE_TO_MANY",
    },
}


def policy_for(left_source: str, right_source: str) -> Dict[str, Any]:
    key = f"{left_source}-{right_source}"
    return SOURCE_PAIR_POLICIES.get(key, {
        "strong_signals": ["reference", "amount", "currency", "date"],
        "left_amount_field": "amount",
        "right_amount_field": "amount",
        "allow_aggregation": False,
        "relationship": "ONE_TO_ONE",
    })
