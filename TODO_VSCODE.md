# AutoForge API — VS Code AI 仕上げ指示書

> **前工程 (Antigravity) で完了済み:** Dockerfile修正, docker-compose整備, structlog, Prometheus metrics接続, feedback endpoint実装, HNSW index, ポート8698統一
>
> **この工程の目的:** 型安全性・エラーハンドリング・テストの仕上げ

---

## 1. 型チェック & Lint 修正

```bash
uv run ruff check src/ --fix
uv run ruff format src/
```

- `src/autoforge/` 以下の全ファイルで `ruff check` のエラーを0にする
- 不要な `import` 削除、`noqa` コメントの整理

---

## 2. models.py の FeedbackRequest 確認

`src/autoforge/models.py` に `FeedbackRequest` モデルが存在するか確認。なければ追加:

```python
class FeedbackRequest(BaseModel):
    proposal_id: str
    accepted: bool
    performance_after: dict[str, Any] | None = None
```

`main.py` で import されている全モデル (`HealthResponse`, `LearnRequest`, `ProposeRequest`, `ProposeResponse`, `QueryRequest`, `FeedbackRequest`) が `models.py` に定義されているか確認。

---

## 3. Neo4j アダプターにメトリクス接続

`src/autoforge/adapters/neo4j_graph.py` の `expand()` メソッドに以下を追加:

- `graph_expand_total.inc()` — 呼び出しカウント
- `graph_expand_duration.observe(duration)` — レイテンシ計測
- `graph_entities_upserted.inc(count)` — upsert時のエンティティ数

metrics は `from .metrics import graph_expand_total, graph_expand_duration, graph_entities_upserted` で import。

---

## 4. embedder.py にメトリクス接続

`src/autoforge/adapters/embedder.py` の `embed()` メソッドに:

- LLM呼び出しカウント (`llm_calls_total.labels(model=..., endpoint="embedding").inc()`)
- レイテンシ計測

---

## 5. テスト拡充

`tests/test_api.py` に以下のテストを追加/修正:

```python
import pytest
from httpx import ASGITransport, AsyncClient
from autoforge.main import app

@pytest.mark.anyio
async def test_health():
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
```

- DB接続が必要なテストは `@pytest.mark.skipif` で条件付きスキップにする
- `pyproject.toml` に `[tool.pytest.ini_options]` でanyio設定があるか確認

---

## 6. interfaces.py のプロトコル整合性

`src/autoforge/interfaces.py` のプロトコル定義と実装クラスが一致しているか確認:

- `VectorDB` プロトコルに `store_proposal()`, `update_feedback()` を追加
- `LLMClient` プロトコルに `chat()`, `chat_json()` のシグネチャが正しいか確認

---

## 7. config.py の LOG_JSON / LOG_LEVEL 追加確認

`Settings` クラスに以下が定義されているか確認:

```python
log_json: bool = False
log_level: str = "INFO"
```

`logging.py` がこれらを参照しているため必須。

---

## 実行手順

```bash
cd /Users/ryota/Library/CloudStorage/GoogleDrive-tanakaryotadayo@gmail.com/マイドライブ/autoforge-api

# Lint & Format
uv run ruff check src/ --fix
uv run ruff format src/

# テスト実行
uv run pytest tests/ -v

# 全部OKなら commit & push
git add -A
git commit -m "polish: type safety, lint fixes, test coverage, metrics wiring"
git push origin main
```
