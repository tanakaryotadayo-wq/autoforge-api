#!/usr/bin/env python3
"""Wait for PostgreSQL to be ready, then run init_db."""

import asyncio
import sys
import time

import asyncpg


async def wait_and_init():
    dsn = "postgresql://autoforge:autoforge@postgres:5432/autoforge"
    max_retries = 30
    retry_interval = 2

    for attempt in range(1, max_retries + 1):
        try:
            conn = await asyncpg.connect(dsn)
            await conn.close()
            print(f"✅ PostgreSQL ready (attempt {attempt})")
            break
        except (OSError, asyncpg.CannotConnectNowError, asyncpg.InvalidCatalogNameError):
            print(f"⏳ Waiting for PostgreSQL... ({attempt}/{max_retries})")
            time.sleep(retry_interval)
    else:
        print("❌ PostgreSQL not available after retries")
        sys.exit(1)

    # Run init_db
    from init_db import init_db

    # Override DSN for Docker network
    import os

    os.environ["DATABASE_URL"] = dsn
    await init_db()
    print("🎉 DB initialization complete")


if __name__ == "__main__":
    asyncio.run(wait_and_init())
