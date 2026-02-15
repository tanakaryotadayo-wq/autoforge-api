"""
LLM Client — DeepSeek (default) or OpenAI, with token-aware truncation.
Implements LLMClient protocol. Wired with Prometheus metrics.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import structlog
import tiktoken
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import settings
from .metrics import llm_calls_total, llm_duration_seconds, llm_errors_total, llm_tokens_total

logger = structlog.get_logger()


class TokenAwareLLMClient:
    """Chat completion client with token counting and cost-effective backend switching."""

    MAX_INPUT_TOKENS = 4000

    def __init__(self):
        self.backend = settings.llm_backend
        self.model = settings.active_chat_model
        self.client = AsyncOpenAI(
            api_key=settings.active_api_key,
            base_url=settings.active_base_url,
        )
        self.sem = asyncio.Semaphore(settings.llm_concurrency)
        self._encoder = tiktoken.get_encoding("cl100k_base")

        logger.info(
            "llm_client_initialized",
            backend=self.backend,
            model=self.model,
        )

    def _truncate(self, text: str) -> str:
        """Truncate text to MAX_INPUT_TOKENS (keep front, cut tail)."""
        tokens = self._encoder.encode(text)
        if len(tokens) <= self.MAX_INPUT_TOKENS:
            return text
        logger.warning(
            "input_truncated",
            original_tokens=len(tokens),
            limit=self.MAX_INPUT_TOKENS,
        )
        return self._encoder.decode(tokens[: self.MAX_INPUT_TOKENS])

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=15))
    async def chat(self, system: str, user: str) -> str:
        truncated_user = self._truncate(user)
        async with self.sem:
            start = time.time()
            try:
                resp = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": truncated_user},
                    ],
                    temperature=0.3,
                )
                duration = time.time() - start
                content = resp.choices[0].message.content or ""

                # Metrics
                llm_calls_total.labels(model=self.model, endpoint="chat").inc()
                llm_duration_seconds.labels(model=self.model).observe(duration)
                if resp.usage:
                    llm_tokens_total.labels(direction="input").inc(resp.usage.prompt_tokens)
                    llm_tokens_total.labels(direction="output").inc(resp.usage.completion_tokens)

                logger.debug(
                    "llm_call",
                    model=self.model,
                    duration=round(duration, 2),
                    input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
                    output_tokens=resp.usage.completion_tokens if resp.usage else 0,
                )
                return content
            except Exception:
                llm_errors_total.labels(model=self.model).inc()
                raise

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=15))
    async def chat_json(self, system: str, user: str) -> dict[str, Any]:
        truncated_user = self._truncate(user)
        async with self.sem:
            start = time.time()
            try:
                resp = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": truncated_user},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.2,
                )
                duration = time.time() - start
                content = resp.choices[0].message.content or "{}"

                # Metrics
                llm_calls_total.labels(model=self.model, endpoint="chat_json").inc()
                llm_duration_seconds.labels(model=self.model).observe(duration)
                if resp.usage:
                    llm_tokens_total.labels(direction="input").inc(resp.usage.prompt_tokens)
                    llm_tokens_total.labels(direction="output").inc(resp.usage.completion_tokens)

                return json.loads(content)
            except Exception:
                llm_errors_total.labels(model=self.model).inc()
                raise
