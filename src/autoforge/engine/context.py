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
            system='テキストからキーエンティティを抽出し、{"entities": ["entity1", "entity2"]} 形式のJSONで返してください。最大5個まで。',
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
            f"[{i}] {d['content'][:150]}" for i, d in enumerate(docs[:settings.rerank_candidates_max])
        )

        result = await self.llm.chat_json(
            system=f'以下の検索結果をクエリとの関連度で並べ替え、上位{settings.rerank_final_limit}件のインデックスをJSON配列で返してください。形式: {{"ranked": [0, 3, 1, ...]}}',
            user=f"クエリ: {query}\n\n検索結果:\n{doc_summaries}",
        )
        ranked_indices = result.get("ranked", list(range(len(docs))))
        reranked = []
        for idx in ranked_indices[:settings.rerank_final_limit]:
            if isinstance(idx, int) and 0 <= idx < len(docs):
                reranked.append(docs[idx])
        return reranked or docs[:settings.rerank_final_limit]

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
        for hop in range(settings.max_hops):
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
        context_text = "\n".join(
            d["content"][:300] for d in context_docs[:10]
        )[:settings.context_max_chars]

        # Build proposal prompt
        system_prompt = self._get_domain_prompt(domain)
        user_prompt = f"""## ナレッジベースからの関連知識
{context_text if context_text.strip() else "(関連知識なし — 一般的な分析に基づいて提案してください)"}

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
        """Get domain-specific system prompt."""
        prompts = {
            "ad_optimization": """あなたは広告運用の上級コンサルタントです。
以下のルールに従って提案を生成してください：

1. 「守り」だけでなく「攻め」の提案を必ず含める（入札引き上げ、新KW追加等）
2. 具体的な数値（入札額、予算額、想定CPA）を含める
3. 季節・天候・地域の特性を考慮する
4. 過去の成功パターンがあれば必ず参照する

出力形式（JSON）:
{
  "recommendations": [
    {
      "type": "bid_adjustment|keyword_add|keyword_exclude|budget_change|targeting",
      "action": "具体的なアクション",
      "reason": "根拠",
      "expected_impact": "想定効果",
      "priority": "high|medium|low",
      "specific_values": {}
    }
  ],
  "summary": "全体の方針要約",
  "risk_assessment": "リスク評価"
}""",
            "music_production": """あなたはプロの音楽プロデューサー兼サウンドデザイナーです。
FL Studio Mobile (FLM) のパラメータを熟知しており、ジャンル特有の制作手法に精通しています。

ナレッジベースの解析データを最優先で参照し、具体的なDAWパラメータ値で提案してください。

対応ジャンル: Psytrance, Techno, Acid, House, Drum & Bass, Ambient, Lo-Fi

出力形式（JSON）:
{
  "recommendations": [
    {
      "type": "synth_patch|drum_pattern|effect_chain|arrangement|mixing|sound_design",
      "action": "具体的なアクション",
      "reason": "根拠（ジャンル理論・KB知識）",
      "expected_impact": "想定効果（聴覚的変化）",
      "priority": "high|medium|low",
      "specific_values": {
        "bpm": 145,
        "key": "A minor",
        "synth": "3x Osc",
        "waveform": "saw",
        "filter_cutoff": 0.35,
        "filter_resonance": 0.6,
        "attack_ms": 5,
        "release_ms": 200,
        "reverb_size": 0.4,
        "delay_time_ms": 375,
        "sidechain_ratio": "4:1"
      }
    }
  ],
  "track_structure": {
    "bpm": 145,
    "key": "A minor",
    "time_signature": "4/4",
    "sections": ["intro_8bar", "buildup_16bar", "drop_16bar", "breakdown_8bar", "drop2_16bar", "outro_8bar"],
    "total_bars": 72,
    "channels": ["kick", "bass", "lead", "pad", "hihat", "clap", "fx"]
  },
  "summary": "制作方針の要約",
  "genre_notes": "ジャンル固有の注意点"
}""",
        }
        return prompts.get(
            domain,
            "あなたは分析エキスパートです。データに基づいた具体的な提案をJSON形式で生成してください。",
        )

    def _audit(self, proposal: dict[str, Any], domain: str) -> AuditResult:
        """ECK-lite audit — validate proposal sanity."""
        errors: list[str] = []
        warnings: list[str] = []

        recommendations = proposal.get("recommendations", [])

        if not recommendations:
            errors.append("提案が空です")
            return AuditResult(is_valid=False, errors=errors)

        if domain == "ad_optimization":
            # Rule 1: Must have at least one non-defensive recommendation
            has_offensive = any(
                r.get("type") in ("bid_adjustment", "keyword_add", "targeting", "budget_change")
                and "引き下げ" not in r.get("action", "")
                and "削減" not in r.get("action", "")
                for r in recommendations
            )
            if not has_offensive:
                warnings.append("全ての提案が守備的です。攻めの提案を追加してください。")

            # Rule 2: Check for specific values
            missing_values = [
                r for r in recommendations if not r.get("specific_values")
            ]
            if missing_values:
                warnings.append(f"{len(missing_values)}件の提案に具体的な数値がありません")

            # Rule 3: Bid adjustments should be within reasonable range
            for r in recommendations:
                vals = r.get("specific_values", {})
                bid_change = vals.get("bid_change_percent")
                if bid_change is not None:
                    if abs(bid_change) > 50:
                        errors.append(
                            f"入札変更率が{bid_change}%は極端すぎます（上限±50%）"
                        )

            # Rule 4: Budget changes should be gradual
            for r in recommendations:
                vals = r.get("specific_values", {})
                budget_change = vals.get("budget_change_percent")
                if budget_change is not None:
                    if abs(budget_change) > 30:
                        warnings.append(
                            f"予算変更率{budget_change}%は急激です（推奨±30%以内）"
                        )

        elif domain == "music_production":
            # Genre-specific BPM ranges
            bpm_ranges = {
                "psytrance": (138, 155), "techno": (125, 150),
                "acid": (120, 140), "house": (118, 132),
                "drum_and_bass": (160, 180), "ambient": (60, 100),
                "lo-fi": (70, 95),
            }

            track = proposal.get("track_structure", {})
            bpm = track.get("bpm")

            # Rule 1: BPM sanity check
            if bpm is not None:
                if bpm < 30 or bpm > 300:
                    errors.append(f"BPM {bpm} は範囲外です（30-300）")

            # Rule 2: Check specific_values on recommendations
            for r in recommendations:
                vals = r.get("specific_values", {})

                # Filter cutoff should be 0.0 - 1.0
                cutoff = vals.get("filter_cutoff")
                if cutoff is not None and not (0.0 <= cutoff <= 1.0):
                    errors.append(f"filter_cutoff {cutoff} は 0.0-1.0 の範囲外です")

                # Resonance should be 0.0 - 1.0
                reso = vals.get("filter_resonance")
                if reso is not None and not (0.0 <= reso <= 1.0):
                    errors.append(f"filter_resonance {reso} は 0.0-1.0 の範囲外です")

                # Reverb size should be 0.0 - 1.0
                reverb = vals.get("reverb_size")
                if reverb is not None and not (0.0 <= reverb <= 1.0):
                    warnings.append(f"reverb_size {reverb} は 0.0-1.0 の範囲外です")

            # Rule 3: Track structure should have sections
            sections = track.get("sections", [])
            if track and not sections:
                warnings.append("track_structure にセクション定義がありません")

            # Rule 4: Channel count sanity
            channels = track.get("channels", [])
            if len(channels) > 16:
                warnings.append(f"チャンネル数 {len(channels)} は FLM の制限を超える可能性があります")

        return AuditResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )
