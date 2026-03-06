"""Tests for rrecall.embedding.openai_provider (mocked, no real API calls)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from rrecall.config import OpenAIEmbeddingConfig
from rrecall.embedding import cost_tracker


def test_missing_api_key_raises():
    from rrecall.embedding.openai_provider import OpenAIProvider

    with pytest.raises(ValueError, match="API key is required"):
        OpenAIProvider(OpenAIEmbeddingConfig(api_key=""))


def test_embed_texts_calls_api_and_records_cost(tmp_path, monkeypatch):
    monkeypatch.setattr(cost_tracker, "_ledger_path", lambda: tmp_path / "ledger.jsonl")

    # Build a mock OpenAI client
    mock_embedding = MagicMock()
    mock_embedding.embedding = [0.1, 0.2, 0.3]
    mock_response = MagicMock()
    mock_response.data = [mock_embedding, mock_embedding]

    with patch("openai.OpenAI") as MockOpenAI:
        MockOpenAI.return_value.embeddings.create.return_value = mock_response

        from rrecall.embedding.openai_provider import OpenAIProvider

        config = OpenAIEmbeddingConfig(api_key="test-key", model="text-embedding-3-small")
        provider = OpenAIProvider(config)

        vecs = provider.embed_texts(["hello", "world"])
        assert len(vecs) == 2
        assert vecs[0] == [0.1, 0.2, 0.3]

    # Verify cost was recorded
    s = cost_tracker.get_summary("month")
    assert s.entries == 1
    assert s.total_tokens > 0


def test_embed_query_delegates_to_embed_texts(tmp_path, monkeypatch):
    monkeypatch.setattr(cost_tracker, "_ledger_path", lambda: tmp_path / "ledger.jsonl")

    mock_embedding = MagicMock()
    mock_embedding.embedding = [0.5, 0.6]
    mock_response = MagicMock()
    mock_response.data = [mock_embedding]

    with patch("openai.OpenAI") as MockOpenAI:
        MockOpenAI.return_value.embeddings.create.return_value = mock_response

        from rrecall.embedding.openai_provider import OpenAIProvider

        provider = OpenAIProvider(OpenAIEmbeddingConfig(api_key="test-key"))
        vec = provider.embed_query("search query")
        assert vec == [0.5, 0.6]
