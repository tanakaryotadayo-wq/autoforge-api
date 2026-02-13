"""
AutoForge API v7.0 — FastAPI application.
Granian-powered, multi-tenant, DeepSeek-ready.
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from .adapters.embedder import OpenAIEmbedder
from .adapters.llm_client import TokenAwareLLMClient
from .adapters.neo4j_graph import Neo4jGraphDB
from .adapters.pgvector import PgVectorDB
from .auth.jwt import (
    create_access_token,
    get_current_user,
    get_tenant_id,
    verify_password,
)
from .config import settings
from .engine.context import ContextEngine
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
    logger.info("autoforge_starting", version="7.0.0", backend=settings.llm_backend)

    # ── Initialize adapters ──
    db = PgVectorDB(settings.database_url)
    await db.connect()

    graph_db: Neo4jGraphDB | None = None
    try:
        graph_db = Neo4jGraphDB(
            settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password
        )
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
    start = time.time()

    try:
        result = await engine.propose(
            user_data=req.user_data,
            tenant_id=tenant_id,
            domain=req.domain,
            account_history=req.account_history,
        )
        duration = time.time() - start
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


@app.post("/v1/feedback")
async def record_feedback(req: FeedbackRequest):
    """Record user feedback on a proposal for learning."""
    # TODO: Phase 3 — store feedback and run learning cycle
    logger.info(
        "feedback_recorded",
        proposal_id=req.proposal_id,
        accepted=req.accepted,
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
