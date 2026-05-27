"""
OmniForge Ultra RAG Engine — Production API
============================================
Routes:
  POST /api/v1/auth/token          — Get JWT access token
  POST /api/v1/ingest              — Upload and ingest a document (protected)
  POST /api/v1/query               — Standard RAG query (protected)
  POST /api/v1/query/stream        — Streaming RAG query via SSE (protected)
  DELETE /api/v1/session/{id}      — Clear a session's conversation history

  ContractIQ — Phase 1
  POST /api/v1/contracts/analyze      — Risk analysis: score + flagged clauses

  ContractIQ — Phase 2
  POST /api/v1/contracts/compare      — Contract diff: added / removed / modified clauses

  ContractIQ — Phase 3
  POST /api/v1/contracts/obligations  — Obligation registry: deadlines, duties, penalties
"""
import time
import json
from loguru import logger
from fastapi import (
    FastAPI, Depends, HTTPException, BackgroundTasks,
    UploadFile, File, Form, Request
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.schemas import (
    QueryRequest, QueryResponse,
    TokenRequest, TokenResponse,
    IngestResponse, SessionCreateResponse,
    AnalyzeRequest, ContractAnalysis,
    CompareRequest, ComparisonResult,
    ObligationsRequest, ObligationRegistry,
)
from app.services.retriever import AdvancedRetriever
from app.services.generator import GenerationService
from app.services.auth import (
    authenticate_user,
    create_access_token,
    get_current_user,
)
from app.services import session_manager
from app.services.ingestion import ingest_file
from app.services.risk_analysis import RiskAnalysisService
from app.services.comparison import ComparisonService
from app.services.obligation_extractor import ObligationExtractor
from app.config import get_settings

settings = get_settings()

# ---------------------------------------------------------------------------
# Rate Limiter Setup
# ---------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address)

# ---------------------------------------------------------------------------
# FastAPI App Initialization
# ---------------------------------------------------------------------------
app = FastAPI(
    title="OmniForge Ultra RAG Engine",
    description=(
        "Production-grade Retrieval-Augmented Generation API.\n\n"
        "**Authentication**: Use `/api/v1/auth/token` to get a Bearer token, "
        "then click 'Authorize' in Swagger UI.\n\n"
        "**Demo credentials**: `admin` / `admin123`"
    ),
    version="3.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Attach rate limiter state and error handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS Middleware — lock down origins in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Replace with specific domains in production
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

# Mount static files folder
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=FileResponse, tags=["Frontend"], summary="Serve Web Frontend Dashboard")
async def serve_frontend():
    """Serves the interactive, premium OmniForge RAG Engine web portal."""
    return "static/index.html"

# ---------------------------------------------------------------------------
# Dependency Injection
# ---------------------------------------------------------------------------
def get_retriever() -> AdvancedRetriever:
    return AdvancedRetriever()

def get_generator() -> GenerationService:
    return GenerationService()

def get_risk_analysis_service() -> RiskAnalysisService:
    return RiskAnalysisService()

def get_comparison_service() -> ComparisonService:
    return ComparisonService()

def get_obligation_extractor() -> ObligationExtractor:
    return ObligationExtractor()

# ---------------------------------------------------------------------------
# Auth Routes
# ---------------------------------------------------------------------------
@app.post(
    "/api/v1/auth/token",
    response_model=TokenResponse,
    tags=["Authentication"],
    summary="Get a JWT access token",
)
@limiter.limit("10/minute")
async def login(request: Request, credentials: TokenRequest):
    """
    Exchange username + password for a signed JWT Bearer token.
    Demo users: **admin / adminpassword** or **user / userpassword**
    """
    username = authenticate_user(credentials.username, credentials.password)
    if not username:
        raise HTTPException(status_code=401, detail="Incorrect username or password.")
    token = create_access_token(subject=username)
    logger.info(f"User '{username}' authenticated successfully.")
    return TokenResponse(access_token=token)

# ---------------------------------------------------------------------------
# Ingestion Route
# ---------------------------------------------------------------------------
@app.post(
    "/api/v1/ingest",
    response_model=IngestResponse,
    tags=["Ingestion"],
    summary="Upload and ingest a document into the knowledge base",
)
@limiter.limit("5/minute")
async def ingest_document(
    request: Request,
    file: UploadFile = File(..., description="PDF, DOCX, TXT, or MD file"),
    department: str = Form(default="general", description="Metadata tag for filtering"),
    current_user: str = Depends(get_current_user),
):
    """
    Full ETL pipeline:
    1. Parse the uploaded file (PDF / DOCX / TXT / MD)
    2. Semantically chunk the content
    3. Embed with local FastEmbed
    4. Upsert into the Qdrant knowledge base
    """
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    logger.info(f"User '{current_user}' uploading '{file.filename}' ({len(file_bytes)} bytes).")

    try:
        count = await ingest_file(
            file_bytes=file_bytes,
            filename=file.filename,
            extra_metadata={"department": department, "uploaded_by": current_user},
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"Ingestion failed for {file.filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")

    return IngestResponse(
        status="success",
        chunks_ingested=count,
        filename=file.filename,
        message=f"Successfully ingested {count} chunks from '{file.filename}'.",
    )

# ---------------------------------------------------------------------------
# Query Route (Standard)
# ---------------------------------------------------------------------------
@app.post(
    "/api/v1/query",
    response_model=QueryResponse,
    tags=["Query"],
    summary="Ask the RAG engine a question",
)
@limiter.limit(f"{settings.RATE_LIMIT_PER_MINUTE}/minute")
async def process_query(
    request: Request,
    body: QueryRequest,
    retriever: AdvancedRetriever = Depends(get_retriever),
    generator: GenerationService = Depends(get_generator),
    current_user: str = Depends(get_current_user),
):
    """
    Full RAG pipeline:
    1. Query rewrite → Dense embedding → Qdrant search → Cohere rerank
    2. Session-aware context injection (if session_id provided)
    3. Grounded generation via Cohere command-a-03-2025
    """
    start_time = time.time()

    # Auto-create session if not provided
    session_id = body.session_id or session_manager.create_session()

    # Build conversation-aware query string
    enriched_query = session_manager.build_context_with_history(session_id, body.query)

    try:
        documents = await retriever.retrieve(enriched_query, body.filters)
        answer = await generator.generate_answer(
            query=body.query,
            chunks=documents,
            conversation_context=session_manager.build_context_with_history(
                session_id, body.query
            ) if body.session_id else None,
        )
    except Exception as e:
        logger.error(f"Query pipeline failed for user '{current_user}': {e}")
        raise HTTPException(status_code=500, detail=str(e))

    # Persist this exchange in session memory
    session_manager.add_turn(session_id, body.query, answer)

    latency = (time.time() - start_time) * 1000
    logger.info(f"Query by '{current_user}' completed in {latency:.1f}ms.")

    return QueryResponse(
        answer=answer,
        source_documents=documents,
        latency_ms=round(latency, 2),
        session_id=session_id,
        usage={"session_turns": len(session_manager.get_history(session_id)) // 2},
    )

# ---------------------------------------------------------------------------
# Streaming Query Route (SSE)
# ---------------------------------------------------------------------------
@app.post(
    "/api/v1/query/stream",
    tags=["Query"],
    summary="Streaming RAG response via Server-Sent Events",
)
@limiter.limit(f"{settings.RATE_LIMIT_PER_MINUTE}/minute")
async def process_query_stream(
    request: Request,
    body: QueryRequest,
    retriever: AdvancedRetriever = Depends(get_retriever),
    generator: GenerationService = Depends(get_generator),
    current_user: str = Depends(get_current_user),
):
    """
    Server-Sent Events stream:
    - First event: `event: metadata` with source documents as JSON
    - Subsequent events: `data: <text_chunk>` streamed as generated
    - Final event: `data: [DONE]`
    """
    session_id = body.session_id or session_manager.create_session()

    async def event_generator():
        full_response = []
        try:
            documents = await retriever.retrieve(body.query, body.filters)
            sources_meta = [doc.model_dump() for doc in documents]
            yield f"event: metadata\ndata: {json.dumps(sources_meta)}\n\n"

            async for text_chunk in generator.generate_stream(
                query=body.query,
                chunks=documents,
                conversation_context=session_manager.build_context_with_history(
                    session_id, body.query
                ) if body.session_id else None,
            ):
                full_response.append(text_chunk)
                yield f"data: {text_chunk}\n\n"

            # Persist to session after stream completes
            session_manager.add_turn(session_id, body.query, "".join(full_response))
            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"Stream error for user '{current_user}': {e}")
            yield f"event: error\ndata: {str(e)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# ---------------------------------------------------------------------------
# Session Management
# ---------------------------------------------------------------------------
@app.post(
    "/api/v1/session",
    response_model=SessionCreateResponse,
    tags=["Session"],
    summary="Create a new conversation session",
)
async def create_session(
    current_user: str = Depends(get_current_user),
):
    """
    Explicitly create a new session and receive a **session_id**.

    Pass this `session_id` in future `/query` requests to enable
    multi-turn conversation memory — the RAG engine will include
    prior exchanges as context for follow-up questions.
    """
    session_id = session_manager.create_session()
    logger.info(f"User '{current_user}' created session: {session_id}")
    return SessionCreateResponse(session_id=session_id)

@app.delete(
    "/api/v1/session/{session_id}",
    tags=["Session"],
    summary="Clear conversation history for a session",
)
async def clear_session(
    session_id: str,
    current_user: str = Depends(get_current_user),
):
    """Delete the stored conversation history for a given session ID."""
    session_manager.delete_session(session_id)
    logger.info(f"Session {session_id} cleared by user '{current_user}'.")
    return {"status": "cleared", "session_id": session_id}

# ---------------------------------------------------------------------------
# ContractIQ — Phase 1: Contract Analysis Routes
# ---------------------------------------------------------------------------
@app.post(
    "/api/v1/contracts/analyze",
    response_model=ContractAnalysis,
    tags=["ContractIQ"],
    summary="Analyse contract risk — score + flagged clauses",
)
@limiter.limit("5/minute")
async def analyze_contract(
    request: Request,
    body: AnalyzeRequest,
    service: RiskAnalysisService = Depends(get_risk_analysis_service),
    current_user: str = Depends(get_current_user),
):
    """
    ContractIQ Risk Analysis Pipeline (Phase 1):
    1. Retrieve all chunks for the specified document from Qdrant
    2. Build structured contract context
    3. Run Cohere command-a with JSON-schema enforcement
    4. Parse + validate each flagged clause into a `RiskClause`
    5. Compute aggregate risk score and return `ContractAnalysis`

    **document_id** must match a filename previously ingested via `POST /api/v1/ingest`.
    """
    logger.info(
        f"ContractIQ: user='{current_user}' requesting analysis of '{body.document_id}' "
        f"(focus='{body.focus_area or 'general'}')"
    )
    try:
        result = await service.analyze(
            document_id=body.document_id,
            focus_area=body.focus_area,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error(f"ContractIQ analysis failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(exc)}")

    return result

# ---------------------------------------------------------------------------
# ContractIQ — Phase 2: Contract Comparison Routes
# ---------------------------------------------------------------------------
@app.post(
    "/api/v1/contracts/compare",
    response_model=ComparisonResult,
    tags=["ContractIQ"],
    summary="Compare two contracts — side-by-side diff with delta scoring",
)
@limiter.limit("3/minute")
async def compare_contracts(
    request: Request,
    body: CompareRequest,
    service: ComparisonService = Depends(get_comparison_service),
    current_user: str = Depends(get_current_user),
):
    """
    ContractIQ Contract Comparison Pipeline (Phase 2):
    1. Dual-parallel retrieval: fetch all chunks from document A and B simultaneously
    2. Build a side-by-side context block for the LLM
    3. Run Cohere command-a with strict JSON delta-detection schema
    4. Parse each difference into a typed `ClauseDelta` (added / removed / modified)
    5. Compute overall risk-shift score and direction
    6. Return a `ComparisonResult`

    Both **document_a** and **document_b** must have been previously ingested
    via `POST /api/v1/ingest`.
    """
    if body.document_a == body.document_b:
        raise HTTPException(
            status_code=400,
            detail="document_a and document_b must be different filenames."
        )

    logger.info(
        f"ContractIQ compare: user='{current_user}' | "
        f"'{body.document_a}' ↔ '{body.document_b}' "
        f"(focus='{body.focus_area or 'general'}')"
    )
    try:
        result = await service.compare(
            document_a=body.document_a,
            document_b=body.document_b,
            focus_area=body.focus_area,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error(f"ContractIQ comparison failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Comparison failed: {str(exc)}")

    return result

# ---------------------------------------------------------------------------
# ContractIQ — Phase 3: Obligation Extractor Routes
# ---------------------------------------------------------------------------
@app.post(
    "/api/v1/contracts/obligations",
    response_model=ObligationRegistry,
    tags=["ContractIQ"],
    summary="Extract obligation registry — deadlines, duties, and penalties",
)
@limiter.limit("4/minute")
async def extract_obligations(
    request: Request,
    body: ObligationsRequest,
    service: ObligationExtractor = Depends(get_obligation_extractor),
    current_user: str = Depends(get_current_user),
):
    """
    ContractIQ Obligation Extraction Pipeline (Phase 3):
    1. Retrieve all chunks for the specified document from Qdrant
    2. Build deduplicated, ordered contract context
    3. Run Cohere command-a with strict JSON obligation-extraction schema
    4. Parse each obligation into a typed `Obligation` with party attribution,
       due dates, priority, recurrence, and penalty clauses
    5. Group by responsible party (party_a / party_b / shared)
    6. Compute priority counts and identify the earliest deadline
    7. Return a fully-typed `ObligationRegistry`

    **document_id** must match a filename previously ingested via `POST /api/v1/ingest`.
    """
    logger.info(
        f"ContractIQ obligations: user='{current_user}' | doc='{body.document_id}' | "
        f"parties: '{body.party_a_name}' vs '{body.party_b_name}'"
    )
    try:
        result = await service.extract(
            document_id=body.document_id,
            party_a_name=body.party_a_name or "Party A",
            party_b_name=body.party_b_name or "Party B",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error(f"ContractIQ obligation extraction failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(exc)}")

    return result

# ---------------------------------------------------------------------------
# Application Runner
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        workers=4,
        limit_concurrency=200,
        access_log=True,
    )
