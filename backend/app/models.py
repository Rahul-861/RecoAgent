"""
Pydantic schemas used for API request/response bodies.
Kept separate from the SQLAlchemy ORM models in db.py.
"""
from typing import Optional, List, Any
from pydantic import BaseModel


class UploadResponse(BaseModel):
    batch_id: str
    bank_count: int
    processor_count: int
    erp_count: int
    has_answer_key: bool


class StageBreakdown(BaseModel):
    exact: int = 0
    fee_aware: int = 0
    many_to_one: int = 0
    one_to_many: int = 0
    fuzzy: int = 0
    semantic: int = 0
    refund: int = 0
    llm: int = 0
    unresolved: int = 0


class AccuracyStage(BaseModel):
    stage: str
    precision: Optional[float] = None
    recall: Optional[float] = None
    n_predicted: int = 0
    n_expected: int = 0


class CalibrationBucket(BaseModel):
    bucket: str
    n: int
    accuracy: Optional[float] = None


class AccuracyReport(BaseModel):
    available: bool
    overall_precision: Optional[float] = None
    overall_recall: Optional[float] = None
    overall_f1: Optional[float] = None
    false_match_rate: Optional[float] = None
    missed_match_rate: Optional[float] = None
    per_stage: List[AccuracyStage] = []
    calibration: List[CalibrationBucket] = []


class ReconcileResponse(BaseModel):
    batch_id: str
    total_records: int
    match_rate: float
    stage_breakdown: StageBreakdown
    exception_count: int
    manual_review_reduction: float
    llm_call_count: int
    llm_batched_call_count: int
    failover_count: int
    throughput_per_sec: float
    processing_ms: float
    settlement_variance: Optional[float] = None
    accuracy: AccuracyReport
    validation_status: Optional[str] = None
    control_totals: Optional[dict] = None
    pipeline_version: Optional[str] = None
    rule_set_version: Optional[str] = None
    normalization_version: Optional[str] = None
    audit_completeness: Optional[float] = None
    invalid_count: int = 0
    reused_existing_run: bool = False


class MatchOut(BaseModel):
    match_id: str
    left_source: Optional[str]
    left_txn_ids: List[str] = []
    right_source: Optional[str]
    right_txn_ids: List[str] = []
    match_stage: str
    confidence: float
    reason: str
    candidates_shown: Optional[Any] = None
    provider_used: Optional[str]
    status: str
    exception_type: Optional[str]
    severity: Optional[str]
    review_status: str
    decision: Optional[str] = None
    state: Optional[str] = None
    decision_stage: Optional[str] = None
    rule_id: Optional[str] = None
    evidence: Optional[Any] = None
    contradictions: Optional[Any] = None
    candidate_ids: Optional[List[str]] = None
    exception_category: Optional[str] = None
    exception_lifecycle: Optional[str] = None
    relationship_type: Optional[str] = None
    top_score: Optional[float] = None
    second_score: Optional[float] = None
    score_margin: Optional[float] = None
    ai_used: Optional[bool] = None
    pipeline_version: Optional[str] = None


class ResultsResponse(BaseModel):
    batch_id: str
    matches: List[MatchOut]


class ResolveRequest(BaseModel):
    action: str  # "resolved" | "rejected" | "escalated" | "in_review"
    note: Optional[str] = None
    # Optional: the candidate the human explicitly picked as the correct
    # counterpart when resolving. Attaching the approval to a specific record
    # is what makes ambiguous multi-candidate exceptions learnable.
    chosen_candidate_id: Optional[str] = None
    resolved_by: Optional[str] = "reviewer"


class GraphNode(BaseModel):
    id: str
    source: str
    label: str
    amount: Optional[float] = None
    kind: str  # order | payment | settlement | bank | erp


class GraphEdge(BaseModel):
    source_id: str
    target_id: str
    label: str


class EventChain(BaseModel):
    chain_id: str
    nodes: List[GraphNode]
    edges: List[GraphEdge]
    status: str  # complete | partial


class GraphResponse(BaseModel):
    batch_id: str
    chains: List[EventChain]


class QARequest(BaseModel):
    question: str


class QAResponse(BaseModel):
    question: str
    answer: str
    data: Optional[Any] = None
