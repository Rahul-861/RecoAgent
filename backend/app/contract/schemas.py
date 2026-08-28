"""Canonical transaction and explicit reconciliation enumerations."""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class DecisionState(str, Enum):
    MATCH = "MATCH"
    PARTIAL_MATCH = "PARTIAL_MATCH"
    AMBIGUOUS = "AMBIGUOUS"
    UNMATCHED = "UNMATCHED"
    DUPLICATE = "DUPLICATE"
    INVALID = "INVALID"
    ERROR = "ERROR"


class ReconciliationState(str, Enum):
    UNPROCESSED = "UNPROCESSED"
    VALIDATED = "VALIDATED"
    NORMALIZED = "NORMALIZED"
    CANDIDATES_FOUND = "CANDIDATES_FOUND"
    EVALUATED = "EVALUATED"
    MATCH = "MATCH"
    PARTIAL_MATCH = "PARTIAL_MATCH"
    AMBIGUOUS = "AMBIGUOUS"
    UNMATCHED = "UNMATCHED"
    RECONCILED = "RECONCILED"
    REVIEW = "REVIEW"
    EXCEPTION = "EXCEPTION"
    DUPLICATE = "DUPLICATE"
    INVALID = "INVALID"
    ERROR = "ERROR"


class ExceptionCategory(str, Enum):
    INVALID_RECORD = "INVALID_RECORD"
    UNMATCHED_SOURCE = "UNMATCHED_SOURCE"
    UNMATCHED_TARGET = "UNMATCHED_TARGET"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    DATE_MISMATCH = "DATE_MISMATCH"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    REFERENCE_MISMATCH = "REFERENCE_MISMATCH"
    MISSING_REFERENCE = "MISSING_REFERENCE"
    DUPLICATE = "DUPLICATE"
    MULTIPLE_CANDIDATES = "MULTIPLE_CANDIDATES"
    PARTIAL_PAYMENT = "PARTIAL_PAYMENT"
    MISSING_SETTLEMENT = "MISSING_SETTLEMENT"
    FEE_MISMATCH = "FEE_MISMATCH"
    REFUND = "REFUND"
    CHARGEBACK = "CHARGEBACK"
    AGGREGATION_REQUIRED = "AGGREGATION_REQUIRED"
    AI_UNCERTAIN = "AI_UNCERTAIN"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    SYSTEM_ERROR = "SYSTEM_ERROR"


class ExceptionSeverity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ExceptionLifecycle(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"


class RelationshipType(str, Enum):
    ONE_TO_ONE = "ONE_TO_ONE"
    ONE_TO_MANY = "ONE_TO_MANY"
    MANY_TO_ONE = "MANY_TO_ONE"


class CanonicalTransaction(BaseModel):
    transaction_id: Optional[str] = None
    source: str
    source_record_id: str

    transaction_date: Optional[date] = None
    value_date: Optional[date] = None
    original_timestamp: Optional[str] = None
    source_timezone: Optional[str] = None

    amount: Optional[float] = None
    original_amount: Optional[str] = None
    currency: Optional[str] = None

    transaction_type: Optional[str] = None
    status: Optional[str] = None

    reference: Optional[str] = None
    reference_normalized: Optional[str] = None
    external_reference: Optional[str] = None

    counterparty_id: Optional[str] = None
    counterparty_name: Optional[str] = None
    counterparty_normalized: Optional[str] = None
    description: Optional[str] = None
    description_normalized: Optional[str] = None

    invoice_id: Optional[str] = None
    order_id: Optional[str] = None
    settlement_id: Optional[str] = None
    payment_id: Optional[str] = None

    fee: Optional[float] = None
    tax: Optional[float] = None
    refund_amount: Optional[float] = None
    chargeback_amount: Optional[float] = None
    gross_amount: Optional[float] = None
    net_amount: Optional[float] = None

    parent_transaction_id: Optional[str] = None

    raw_record: Dict[str, Any] = Field(default_factory=dict)
    normalized_record: Dict[str, Any] = Field(default_factory=dict)
    normalization_version: str = "1.0"

    is_valid: bool = True
    validation_errors: List[str] = Field(default_factory=list)
    recon_state: ReconciliationState = ReconciliationState.UNPROCESSED

    model_config = ConfigDict(use_enum_values=True)
