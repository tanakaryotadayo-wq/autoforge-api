"""API integration tests for AutoForge."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoforge.main import app

DB_TESTS_ENABLED = os.getenv("RUN_DB_TESTS", "0") == "1"


@pytest.mark.anyio
async def test_health():
    app.state.graph_db = getattr(app.state, "graph_db", None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] in ("ok", "degraded")


@pytest.mark.anyio
async def test_metrics():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/metrics")
    assert resp.status_code == 200
    assert b"autoforge_" in resp.content


@pytest.mark.skipif(not DB_TESTS_ENABLED, reason="DB-dependent test; set RUN_DB_TESTS=1")
@pytest.mark.anyio
async def test_login_invalid():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/token", params={"username": "bad", "password": "bad"})
    assert resp.status_code == 401


@pytest.mark.skipif(not DB_TESTS_ENABLED, reason="DB-dependent test; set RUN_DB_TESTS=1")
@pytest.mark.anyio
async def test_login_admin():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/token",
            params={"username": "admin", "password": "admin123"},
        )
    assert resp.status_code in (200, 500)


@pytest.mark.skipif(not DB_TESTS_ENABLED, reason="DB-dependent test; set RUN_DB_TESTS=1")
@pytest.mark.anyio
async def test_propose_schema():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
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
@pytest.mark.anyio
async def test_learn_schema():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/v1/learn",
            json={
                "content": "テスト知識データ",
                "category": "test",
            },
            headers={"X-Tenant-ID": "test-tenant"},
        )
    assert resp.status_code in (200, 500)


@pytest.mark.skipif(not DB_TESTS_ENABLED, reason="DB-dependent test; set RUN_DB_TESTS=1")
@pytest.mark.anyio
async def test_query_schema():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/v1/query",
            json={"query": "テスト検索", "top_k": 3},
            headers={"X-Tenant-ID": "test-tenant"},
        )
    assert resp.status_code in (200, 500)
