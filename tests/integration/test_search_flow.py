"""Integration test: Search flow consistency.

Tests that:
1. SearchIndex.search() returns consistent results
2. Filter parameters work correctly
3. Author search works correctly
4. Top-cited ordering works
"""

import pytest
import tempfile
import sqlite3
from pathlib import Path

# Skip all tests if faiss is not available
pytestmark = pytest.mark.skipif(
    pytest.importorskip("faiss") is None, reason="faiss not installed"
)


class TestSearchFlow:
    """Tests for search flow consistency."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database with test data."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"

            # Create schema - must match SearchIndex FTS5 schema in linkora/index/text.py
            conn = sqlite3.connect(db_path)
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS papers USING fts5(
                    paper_id       UNINDEXED,
                    title,
                    authors,
                    year,
                    journal,
                    abstract,
                    conclusion,
                    doi            UNINDEXED,
                    paper_type     UNINDEXED,
                    citation_count UNINDEXED,
                    md_path        UNINDEXED,
                    tokenize       = 'unicode61'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS papers_hash (
                    paper_id     TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS papers_registry (
                    id           TEXT PRIMARY KEY,
                    dir_name     TEXT NOT NULL UNIQUE,
                    title        TEXT,
                    doi          TEXT,
                    year         INTEGER,
                    first_author TEXT
                )
            """)

            # Insert test data into FTS5 table
            test_papers = [
                (
                    "p1",
                    "Deep Learning for NLP",
                    "Smith,John",
                    "2023",
                    "JMLR",
                    "",  # abstract
                    "",  # conclusion
                    "",  # doi
                    "research",
                    "100",
                    "",  # md_path
                ),
                (
                    "p2",
                    "Machine Learning Survey",
                    "Doe,Jane",
                    "2022",
                    "Nature",
                    "",  # abstract
                    "",  # conclusion
                    "",  # doi
                    "review",
                    "50",
                    "",  # md_path
                ),
                (
                    "p3",
                    "Neural Networks Tutorial",
                    "Brown,Bob",
                    "2023",
                    "Science",
                    "",  # abstract
                    "",  # conclusion
                    "",  # doi
                    "tutorial",
                    "75",
                    "",  # md_path
                ),
                (
                    "p4",
                    "Advanced Deep Learning",
                    "Smith,John",
                    "2024",
                    "JMLR",
                    "",  # abstract
                    "",  # conclusion
                    "",  # doi
                    "research",
                    "25",
                    "",  # md_path
                ),
                (
                    "p5",
                    "Natural Language Processing",
                    "White,Alice",
                    "2023",
                    "ACL",
                    "",  # abstract
                    "",  # conclusion
                    "",  # doi
                    "research",
                    "200",
                    "",  # md_path
                ),
            ]

            conn.executemany(
                "INSERT INTO papers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                test_papers,
            )

            conn.commit()

            yield db_path

            conn.close()

    def test_basic_search(self, temp_db):
        """Basic search returns relevant results."""
        from linkora.index import SearchIndex

        with SearchIndex(temp_db) as idx:
            results = idx.search("deep learning", top_k=10)

        assert len(results) > 0
        # Should find papers with "Deep Learning" in title
        titles = [r.get("title", "") for r in results]
        assert any("deep" in t.lower() or "learning" in t.lower() for t in titles)

    def test_search_with_year_filter(self, temp_db):
        """Search with year filter works correctly."""
        from linkora.index import SearchIndex

        with SearchIndex(temp_db) as idx:
            results = idx.search("machine", top_k=10, year="2023")

        # All results should be from 2023
        for r in results:
            if "year" in r:
                assert r["year"] == 2023

    def test_search_with_journal_filter(self, temp_db):
        """Search with journal filter works correctly."""
        from linkora.index import SearchIndex

        with SearchIndex(temp_db) as idx:
            results = idx.search("learning", top_k=10, journal="JMLR")

        # All results should be from JMLR
        for r in results:
            if "journal" in r:
                assert r["journal"] == "JMLR"

    def test_author_search(self, temp_db):
        """Author search returns correct papers."""
        from linkora.index import SearchIndex

        with SearchIndex(temp_db) as idx:
            results = idx.search_author("Smith", top_k=10)

        # Should find papers by Smith
        assert len(results) > 0

    def test_top_cited(self, temp_db):
        """Top cited returns papers sorted by citation count."""
        from linkora.index import SearchIndex

        with SearchIndex(temp_db) as idx:
            results = idx.top_cited(top_k=10)

        # Should be sorted by citation count descending
        # Note: citation_count is stored as string in FTS5, convert to int for comparison
        citations = [int(r.get("citation_count", 0)) for r in results]
        assert citations == sorted(citations, reverse=True)
