#!/usr/bin/env python3
"""PostgreSQL + pgvector table initialization."""
import asyncio
import os

import asyncpg
from dotenv import load_dotenv

load_dotenv()


async def init_db():
    dsn = os.getenv(
        "DATABASE_URL",
        "postgresql://autoforge:autoforge@localhost:5433/autoforge",
    )
    conn = await asyncpg.connect(dsn)

    # pgvector extension
    await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Documents table (main knowledge store)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            content TEXT NOT NULL,
            vector vector(1536) NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)

    # HNSW index for cosine similarity (better quality than IVFFlat, no list tuning)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS documents_vector_hnsw_idx
        ON documents
        USING hnsw (vector vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)

    # Drop old IVFFlat index if it exists
    await conn.execute("""
        DROP INDEX IF EXISTS documents_vector_idx
    """)

    # Metadata GIN index for tenant/user filtering
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS documents_metadata_idx
        ON documents
        USING gin (metadata)
    """)

    # Proposals table (for feedback learning)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS proposals (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id TEXT NOT NULL DEFAULT 'default',
            domain TEXT NOT NULL DEFAULT 'ad_optimization',
            user_data JSONB NOT NULL DEFAULT '{}',
            proposal JSONB NOT NULL,
            audit_result JSONB NOT NULL DEFAULT '{}',
            accepted BOOLEAN DEFAULT NULL,
            performance_after JSONB DEFAULT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            feedback_at TIMESTAMP WITH TIME ZONE DEFAULT NULL
        )
    """)

    # Index for querying proposals by tenant
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS proposals_tenant_idx
        ON proposals (tenant_id, created_at DESC)
    """)

    # Index for finding proposals awaiting feedback
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS proposals_feedback_pending_idx
        ON proposals (accepted)
        WHERE accepted IS NULL
    """)

    print("✅ Database initialized:")
    print("   - documents table (HNSW index)")
    print("   - proposals table (tenant + feedback indexes)")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(init_db())
