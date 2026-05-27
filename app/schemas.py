from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

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
