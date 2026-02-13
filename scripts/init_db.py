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
        "postgresql://autoforge:autoforge@localhost:5432/autoforge",
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

    # IVFFlat index for cosine similarity
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS documents_vector_idx
        ON documents
        USING ivfflat (vector vector_cosine_ops)
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
            proposal JSONB NOT NULL,
            accepted BOOLEAN DEFAULT NULL,
            performance_after JSONB DEFAULT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)

    print("✅ Database initialized (documents + proposals tables)")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(init_db())
