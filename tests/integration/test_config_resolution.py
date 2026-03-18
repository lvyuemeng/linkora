"""Integration test: Config resolution consistency.

Tests that:
1. Default values are applied correctly
2. Environment variables override defaults
3. Workspace resolution works
4. Path properties resolve correctly
"""

import os
from pathlib import Path
from linkora.config import (
    Config,
    WorkspaceConfig,
    LLMConfig,
    IndexConfig,
    SourcesConfig,
    IngestConfig,
    TopicsConfig,
    LogConfig,
)


def make_test_config(**overrides) -> Config:
    """Create a Config object with default values for testing."""
    workspace = WorkspaceConfig(name="default")
    workspace_store = {"default": WorkspaceConfig(name="default")}
    default_workspace = "default"
    sources = SourcesConfig()
    index = IndexConfig()
    llm = LLMConfig()
    ingest = IngestConfig()
    topics = TopicsConfig()
    log = LogConfig()
    root = Path.cwd()

    # Apply overrides
    if "workspace" in overrides:
        workspace = overrides["workspace"]
    if "workspace_store" in overrides:
        workspace_store = overrides["workspace_store"]
    if "default_workspace" in overrides:
        default_workspace = overrides["default_workspace"]
    if "sources" in overrides:
        sources = overrides["sources"]
    if "index" in overrides:
        index = overrides["index"]
    if "llm" in overrides:
        llm = overrides["llm"]
    if "ingest" in overrides:
        ingest = overrides["ingest"]
    if "topics" in overrides:
        topics = overrides["topics"]
    if "log" in overrides:
        log = overrides["log"]
    if "_root" in overrides:
        root = overrides["_root"]

    return Config(
        workspace=workspace,
        workspace_store=workspace_store,
        default_workspace=default_workspace,
        sources=sources,
        index=index,
        llm=llm,
        ingest=ingest,
        topics=topics,
        log=log,
        _root=root,
    )


class TestConfigResolution:
    """Tests for config resolution."""

    def test_default_values(self):
        """Default config has correct values."""
        cfg = make_test_config()

        assert cfg.workspace.name == "default"
        assert cfg.index.top_k == 20
        assert cfg.llm.model == "deepseek-chat"

    def test_workspace_path_resolution(self):
        """Workspace paths resolve correctly."""
        root = Path("C:/test/root")  # Use Windows-style for cross-platform
        cfg = make_test_config(_root=root)

        expected = root / "workspace" / "default"
        assert cfg.workspace_dir == expected
        assert cfg.papers_dir == expected / "papers"
        assert cfg.index_db == expected / "index.db"

    def test_custom_workspace(self):
        """Custom workspace name changes paths."""
        root = Path("/test/root")
        cfg = make_test_config(
            _root=root,
            workspace=WorkspaceConfig(name="research"),
            workspace_store={"research": WorkspaceConfig(name="research")},
        )

        assert "research" in str(cfg.workspace_dir)

    def test_llm_config_resolve_api_key(self):
        """LLM API key resolution from env."""
        # Set environment variable
        os.environ["DEEPSEEK_API_KEY"] = "test-key-123"

        try:
            cfg = make_test_config()
            api_key = cfg.llm.resolve_api_key()
            assert api_key == "test-key-123"
        finally:
            if "DEEPSEEK_API_KEY" in os.environ:
                del os.environ["DEEPSEEK_API_KEY"]

    def test_index_config_defaults(self):
        """Index config has correct defaults."""
        cfg = IndexConfig()

        assert cfg.top_k == 20
        assert cfg.chunk_size == 800
        assert cfg.chunk_overlap == 150

    def test_workspace_config_defaults(self):
        """Workspace config has correct defaults."""
        cfg = WorkspaceConfig()

        assert cfg.name == "default"
        assert cfg.description == ""
