"""
Neo4j GraphDB adapter — entity/relation management + graph expansion.
Implements GraphDB protocol.
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from neo4j import AsyncDriver, AsyncGraphDatabase

from .metrics import graph_entities_upserted, graph_expand_duration, graph_expand_total

logger = structlog.get_logger()


class Neo4jGraphDB:
    """Neo4j backed graph database for GraphRAG."""

    def __init__(self, uri: str, user: str, password: str):
        self.uri = uri
        self.user = user
        self.password = password
        self.database = "neo4j"
        self.driver: AsyncDriver | None = None

    async def connect(self) -> None:
        self.driver = AsyncGraphDatabase.driver(self.uri, auth=(self.user, self.password))
        async with self.driver.session(database=self.database) as session:
            await session.run(
                "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Entity) REQUIRE n.name IS UNIQUE"
            )
        logger.info("neo4j_connected", uri=self.uri)

    async def upsert_entities(self, entities: list[dict[str, Any]]) -> None:
        if not entities:
            return
        async with self.driver.session(database=self.database) as session:
            for ent in entities:
                await session.run(
                    """
                    MERGE (e:Entity {name: $name})
                    SET e.type = $type, e.updated_at = datetime()
                    """,
                    name=ent["name"],
                    type=ent.get("type", "unknown"),
                )
                graph_entities_upserted.inc(len(entities))
        logger.debug("entities_upserted", count=len(entities))

    async def upsert_relations(self, relations: list[tuple[str, str, str]]) -> None:
        if not relations:
            return
        async with self.driver.session(database=self.database) as session:
            for src, rel, tgt in relations:
                # Sanitize relation name (Neo4j requires alphanumeric + underscore)
                safe_rel = "".join(c if c.isalnum() or c == "_" else "_" for c in rel)
                await session.run(
                    f"""
                    MATCH (a:Entity {{name: $src}})
                    MATCH (b:Entity {{name: $tgt}})
                    MERGE (a)-[r:{safe_rel}]->(b)
                    SET r.updated_at = datetime()
                    """,
                    src=src,
                    tgt=tgt,
                )
        logger.debug("relations_upserted", count=len(relations))

    async def expand(self, seed_entities: list[str], depth: int = 1) -> list[str]:
        if not seed_entities:
            return []
        graph_expand_total.inc()
        start = time.time()
        async with self.driver.session(database=self.database) as session:
            result = await session.run(
                f"""
                MATCH (seed:Entity)
                WHERE seed.name IN $seeds
                MATCH (seed)-[*1..{min(depth, 5)}]-(neighbor:Entity)
                WHERE neighbor.name <> seed.name
                RETURN DISTINCT neighbor.name AS name
                LIMIT 50
                """,
                seeds=seed_entities,
            )
            records = await result.fetch(50)
            graph_expand_duration.observe(time.time() - start)
            return [r["name"] for r in records]

    async def close(self) -> None:
        if self.driver:
            await self.driver.close()
