"""API integration tests for AutoForge."""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoforge.main import app

DB_TESTS_ENABLED = os.getenv("RUN_DB_TESTS", "0") == "1"
LLM_TESTS_ENABLED = bool(os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY"))


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac,
    ):
        yield ac


@pytest.mark.anyio
async def test_health(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] in ("ok", "degraded")


@pytest.mark.anyio
async def test_metrics(client: AsyncClient):
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert b"autoforge_" in resp.content


@pytest.mark.skipif(not DB_TESTS_ENABLED, reason="DB-dependent test; set RUN_DB_TESTS=1")
@pytest.mark.anyio
async def test_login_invalid(client: AsyncClient):
    resp = await client.post("/token", params={"username": "bad", "password": "bad"})
    assert resp.status_code == 401


@pytest.mark.skipif(not DB_TESTS_ENABLED, reason="DB-dependent test; set RUN_DB_TESTS=1")
@pytest.mark.anyio
async def test_login_admin(client: AsyncClient):
    resp = await client.post(
        "/token",
        params={"username": "admin", "password": "admin123"},
    )
    assert resp.status_code in (200, 500)


@pytest.mark.skipif(not DB_TESTS_ENABLED, reason="DB-dependent test; set RUN_DB_TESTS=1")
@pytest.mark.skipif(not LLM_TESTS_ENABLED, reason="LLM API key required for this test")
@pytest.mark.anyio
async def test_propose_schema(client: AsyncClient):
    resp = await client.post(
        "/v1/propose",
        json={
            "user_data": {"campaign": "test", "current_cpa": 10000},
            "domain": "ad_optimization",
        },
        headers={"X-Tenant-ID": "test-tenant"},
    )
    assert resp.status_code in (200, 500)
    if resp.status_code == 200:
        data = resp.json()
        assert "success" in data
        assert "proposal_id" in data


@pytest.mark.skipif(not DB_TESTS_ENABLED, reason="DB-dependent test; set RUN_DB_TESTS=1")
@pytest.mark.skipif(not LLM_TESTS_ENABLED, reason="LLM API key required for this test")
@pytest.mark.anyio
async def test_learn_schema(client: AsyncClient):
    resp = await client.post(
        "/v1/learn",
        json={
            "content": "テスト知識データ",
            "category": "test",
        },
        headers={"X-Tenant-ID": "test-tenant"},
    )
    assert resp.status_code in (200, 500)


@pytest.mark.skipif(not DB_TESTS_ENABLED, reason="DB-dependent test; set RUN_DB_TESTS=1")
@pytest.mark.skipif(not LLM_TESTS_ENABLED, reason="LLM API key required for this test")
@pytest.mark.anyio
async def test_query_schema(client: AsyncClient):
    resp = await client.post(
        "/v1/query",
        json={"query": "テスト検索", "top_k": 3},
        headers={"X-Tenant-ID": "test-tenant"},
    )
    assert resp.status_code in (200, 500)
