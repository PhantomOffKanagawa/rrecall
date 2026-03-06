"""Tests for rrecall.embedding.local_onnx."""

from __future__ import annotations

import pytest

from rrecall.config import LocalEmbeddingConfig
from rrecall.embedding.local_onnx import LocalOnnxProvider


@pytest.fixture(scope="module")
def provider():
    """Module-scoped provider so the model loads once for all tests."""
    config = LocalEmbeddingConfig(model="BAAI/bge-small-en-v1.5", use_gpu=False)
    return LocalOnnxProvider(config)


def test_lazy_loading():
    config = LocalEmbeddingConfig(model="BAAI/bge-small-en-v1.5", use_gpu=False)
    p = LocalOnnxProvider(config)
    assert p._model is None  # not loaded yet


def test_embed_texts(provider):
    vecs = provider.embed_texts(["hello world", "foo bar"])
    assert len(vecs) == 2
    assert len(vecs[0]) == 384


def test_embed_texts_empty(provider):
    assert provider.embed_texts([]) == []


def test_embed_query(provider):
    vec = provider.embed_query("what is python?")
    assert len(vec) == 384


def test_dimension(provider):
    assert provider.dimension == 384


def test_model_name(provider):
    assert provider.model_name == "BAAI/bge-small-en-v1.5"
