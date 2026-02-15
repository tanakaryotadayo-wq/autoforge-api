"""
AutoForge API v7.0 — FastAPI application.
Granian-powered, multi-tenant, DeepSeek-ready.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .adapters.embedder import OpenAIEmbedder
from .adapters.llm_client import TokenAwareLLMClient
from .adapters.metrics import (
    active_proposals,
    audit_results_total,
    facts_learned_total,
    http_request_duration,
    http_requests_total,
)
from .adapters.neo4j_graph import Neo4jGraphDB
from .adapters.pgvector import PgVectorDB
from .auth.jwt import (
    create_access_token,
    get_current_user,
    get_tenant_id,
)
from .config import settings
from .engine.context import ContextEngine
from .logging import setup_logging
from .models import (
    FeedbackRequest,
    HealthResponse,
    LearnRequest,
    ProposeRequest,
    ProposeResponse,
    QueryRequest,
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup all components."""
    setup_logging()
    logger.info("autoforge_starting", version="7.0.0", backend=settings.llm_backend)

    # ── Initialize adapters ──
    db = PgVectorDB(settings.database_url)
    await db.connect()

    graph_db: Neo4jGraphDB | None = None
    try:
        graph_db = Neo4jGraphDB(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
        await graph_db.connect()
    except Exception as e:
        logger.warning("neo4j_unavailable", error=str(e))
        graph_db = None

    embedder = OpenAIEmbedder()
    llm = TokenAwareLLMClient()

    # ── Initialize engine ──
    engine = ContextEngine(db=db, graph_db=graph_db, embedder=embedder, llm=llm)

    app.state.db = db
    app.state.graph_db = graph_db
    app.state.engine = engine

    logger.info("autoforge_ready")
    yield

    # ── Cleanup ──
    if graph_db:
        await graph_db.close()
    await db.close()
    logger.info("autoforge_shutdown")


app = FastAPI(
    title="AutoForge API",
    version="7.0.0",
    description="AI Memory & Audit Engine — HyDE + Multi-hop RAG + GraphRAG",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Middleware ──


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """Track HTTP request metrics."""
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start

    path = request.url.path
    # Normalize paths to avoid cardinality explosion
    if path.startswith("/v1/"):
        path = "/v1/" + path.split("/")[2] if len(path.split("/")) > 2 else path

    http_requests_total.labels(method=request.method, path=path, status=response.status_code).inc()
    http_request_duration.labels(method=request.method, path=path).observe(duration)

    return response


# ── Health ──


@app.get("/health", response_model=HealthResponse)
async def health():
    components: dict[str, str] = {"api": "ok"}
    try:
        async with app.state.db.pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        components["postgres"] = "ok"
    except Exception:
        components["postgres"] = "error"

    if app.state.graph_db:
        try:
            async with app.state.graph_db.driver.session() as s:
                await s.run("RETURN 1")
            components["neo4j"] = "ok"
        except Exception:
            components["neo4j"] = "error"
    else:
        components["neo4j"] = "disabled"

    overall = "ok" if components.get("postgres") == "ok" else "degraded"
    return HealthResponse(status=overall, components=components)


# ── Metrics (Prometheus scrape) ──


@app.get("/metrics")
async def metrics():
    """Prometheus scrape endpoint."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ── Auth ──


@app.post("/token")
async def login(username: str, password: str):
    """Simple admin login. Returns JWT."""
    if username == "admin" and password == settings.admin_password:
        token = create_access_token({"sub": "admin"})
        return {"access_token": token, "token_type": "bearer"}
    raise HTTPException(401, "Invalid credentials")


# ── Core API ──


@app.post("/v1/learn")
async def learn_fact(
    req: LearnRequest,
    tenant_id: str = Depends(get_tenant_id),
    user_id: str = Depends(get_current_user),
):
    """Store new knowledge in the RAG knowledge base."""
    engine: ContextEngine = app.state.engine
    doc_id = await engine.learn(
        content=req.content,
        tenant_id=tenant_id,
        user_id=user_id if user_id != "anonymous" else None,
        category=req.category,
        metadata=req.metadata,
    )
    facts_learned_total.labels(tenant=tenant_id).inc()
    return {"doc_id": doc_id, "status": "learned"}


@app.post("/v1/query")
async def query_knowledge(
    req: QueryRequest,
    tenant_id: str = Depends(get_tenant_id),
    user_id: str = Depends(get_current_user),
):
    """Search the knowledge base using HyDE + multi-hop RAG."""
    engine: ContextEngine = app.state.engine
    results = await engine.search(
        query=req.query,
        tenant_id=tenant_id,
        user_id=user_id if user_id != "anonymous" else None,
    )
    return {"results": results, "count": len(results)}


@app.post("/v1/propose", response_model=ProposeResponse)
async def generate_proposal(
    req: ProposeRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate AI proposal with RAG context + ECK audit."""
    engine: ContextEngine = app.state.engine
    db: PgVectorDB = app.state.db
    active_proposals.inc()
    start = time.time()

    try:
        result = await engine.propose(
            user_data=req.user_data,
            tenant_id=tenant_id,
            domain=req.domain,
            account_history=req.account_history,
        )
        duration = time.time() - start

        # Store proposal for feedback tracking
        await db.store_proposal(
            proposal_id=result["proposal_id"],
            tenant_id=tenant_id,
            domain=req.domain,
            user_data=req.user_data,
            proposal=result["proposal"],
            audit_result=result["audit"].model_dump(),
        )

        # Track audit metrics
        audit_status = "valid" if result["audit"].is_valid else "invalid"
        audit_results_total.labels(status=audit_status).inc()

        logger.info("proposal_served", duration=round(duration, 2))

        return ProposeResponse(
            success=True,
            proposal=result["proposal"],
            proposal_id=result["proposal_id"],
            audit=result["audit"],
        )
    except Exception as e:
        logger.error("proposal_failed", error=str(e))
        return ProposeResponse(success=False, error=str(e))
    finally:
        active_proposals.dec()


@app.post("/v1/feedback")
async def record_feedback(
    req: FeedbackRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    """Record user feedback on a proposal and update for learning."""
    db: PgVectorDB = app.state.db

    found = await db.update_feedback(
        proposal_id=req.proposal_id,
        accepted=req.accepted,
        performance_after=req.performance_after,
    )

    if not found:
        raise HTTPException(404, f"Proposal {req.proposal_id} not found")

    logger.info(
        "feedback_recorded",
        proposal_id=req.proposal_id,
        accepted=req.accepted,
        tenant=tenant_id,
    )
    return {"status": "recorded", "proposal_id": req.proposal_id}


# ── Admin ──


@app.post("/admin/cleanup")
async def trigger_cleanup(user_id: str = Depends(get_current_user)):
    """Manually trigger old facts cleanup."""
    if user_id != "admin":
        raise HTTPException(403, "Admin only")
    db: PgVectorDB = app.state.db
    deleted = await db.cleanup_old_facts(
        days=settings.cleanup_days_unused,
        min_importance=settings.cleanup_min_importance,
    )
    return {"deleted": deleted}


# ── Business Layer ──


@app.get("/v1/domains")
async def list_domains():
    """List all available domains with descriptions."""
    from .domains import list_domains as get_domains

    # Proposal (not applied to preserve behavior):
    # add response_model=DomainsResponse for stricter response validation.
    return {"domains": get_domains()}


@app.get("/v1/stats")
async def tenant_stats(tenant_id: str = Depends(get_tenant_id)):
    """Get tenant-level statistics."""
    db: PgVectorDB = app.state.db
    # Proposal (not applied to preserve behavior):
    # catch DB connectivity errors and convert them to HTTP 503.
    # Proposal (not applied to preserve behavior):
    # add response_model=StatsResponse for stricter response validation.
    stats = await db.get_stats(tenant_id)
    return stats


@app.get("/v1/proposals/history")
async def proposals_history(
    limit: int = 20,
    offset: int = 0,
    tenant_id: str = Depends(get_tenant_id),
):
    """Get paginated proposal history for the tenant."""
    db: PgVectorDB = app.state.db
    # Proposal (not applied to preserve behavior):
    # catch DB connectivity errors and convert them to HTTP 503.
    # Proposal (not applied to preserve behavior):
    # add response_model=ProposalsHistoryResponse for stricter response validation.
    proposals = await db.get_proposals_history(tenant_id, limit=limit, offset=offset)
    return {"proposals": proposals, "limit": limit, "offset": offset}
