"""Tests for rrecall.config — TOML loading, validation, env overrides, singleton."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from rrecall.config import (
    RrecallConfig,
    GeneralConfig,
    EmbeddingConfig,
    HooksConfig,
    HooksSummaryConfig,
    NotesConfig,
    CodeConfig,
    _deep_merge,
    _apply_env_overrides,
    load_config,
    get_config,
    get_config_dir,
    get_config_path,
)


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_full_defaults(self):
        cfg = RrecallConfig()
        assert cfg.general.obsidian_vault == "~/Obsidian/MyVault"
        assert cfg.general.session_subfolder == "Claude Sessions"
        assert cfg.general.log_level == "info"
        assert cfg.embedding.provider == "local"
        assert cfg.embedding.local.model == "BAAI/bge-small-en-v1.5"
        assert cfg.embedding.local.use_gpu is True
        assert cfg.hooks.enabled is True
        assert cfg.notes.chunk_max_tokens == 512
        assert cfg.code.chunk_max_chars == 1500

    def test_general_vault_path_expands_tilde(self):
        g = GeneralConfig(obsidian_vault="~/MyVault")
        assert g.vault_path == Path("~/MyVault").expanduser()
        assert g.vault_path.is_absolute()

    def test_general_session_dir(self):
        g = GeneralConfig(obsidian_vault="/tmp/vault", session_subfolder="Sessions")
        assert g.session_dir == Path("/tmp/vault/Sessions")

    def test_notes_default_patterns(self):
        n = NotesConfig()
        assert "*.md" in n.include_patterns
        assert ".obsidian/*" in n.exclude_patterns

    def test_code_default_repos(self):
        c = CodeConfig()
        assert c.repos.all.scan_depth == 2
        assert isinstance(c.repos.groups, dict)
        assert len(c.repos.groups) == 0

    def test_hooks_auto_index_default_true(self):
        cfg = RrecallConfig()
        assert cfg.hooks.auto_index is True

    def test_openai_default_pricing(self):
        cfg = RrecallConfig()
        pricing = cfg.embedding.openai.pricing
        assert "text-embedding-3-small" in pricing
        assert "text-embedding-3-large" in pricing


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_log_level_rejected(self):
        with pytest.raises(ValidationError, match="log_level"):
            GeneralConfig(log_level="verbose")

    def test_log_level_normalized_to_lowercase(self):
        g = GeneralConfig(log_level="DEBUG")
        assert g.log_level == "debug"

    def test_invalid_embedding_provider_rejected(self):
        with pytest.raises(ValidationError, match="provider"):
            EmbeddingConfig(provider="anthropic")

    def test_invalid_summary_strategy_rejected(self):
        with pytest.raises(ValidationError, match="strategy"):
            HooksSummaryConfig(strategy="magic")

    def test_valid_summary_strategies_accepted(self):
        for s in ("transcript", "claude", "both"):
            m = HooksSummaryConfig(strategy=s)
            assert m.strategy == s

    def test_valid_providers_accepted(self):
        for p in ("local", "openai"):
            e = EmbeddingConfig(provider=p)
            assert e.provider == p


# ---------------------------------------------------------------------------
# TOML loading
# ---------------------------------------------------------------------------


class TestTOMLLoading:
    def test_load_from_example_file(self):
        cfg = load_config(Path("config/rrecall.example.toml"))
        assert cfg.general.obsidian_vault == "~/Documents/RRecall-Test"
        assert cfg.embedding.provider == "local"
        assert cfg.notes.chunk_max_tokens == 512
        assert cfg.hooks.filtering.min_messages == 3
        assert cfg.hooks.auto_index is True

    def test_load_missing_file_returns_defaults(self, tmp_path: Path):
        cfg = load_config(tmp_path / "nonexistent.toml")
        expected = RrecallConfig()
        assert cfg.general.obsidian_vault == expected.general.obsidian_vault
        assert cfg.embedding.provider == expected.embedding.provider

    def test_load_partial_toml(self, tmp_path: Path):
        toml_file = tmp_path / "partial.toml"
        toml_file.write_text('[general]\nobsidian_vault = "/custom/vault"\n')
        cfg = load_config(toml_file)
        assert cfg.general.obsidian_vault == "/custom/vault"
        # Everything else should be defaults
        assert cfg.embedding.provider == "local"
        assert cfg.hooks.enabled is True

    def test_load_auto_index_disabled(self, tmp_path: Path):
        toml_file = tmp_path / "no_autoindex.toml"
        toml_file.write_text('[hooks]\nauto_index = false\n')
        cfg = load_config(toml_file)
        assert cfg.hooks.auto_index is False

    def test_load_invalid_toml_raises(self, tmp_path: Path):
        bad_file = tmp_path / "bad.toml"
        bad_file.write_text("this is not valid [[ toml {{")
        with pytest.raises(Exception):
            load_config(bad_file)


# ---------------------------------------------------------------------------
# Environment variable overrides
# ---------------------------------------------------------------------------


class TestEnvOverrides:
    def test_openai_api_key_override(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("RRECALL_OPENAI_API_KEY", "sk-test-123")
        data: dict = {}
        result = _apply_env_overrides(data)
        assert result["embedding"]["openai"]["api_key"] == "sk-test-123"

    def test_vault_override(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("RRECALL_OBSIDIAN_VAULT", "/env/vault")
        data: dict = {}
        result = _apply_env_overrides(data)
        assert result["general"]["obsidian_vault"] == "/env/vault"

    def test_log_level_override(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("RRECALL_LOG_LEVEL", "debug")
        data: dict = {}
        result = _apply_env_overrides(data)
        assert result["general"]["log_level"] == "debug"

    def test_env_overrides_win_over_toml(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            '[general]\nobsidian_vault = "/toml/vault"\nlog_level = "info"\n'
        )
        monkeypatch.setenv("RRECALL_OBSIDIAN_VAULT", "/env/vault")
        cfg = load_config(toml_file)
        assert cfg.general.obsidian_vault == "/env/vault"
        # Non-overridden field stays from TOML
        assert cfg.general.log_level == "info"

    def test_no_env_vars_leaves_data_unchanged(self):
        data = {"general": {"obsidian_vault": "/original"}}
        result = _apply_env_overrides(data)
        assert result["general"]["obsidian_vault"] == "/original"
        assert "embedding" not in result


# ---------------------------------------------------------------------------
# Deep merge
# ---------------------------------------------------------------------------


class TestDeepMerge:
    def test_flat_merge(self):
        assert _deep_merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}

    def test_override_scalar(self):
        assert _deep_merge({"a": 1}, {"a": 2}) == {"a": 2}

    def test_nested_merge(self):
        base = {"embedding": {"provider": "local", "local": {"use_gpu": True}}}
        override = {"embedding": {"local": {"use_gpu": False, "model": "new"}}}
        result = _deep_merge(base, override)
        assert result["embedding"]["provider"] == "local"  # kept from base
        assert result["embedding"]["local"]["use_gpu"] is False  # overridden
        assert result["embedding"]["local"]["model"] == "new"  # added

    def test_base_unchanged(self):
        base = {"a": {"b": 1}}
        override = {"a": {"b": 2}}
        _deep_merge(base, override)
        assert base["a"]["b"] == 1  # original not mutated


# ---------------------------------------------------------------------------
# Config path helpers
# ---------------------------------------------------------------------------


class TestConfigPaths:
    def test_get_config_dir_default(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("RRECALL_CONFIG_DIR", raising=False)
        d = get_config_dir()
        assert d == Path("~/.rrecall").expanduser()

    def test_get_config_dir_from_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        custom = tmp_path / "custom_rrecall"
        monkeypatch.setenv("RRECALL_CONFIG_DIR", str(custom))
        d = get_config_dir()
        assert d == custom
        assert d.is_dir()

    def test_get_config_path_default(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("RRECALL_CONFIG", raising=False)
        p = get_config_path()
        assert p.name == "config.toml"

    def test_get_config_path_from_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        custom = tmp_path / "my_config.toml"
        monkeypatch.setenv("RRECALL_CONFIG", str(custom))
        assert get_config_path() == custom


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_get_config_returns_same_object(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("RRECALL_CONFIG", str(tmp_path / "nope.toml"))
        c1 = get_config()
        c2 = get_config()
        assert c1 is c2

    def test_get_config_reload(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text('[general]\nlog_level = "info"\n')
        monkeypatch.setenv("RRECALL_CONFIG", str(toml_file))

        c1 = get_config()
        assert c1.general.log_level == "info"

        toml_file.write_text('[general]\nlog_level = "debug"\n')
        c2 = get_config(reload=True)
        assert c2.general.log_level == "debug"
        assert c1 is not c2
