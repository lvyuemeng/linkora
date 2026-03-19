"""
context.py — Lazy-initialized CLI Context

Provides context injection for CLI commands with lazy initialization of resources.
This enables:
- Faster CLI startup (lazy init)
- Proper error handling per command
- Testability (inject mock clients)
- Handling optional dependencies gracefully

Usage:
    from linkora.cli.context import AppContext

    ctx = AppContext(config)
    with ctx.search_index() as idx:
        results = idx.search("query")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from linkora.log import get_logger

if TYPE_CHECKING:
    from linkora.config import Config
    from linkora.http import HTTPClient
    from linkora.llm import LLMRunner
    from linkora.loader import PaperEnricher
    from linkora.papers import PaperStore
    from linkora.index import SearchIndex, VectorIndex
    from linkora.ingest.matching import DefaultDispatcher

_log = get_logger(__name__)


@dataclass
class AppContext:
    """Lazy-initialized context for CLI commands.

    Resources are created on first access, not at startup.
    This enables proper handling of optional dependencies.
    """

    config: "Config"
    _http_client: "HTTPClient | None" = field(default=None, repr=False)
    _llm_runner: "LLMRunner | None" = field(default=None, repr=False)
    _paper_store: "PaperStore | None" = field(default=None, repr=False)
    _dispatcher: "DefaultDispatcher | None" = field(default=None, repr=False)

    def http_client(self) -> "HTTPClient":
        """Get or create HTTP client (lazy init)."""
        if self._http_client is None:
            from linkora.http import RequestsClient

            self._http_client = RequestsClient()
        return self._http_client

    def llm_runner(self) -> "LLMRunner":
        """Get or create LLM runner (lazy init)."""
        if self._llm_runner is None:
            from linkora.llm import LLMRunner

            self._llm_runner = LLMRunner(
                config=self.config.llm,
                http_client=self.http_client(),
                api_key=self.config.resolve_llm_api_key(),
            )
        return self._llm_runner

    def paper_store(self) -> "PaperStore":
        """Get or create paper store (lazy init)."""
        if self._paper_store is None:
            from linkora.papers import PaperStore

            self._paper_store = PaperStore(self.config.papers_store_dir)
        return self._paper_store

    def search_index(self) -> "SearchIndex":
        """Returns context manager for SearchIndex."""
        from linkora.index import SearchIndex

        return SearchIndex(self.config.index_db)

    def vector_index(self) -> "VectorIndex":
        """Returns context manager for VectorIndex (optional dependency).

        Raises ImportError if faiss is not installed.
        """
        from linkora.index import VectorIndex

        return VectorIndex(self.config.index_db)

    def paper_enricher(self) -> "PaperEnricher":
        """Get or create paper enricher (lazy init).

        Uses config and LLM runner from context.
        """
        from linkora.loader import PaperEnricher

        return PaperEnricher(
            papers_dir=self.config.papers_store_dir,
            config=self.config,
            runner=self.llm_runner(),
        )

    def source_dispatcher(self) -> "DefaultDispatcher":
        """Get or create source dispatcher with multi-path support.

        Uses lazy initialization for efficiency.
        """
        if self._dispatcher is None:
            from linkora.ingest.matching import DefaultDispatcher

            paths = self.config.resolve_local_source_paths()
            self._dispatcher = DefaultDispatcher(
                local_pdf_dirs=paths, http_client=self.http_client()
            )
        return self._dispatcher

    def close(self) -> None:
        """Close all resources."""
        self._http_client = None
        self._llm_runner = None
        self._paper_store = None
        self._dispatcher = None


__all__ = ["AppContext"]
