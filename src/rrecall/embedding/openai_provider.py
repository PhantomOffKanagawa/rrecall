"""OpenAI embedding provider with cost tracking."""

from __future__ import annotations

from typing import TYPE_CHECKING

import tiktoken

from rrecall.embedding.base import EmbeddingProvider
from rrecall.embedding.cost_tracker import record
from rrecall.utils.logging import get_logger

if TYPE_CHECKING:
    from rrecall.config import OpenAIEmbeddingConfig

logger = get_logger("embedding.openai_provider")

_BATCH_SIZE = 100  # OpenAI supports up to 2048 but smaller is more reliable


class OpenAIProvider(EmbeddingProvider):
    """Wraps the OpenAI embeddings API."""

    def __init__(self, config: OpenAIEmbeddingConfig) -> None:
        from openai import OpenAI

        if not config.api_key:
            raise ValueError("OpenAI API key is required (set RRECALL_OPENAI_API_KEY or config)")
        self._client = OpenAI(api_key=config.api_key)
        self._model_id = config.model
        self._pricing = config.pricing
        self._dimension: int | None = None

    def _count_tokens(self, texts: list[str]) -> int:
        try:
            enc = tiktoken.encoding_for_model(self._model_id)
        except KeyError:
            enc = tiktoken.get_encoding("cl100k_base")
        return sum(len(enc.encode(t)) for t in texts)

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        resp = self._client.embeddings.create(input=texts, model=self._model_id)
        return [item.embedding for item in resp.data]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        total_tokens = self._count_tokens(texts)
        results: list[list[float]] = []

        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i : i + _BATCH_SIZE]
            results.extend(self._embed_batch(batch))

        price_per_1k = self._pricing.get(self._model_id, 0.0)
        record(
            model=self._model_id,
            tokens=total_tokens,
            requests=len(range(0, len(texts), _BATCH_SIZE)),
            cost=total_tokens / 1000 * price_per_1k,
        )

        if self._dimension is None and results:
            self._dimension = len(results[0])

        return results

    def embed_query(self, query: str) -> list[float]:
        vecs = self.embed_texts([query])
        return vecs[0]

    @property
    def dimension(self) -> int:
        if self._dimension is not None:
            return self._dimension
        # Must make one API call to discover dimension
        vecs = self._embed_batch(["dimension probe"])
        self._dimension = len(vecs[0])
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model_id
