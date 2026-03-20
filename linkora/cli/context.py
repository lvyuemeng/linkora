"""
context.py — Lazy-initialised application context for CLI commands.

AppContext is constructed once per CLI invocation and injected into every
command handler.  It holds:

  config          — immutable AppConfig (settings values)
  config_dir      — directory of the active config file (for resolving
                    relative paths declared in config, e.g. sources.local.paths)
  store           — WorkspaceStore (workspace registry service)
  workspace_name  — the name of the currently active workspace

All workspace filesystem paths are obtained through ctx.workspace, which
returns a freshly computed WorkspacePaths.  No path strings are stored
inside the context itself.

Heavy resources (HTTP client, LLM runner, search index, …) are initialised
lazily to keep CLI startup fast and to let individual commands fail cleanly
when an optional dependency is missing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, ContextManager

from linkora.log import get_logger

if TYPE_CHECKING:
    from linkora.config import AppConfig
    from linkora.workspace import WorkspaceStore, WorkspacePaths
    from linkora.http import HTTPClient
    from linkora.llm import LLMRunner
    from linkora.loader import PaperEnricher
    from linkora.papers import PaperStore
    from linkora.index import SearchIndex, VectorIndex
    from linkora.ingest.matching import DefaultDispatcher

_log = get_logger(__name__)


@dataclass
class AppContext:
    """
    Per-invocation application context.

    Parameters
    ----------
    config:
        Loaded application settings (frozen Pydantic model).
    config_dir:
        Directory that contained the active config.yml, used to resolve
        relative paths appearing in config values.  Pass the parent of
        ``get_config_path()``; fall back to ``get_config_dir()``.
    store:
        WorkspaceStore bound to the data root.
    workspace_name:
        Name of the active workspace for this invocation.
    """

    config: "AppConfig"
    config_dir: Path
    store: "WorkspaceStore"
    workspace_name: str

    # Lazily initialised resources — not part of the public API.
    _http_client: "HTTPClient | None" = field(default=None, repr=False, compare=False)
    _llm_runner: "LLMRunner | None" = field(default=None, repr=False, compare=False)
    _paper_store: "PaperStore | None" = field(default=None, repr=False, compare=False)
    _dispatcher: "DefaultDispatcher | None" = field(
        default=None, repr=False, compare=False
    )

    # ------------------------------------------------------------------
    # Workspace path access
    # ------------------------------------------------------------------

    @property
    def workspace(self) -> "WorkspacePaths":
        """
        Computed paths for the active workspace.

        Always fresh — no caching — so that a workspace rename mid-session
        would still produce correct paths (though that case is not expected
        in normal CLI usage).
        """
        return self.store.paths(self.workspace_name)

    def ensure_workspace_dirs(self) -> None:
        """Create workspace directories if they do not yet exist."""
        self.workspace.ensure_dirs()

    def resolve_local_source_paths(self) -> list[Path]:
        """Delegate to AppConfig with the correct config_dir context."""
        return self.config.resolve_local_source_paths(self.config_dir)

    # ------------------------------------------------------------------
    # Lazy resources
    # ------------------------------------------------------------------

    def http_client(self) -> "HTTPClient":
        if self._http_client is None:
            from linkora.http import RequestsClient

            self._http_client = RequestsClient()
        return self._http_client

    def llm_runner(self) -> "LLMRunner":
        if self._llm_runner is None:
            from linkora.llm import LLMRunner

            self._llm_runner = LLMRunner(
                config=self.config.llm,
                http_client=self.http_client(),
                api_key=self.config.resolve_llm_api_key(),
            )
        return self._llm_runner

    def paper_store(self) -> "PaperStore":
        """
        PaperStore bound to the active workspace's papers directory.

        Re-creates the store if the workspace has changed between calls
        (unlikely in CLI usage, but correct).
        """
        papers_dir = self.workspace.papers_dir
        if self._paper_store is None:
            from linkora.papers import PaperStore

            self._paper_store = PaperStore(papers_dir)
        return self._paper_store

    def search_index(self) -> "ContextManager[SearchIndex]":
        """Return a context manager for the FTS search index."""
        from linkora.index import SearchIndex

        return SearchIndex(self.workspace.index_db)

    def vector_index(self) -> "ContextManager[VectorIndex]":
        """
        Return a context manager for the vector index.

        Raises ImportError if faiss is not installed.
        """
        from linkora.index import VectorIndex

        return VectorIndex(self.workspace.index_db)

    def paper_enricher(self) -> "PaperEnricher":
        from linkora.loader import PaperEnricher

        return PaperEnricher(
            papers_dir=self.workspace.papers_dir,
            config=self.config,
            runner=self.llm_runner(),
        )

    def source_dispatcher(self) -> "DefaultDispatcher":
        if self._dispatcher is None:
            from linkora.ingest.matching import DefaultDispatcher

            self._dispatcher = DefaultDispatcher(
                local_pdf_dirs=self.resolve_local_source_paths(),
                http_client=self.http_client(),
            )
        return self._dispatcher

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Release all open resources."""
        if self._http_client is not None:
            try:
                self._http_client.close()
            except Exception:
                pass
        self._http_client = None
        self._llm_runner = None
        self._paper_store = None
        self._dispatcher = None

    def __enter__(self) -> "AppContext":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


__all__ = ["AppContext"]
