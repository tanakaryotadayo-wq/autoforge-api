"""
pgvector adapter — PostgreSQL + pgvector for RAG vector search.
Implements VectorDB protocol.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

import asyncpg
import structlog

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

    async def search(
        self,
        vector: list[float],
        top_k: int = 5,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        vector_str = json.dumps(vector)

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
