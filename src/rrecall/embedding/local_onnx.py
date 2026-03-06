"""Local ONNX embedding provider using FastEmbed."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rrecall.embedding.base import EmbeddingProvider
from rrecall.utils.logging import get_logger

if TYPE_CHECKING:
    from fastembed import TextEmbedding

    from rrecall.config import LocalEmbeddingConfig

logger = get_logger("embedding.local_onnx")


class LocalOnnxProvider(EmbeddingProvider):
    """Wraps FastEmbed's TextEmbedding for local CPU/GPU inference."""

    def __init__(self, config: LocalEmbeddingConfig) -> None:
        self._model_id = config.model
        self._use_gpu = config.use_gpu
        self._model: TextEmbedding | None = None
        self._dimension: int | None = None

    def _get_model(self) -> TextEmbedding:
        """Lazy-load the model on first use."""
        if self._model is not None:
            return self._model

        from fastembed import TextEmbedding

        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if self._use_gpu else ["CPUExecutionProvider"]
        logger.info("Loading embedding model %s (providers=%s)", self._model_id, providers)

        self._model = TextEmbedding(
            model_name=self._model_id,
            providers=providers,
        )
        return self._model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._get_model()
        embeddings = model.embed(texts)
        return [vec.tolist() for vec in embeddings]

    def embed_query(self, query: str) -> list[float]:
        model = self._get_model()
        results = list(model.query_embed(query))
        return results[0].tolist()

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            model = self._get_model()
            sample = list(model.embed(["dimension probe"]))[0]
            self._dimension = len(sample)
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model_id
