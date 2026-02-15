"""
AutoForge v7.0 Configuration
Granian + uv + DeepSeek + structlog
"""
from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── LLM Backend ──
    llm_backend: str = "deepseek"  # "deepseek" | "openai"

    # ── DeepSeek (default — $0.28/1M input tokens) ──
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_chat_model: str = "deepseek-chat"

    # ── OpenAI (fallback) ──
    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4o-mini"

    # ── Embedding (both use OpenAI embedding API) ──
    openai_embedding_model: str = "text-embedding-3-small"

    # ── PostgreSQL + pgvector ──
    database_url: str = "postgresql://autoforge:autoforge@localhost:5433/autoforge"

    # ── Neo4j ──
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password123"

    # ── JWT ──
    secret_key: str = "change-me-in-production"
    admin_password: str = "admin123"

    # ── RAG Search ──
    max_hops: int = 3
    rag_top_k: int = 5
    rag_min_score: float = 0.7
    rerank_candidates_max: int = 50
    rerank_final_limit: int = 20
    context_max_chars: int = 2500

    # ── Memory ──
    max_history_turns: int = 10

    # ── Cleanup ──
    cleanup_days_unused: int = 30
    cleanup_min_importance: float = 2.0

    # ── Concurrency ──
    llm_concurrency: int = 2
    embedding_concurrency: int = 2

    # ── Logging ──
    log_level: str = "info"
    log_json: bool = False

    # ── Server ──
    host: str = "0.0.0.0"
    port: int = 8000

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def active_api_key(self) -> str:
        """現在のバックエンドに対応するAPIキーを返す"""
        if self.llm_backend == "deepseek":
            return self.deepseek_api_key
        return self.openai_api_key

    @property
    def active_chat_model(self) -> str:
        """現在のバックエンドに対応するモデル名を返す"""
        if self.llm_backend == "deepseek":
            return self.deepseek_chat_model
        return self.openai_chat_model

    @property
    def active_base_url(self) -> str | None:
        """DeepSeekの場合はbase_urlを返す"""
        if self.llm_backend == "deepseek":
            return self.deepseek_base_url
        return None


settings = Settings()
