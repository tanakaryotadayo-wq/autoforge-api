# Copilot Instructions for `autoforge-api`

## Big Picture
- This is a single FastAPI service (`src/autoforge/main.py`) exposing AI memory + proposal APIs on port `8698`.
- Core flow is `API -> ContextEngine -> adapters`: `main.py` builds `PgVectorDB`, optional `Neo4jGraphDB`, `OpenAIEmbedder`, `TokenAwareLLMClient`, then injects `ContextEngine` via `app.state`.
- Retrieval/proposal logic lives in `src/autoforge/engine/context.py`:
  - HyDE generation (`_generate_hyde`) -> embedding -> vector search
  - optional graph expansion (`_extract_entities` + `graph_db.expand`)
  - optional rerank (`_rerank`) -> proposal generation -> domain audit (`_audit`)
- Multi-tenant isolation is metadata-driven (`tenant_id` in pgvector metadata, `X-Tenant-ID` header via `get_tenant_id`).

## Project Conventions
- Keep adapters aligned with protocols in `src/autoforge/interfaces.py` (especially `VectorDB.store_proposal` / `update_feedback`, `LLMClient.chat` / `chat_json`).
- Preserve metrics wiring and naming from `src/autoforge/adapters/metrics.py` (`autoforge_*`).
- Use structured logs (`structlog`) and settings-driven logging (`settings.log_json`, `settings.log_level`) via `src/autoforge/logging.py`.
- Prefer minimal, surgical edits; do not refactor unrelated parts of `ContextEngine`.

## Runtime & Environment
- Settings source is `src/autoforge/config.py` (`BaseSettings`, `.env` file).
- For local host-run app/tests, use host endpoints:
  - `DATABASE_URL=postgresql://autoforge:autoforge@localhost:5433/autoforge`
  - `NEO4J_URI=bolt://localhost:7687`
- For compose app container, use service names:
  - `DATABASE_URL=postgresql://autoforge:autoforge@postgres:5432/autoforge`
  - `NEO4J_URI=bolt://neo4j:7687`

## Developer Workflows
- Lint/format (Python 3.12 target):
  - `uv run ruff check src/ tests/test_api.py --fix`
  - `uv run ruff format src/ tests/test_api.py`
- DB bootstrap:
  - `uv run python scripts/init_db.py`
- Tests:
  - default: `uv run pytest tests/ -v`
  - enable DB tests: `RUN_DB_TESTS=1 uv run pytest tests/ -v`
  - LLM-dependent tests auto-skip unless `DEEPSEEK_API_KEY` or `OPENAI_API_KEY` is set.

## Testing Patterns
- `tests/test_api.py` uses `app.router.lifespan_context(app)` fixture; keep this pattern when adding API tests so `app.state` is initialized.
- Keep API schema smoke tests tolerant of external dependencies (e.g., LLM path can return `200` or controlled failure).

## Integration Points
- PostgreSQL/pgvector schema and HNSW index are created in `scripts/init_db.py` (`documents`, `proposals`).
- Graph relationships are optional at runtime: app should still boot when Neo4j is unavailable (`main.py` sets `graph_db=None`).
- Feedback loop is first-class: `/v1/propose` persists proposal, `/v1/feedback` updates acceptance/performance.

## When modifying APIs
- Update both Pydantic schemas in `src/autoforge/models.py` and endpoint handlers in `src/autoforge/main.py` together.
- Preserve response contract for `HealthResponse`, `ProposeResponse`, and `/metrics` scrape behavior.
