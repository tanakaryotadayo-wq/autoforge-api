"""Pydantic models for AutoForge facts, proposals, and API schemas."""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field

# ── Domain Models ──


class Fact(BaseModel):
    content: str
    vector: list[float] | None = None
    tenant_id: str = "default"
    user_id: str | None = None
    category: str = "general"
    timestamp: float = Field(default_factory=time.time)
    access_count: int = 0
    last_accessed: float | None = None
    importance_score: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuditResult(BaseModel):
    is_valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ── API Request/Response Schemas ──


class LearnRequest(BaseModel):
    content: str
    category: str = "general"
    metadata: dict[str, Any] = Field(default_factory=dict)


class QueryRequest(BaseModel):
    query: str
    top_k: int = 5
    min_score: float = 0.7


class ProposeRequest(BaseModel):
    """広告ツール等から送られる提案リクエスト"""

    user_data: dict[str, Any]
    account_history: dict[str, Any] = Field(default_factory=dict)
    domain: str = "ad_optimization"  # ドメイン（将来の汎用化用）


class ProposeResponse(BaseModel):
    success: bool
    proposal: dict[str, Any] | None = None
    proposal_id: str | None = None
    audit: AuditResult | None = None
    error: str | None = None


class FeedbackRequest(BaseModel):
    proposal_id: str
    accepted: bool
    performance_after: dict[str, Any] | None = None


class HealthResponse(BaseModel):
    status: str
    components: dict[str, str] = Field(default_factory=dict)
    version: str = "7.0.0"


class DomainInfo(BaseModel):
    id: str
    description: str


class DomainsResponse(BaseModel):
    domains: list[DomainInfo]


class StatsResponse(BaseModel):
    tenant_id: str
    total_facts: int
    total_proposals: int
    accepted_proposals: int
    acceptance_rate: float


class ProposalHistoryItem(BaseModel):
    id: str
    domain: str
    user_data: dict[str, Any]
    proposal: dict[str, Any]
    audit_result: dict[str, Any]
    accepted: bool | None = None
    created_at: str | None = None
    feedback_at: str | None = None


class ProposalsHistoryResponse(BaseModel):
    proposals: list[ProposalHistoryItem]
    limit: int
    offset: int
