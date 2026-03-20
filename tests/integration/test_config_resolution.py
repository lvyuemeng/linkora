"""
test_config_resolution.py — Unit tests for AppConfig, WorkspacePaths, and ConfigLoader.

Covers:
  - AppConfig field defaults and immutability
  - API key resolution (config value → env var priority chain)
  - WorkspacePaths computed properties
  - resolve_local_source_paths(config_dir) path resolution
  - ConfigLoader file discovery and conflict detection
  - YAML round-trip via _build_config / ConfigLoader.load()
  - Env-variable interpolation in YAML values
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from linkora.config import (
    AppConfig,
    ConfigLoader,
    IndexConfig,
    IngestConfig,
    LLMConfig,
    LocalSourceConfig,
    LogConfig,
    SourcesConfig,
    TopicsConfig,
    ZoteroSourceConfig,
    _build_config,
    _resolve_env,
    reset_config,
)
from linkora.workspace import WorkspacePaths


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_config(**overrides) -> AppConfig:
    """
    Construct an AppConfig with built-in defaults, selectively overriding
    top-level sub-config objects.

    Accepted keys: sources, index, llm, ingest, topics, log.
    """
    defaults: dict = {
        "sources": SourcesConfig(),
        "index": IndexConfig(),
        "llm": LLMConfig(),
        "ingest": IngestConfig(),
        "topics": TopicsConfig(),
        "log": LogConfig(),
    }
    defaults.update(overrides)
    return AppConfig(**defaults)


def make_paths(name: str = "default", root: Path | None = None) -> WorkspacePaths:
    return WorkspacePaths(data_root=root or Path("/data/linkora"), name=name)


# ---------------------------------------------------------------------------
# AppConfig defaults
# ---------------------------------------------------------------------------


class TestAppConfigDefaults:
    def test_index_defaults(self):
        cfg = AppConfig()
        assert cfg.index.top_k == 20
        assert cfg.index.chunk_size == 800
        assert cfg.index.chunk_overlap == 150
        assert cfg.index.embed_model == "Qwen/Qwen3-Embedding-0.6B"

    def test_llm_defaults(self):
        cfg = AppConfig()
        assert cfg.llm.model == "deepseek-chat"
        assert cfg.llm.base_url == "https://api.deepseek.com"
        assert cfg.llm.api_key == ""
        assert cfg.llm.timeout == 30

    def test_sources_defaults(self):
        cfg = AppConfig()
        assert cfg.sources.local.enabled is True
        assert cfg.sources.local.paths == []
        assert cfg.sources.arxiv.enabled is False
        assert cfg.sources.zotero.enabled is False

    def test_log_defaults(self):
        cfg = AppConfig()
        assert cfg.log.level == "INFO"
        assert cfg.log.file == "linkora.log"
        assert cfg.log.metrics_db == "metrics.db"
        assert cfg.log.max_bytes == 10_000_000

    def test_ingest_defaults(self):
        cfg = AppConfig()
        assert cfg.ingest.extractor == "robust"
        assert cfg.ingest.mineru_endpoint == "http://localhost:8000"

    def test_topics_defaults(self):
        cfg = AppConfig()
        assert cfg.topics.min_topic_size == 5
        assert cfg.topics.nr_topics == 0

    def test_frozen(self):
        """AppConfig and sub-configs must be immutable."""
        cfg = AppConfig()
        with pytest.raises(Exception):  # ValidationError or TypeError
            cfg.index = IndexConfig(top_k=99)
        with pytest.raises(Exception):
            cfg.llm.model = "gpt-4o"


# ---------------------------------------------------------------------------
# API key resolution — priority chain
# ---------------------------------------------------------------------------


class TestApiKeyResolution:
    """
    Resolution order for LLM key:
      llm.api_key in config  >  LINKORA_LLM_API_KEY  >  DEEPSEEK_API_KEY  >  OPENAI_API_KEY

    Env vars must be cleaned up after each test so they don't bleed through.
    """

    def _clean(self, *names: str) -> None:
        for n in names:
            os.environ.pop(n, None)

    def test_config_value_takes_priority(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
        cfg = make_config(llm=LLMConfig(api_key="config-key"))
        assert cfg.resolve_llm_api_key() == "config-key"

    def test_linkora_env_var(self, monkeypatch):
        monkeypatch.setenv("LINKORA_LLM_API_KEY", "linkora-key")
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        cfg = make_config()
        assert cfg.resolve_llm_api_key() == "linkora-key"

    def test_deepseek_env_var(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
        monkeypatch.delenv("LINKORA_LLM_API_KEY", raising=False)
        cfg = make_config()
        assert cfg.resolve_llm_api_key() == "deepseek-key"

    def test_openai_env_var_fallback(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("LINKORA_LLM_API_KEY", raising=False)
        cfg = make_config()
        assert cfg.resolve_llm_api_key() == "openai-key"

    def test_no_key_returns_empty(self, monkeypatch):
        for k in ("LINKORA_LLM_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        cfg = make_config()
        assert cfg.resolve_llm_api_key() == ""

    def test_zotero_key_from_config(self):
        cfg = make_config(
            sources=SourcesConfig(zotero=ZoteroSourceConfig(api_key="zt-config"))
        )
        assert cfg.resolve_zotero_api_key() == "zt-config"

    def test_zotero_key_from_env(self, monkeypatch):
        monkeypatch.setenv("ZOTERO_API_KEY", "zt-env")
        cfg = make_config()
        assert cfg.resolve_zotero_api_key() == "zt-env"

    def test_zotero_library_id_from_config(self):
        cfg = make_config(
            sources=SourcesConfig(zotero=ZoteroSourceConfig(library_id="123456"))
        )
        assert cfg.resolve_zotero_library_id() == "123456"

    def test_mineru_key_from_env(self, monkeypatch):
        monkeypatch.setenv("MINERU_API_KEY", "mineru-env")
        cfg = make_config()
        assert cfg.resolve_mineru_api_key() == "mineru-env"


# ---------------------------------------------------------------------------
# resolve_local_source_paths
# ---------------------------------------------------------------------------


class TestResolveLocalSourcePaths:
    """
    resolve_local_source_paths(config_dir) returns only the entries in
    sources.local.paths — resolved relative to config_dir.
    It does NOT return the workspace papers_dir (that is a WorkspacePaths concern).
    """

    def test_empty_paths_list_returns_empty(self, tmp_path):
        cfg = make_config()  # paths=[] by default
        result = cfg.resolve_local_source_paths(tmp_path)
        assert result == []

    def test_disabled_source_returns_empty(self, tmp_path):
        cfg = make_config(
            sources=SourcesConfig(
                local=LocalSourceConfig(enabled=False, paths=["/some/dir"])
            )
        )
        assert cfg.resolve_local_source_paths(tmp_path) == []

    def test_absolute_path_used_as_is(self, tmp_path):
        abs_path = tmp_path / "shared_papers"
        cfg = make_config(
            sources=SourcesConfig(local=LocalSourceConfig(paths=[str(abs_path)]))
        )
        result = cfg.resolve_local_source_paths(tmp_path)
        assert result == [abs_path]

    def test_relative_path_resolved_from_config_dir(self, tmp_path):
        cfg_dir = tmp_path / "config_home"
        cfg_dir.mkdir()

        cfg = make_config(
            sources=SourcesConfig(local=LocalSourceConfig(paths=["extra_papers"]))
        )
        result = cfg.resolve_local_source_paths(cfg_dir)
        assert result == [(cfg_dir / "extra_papers").resolve()]

    def test_relative_path_uses_config_dir_not_cwd(self, tmp_path):
        """Relative resolution must be anchored to config_dir, never cwd."""
        cfg_dir = tmp_path / "cfg"
        cfg_dir.mkdir()
        other_dir = tmp_path / "other"
        other_dir.mkdir()

        cfg = make_config(
            sources=SourcesConfig(local=LocalSourceConfig(paths=["papers_rel"]))
        )
        result_from_cfg = cfg.resolve_local_source_paths(cfg_dir)
        result_from_other = cfg.resolve_local_source_paths(other_dir)

        # Same config, different config_dir → different results.
        assert result_from_cfg != result_from_other
        assert result_from_cfg == [(cfg_dir / "papers_rel").resolve()]
        assert result_from_other == [(other_dir / "papers_rel").resolve()]

    def test_multiple_paths(self, tmp_path):
        abs_a = tmp_path / "abs_a"
        cfg = make_config(
            sources=SourcesConfig(local=LocalSourceConfig(paths=[str(abs_a), "rel_b"]))
        )
        result = cfg.resolve_local_source_paths(tmp_path)
        assert result == [abs_a, (tmp_path / "rel_b").resolve()]

    def test_empty_string_entries_are_skipped(self, tmp_path):
        cfg = make_config(
            sources=SourcesConfig(local=LocalSourceConfig(paths=["", "real_dir", ""]))
        )
        result = cfg.resolve_local_source_paths(tmp_path)
        assert len(result) == 1
        assert result[0] == (tmp_path / "real_dir").resolve()

    def test_all_results_are_absolute(self, tmp_path):
        cfg = make_config(
            sources=SourcesConfig(local=LocalSourceConfig(paths=["a", "b/c"]))
        )
        result = cfg.resolve_local_source_paths(tmp_path)
        assert all(p.is_absolute() for p in result)


# ---------------------------------------------------------------------------
# WorkspacePaths — computed properties
# ---------------------------------------------------------------------------


class TestWorkspacePaths:
    """
    WorkspacePaths derives every path from (data_root, name).
    No filesystem access — pure computation tests.
    """

    def test_workspace_dir(self):
        p = make_paths("default", Path("/data"))
        assert p.workspace_dir == Path("/data/workspace/default")

    def test_papers_dir(self):
        p = make_paths("ml", Path("/data"))
        assert p.papers_dir == Path("/data/workspace/ml/papers")

    def test_index_db(self):
        p = make_paths("ml", Path("/data"))
        assert p.index_db == Path("/data/workspace/ml/index.db")

    def test_vectors_file(self):
        p = make_paths("ml", Path("/data"))
        assert p.vectors_file == Path("/data/workspace/ml/vectors.faiss")

    def test_metadata_file(self):
        p = make_paths("ml", Path("/data"))
        assert p.metadata_file == Path("/data/workspace/ml/workspace.json")

    def test_log_file(self):
        p = make_paths("default", Path("/data"))
        assert p.log_file("linkora.log") == Path(
            "/data/workspace/default/logs/linkora.log"
        )

    def test_metrics_db(self):
        p = make_paths("default", Path("/data"))
        assert p.metrics_db("metrics.db") == Path("/data/workspace/default/metrics.db")

    def test_different_names_produce_different_dirs(self):
        root = Path("/data")
        assert (
            make_paths("ml", root).workspace_dir
            != make_paths("physics", root).workspace_dir
        )

    def test_different_roots_produce_different_paths(self):
        assert (
            make_paths("default", Path("/root_a")).papers_dir
            != make_paths("default", Path("/root_b")).papers_dir
        )

    def test_ensure_dirs_creates_structure(self, tmp_path):
        p = WorkspacePaths(data_root=tmp_path, name="test_ws")
        p.ensure_dirs()
        assert p.papers_dir.exists()
        assert (p.workspace_dir / "logs").exists()

    def test_paths_are_frozen(self):
        p = make_paths()
        with pytest.raises(Exception):
            p.name = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ConfigLoader — file discovery and conflict detection
# ---------------------------------------------------------------------------


class TestConfigLoader:
    """
    ConfigLoader must discover candidate files, pick the highest-priority
    one, and report conflicts without merging.
    """

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Ensure the singleton is reset before/after each test."""
        reset_config()
        yield
        reset_config()

    def test_no_config_files_returns_defaults(self, tmp_path, monkeypatch):
        """When no config files exist, built-in defaults are returned."""
        monkeypatch.setattr(
            "linkora.config._CANDIDATE_PATHS",
            (tmp_path / "xdg.yml", tmp_path / "home.yml"),
        )
        cfg, path = ConfigLoader().load()
        assert path is None
        assert cfg.index.top_k == 20  # built-in default

    def test_single_file_loaded(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config.yml"
        config_file.write_text("index:\n  top_k: 42\n", encoding="utf-8")

        monkeypatch.setattr(
            "linkora.config._CANDIDATE_PATHS",
            (tmp_path / "xdg.yml", config_file),  # only config_file exists
        )
        cfg, path = ConfigLoader().load()
        assert path == config_file
        assert cfg.index.top_k == 42

    def test_higher_priority_file_wins(self, tmp_path, monkeypatch):
        """The last file in _CANDIDATE_PATHS has highest priority."""
        low = tmp_path / "low.yml"
        high = tmp_path / "high.yml"
        low.write_text("index:\n  top_k: 10\n", encoding="utf-8")
        high.write_text("index:\n  top_k: 99\n", encoding="utf-8")

        monkeypatch.setattr(
            "linkora.config._CANDIDATE_PATHS",
            (low, high),  # high is last → highest priority
        )
        cfg, path = ConfigLoader().load()
        assert path == high
        assert cfg.index.top_k == 99

    def test_lower_priority_file_completely_ignored(self, tmp_path, monkeypatch):
        """High-priority file wins entirely — no merging with lower-priority file."""
        low = tmp_path / "low.yml"
        high = tmp_path / "high.yml"
        # Low-priority file sets llm.model; high-priority file does not.
        low.write_text("llm:\n  model: from-low\n", encoding="utf-8")
        high.write_text("index:\n  top_k: 5\n", encoding="utf-8")

        monkeypatch.setattr(
            "linkora.config._CANDIDATE_PATHS",
            (low, high),
        )
        cfg, path = ConfigLoader().load()
        # high won — low's llm.model must NOT bleed through.
        assert path == high
        assert cfg.llm.model == "deepseek-chat"  # built-in default, not "from-low"

    def test_find_all_returns_existing_only(self, tmp_path, monkeypatch):
        existing = tmp_path / "exists.yml"
        existing.write_text("{}", encoding="utf-8")
        missing = tmp_path / "missing.yml"

        monkeypatch.setattr(
            "linkora.config._CANDIDATE_PATHS",
            (missing, existing),
        )
        found = ConfigLoader.find_all()
        assert found == [existing]

    def test_active_path_returns_highest_priority(self, tmp_path, monkeypatch):
        low = tmp_path / "low.yml"
        high = tmp_path / "high.yml"
        low.write_text("{}", encoding="utf-8")
        high.write_text("{}", encoding="utf-8")

        monkeypatch.setattr(
            "linkora.config._CANDIDATE_PATHS",
            (low, high),
        )
        assert ConfigLoader.active_path() == high

    def test_active_path_none_when_no_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "linkora.config._CANDIDATE_PATHS",
            (tmp_path / "a.yml", tmp_path / "b.yml"),
        )
        assert ConfigLoader.active_path() is None

    def test_default_write_path_is_highest_priority(self):
        """The default write target must always be the highest-priority candidate."""
        candidates = ConfigLoader.candidates()
        assert ConfigLoader.default_write_path() == candidates[-1]


# ---------------------------------------------------------------------------
# Environment variable interpolation in YAML
# ---------------------------------------------------------------------------


class TestEnvInterpolation:
    def test_simple_var(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "hello")
        from linkora.config import _expand_env

        assert _expand_env("${MY_KEY}") == "hello"

    def test_fallback_used_when_unset(self, monkeypatch):
        monkeypatch.delenv("MISSING_VAR", raising=False)
        from linkora.config import _expand_env

        assert _expand_env("${MISSING_VAR:-default_val}") == "default_val"

    def test_fallback_ignored_when_var_set(self, monkeypatch):
        monkeypatch.setenv("PRESENT_VAR", "real")
        from linkora.config import _expand_env

        assert _expand_env("${PRESENT_VAR:-ignored}") == "real"

    def test_resolve_env_recurses_into_dicts(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "sk-123")
        result = _resolve_env({"llm": {"api_key": "${API_KEY}"}})
        assert result == {"llm": {"api_key": "sk-123"}}

    def test_resolve_env_recurses_into_lists(self, monkeypatch):
        monkeypatch.setenv("DIR_A", "/papers")
        result = _resolve_env(["${DIR_A}", "static"])
        assert result == ["/papers", "static"]

    def test_non_strings_pass_through(self):
        assert _resolve_env(42) == 42
        assert _resolve_env(True) is True
        assert _resolve_env(None) is None


# ---------------------------------------------------------------------------
# _build_config — raw dict → AppConfig
# ---------------------------------------------------------------------------


class TestBuildConfig:
    def test_empty_dict_gives_defaults(self):
        cfg = _build_config({})
        assert cfg.index.top_k == 20
        assert cfg.llm.model == "deepseek-chat"

    def test_partial_overrides_applied(self):
        cfg = _build_config({"index": {"top_k": 50}})
        assert cfg.index.top_k == 50
        # Unspecified fields stay at default.
        assert cfg.index.chunk_size == 800

    def test_nested_sources(self):
        cfg = _build_config(
            {
                "sources": {
                    "local": {"enabled": False},
                    "arxiv": {"enabled": True},
                }
            }
        )
        assert cfg.sources.local.enabled is False
        assert cfg.sources.arxiv.enabled is True

    def test_logging_key_maps_to_log_field(self):
        """YAML uses 'logging:' key but AppConfig field is 'log'."""
        cfg = _build_config({"logging": {"level": "DEBUG"}})
        assert cfg.log.level == "DEBUG"

    def test_unknown_keys_raise(self):
        """Pydantic must reject unrecognised fields."""
        with pytest.raises(Exception):
            _build_config({"index": {"nonexistent_field": 999}})
