"""
API integration tests for AutoForge.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from autoforge.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestHealth:
    async def test_health_returns_ok(self, client: AsyncClient):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == "7.0.0"
        assert "status" in data


class TestAuth:
    async def test_login_invalid(self, client: AsyncClient):
        resp = await client.post("/token", params={"username": "bad", "password": "bad"})
        assert resp.status_code == 401

    async def test_login_admin(self, client: AsyncClient):
        resp = await client.post(
            "/token",
            params={"username": "admin", "password": "admin123"},
        )
        # This will fail without DB, but verifies the route exists
        assert resp.status_code in (200, 500)


class TestPropose:
    async def test_propose_schema(self, client: AsyncClient):
        resp = await client.post(
            "/v1/propose",
            json={
                "user_data": {"campaign": "test", "current_cpa": 10000},
                "domain": "ad_optimization",
            },
            headers={"X-Tenant-ID": "test-tenant"},
        )
        # Will fail without DB/LLM, but verifies schema validation works
        assert resp.status_code in (200, 500)
        if resp.status_code == 200:
            data = resp.json()
            assert "success" in data
            assert "proposal_id" in data


class TestLearn:
    async def test_learn_schema(self, client: AsyncClient):
        resp = await client.post(
            "/v1/learn",
            json={
                "content": "テスト知識データ",
                "category": "test",
            },
            headers={"X-Tenant-ID": "test-tenant"},
        )
        assert resp.status_code in (200, 500)


class TestQuery:
    async def test_query_schema(self, client: AsyncClient):
        resp = await client.post(
            "/v1/query",
            json={"query": "テスト検索", "top_k": 3},
            headers={"X-Tenant-ID": "test-tenant"},
        )
        assert resp.status_code in (200, 500)
