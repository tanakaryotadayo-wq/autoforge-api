"""Protocol definitions — all adapters implement these interfaces."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class VectorDB(Protocol):
    async def upsert(
        self,
        doc_id: str,
        content: str,
        vector: list[float],
        metadata: dict[str, Any],
    ) -> None: ...

    async def search(
        self,
        vector: list[float],
        top_k: int = 5,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...

    async def delete(self, doc_id: str) -> None: ...
    async def increment_counter(self, doc_ids: list[str]) -> None: ...
    async def store_proposal(
        self,
        proposal_id: str,
        tenant_id: str,
        domain: str,
        user_data: dict[str, Any],
        proposal: dict[str, Any],
        audit_result: dict[str, Any],
    ) -> None: ...
    async def update_feedback(
        self,
        proposal_id: str,
        accepted: bool,
        performance_after: dict[str, Any] | None = None,
    ) -> bool: ...
    async def get_stats(self, tenant_id: str) -> dict[str, Any]: ...
    async def get_proposals_history(
        self,
        tenant_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]: ...


@runtime_checkable
class GraphDB(Protocol):
    async def connect(self) -> None: ...
    async def expand(self, seed_entities: list[str], depth: int = 1) -> list[str]: ...
    async def upsert_entities(self, entities: list[dict[str, Any]]) -> None: ...
    async def upsert_relations(self, relations: list[tuple[str, str, str]]) -> None: ...
    async def close(self) -> None: ...


@runtime_checkable
class Embedder(Protocol):
    async def embed(self, text: str) -> list[float]: ...
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


@runtime_checkable
class LLMClient(Protocol):
    async def chat(self, system: str, user: str) -> str: ...
    async def chat_json(self, system: str, user: str) -> dict[str, Any]: ...


@runtime_checkable
class Cache(Protocol):
    async def get(self, namespace: str, key: str) -> Any | None: ...
    async def set(self, namespace: str, key: str, value: Any, ttl: int = 3600) -> None: ...
