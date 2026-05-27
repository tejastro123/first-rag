from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal

# --- Auth Schemas ---
class TokenRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

# --- Query Schemas ---
class QueryRequest(BaseModel):
    query: str = Field(..., description="The user's input query", min_length=2, max_length=1000)
    session_id: Optional[str] = Field(default=None, description="For multi-turn conversation memory tracking")
    filters: Optional[Dict[str, Any]] = Field(default=None, description="Metadata filters (e.g., {'department': 'engineering'})")

class DocumentChunk(BaseModel):
    chunk_id: str
    text: str
    metadata: Dict[str, Any]
    relevance_score: float

class QueryResponse(BaseModel):
    answer: str
    source_documents: List[DocumentChunk]
    latency_ms: float
    usage: Dict[str, int]
    session_id: str  # Return to client so they can use it for follow-up queries

class SessionCreateResponse(BaseModel):
    session_id: str
    message: str = "Session created. Pass this session_id in future queries for multi-turn conversation."

# --- Ingestion Schemas ---
class IngestResponse(BaseModel):
    status: str
    chunks_ingested: int
    filename: str
    message: str

# ---------------------------------------------------------------------------
# ContractIQ — Phase 1: Risk Analysis Schemas
# ---------------------------------------------------------------------------

RISK_CATEGORIES = Literal[
    "indemnification",
    "liability_cap",
    "termination",
    "ip_ownership",
    "governing_law",
    "payment_terms",
    "confidentiality",
    "force_majeure",
    "warranty",
    "dispute_resolution",
    "other",
]

class RiskClause(BaseModel):
    """A single flagged contract clause with risk metadata."""
    clause_text: str = Field(..., description="The verbatim or paraphrased clause text")
    category: RISK_CATEGORIES = Field(..., description="Legal category of the clause")
    risk_score: float = Field(..., ge=0.0, le=1.0, description="Risk score from 0.0 (low) to 1.0 (critical)")
    risk_level: Literal["low", "medium", "high", "critical"] = Field(..., description="Human-readable risk tier")
    explanation: str = Field(..., description="Why this clause is flagged and what the risk is")
    recommendation: str = Field(..., description="Suggested negotiation position or mitigation")

class ContractAnalysis(BaseModel):
    """Top-level result of a contract risk analysis."""
    document_id: str = Field(..., description="The source document filename/identifier")
    overall_risk_score: float = Field(..., ge=0.0, le=1.0, description="Aggregate risk score for the whole contract")
    overall_risk_level: Literal["low", "medium", "high", "critical"]
    executive_summary: str = Field(..., description="Plain-English executive summary of the contract risk profile")
    flagged_clauses: List[RiskClause] = Field(default_factory=list, description="All identified risk clauses, sorted by severity")
    clause_count: int = Field(..., description="Total number of clauses analysed")
    latency_ms: float

class AnalyzeRequest(BaseModel):
    """Inbound request to trigger contract risk analysis."""
    document_id: str = Field(..., description="Filename of an already-ingested document (e.g. 'contract.pdf')")
    focus_area: Optional[str] = Field(
        default=None,
        description="Optional plain-English focus, e.g. 'indemnification and liability caps'",
        max_length=300,
    )

# ---------------------------------------------------------------------------
# ContractIQ — Phase 2: Contract Comparison Schemas
# ---------------------------------------------------------------------------

DELTA_TYPES = Literal["added", "removed", "modified", "unchanged"]

class ClauseDelta(BaseModel):
    """A single clause-level difference between two contracts."""
    delta_type: DELTA_TYPES = Field(..., description="Nature of the change")
    category: RISK_CATEGORIES = Field(..., description="Legal category of this clause")
    # For 'added' → only text_b is populated; 'removed' → only text_a; 'modified' → both
    text_a: Optional[str] = Field(default=None, description="Clause text from document A (baseline)")
    text_b: Optional[str] = Field(default=None, description="Clause text from document B (revised)")
    significance: Literal["low", "medium", "high", "critical"] = Field(
        ..., description="Business/legal significance of this delta"
    )
    explanation: str = Field(..., description="Plain-English explanation of what changed and why it matters")
    favours: Literal["party_a", "party_b", "neutral", "unknown"] = Field(
        ..., description="Which party benefits from this change"
    )

class ComparisonResult(BaseModel):
    """Full structured comparison between two ingested contracts."""
    document_a: str = Field(..., description="Baseline contract filename")
    document_b: str = Field(..., description="Revised contract filename")
    executive_delta: str = Field(..., description="2-4 sentence plain-English summary of key differences")
    overall_risk_shift: float = Field(
        ..., ge=-1.0, le=1.0,
        description="Risk delta: positive = B is riskier than A, negative = B improved over A"
    )
    risk_shift_direction: Literal["improved", "worsened", "neutral"]
    added_clauses: List[ClauseDelta] = Field(default_factory=list)
    removed_clauses: List[ClauseDelta] = Field(default_factory=list)
    modified_clauses: List[ClauseDelta] = Field(default_factory=list)
    total_deltas: int = Field(..., description="Total number of meaningful differences detected")
    latency_ms: float

class CompareRequest(BaseModel):
    """Inbound request to compare two already-ingested contracts."""
    document_a: str = Field(..., description="Baseline contract filename (the 'old' version)")
    document_b: str = Field(..., description="Revised contract filename (the 'new' version)")
    focus_area: Optional[str] = Field(
        default=None,
        description="Optional clause types to focus on, e.g. 'termination and IP ownership'",
        max_length=300,
    )

# ---------------------------------------------------------------------------
# ContractIQ — Phase 3: Obligation Extractor Schemas
# ---------------------------------------------------------------------------

OBLIGATION_TYPES = Literal[
    "payment",
    "delivery",
    "reporting",
    "approval",
    "notice",
    "non_compete",
    "confidentiality",
    "insurance",
    "indemnification",
    "termination_right",
    "renewal",
    "other",
]

OBLIGATION_PRIORITY = Literal["critical", "high", "medium", "low"]
OBLIGATION_STATUS   = Literal["pending", "recurring", "conditional", "expired"]
OBLIGATION_PARTY    = Literal["party_a", "party_b", "both", "unknown"]

class Obligation(BaseModel):
    """A single actionable obligation extracted from a contract."""
    obligation_id: str = Field(..., description="Stable unique identifier (e.g. 'OBL-001')")
    obligation_type: OBLIGATION_TYPES = Field(..., description="Functional category of the obligation")
    description: str = Field(..., description="Plain-English description of what must be done")
    verbatim_text: str = Field(..., description="Verbatim or near-verbatim clause text, max 400 chars")
    responsible_party: OBLIGATION_PARTY = Field(..., description="Who must perform this obligation")
    counterparty: OBLIGATION_PARTY = Field(..., description="Who benefits from / receives performance")
    due_date: Optional[str] = Field(
        default=None,
        description="Exact date (ISO 8601) or relative expression (e.g. '30 days after signing', 'monthly')"
    )
    is_recurring: bool = Field(default=False, description="True if this obligation repeats on a schedule")
    recurrence_schedule: Optional[str] = Field(
        default=None, description="Human-readable recurrence pattern, e.g. 'quarterly', 'on each invoice'"
    )
    priority: OBLIGATION_PRIORITY = Field(..., description="Business/legal priority of this obligation")
    status: OBLIGATION_STATUS = Field(default="pending", description="Current lifecycle status")
    penalty_clause: Optional[str] = Field(
        default=None,
        description="Penalty or consequence for non-performance, if stated in the contract"
    )
    conditions: Optional[str] = Field(
        default=None,
        description="Any conditions that must be met before this obligation is triggered"
    )

class ObligationRegistry(BaseModel):
    """Full structured obligation registry extracted from a contract."""
    document_id: str
    total_obligations: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    party_a_obligations: List[Obligation] = Field(default_factory=list)
    party_b_obligations: List[Obligation] = Field(default_factory=list)
    shared_obligations:  List[Obligation] = Field(default_factory=list)
    executive_summary: str = Field(..., description="2-4 sentence plain-English overview of key obligations")
    earliest_deadline: Optional[str] = Field(default=None, description="The soonest deadline found in the contract")
    latency_ms: float

class ObligationsRequest(BaseModel):
    """Inbound request to extract obligations from an ingested contract."""
    document_id: str = Field(..., description="Filename of an already-ingested document")
    party_a_name: Optional[str] = Field(
        default="Party A",
        description="Name or role of the first party (e.g. 'Vendor', 'Licensor')",
        max_length=100,
    )
    party_b_name: Optional[str] = Field(
        default="Party B",
        description="Name or role of the second party (e.g. 'Client', 'Licensee')",
        max_length=100,
    )
