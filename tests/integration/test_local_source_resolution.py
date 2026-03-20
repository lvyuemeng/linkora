"""Integration test: Local source multi-path resolution.

Tests for resolve_local_source_paths() - multi-path support.
Focus on integrated tests for new functionality.
"""

from pathlib import Path
from linkora.config import (
    Config,
    WorkspaceConfig,
    SourcesConfig,
    LocalSourceConfig,
    IndexConfig,
    LLMConfig,
    IngestConfig,
    TopicsConfig,
    LogConfig,
)


def make_test_config(
    root: Path | None = None,
    sources: SourcesConfig | None = None,
    _config_root: Path | None = None,
) -> Config:
    """Create a Config object for testing."""
    workspace = WorkspaceConfig(name="default")
    workspace_store = {"default": WorkspaceConfig(name="default")}
    default_workspace = "default"
    index = IndexConfig()
    llm = LLMConfig()
    ingest = IngestConfig()
    topics = TopicsConfig()
    log = LogConfig()
    root = root or Path.cwd()
    _config_root = _config_root or root

    return Config(
        workspace=workspace,
        workspace_store=workspace_store,
        default_workspace=default_workspace,
        sources=sources or SourcesConfig(),
        index=index,
        llm=llm,
        ingest=ingest,
        topics=topics,
        log=log,
        _root=root,
        _config_root=_config_root,
    )


class TestLocalSourceResolution:
    """Tests for resolve_local_source_paths() - multi-path support."""

    def test_single_path_resolution(self, tmp_path):
        """Single papers_dir resolves correctly."""
        # Create config with single papers_dir
        sources = SourcesConfig(
            local=LocalSourceConfig(
                enabled=True,
                papers_dir="papers",
                paths=[],
            )
        )

        # Create papers directory
        papers_dir = tmp_path / "papers"
        papers_dir.mkdir()

        config = make_test_config(
            root=tmp_path,
            sources=sources,
            _config_root=tmp_path,
        )

        paths = config.resolve_local_source_paths()

        assert len(paths) == 1
        assert paths[0] == papers_dir.resolve()

    def test_multiple_paths_resolution(self, tmp_path):
        """Multiple paths resolve correctly."""
        # Create additional paths
        extra_papers = tmp_path / "extra_papers"
        extra_papers.mkdir()

        sources = SourcesConfig(
            local=LocalSourceConfig(
                enabled=True,
                papers_dir="papers",
                paths=[str(extra_papers)],
            )
        )

        # Create papers directory
        papers_dir = tmp_path / "papers"
        papers_dir.mkdir()

        config = make_test_config(
            root=tmp_path,
            sources=sources,
            _config_root=tmp_path,
        )

        paths = config.resolve_local_source_paths()

        assert len(paths) == 2
        assert papers_dir.resolve() in paths
        assert extra_papers.resolve() in paths

    def test_relative_path_resolution(self, tmp_path):
        """Relative paths resolved from config root."""
        sources = SourcesConfig(
            local=LocalSourceConfig(
                enabled=True,
                papers_dir="papers",
                paths=["relative_papers"],
            )
        )

        # Create both directories
        papers_dir = tmp_path / "papers"
        relative_dir = tmp_path / "relative_papers"
        papers_dir.mkdir()
        relative_dir.mkdir()

        config = make_test_config(
            root=tmp_path,
            sources=sources,
            _config_root=tmp_path,
        )

        paths = config.resolve_local_source_paths()

        # All paths should be absolute
        assert all(p.is_absolute() for p in paths)
        assert len(paths) == 2

    def test_disabled_source_returns_empty(self, tmp_path):
        """Disabled local source returns empty list."""
        sources = SourcesConfig(
            local=LocalSourceConfig(
                enabled=False,
                papers_dir="papers",
                paths=[],
            )
        )

        config = make_test_config(
            root=tmp_path,
            sources=sources,
            _config_root=tmp_path,
        )

        paths = config.resolve_local_source_paths()

        assert paths == []

    def test_absolute_path_resolution(self, tmp_path):
        """Absolute paths are resolved correctly."""
        # Use a different absolute path
        absolute_path = tmp_path / "absolute_papers"
        absolute_path.mkdir()

        sources = SourcesConfig(
            local=LocalSourceConfig(
                enabled=True,
                papers_dir="papers",
                paths=[str(absolute_path)],
            )
        )

        # Create papers directory
        papers_dir = tmp_path / "papers"
        papers_dir.mkdir()

        config = make_test_config(
            root=tmp_path,
            sources=sources,
            _config_root=tmp_path,
        )

        paths = config.resolve_local_source_paths()

        assert len(paths) == 2
        assert absolute_path.resolve() in paths

    def test_empty_paths_list(self, tmp_path):
        """Empty paths list works correctly."""
        sources = SourcesConfig(
            local=LocalSourceConfig(
                enabled=True,
                papers_dir="papers",
                paths=[],
            )
        )

        papers_dir = tmp_path / "papers"
        papers_dir.mkdir()

        config = make_test_config(
            root=tmp_path,
            sources=sources,
            _config_root=tmp_path,
        )

        paths = config.resolve_local_source_paths()

        assert len(paths) == 1
        assert paths[0] == papers_dir.resolve()

    def test_config_root_resolution(self, tmp_path):
        """Paths are resolved from config root, not workspace root."""
        # Create a nested structure
        config_root = tmp_path / "config_root"
        config_root.mkdir()
        papers_dir = config_root / "papers"
        papers_dir.mkdir()

        sources = SourcesConfig(
            local=LocalSourceConfig(
                enabled=True,
                papers_dir="papers",
                paths=[],
            )
        )

        # Workspace root is different from config root
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()

        config = make_test_config(
            root=workspace_root,
            sources=sources,
            _config_root=config_root,
        )

        paths = config.resolve_local_source_paths()

        # Should resolve from config_root, not workspace_root
        assert paths[0] == papers_dir.resolve()
        assert config_root in paths[0].parents
