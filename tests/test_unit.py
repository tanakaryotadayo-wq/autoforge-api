"""Unit tests — no database, no API keys needed."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoforge.engine.context import ContextEngine
from autoforge.models import (
    AuditResult,
    Fact,
    FeedbackRequest,
    HealthResponse,
    LearnRequest,
    ProposeRequest,
    ProposeResponse,
    QueryRequest,
)

# ── Audit Tests ──


class TestAudit:
    """Test the ECK-lite audit logic without any external calls."""

    def _make_engine(self, mock_db, mock_embedder, mock_llm):
        return ContextEngine(db=mock_db, graph_db=None, embedder=mock_embedder, llm=mock_llm)

    def test_audit_empty_proposal(self, engine):
        result = engine._audit({}, "ad_optimization")
        assert not result.is_valid
        assert any("空" in e for e in result.errors)

    def test_audit_valid_ad_proposal(self, engine):
        proposal = {
            "recommendations": [
                {
                    "type": "bid_adjustment",
                    "action": "入札を15%引き上げ",
                    "reason": "test",
                    "expected_impact": "CPA改善",
                    "priority": "high",
                    "specific_values": {"bid_change_percent": 15},
                }
            ]
        }
        result = engine._audit(proposal, "ad_optimization")
        assert result.is_valid

    def test_audit_extreme_bid(self, engine):
        proposal = {
            "recommendations": [
                {
                    "type": "bid_adjustment",
                    "action": "入札を80%引き上げ",
                    "specific_values": {"bid_change_percent": 80},
                }
            ]
        }
        result = engine._audit(proposal, "ad_optimization")
        assert not result.is_valid
        assert any("極端" in e for e in result.errors)

    def test_audit_defensive_only_warning(self, engine):
        proposal = {
            "recommendations": [
                {
                    "type": "keyword_exclude",
                    "action": "無関連KWを削減",
                    "specific_values": {},
                }
            ]
        }
        result = engine._audit(proposal, "ad_optimization")
        assert result.is_valid  # warnings don't make it invalid
        assert any("守備的" in w for w in result.warnings)

    def test_audit_music_valid(self, engine):
        proposal = {
            "recommendations": [
                {
                    "type": "synth_patch",
                    "action": "3x Osc saw wave lead",
                    "reason": "Psytrance standard",
                    "expected_impact": "シャープなリード",
                    "priority": "high",
                    "specific_values": {
                        "filter_cutoff": 0.35,
                        "filter_resonance": 0.6,
                    },
                }
            ],
            "track_structure": {
                "bpm": 145,
                "key": "A minor",
                "sections": ["intro", "buildup", "drop"],
                "channels": ["kick", "bass", "lead"],
            },
        }
        result = engine._audit(proposal, "music_production")
        assert result.is_valid

    def test_audit_music_invalid_bpm(self, engine):
        proposal = {
            "recommendations": [{"type": "synth_patch", "action": "test"}],
            "track_structure": {"bpm": 999},
        }
        result = engine._audit(proposal, "music_production")
        assert not result.is_valid
        assert any("BPM" in e for e in result.errors)

    def test_audit_music_invalid_cutoff(self, engine):
        proposal = {
            "recommendations": [
                {
                    "type": "synth_patch",
                    "action": "test",
                    "specific_values": {"filter_cutoff": 5.0},
                }
            ],
        }
        result = engine._audit(proposal, "music_production")
        assert not result.is_valid
        assert any("filter_cutoff" in e for e in result.errors)

    def test_audit_unknown_domain(self, engine):
        proposal = {"recommendations": [{"type": "test", "action": "test"}]}
        result = engine._audit(proposal, "unknown_domain")
        assert result.is_valid  # unknown domain = no domain-specific rules


# ── Model Validation Tests ──


class TestModels:
    """Test Pydantic model validation."""

    def test_learn_request_defaults(self):
        req = LearnRequest(content="test knowledge")
        assert req.category == "general"
        assert req.metadata == {}

    def test_query_request_defaults(self):
        req = QueryRequest(query="search test")
        assert req.top_k == 5
        assert req.min_score == 0.7

    def test_propose_request_defaults(self):
        req = ProposeRequest(user_data={"campaign": "test"})
        assert req.domain == "ad_optimization"
        assert req.account_history == {}

    def test_feedback_request(self):
        req = FeedbackRequest(proposal_id="abc-123", accepted=True)
        assert req.accepted is True
        assert req.performance_after is None

    def test_health_response_version(self):
        resp = HealthResponse(status="ok", components={"api": "ok"})
        assert resp.version == "7.0.0"

    def test_propose_response_error(self):
        resp = ProposeResponse(success=False, error="test error")
        assert resp.proposal is None
        assert resp.error == "test error"

    def test_audit_result_defaults(self):
        result = AuditResult(is_valid=True)
        assert result.errors == []
        assert result.warnings == []

    def test_fact_defaults(self):
        fact = Fact(content="test fact")
        assert fact.tenant_id == "default"
        assert fact.access_count == 0
        assert fact.importance_score == 1.0


# ── Engine Integration (with mocks) ──


class TestEngineWithMocks:
    """Test ContextEngine pipeline using mock adapters."""

    @pytest.mark.anyio
    async def test_learn_stores_fact(self, engine, mock_db):
        doc_id = await engine.learn(content="テスト知識", tenant_id="test")
        assert doc_id is not None
        assert len(mock_db.docs) == 1

    @pytest.mark.anyio
    async def test_search_returns_results(self, engine, mock_db):
        # Pre-populate
        await engine.learn(content="テスト知識データ", tenant_id="test")
        results = await engine.search(query="テスト", tenant_id="test")
        assert isinstance(results, list)

    @pytest.mark.anyio
    async def test_propose_generates_proposal(self, engine):
        result = await engine.propose(
            user_data={"campaign": "test", "cpa": 10000},
            tenant_id="test",
            domain="ad_optimization",
        )
        assert "proposal_id" in result
        assert "proposal" in result
        assert "audit" in result
        assert isinstance(result["audit"], AuditResult)

    @pytest.mark.anyio
    async def test_propose_unknown_domain(self, engine):
        result = await engine.propose(
            user_data={"data": "test"},
            tenant_id="test",
            domain="custom_domain",
        )
        assert result["audit"].is_valid  # unknown domain passes
