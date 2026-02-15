"""
ContextEngine — the brain of AutoForge.
HyDE + multi-hop RAG + GraphRAG + relation extraction + ECK audit.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from typing import Any

import structlog

from ..adapters.embedder import OpenAIEmbedder
from ..adapters.llm_client import TokenAwareLLMClient
from ..adapters.neo4j_graph import Neo4jGraphDB
from ..adapters.pgvector import PgVectorDB
from ..config import settings
from ..models import AuditResult

logger = structlog.get_logger()


class ContextEngine:
    """
    Core RAG + GraphRAG engine.
    - HyDE: generates a hypothetical answer, embeds it for better retrieval
    - Multi-hop: iteratively expands search with new entities
    - GraphRAG: Neo4j entity expansion
    - Relation extraction: auto-builds the knowledge graph
    - Reranking: LLM-scored relevance
    """

    def __init__(
        self,
        db: PgVectorDB,
        graph_db: Neo4jGraphDB | None,
        embedder: OpenAIEmbedder,
        llm: TokenAwareLLMClient,
    ):
        self.db = db
        self.graph_db = graph_db
        self.embedder = embedder
        self.llm = llm
        self.llm_sem = asyncio.Semaphore(settings.llm_concurrency)
        # In-memory cache (Redis replacement for cost savings)
        self._cache: dict[str, tuple[Any, float]] = {}

    def _cache_key(self, prefix: str, text: str) -> str:
        return f"{prefix}:{hashlib.sha256(text.encode()).hexdigest()[:16]}"

    def _cache_get(self, key: str) -> Any | None:
        if key in self._cache:
            val, expires = self._cache[key]
            if time.time() < expires:
                return val
            del self._cache[key]
        return None

    def _cache_set(self, key: str, value: Any, ttl: int = 3600) -> None:
        self._cache[key] = (value, time.time() + ttl)

    # ── HyDE: Hypothetical Document Embeddings ──

    async def _generate_hyde(self, query: str) -> str:
        """Generate a hypothetical answer to improve retrieval."""
        cached = self._cache_get(self._cache_key("hyde", query))
        if cached:
            return cached

        hyde_text = await self.llm.chat(
            system="あなたはドメインエキスパートです。以下の質問に対して、ナレッジベースに存在しそうな理想的な回答文を生成してください。実際の正確さは重要ではなく、検索に役立つ文体・用語を含めてください。",
            user=query,
        )
        self._cache_set(self._cache_key("hyde", query), hyde_text, ttl=1800)
        return hyde_text

    # ── Entity Extraction (for GraphRAG) ──

    async def _extract_entities(self, text: str) -> list[str]:
        """Extract key entities from text for graph expansion."""
        cached = self._cache_get(self._cache_key("ent", text[:200]))
        if cached:
            return cached

        result = await self.llm.chat_json(
            system=(
                "テキストからキーエンティティを抽出し、"
                '{"entities": ["entity1", "entity2"]} 形式のJSONで返してください。'
                "最大5個まで。"
            ),
            user=text[:800],
        )
        entities = result.get("entities", [])[:5]
        self._cache_set(self._cache_key("ent", text[:200]), entities, ttl=3600)
        return entities

    # ── Relation Extraction (for building the graph) ──

    async def _extract_relations(self, text: str) -> list[tuple[str, str, str]]:
        """Extract (subject, relation, object) triples from text."""
        cached = self._cache_get(self._cache_key("rel", text[:200]))
        if cached:
            return [tuple(t) for t in cached]

        result = await self.llm.chat_json(
            system="""知識グラフ構築エキスパートとして、テキストから事実に基づく関係性を抽出してください。
出力形式: {"relations": [["主体", "関係", "客体"], ...]}
関係の例: 開発者, 一部である, 含む, 所属する, 依存する, 競合する, 位置する
最大5つまで。""",
            user=text[:800],
        )
        raw = result.get("relations", [])
        valid = [tuple(r[:3]) for r in raw if isinstance(r, list) and len(r) >= 3]
        self._cache_set(self._cache_key("rel", text[:200]), [list(r) for r in valid], ttl=86400)
        return valid

    # ── Reranking ──

    async def _rerank(self, query: str, docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """LLM-based reranking of retrieved documents."""
        if len(docs) <= settings.rerank_final_limit:
            return docs

        # Batch rerank
        doc_summaries = "\n".join(
            f"[{i}] {d['content'][:150]}"
            for i, d in enumerate(docs[: settings.rerank_candidates_max])
        )

        result = await self.llm.chat_json(
            system=(
                "以下の検索結果をクエリとの関連度で並べ替え、"
                f"上位{settings.rerank_final_limit}件のインデックスをJSON配列で"
                '返してください。形式: {"ranked": [0, 3, 1, ...]}'
            ),
            user=f"クエリ: {query}\n\n検索結果:\n{doc_summaries}",
        )
        ranked_indices = result.get("ranked", list(range(len(docs))))
        reranked = []
        for idx in ranked_indices[: settings.rerank_final_limit]:
            if isinstance(idx, int) and 0 <= idx < len(docs):
                reranked.append(docs[idx])
        return reranked or docs[: settings.rerank_final_limit]

    # ── Multi-hop Search ──

    async def search(
        self,
        query: str,
        tenant_id: str = "default",
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Full multi-hop search pipeline: HyDE → vector search → GraphRAG → rerank."""
        all_docs: dict[str, dict[str, Any]] = {}

        # Step 1: HyDE
        hyde_text = await self._generate_hyde(query)
        hyde_vector = await self.embedder.embed(hyde_text)

        # Step 2: Initial vector search
        filter_meta = {"tenant_id": tenant_id}
        if user_id:
            filter_meta["user_id"] = user_id

        initial_results = await self.db.search(
            vector=hyde_vector, top_k=settings.rag_top_k, filter_metadata=filter_meta
        )
        for doc in initial_results:
            all_docs[doc["id"]] = doc

        # Step 3: Multi-hop expansion
        for _hop in range(settings.max_hops):
            if not all_docs:
                break

            # Extract entities from current results
            combined_text = " ".join(d["content"][:200] for d in all_docs.values())
            entities = await self._extract_entities(combined_text)

            # GraphRAG expansion
            if self.graph_db and entities:
                neighbors = await self.graph_db.expand(entities, depth=1)
                if neighbors:
                    neighbor_text = " ".join(neighbors)
                    neighbor_vector = await self.embedder.embed(neighbor_text)
                    graph_results = await self.db.search(
                        vector=neighbor_vector, top_k=3, filter_metadata=filter_meta
                    )
                    for doc in graph_results:
                        if doc["id"] not in all_docs:
                            all_docs[doc["id"]] = doc

            # Check if we have enough new results to continue
            if len(all_docs) >= settings.rerank_candidates_max:
                break

        docs_list = list(all_docs.values())

        # Step 4: Rerank
        if len(docs_list) > settings.rerank_final_limit:
            docs_list = await self._rerank(query, docs_list)

        # Step 5: Increment access counters
        doc_ids = [d["id"] for d in docs_list if d.get("id")]
        await self.db.increment_counter(doc_ids)

        logger.info(
            "search_completed",
            query=query[:50],
            total_results=len(docs_list),
            tenant=tenant_id,
        )
        return docs_list

    # ── Learn (store new knowledge) ──

    async def learn(
        self,
        content: str,
        tenant_id: str = "default",
        user_id: str | None = None,
        category: str = "general",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Store a new fact in the knowledge base + auto-extract graph relations."""
        doc_id = str(uuid.uuid4())
        vector = await self.embedder.embed(content)

        doc_metadata = {
            "tenant_id": tenant_id,
            "category": category,
            "timestamp": time.time(),
            "access_count": 0,
            "importance_score": 1.0,
            **({"user_id": user_id} if user_id else {}),
            **(metadata or {}),
        }

        await self.db.upsert(doc_id, content, vector, doc_metadata)

        # Auto-extract relations for GraphRAG
        if self.graph_db:
            relations = await self._extract_relations(content)
            if relations:
                entities: set[str] = set()
                for src, _rel, tgt in relations:
                    entities.add(src)
                    entities.add(tgt)
                await self.graph_db.upsert_entities(
                    [{"name": e, "type": "unknown"} for e in entities]
                )
                await self.graph_db.upsert_relations(relations)
                logger.info("relations_extracted", count=len(relations))

        logger.info("fact_learned", doc_id=doc_id, tenant=tenant_id, category=category)
        return doc_id

    # ── Propose (generate suggestions with context) ──

    async def propose(
        self,
        user_data: dict[str, Any],
        tenant_id: str = "default",
        domain: str = "ad_optimization",
        account_history: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate a proposal using RAG context + domain knowledge."""
        # Build query from user data
        query_parts = []
        if isinstance(user_data, dict):
            for key, val in user_data.items():
                query_parts.append(f"{key}: {val}")
        query = " ".join(query_parts)[:1000]

        # Search for relevant knowledge
        context_docs = await self.search(query, tenant_id=tenant_id)
        context_text = "\n".join(d["content"][:300] for d in context_docs[:10])[
            : settings.context_max_chars
        ]

        # Build proposal prompt
        system_prompt = self._get_domain_prompt(domain)
        context_part = (
            context_text
            if context_text.strip()
            else "(関連知識なし — 一般的な分析に基づいて提案してください)"
        )
        user_prompt = f"""## ナレッジベースからの関連知識
    {context_part}

## ユーザーデータ
{json.dumps(user_data, ensure_ascii=False, indent=2)[:2000]}

## アカウント履歴
{json.dumps(account_history or {}, ensure_ascii=False, indent=2)[:1000]}

上記に基づいて、JSON形式で攻撃的かつ具体的な提案を生成してください。
"""

        proposal = await self.llm.chat_json(system=system_prompt, user=user_prompt)

        # Audit
        audit = self._audit(proposal, domain)

        proposal_id = str(uuid.uuid4())
        logger.info(
            "proposal_generated",
            proposal_id=proposal_id,
            tenant=tenant_id,
            domain=domain,
            audit_valid=audit.is_valid,
        )

        return {
            "proposal_id": proposal_id,
            "proposal": proposal,
            "audit": audit,
            "context_docs_used": len(context_docs),
        }

    def _get_domain_prompt(self, domain: str) -> str:
        """Get domain-specific system prompt from the domain registry."""
        from ..domains import get_domain_prompt

        return get_domain_prompt(domain)

    def _audit(self, proposal: dict[str, Any], domain: str) -> AuditResult:
        """ECK-lite audit — delegate to domain registry."""
        from ..domains import audit_proposal

        return audit_proposal(proposal, domain)
