"""Shared test fixtures — mock adapters for DB-free unit testing."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoforge.engine.context import ContextEngine


class MockPgVectorDB:
    """In-memory mock for PgVectorDB — no real PostgreSQL needed."""

    def __init__(self):
        self.docs: dict[str, dict[str, Any]] = {}
        self.proposals: dict[str, dict[str, Any]] = {}
        self.pool = AsyncMock()

    async def connect(self) -> None:
        """Mimic opening a DB connection."""
        pass

    async def close(self) -> None:
        """Mimic closing a DB connection."""
        pass

    async def upsert(
        self, doc_id: str, content: str, vector: list[float], metadata: dict[str, Any]
    ) -> None:
        """Store a document record in memory."""
        self.docs[doc_id] = {
            "id": doc_id,
            "content": content,
            "vector": vector,
            "metadata": metadata,
        }

    async def search(
        self,
        vector: list[float],
        top_k: int = 5,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Return deterministic top-k in-memory documents."""
        results = list(self.docs.values())[:top_k]
        return [
            {"id": d["id"], "content": d["content"], "metadata": d["metadata"], "similarity": 0.95}
            for d in results
        ]

    async def delete(self, doc_id: str) -> None:
        """Delete a document from in-memory storage."""
        self.docs.pop(doc_id, None)

    async def increment_counter(self, doc_ids: list[str]) -> None:
        """No-op for access counter updates in tests."""
        pass

    async def store_proposal(
        self,
        proposal_id: str,
        tenant_id: str,
        domain: str,
        user_data: dict[str, Any],
        proposal: dict[str, Any],
        audit_result: dict[str, Any],
    ) -> None:
        """Store proposal payload for feedback/history tests."""
        self.proposals[proposal_id] = {
            "id": proposal_id,
            "tenant_id": tenant_id,
            "domain": domain,
            "user_data": user_data,
            "proposal": proposal,
            "audit_result": audit_result,
            "accepted": None,
        }

    async def update_feedback(
        self,
        proposal_id: str,
        accepted: bool,
        performance_after: dict[str, Any] | None = None,
    ) -> bool:
        """Update proposal acceptance flag if proposal exists."""
        if proposal_id in self.proposals:
            self.proposals[proposal_id]["accepted"] = accepted
            return True
        return False

    async def cleanup_old_facts(self, days: int, min_importance: float) -> int:
        """Return zero to indicate no cleanup in mock."""
        return 0

    async def get_stats(self, tenant_id: str) -> dict[str, Any]:
        """Compute tenant-level counts from in-memory docs and proposals."""
        tenant_docs = [d for d in self.docs.values() if d["metadata"].get("tenant_id") == tenant_id]
        tenant_proposals = [p for p in self.proposals.values() if p["tenant_id"] == tenant_id]
        accepted = [p for p in tenant_proposals if p["accepted"] is True]
        return {
            "tenant_id": tenant_id,
            "total_facts": len(tenant_docs),
            "total_proposals": len(tenant_proposals),
            "accepted_proposals": len(accepted),
            "acceptance_rate": len(accepted) / max(len(tenant_proposals), 1),
        }

    async def get_proposals_history(
        self, tenant_id: str, limit: int = 20, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Return paginated proposal history for a tenant."""
        tenant_proposals = [p for p in self.proposals.values() if p["tenant_id"] == tenant_id]
        return tenant_proposals[offset : offset + limit]


class MockEmbedder:
    """Returns deterministic fake embeddings."""

    async def embed(self, text: str) -> list[float]:
        """Generate deterministic 1536-dim vector based on text hash."""
        # 1536-dim fake vector seeded from text hash
        seed = hash(text) % 1000
        return [float(seed + i) / 10000.0 for i in range(1536)]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts using the same deterministic strategy."""
        return [await self.embed(t) for t in texts]


class MockLLMClient:
    """Returns canned LLM responses for testing."""

    async def chat(self, system: str, user: str) -> str:
        """Return a canned text response for HyDE generation tests."""
        return "これはテスト用の仮想的な回答です。"

    async def chat_json(self, system: str, user: str) -> dict[str, Any]:
        """Return a canned JSON proposal payload for proposal path tests."""
        return {
            "recommendations": [
                {
                    "type": "bid_adjustment",
                    "action": "入札を15%引き上げ",
                    "reason": "CTRが高いため",
                    "expected_impact": "CPA 10%改善",
                    "priority": "high",
                    "specific_values": {"bid_change_percent": 15},
                }
            ],
            "summary": "テスト提案",
            "risk_assessment": "低リスク",
        }


@pytest.fixture
def mock_db() -> MockPgVectorDB:
    return MockPgVectorDB()


@pytest.fixture
def mock_embedder() -> MockEmbedder:
    return MockEmbedder()


@pytest.fixture
def mock_llm() -> MockLLMClient:
    return MockLLMClient()


@pytest.fixture
def engine(mock_db, mock_embedder, mock_llm) -> ContextEngine:
    return ContextEngine(db=mock_db, graph_db=None, embedder=mock_embedder, llm=mock_llm)
