"""Abstract base class for embedding providers."""

from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """Interface that all embedding providers must implement."""

    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of document texts. Returns one vector per text."""
        ...

    @abstractmethod
    def embed_query(self, query: str) -> list[float]:
        """Embed a single query string for search."""
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Dimensionality of the embedding vectors."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Name/identifier of the underlying model."""
        ...


def get_provider(config) -> EmbeddingProvider:
    """Factory: return the configured embedding provider.

    Parameters
    ----------
    config : rrecall.config.RrecallConfig
        The top-level rrecall configuration object.
    """
    provider = config.embedding.provider

    if provider == "local":
        from rrecall.embedding.local_onnx import LocalOnnxProvider

        return LocalOnnxProvider(config.embedding.local)

    if provider == "openai":
        from rrecall.embedding.openai_provider import OpenAIProvider

        return OpenAIProvider(config.embedding.openai)

    raise ValueError(f"Unknown embedding provider: {provider!r}")
