"""Integration test: DefaultDispatcher multi-path support.

Tests for DefaultDispatcher with multi-path support.
Focus on integrated tests for new functionality.
"""

from linkora.ingest.matching import DefaultDispatcher
from linkora.sources.local import LocalSource


class TestDefaultDispatcherMultiPath:
    """Tests for DefaultDispatcher with multi-path support."""

    def test_dispatcher_accepts_path_list(self, tmp_path):
        """Dispatcher accepts list of paths."""
        path1 = tmp_path / "p1"
        path2 = tmp_path / "p2"
        path1.mkdir()
        path2.mkdir()

        paths = [path1, path2]
        dispatcher = DefaultDispatcher(local_pdf_dirs=paths)

        assert dispatcher._local_pdf_dirs == paths

    def test_dispatcher_empty_paths(self):
        """Dispatcher handles empty path list."""
        dispatcher = DefaultDispatcher(local_pdf_dirs=[])

        assert dispatcher._local_pdf_dirs == []

    def test_dispatcher_none_paths(self):
        """Dispatcher handles None path list."""
        dispatcher = DefaultDispatcher(local_pdf_dirs=None)

        assert dispatcher._local_pdf_dirs == []

    def test_dispatcher_creates_single_local_source(self, tmp_path):
        """Dispatcher creates single LocalSource for all paths."""
        path1 = tmp_path / "p1"
        path2 = tmp_path / "p2"
        path1.mkdir()
        path2.mkdir()

        paths = [path1, path2]
        dispatcher = DefaultDispatcher(local_pdf_dirs=paths)

        # Should create one LocalSource, not multiple
        dispatcher._ensure_sources()
        assert isinstance(dispatcher._local_source, LocalSource)

    def test_dispatcher_sources_not_initialized_until_accessed(self, tmp_path):
        """Dispatcher lazily initializes sources."""
        path1 = tmp_path / "p1"
        path1.mkdir()

        dispatcher = DefaultDispatcher(local_pdf_dirs=[path1])

        # Sources should not be initialized yet
        assert not dispatcher._initialized
        assert dispatcher._local_source is None

        # After accessing, should be initialized
        dispatcher._ensure_sources()

        assert dispatcher._initialized


class TestDefaultDispatcherWithHTTP:
    """Tests for DefaultDispatcher with HTTP client."""

    def test_dispatcher_with_http_client(self, tmp_path, monkeypatch):
        """Dispatcher accepts HTTP client."""

        # Create mock HTTP client
        class MockHTTP:
            pass

        mock_http = MockHTTP()

        path1 = tmp_path / "p1"
        path1.mkdir()

        dispatcher = DefaultDispatcher(local_pdf_dirs=[path1], http_client=mock_http)

        assert dispatcher._http_client is mock_http


class TestDefaultDispatcherSources:
    """Tests for DefaultDispatcher source management."""

    def test_dispatcher_disabled_local_source(self):
        """Dispatcher handles disabled local source."""
        # When local source is disabled, should not create it
        dispatcher = DefaultDispatcher(local_pdf_dirs=None)

        dispatcher._ensure_sources()

        assert dispatcher._local_source is None

    def test_dispatcher_multiple_sources_initialized(self, tmp_path):
        """Multiple sources are properly initialized."""
        path1 = tmp_path / "p1"
        path1.mkdir()

        dispatcher = DefaultDispatcher(
            local_pdf_dirs=[path1],
            # No other sources enabled by default
        )

        dispatcher._ensure_sources()

        # Only local source should be created (others disabled by config)
        assert dispatcher._local_source is not None
