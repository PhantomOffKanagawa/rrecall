"""Tests for rrecall.embedding.base."""

from __future__ import annotations

import pytest

from rrecall.embedding.base import EmbeddingProvider, get_provider


class DummyProvider(EmbeddingProvider):
    """Concrete implementation for testing the ABC."""

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 3 for _ in texts]

    def embed_query(self, query: str) -> list[float]:
        return [0.0] * 3

    @property
    def dimension(self) -> int:
        return 3

    @property
    def model_name(self) -> str:
        return "dummy"


def test_abc_can_be_implemented():
    p = DummyProvider()
    assert p.dimension == 3
    assert p.model_name == "dummy"
    vecs = p.embed_texts(["a", "b"])
    assert len(vecs) == 2
    assert len(vecs[0]) == 3


def test_abc_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        EmbeddingProvider()  # type: ignore[abstract]


def test_get_provider_unknown_raises():
    class FakeConfig:
        class embedding:
            provider = "nonexistent"

    with pytest.raises(ValueError, match="Unknown embedding provider"):
        get_provider(FakeConfig())
