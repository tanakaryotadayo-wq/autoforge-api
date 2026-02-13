"""
OpenAI-compatible Embedder — works with both OpenAI and DeepSeek.
Implements Embedder protocol.
"""
from __future__ import annotations

import asyncio

import structlog
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import settings

logger = structlog.get_logger()


class OpenAIEmbedder:
    """Embedding client using OpenAI API (also compatible with DeepSeek text-embedding)."""

    def __init__(self):
        # Embedding always uses OpenAI's API (DeepSeek doesn't have its own embeddings)
        self.client = AsyncOpenAI(api_key=settings.openai_api_key or settings.deepseek_api_key)
        self.model = settings.openai_embedding_model
        self.sem = asyncio.Semaphore(settings.embedding_concurrency)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def embed(self, text: str) -> list[float]:
        async with self.sem:
            resp = await self.client.embeddings.create(
                input=text[:8000],  # Truncate to stay within limits
                model=self.model,
            )
            return resp.data[0].embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        tasks = [self.embed(t) for t in texts]
        return await asyncio.gather(*tasks)
