import logging
import time

import openai
from openai import AsyncOpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

_BATCH_SIZE = 100


class EmbeddingService:
    def __init__(self, api_key: str, model: str, dimensions: int):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.dimensions = dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts.

        Batches internally to avoid API limits. Returns embeddings in the same
        order as the input texts.
        """
        if not texts:
            return []

        all_embeddings: list[list[float]] = []

        for batch_start in range(0, len(texts), _BATCH_SIZE):
            batch = texts[batch_start : batch_start + _BATCH_SIZE]
            embeddings = await self._embed_batch(batch)
            all_embeddings.extend(embeddings)
            logger.info(
                f"Embedded batch {batch_start // _BATCH_SIZE + 1} "
                f"({len(batch)} texts, model={self.model})"
            )

        return all_embeddings

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((openai.RateLimitError, openai.APITimeoutError)),
    )
    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        start = time.monotonic()
        response = await self.client.embeddings.create(
            model=self.model,
            input=texts,
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            f"Embedding batch done: {response.usage.total_tokens} tokens, {latency_ms}ms"
        )
        # OpenAI returns embeddings sorted by index — safe to sort and extract
        return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
