"""Append-only cost ledger for API embedding calls."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from rrecall.config import get_config_dir
from rrecall.utils.logging import get_logger

logger = get_logger("embedding.cost_tracker")


def _ledger_path() -> Path:
    return get_config_dir() / "cost_ledger.jsonl"


def record(model: str, tokens: int, requests: int, cost: float) -> None:
    """Append a cost entry to the ledger."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "tokens": tokens,
        "requests": requests,
        "cost": cost,
    }
    path = _ledger_path()
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


@dataclass
class CostSummary:
    period: str
    total_tokens: int
    total_requests: int
    total_cost: float
    entries: int


def get_summary(period: str = "month") -> CostSummary:
    """Read the ledger and aggregate costs for a period."""
    now = datetime.now(timezone.utc)
    if period == "day":
        cutoff = now - timedelta(days=1)
    elif period == "week":
        cutoff = now - timedelta(weeks=1)
    elif period == "month":
        cutoff = now - timedelta(days=30)
    else:
        raise ValueError(f"Unknown period: {period!r}. Use 'day', 'week', or 'month'.")

    path = _ledger_path()
    total_tokens = 0
    total_requests = 0
    total_cost = 0.0
    entries = 0

    if not path.exists():
        return CostSummary(period=period, total_tokens=0, total_requests=0, total_cost=0.0, entries=0)

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = datetime.fromisoformat(entry["ts"])
        if ts >= cutoff:
            total_tokens += entry.get("tokens", 0)
            total_requests += entry.get("requests", 0)
            total_cost += entry.get("cost", 0.0)
            entries += 1

    return CostSummary(
        period=period,
        total_tokens=total_tokens,
        total_requests=total_requests,
        total_cost=total_cost,
        entries=entries,
    )
