"""Central configuration for rrecall — loads from TOML, validates with Pydantic."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Config directory & paths
# ---------------------------------------------------------------------------

def get_config_dir() -> Path:
    """Return ~/.rrecall, creating it if needed."""
    path = Path(os.environ.get("RRECALL_CONFIG_DIR", "~/.rrecall")).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_config_path() -> Path:
    """Return the config file path (env override or default)."""
    if env := os.environ.get("RRECALL_CONFIG"):
        return Path(env).expanduser()
    return get_config_dir() / "config.toml"


# ---------------------------------------------------------------------------
# Pydantic models — one per TOML section
# ---------------------------------------------------------------------------

class GeneralConfig(BaseModel):
    obsidian_vault: str = "~/Obsidian/MyVault"
    session_subfolder: str = "Claude Sessions"
    log_level: str = "info"

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        allowed = {"debug", "info", "warning", "error"}
        if v.lower() not in allowed:
            raise ValueError(f"log_level must be one of {allowed}, got {v!r}")
        return v.lower()

    @property
    def vault_path(self) -> Path:
        return Path(self.obsidian_vault).expanduser()

    @property
    def session_dir(self) -> Path:
        return self.vault_path / self.session_subfolder


class LocalEmbeddingConfig(BaseModel):
    model: str = "BAAI/bge-small-en-v1.5"
    use_gpu: bool = True
    use_server: bool = False
    server_url: str = "http://localhost:9876"


class OpenAIEmbeddingConfig(BaseModel):
    api_key: str = ""
    model: str = "text-embedding-3-small"
    pricing: dict[str, float] = Field(default_factory=lambda: {
        "text-embedding-3-small": 0.00002,
        "text-embedding-3-large": 0.00013,
    })


class EmbeddingConfig(BaseModel):
    provider: str = "local"
    local: LocalEmbeddingConfig = Field(default_factory=LocalEmbeddingConfig)
    openai: OpenAIEmbeddingConfig = Field(default_factory=OpenAIEmbeddingConfig)

    @field_validator("provider")
    @classmethod
    def _validate_provider(cls, v: str) -> str:
        allowed = {"local", "openai"}
        if v not in allowed:
            raise ValueError(f"embedding.provider must be one of {allowed}, got {v!r}")
        return v


class HooksFilteringConfig(BaseModel):
    enabled: bool = True
    min_messages: int = 3
    min_duration_seconds: int = 30
    use_llm_filter: bool = False


class HooksSummaryConfig(BaseModel):
    enabled: bool = True
    strategy: str = "transcript"

    @field_validator("strategy")
    @classmethod
    def _validate_strategy(cls, v: str) -> str:
        allowed = {"transcript", "claude", "both"}
        if v not in allowed:
            raise ValueError(f"hooks.summary.strategy must be one of {allowed}, got {v!r}")
        return v


class HooksConfig(BaseModel):
    enabled: bool = True
    filtering: HooksFilteringConfig = Field(default_factory=HooksFilteringConfig)
    summary: HooksSummaryConfig = Field(default_factory=HooksSummaryConfig)


class NotesConfig(BaseModel):
    include_patterns: list[str] = Field(default_factory=lambda: ["*.md"])
    exclude_patterns: list[str] = Field(default_factory=lambda: [
        "*.excalidraw.md", ".obsidian/*", ".trash/*",
    ])
    chunk_max_tokens: int = 512
    chunk_overlap_tokens: int = 50


class RepoAllConfig(BaseModel):
    paths: list[str] = Field(default_factory=lambda: ["~/projects", "~/work"])
    scan_depth: int = 2


class RepoGroupConfig(BaseModel):
    paths: list[str] = Field(default_factory=list)


class CodeReposConfig(BaseModel):
    all: RepoAllConfig = Field(default_factory=RepoAllConfig)
    groups: dict[str, RepoGroupConfig] = Field(default_factory=dict)


class CodeConfig(BaseModel):
    chunk_max_chars: int = 1500
    chunk_min_chars: int = 100
    chunk_overlap_lines: int = 3
    repos: CodeReposConfig = Field(default_factory=CodeReposConfig)


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------

class RrecallConfig(BaseModel):
    general: GeneralConfig = Field(default_factory=GeneralConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    hooks: HooksConfig = Field(default_factory=HooksConfig)
    notes: NotesConfig = Field(default_factory=NotesConfig)
    code: CodeConfig = Field(default_factory=CodeConfig)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge override into base (override wins on conflicts)."""
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """Apply RRECALL_* environment variable overrides."""
    if api_key := os.environ.get("RRECALL_OPENAI_API_KEY"):
        data.setdefault("embedding", {}).setdefault("openai", {})["api_key"] = api_key
    if vault := os.environ.get("RRECALL_OBSIDIAN_VAULT"):
        data.setdefault("general", {})["obsidian_vault"] = vault
    if log_level := os.environ.get("RRECALL_LOG_LEVEL"):
        data.setdefault("general", {})["log_level"] = log_level
    return data


def load_config(path: Path | None = None) -> RrecallConfig:
    """Load and validate config from TOML file, with env var overrides."""
    config_path = path or get_config_path()

    data: dict[str, Any] = {}
    if config_path.exists():
        with open(config_path, "rb") as f:
            data = tomllib.load(f)

    data = _apply_env_overrides(data)
    return RrecallConfig.model_validate(data)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_config: RrecallConfig | None = None


def get_config(*, reload: bool = False) -> RrecallConfig:
    """Return the global config singleton. Loads on first call."""
    global _config
    if _config is None or reload:
        _config = load_config()
    return _config
