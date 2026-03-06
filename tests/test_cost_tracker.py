"""Tests for rrecall.embedding.cost_tracker."""

from __future__ import annotations

import json

from rrecall.embedding import cost_tracker


def test_record_and_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(cost_tracker, "_ledger_path", lambda: tmp_path / "ledger.jsonl")

    cost_tracker.record(model="text-embedding-3-small", tokens=500, requests=1, cost=0.01)
    cost_tracker.record(model="text-embedding-3-small", tokens=300, requests=1, cost=0.006)

    s = cost_tracker.get_summary("month")
    assert s.entries == 2
    assert s.total_tokens == 800
    assert s.total_requests == 2
    assert abs(s.total_cost - 0.016) < 1e-9


def test_summary_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(cost_tracker, "_ledger_path", lambda: tmp_path / "ledger.jsonl")
    s = cost_tracker.get_summary("day")
    assert s.entries == 0
    assert s.total_cost == 0.0


def test_summary_ignores_malformed_lines(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setattr(cost_tracker, "_ledger_path", lambda: ledger)

    cost_tracker.record(model="m", tokens=100, requests=1, cost=0.001)
    # Append a bad line
    with open(ledger, "a") as f:
        f.write("not json\n")

    s = cost_tracker.get_summary("month")
    assert s.entries == 1
