"""
pgvector adapter — PostgreSQL + pgvector for RAG vector search.
Implements VectorDB protocol. Wired with Prometheus metrics.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import asyncpg
import structlog

from .metrics import vector_search_duration, vector_search_total, vector_upsert_total

logger = structlog.get_logger()


class PgVectorDB:
    """PostgreSQL + pgvector backed vector store with multi-tenant support."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self.pool = await asyncpg.create_pool(self.dsn, min_size=2, max_size=10)
        logger.info("pgvector_connected", dsn=self.dsn[:30] + "...")

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    async def upsert(
        self,
        doc_id: str,
        content: str,
        vector: list[float],
        metadata: dict[str, Any],
    ) -> None:
        vector_str = json.dumps(vector)
        metadata_json = json.dumps(metadata)
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO documents (id, content, vector, metadata)
                VALUES ($1::uuid, $2, $3::vector, $4::jsonb)
                ON CONFLICT (id) DO UPDATE SET
                    content = EXCLUDED.content,
                    vector = EXCLUDED.vector,
                    metadata = EXCLUDED.metadata
                """,
                uuid.UUID(doc_id),
                content,
                vector_str,
                metadata_json,
            )
        vector_upsert_total.inc()

    async def search(
        self,
        vector: list[float],
        top_k: int = 5,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        vector_str = json.dumps(vector)
        start = time.time()

        # Build filter clause for tenant isolation
        where_clauses = []
        params: list[Any] = [vector_str, top_k]

        if filter_metadata:
            for i, (key, val) in enumerate(filter_metadata.items(), start=3):
                where_clauses.append(f"metadata->>'{key}' = ${i}")
                params.append(str(val))

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT id::text, content, metadata::text,
                       1 - (vector <=> $1::vector) AS similarity
                FROM documents
                {where_sql}
                ORDER BY vector <=> $1::vector
                LIMIT $2
                """,
                *params,
            )

        duration = time.time() - start
        tenant = "unknown"
        if filter_metadata and "tenant_id" in filter_metadata:
            tenant = filter_metadata["tenant_id"]
        vector_search_total.labels(tenant=tenant).inc()
        vector_search_duration.observe(duration)

        return [
            {
                "id": row["id"],
                "content": row["content"],
                "metadata": json.loads(row["metadata"]),
                "similarity": float(row["similarity"]),
            }
            for row in rows
        ]

    async def delete(self, doc_id: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM documents WHERE id = $1::uuid",
                uuid.UUID(doc_id),
            )

    async def increment_counter(self, doc_ids: list[str]) -> None:
        """Increment access_count and update last_accessed for retrieved docs."""
        if not doc_ids:
            return
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE documents
                SET metadata = jsonb_set(
                    jsonb_set(
                        metadata,
                        '{access_count}',
                        (COALESCE(metadata->>'access_count', '0')::int + 1)::text::jsonb
                    ),
                    '{last_accessed}',
                    to_jsonb(extract(epoch from now()))
                )
                WHERE id = ANY($1::uuid[])
                """,
                [uuid.UUID(d) for d in doc_ids],
            )

    async def cleanup_old_facts(self, days: int, min_importance: float) -> int:
        """Remove old, low-importance personal facts."""
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM documents
                WHERE metadata->>'user_id' IS NOT NULL
                  AND (metadata->>'last_accessed')::float
                      < extract(epoch from now()) - ($1 * 86400)
                  AND (metadata->>'importance_score')::float < $2
                """,
                days,
                min_importance,
            )
            deleted = int(result.split()[-1]) if result else 0
            logger.info("cleanup_completed", deleted=deleted)
            return deleted

    # ── Proposal storage (for feedback learning) ──

    async def store_proposal(
        self,
        proposal_id: str,
        tenant_id: str,
        domain: str,
        user_data: dict[str, Any],
        proposal: dict[str, Any],
        audit_result: dict[str, Any],
    ) -> None:
        """Store a generated proposal for future feedback tracking."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO proposals (id, tenant_id, domain, user_data, proposal, audit_result)
                VALUES ($1::uuid, $2, $3, $4::jsonb, $5::jsonb, $6::jsonb)
                ON CONFLICT (id) DO UPDATE SET
                    proposal = EXCLUDED.proposal,
                    audit_result = EXCLUDED.audit_result
                """,
                uuid.UUID(proposal_id),
                tenant_id,
                domain,
                json.dumps(user_data, ensure_ascii=False),
                json.dumps(proposal, ensure_ascii=False),
                json.dumps(audit_result, ensure_ascii=False),
            )

    async def update_feedback(
        self,
        proposal_id: str,
        accepted: bool,
        performance_after: dict[str, Any] | None = None,
    ) -> bool:
        """Record user feedback on a proposal. Returns True if proposal found."""
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE proposals
                SET accepted = $2,
                    performance_after = $3::jsonb,
                    feedback_at = NOW()
                WHERE id = $1::uuid
                """,
                uuid.UUID(proposal_id),
                accepted,
                json.dumps(performance_after or {}),
            )
            updated = int(result.split()[-1]) if result else 0
            return updated > 0

    # ── Business Layer Queries ──

    async def get_stats(self, tenant_id: str) -> dict[str, str | int | float]:
        """Get tenant-level statistics."""
        async with self.pool.acquire() as conn:
            facts_count = await conn.fetchval(
                "SELECT COUNT(*) FROM documents WHERE metadata->>'tenant_id' = $1",
                tenant_id,
            )
            proposals_count = await conn.fetchval(
                "SELECT COUNT(*) FROM proposals WHERE tenant_id = $1",
                tenant_id,
            )
            accepted_count = await conn.fetchval(
                "SELECT COUNT(*) FROM proposals WHERE tenant_id = $1 AND accepted = TRUE",
                tenant_id,
            )
            return {
                "tenant_id": tenant_id,
                "total_facts": facts_count or 0,
                "total_proposals": proposals_count or 0,
                "accepted_proposals": accepted_count or 0,
                "acceptance_rate": round((accepted_count or 0) / max(proposals_count or 1, 1), 3),
            }

    async def get_proposals_history(
        self, tenant_id: str, limit: int = 20, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Get paginated proposal history for a tenant.

        This method guards against partially corrupted JSON in DB columns by
        falling back to a sensible default and logging a warning.
        """
        def _safe_load(text: str, fallback: Any) -> Any:
            if text is None:
                return fallback
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning("proposal_history_json_decode", error=str(e))
                return fallback

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id::text, domain, user_data::text, proposal::text,
                       audit_result::text, accepted, created_at, feedback_at
                FROM proposals
                WHERE tenant_id = $1
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
                """,
                tenant_id,
                limit,
                offset,
            )

            result: list[dict[str, Any]] = []
            for row in rows:
                user_data = _safe_load(row["user_data"], {})
                proposal = _safe_load(row["proposal"], {})
                audit_result = _safe_load(row["audit_result"], {})

                result.append(
                    {
                        "id": row["id"],
                        "domain": row["domain"],
                        "user_data": user_data,
                        "proposal": proposal,
                        "audit_result": audit_result,
                        "accepted": row["accepted"],
                        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                        "feedback_at": row["feedback_at"].isoformat() if row["feedback_at"] else None,
                    }
                )

            return result
