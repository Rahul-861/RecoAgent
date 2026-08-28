"""Formal reconciliation contract: inputs, normalization, matching, decisions, audit."""
from __future__ import annotations

from typing import Any, Dict, List

from app.config import settings
from app.contract.schemas import DecisionState, ExceptionCategory, ExceptionSeverity


SUPPORTED_SOURCES = ("bank", "processor", "erp")

REQUIRED_FIELDS = {
    "bank": ["source_record_id", "amount", "currency"],
    "processor": ["source_record_id", "currency"],
    "erp": ["source_record_id", "currency"],
}

OPTIONAL_FIELDS = [
    "transaction_date", "value_date", "reference", "counterparty", "description",
    "invoice_id", "order_id", "settlement_id", "fee_amount", "refund_amount",
    "gross_amount", "net_amount", "tax", "chargeback_amount", "parent_transaction_id",
]

FIELD_TYPES = {
    "amount": "number",
    "gross_amount": "number",
    "net_amount": "number",
    "fee_amount": "number",
    "refund_amount": "number",
    "currency": "iso4217_or_known",
    "transaction_date": "date",
    "value_date": "date",
    "source_record_id": "string",
}

KNOWN_CURRENCIES = {"INR", "USD", "EUR", "GBP", "SGD", "AED", "JPY", "AUD", "CAD"}

ALLOWED_TRANSACTION_TYPES = {
    "credit", "debit", "payment", "refund", "fee", "settlement", "journal", "chargeback",
}


class ReconciliationContract:
    """Single source of truth for how reconciliation is supposed to work."""

    version = settings.RECONCILIATION_VERSION
    pipeline_version = settings.PIPELINE_VERSION
    normalization_version = settings.NORMALIZATION_VERSION
    rule_set_version = settings.RULE_SET_VERSION
    candidate_generation_version = settings.CANDIDATE_GENERATION_VERSION
    configuration_version = settings.CONFIGURATION_VERSION

    supported_sources = SUPPORTED_SOURCES
    required_fields = REQUIRED_FIELDS
    optional_fields = OPTIONAL_FIELDS
    field_types = FIELD_TYPES
    known_currencies = KNOWN_CURRENCIES
    allowed_transaction_types = ALLOWED_TRANSACTION_TYPES
    decision_states = [s.value for s in DecisionState]
    exception_categories = [c.value for c in ExceptionCategory]
    exception_severities = [s.value for s in ExceptionSeverity]

    missing_field_behavior = "Classify the record INVALID and keep it in batch totals."
    invalid_value_behavior = "Do not send the record into matching; emit INVALID_RECORD."

    normalization = {
        "date": "ISO date (YYYY-MM-DD); preserve original_timestamp and source timezone.",
        "amount": "Decimal number; strip currency symbols and grouping separators. No silent FX conversion.",
        "currency": "Uppercase ISO code. Unknown codes are INVALID unless empty (default INR).",
        "reference": "Preserve original; comparison key is alphanumeric uppercase without boilerplate prefixes.",
        "counterparty": "Preserve original; comparison key collapses legal suffixes, punctuation, case.",
        "description": "Collapse whitespace/case/punctuation; do not drop meaningful tokens.",
    }

    matching = {
        "rule_order": [
            "R001_exact_identity",
            "R002_settlement",
            "R003_fee_adjusted",
            "R007_refund",
            "R008_invoice_aggregation",
            "R004_strong_candidate",
            "R005_currency_conflict",
            "R006_consumed_candidate",
        ],
        "amount_tolerance": settings.AMOUNT_TOLERANCE,
        "timing_tolerance_days": settings.TIMING_TOLERANCE_DAYS,
        "fuzzy_threshold": settings.FUZZY_MATCH_THRESHOLD,
        "semantic_threshold": settings.SEMANTIC_MATCH_THRESHOLD,
        "min_candidate_margin": settings.MIN_CANDIDATE_MARGIN,
        "max_candidates": settings.MAX_CANDIDATES,
        "exact_match": "amount + currency + (reference original or normalized) + date window",
        "partial_match": "compatible amounts that do not fully close (e.g. partial payment)",
        "candidate_rejection": [
            "currency mismatch without FX rule",
            "impossible amount relationship",
            "already consumed transaction",
            "invalid record",
            "impossible date relationship",
        ],
        "signal_priority": [
            "financial_consistency",
            "identity_reference_consistency",
            "temporal_consistency",
            "text_similarity",
        ],
    }

    audit_required_fields = [
        "batch_id", "transaction_id", "matched_transaction_id", "decision", "state",
        "decision_stage", "rule_id", "rule_set_version", "score", "confidence",
        "candidate_ids", "evidence", "contradictions", "AI_used", "AI_provider",
        "AI_model", "pipeline_version", "timestamp",
    ]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "pipeline_version": self.pipeline_version,
            "normalization_version": self.normalization_version,
            "rule_set_version": self.rule_set_version,
            "candidate_generation_version": self.candidate_generation_version,
            "configuration_version": self.configuration_version,
            "inputs": {
                "supported_sources": list(self.supported_sources),
                "required_fields": self.required_fields,
                "optional_fields": self.optional_fields,
                "field_types": self.field_types,
                "missing_field_behavior": self.missing_field_behavior,
                "invalid_value_behavior": self.invalid_value_behavior,
            },
            "normalization": self.normalization,
            "matching": self.matching,
            "decisions": self.decision_states,
            "exceptions": {
                "categories": self.exception_categories,
                "severities": self.exception_severities,
            },
            "audit_required_fields": self.audit_required_fields,
        }


def get_contract() -> ReconciliationContract:
    return ReconciliationContract()
