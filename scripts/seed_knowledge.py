#!/usr/bin/env python3
"""
Knowledge Seed Script — load industry knowledge into AutoForge.
Usage: python scripts/seed_knowledge.py --file data/industry_knowledge.json
"""

import argparse
import asyncio
import json
import os

import asyncpg
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()


async def seed(filepath: str, tenant_id: str = "default"):
    dsn = os.getenv("DATABASE_URL", "postgresql://autoforge:autoforge@localhost:5433/autoforge")
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
    model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

    client = AsyncOpenAI(api_key=api_key)
    conn = await asyncpg.connect(dsn)

    with open(filepath, encoding="utf-8") as f:
        items = json.load(f)

    print(f"📦 {len(items)} 件の知識データを投入開始...")

    for i, item in enumerate(items):
        content = item.get("content", "")
        category = item.get("category", "general")
        metadata = {
            "tenant_id": tenant_id,
            "category": category,
            "importance_score": item.get("importance", 1.0),
            "access_count": 0,
            **(item.get("metadata", {})),
        }

        # Generate embedding
        resp = await client.embeddings.create(input=content[:8000], model=model)
        vector = resp.data[0].embedding
        vector_str = json.dumps(vector)

        await conn.execute(
            """
            INSERT INTO documents (content, vector, metadata)
            VALUES ($1, $2::vector, $3::jsonb)
            """,
            content,
            vector_str,
            json.dumps(metadata),
        )

        if (i + 1) % 10 == 0:
            print(f"  ✅ {i + 1}/{len(items)} 完了")

    print(f"🎉 全 {len(items)} 件の投入完了！")
    await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help="JSON file with knowledge data")
    parser.add_argument("--tenant", default="default", help="Tenant ID")
    args = parser.parse_args()
    asyncio.run(seed(args.file, args.tenant))
