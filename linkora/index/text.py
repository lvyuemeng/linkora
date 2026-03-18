"""
index/text.py — SQLite FTS5 Full-Text Search Index
==============================================

Indexed fields: title + abstract + conclusion (all searchable).
Other fields (paper_id, authors, year, journal, doi, paper_type, citation_count, md_path)
are stored but not searched.

Usage:
    from linkora.index import SearchIndex

    index = SearchIndex(db_path)
    results = index.search("turbulent boundary layer")
    author_results = index.search_author("Einstein")
    top_cited = index.top_cited()
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from linkora.hash import compute_full_hash
from linkora.papers import best_citation, parse_year_range

# ============================================================================
# Query Data Classes (Immutable, No Side Effects)
# ============================================================================

_SEARCH_COLS = (
    "paper_id, title, authors, year, journal, doi, paper_type, citation_count"
)


@dataclass(frozen=True)
class FilterParams:
    """Filter parameters for search queries (immutable)."""

    year: str | None = None
    journal: str | None = None
    paper_type: str | None = None

    def to_sql(self) -> tuple[str, list[str]]:
        """Convert to SQL WHERE clause and params."""
        clauses: list[str] = []
        params: list[str] = []

        # Year filter
        if self.year:
            start, end = parse_year_range(self.year)
            if start is not None and end is not None:
                if start == end:
                    clauses.append("year = ?")
                    params.append(str(start))
                else:
                    clauses.append("year >= ? AND year <= ?")
                    params.extend([str(start), str(end)])
            elif start is not None:
                clauses.append("year >= ?")
                params.append(str(start))
            elif end is not None:
                clauses.append("year <= ?")
                params.append(str(end))

        # Journal filter
        if self.journal:
            clauses.append("journal LIKE ?")
            params.append(f"%{self.journal}%")

        # Paper type filter
        if self.paper_type:
            clauses.append("paper_type LIKE ?")
            params.append(f"%{self.paper_type}%")

        return ("".join(f" AND {c}" for c in clauses), params) if clauses else ("", [])


# ============================================================================
# Search Mode Factories (Pure Data, No Side Effects)
# ============================================================================


class SearchMode:
    """Search mode factories - pure data, no side effects."""

    @staticmethod
    def fts(query: str) -> tuple[str, str, list[str]]:
        """Full-text search mode."""
        safe = re.sub(r"[^\w\s]", " ", query).strip()
        return (_SEARCH_COLS, "papers MATCH ?", [safe])

    @staticmethod
    def author(name: str) -> tuple[str, str, list[str]]:
        """Author search mode."""
        return (_SEARCH_COLS, "authors LIKE ?", [f"%{name}%"])

    @staticmethod
    def top_cited() -> tuple[str, str, list[str]]:
        """Top-cited mode."""
        return (_SEARCH_COLS, "citation_count != ''", [])


# ============================================================================
# Schemas (Constants)
# ============================================================================

_SCHEMAS = """
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
);

CREATE TABLE IF NOT EXISTS papers_hash (
    paper_id     TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS papers_registry (
    id           TEXT PRIMARY KEY,
    dir_name     TEXT NOT NULL UNIQUE,
    title        TEXT,
    doi          TEXT,
    year         INTEGER,
    first_author TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_registry_doi
    ON papers_registry(doi) WHERE doi IS NOT NULL AND doi != '';

CREATE TABLE IF NOT EXISTS citations (
    source_id   TEXT NOT NULL,
    target_doi  TEXT NOT NULL,
    target_id   TEXT,
    PRIMARY KEY (source_id, target_doi)
);

CREATE INDEX IF NOT EXISTS idx_cit_target_doi ON citations(target_doi);
CREATE INDEX IF NOT EXISTS idx_cit_target_id ON citations(target_id) WHERE target_id IS NOT NULL;
"""

_SCHEMA = _SCHEMAS.split(";")[0] + ";"
_HASH_SCHEMA = _SCHEMAS.split(";")[1] + ";"
_REGISTRY_SCHEMA = _SCHEMAS.split(";")[2] + ";"
_REGISTRY_DOI_INDEX = _SCHEMAS.split(";")[3] + ";"
_CITATIONS_SCHEMA = _SCHEMAS.split(";")[4] + ";"
_CITATIONS_IDX_TARGET_DOI = _SCHEMAS.split(";")[5]
_CITATIONS_IDX_TARGET_ID = _SCHEMAS.split(";")[6]


# ============================================================================
# Search Index Class (Encapsulates DB Connection)
# ============================================================================


class SearchIndex:
    """Search index with encapsulated DB connection."""

    def __init__(self, db_path: Path) -> None:
        """Initialize search index with database path."""
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _ensure_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _ensure_fts_table(self) -> None:
        conn = self._ensure_connection()
        has_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='papers'"
        ).fetchone()
        if not has_table:
            raise FileNotFoundError("FTS5 index table not found.")

    def _enrich_dir_names(self, results: list[dict]) -> None:
        conn = self._ensure_connection()
        id_to_dir: dict[str, str] = {}
        has_reg = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='papers_registry'"
        ).fetchone()
        if has_reg:
            for row in conn.execute(
                "SELECT id, dir_name FROM papers_registry"
            ).fetchall():
                id_to_dir[row[0]] = row[1]
        for r in results:
            r["dir_name"] = id_to_dir.get(r["paper_id"], "")

    def _query(
        self,
        mode: tuple[str, str, list[str]],
        filters: FilterParams,
        top_k: int,
        order_by: str = "rank",
        paper_ids: set[str] | None = None,
    ) -> list[dict]:
        self._ensure_fts_table()
        conn = self._ensure_connection()

        cols, where_clause, where_params = mode
        filter_sql, filter_params = filters.to_sql()

        fetch_k = top_k * 5 if paper_ids else top_k

        rows = conn.execute(
            f"SELECT {cols} FROM papers WHERE {where_clause}{filter_sql} ORDER BY {order_by} LIMIT ?",
            [*where_params, *filter_params, fetch_k],
        ).fetchall()

        results = [dict(r) for r in rows]
        self._enrich_dir_names(results)

        if paper_ids is not None:
            results = [r for r in results if r["paper_id"] in paper_ids]
        return results[:top_k]

    # -------------------------------------------------------------------------
    # Search Methods
    # -------------------------------------------------------------------------

    def search(
        self,
        query: str,
        top_k: int = 20,
        *,
        year: str | None = None,
        journal: str | None = None,
        paper_type: str | None = None,
        paper_ids: set[str] | None = None,
    ) -> list[dict]:
        filters = FilterParams(year=year, journal=journal, paper_type=paper_type)
        return self._query(SearchMode.fts(query), filters, top_k, "rank", paper_ids)

    def search_author(
        self,
        query: str,
        top_k: int = 20,
        *,
        year: str | None = None,
        journal: str | None = None,
        paper_type: str | None = None,
        paper_ids: set[str] | None = None,
    ) -> list[dict]:
        filters = FilterParams(year=year, journal=journal, paper_type=paper_type)
        return self._query(
            SearchMode.author(query), filters, top_k, "year DESC", paper_ids
        )

    def top_cited(
        self,
        top_k: int = 10,
        *,
        year: str | None = None,
        journal: str | None = None,
        paper_type: str | None = None,
        paper_ids: set[str] | None = None,
    ) -> list[dict]:
        filters = FilterParams(year=year, journal=journal, paper_type=paper_type)
        return self._query(
            SearchMode.top_cited(),
            filters,
            top_k,
            "CAST(citation_count AS INTEGER) DESC",
            paper_ids,
        )

    # -------------------------------------------------------------------------
    # Citation Graph Methods
    # -------------------------------------------------------------------------

    def _fetch_citations(
        self, sql: str, params: list, paper_ids: set[str] | None = None
    ) -> list[dict]:
        conn = self._ensure_connection()
        rows = conn.execute(sql, params).fetchall()
        results = [dict(r) for r in rows]
        if paper_ids is not None:
            id_fields = ["target_id", "source_id", "paper_id"]
            results = [
                r
                for r in results
                if any(r.get(f) in paper_ids for f in id_fields if r.get(f))
            ]
        return results

    def references(
        self, paper_id: str, *, paper_ids: set[str] | None = None
    ) -> list[dict]:
        """Get outgoing citations (what this paper cites)."""
        sql = """SELECT c.target_doi, c.target_id,
                         pr.title, pr.dir_name, pr.year, pr.first_author
                  FROM citations c
                  LEFT JOIN papers_registry pr ON c.target_id = pr.id
                  WHERE c.source_id = ?
                  ORDER BY pr.year DESC NULLS LAST, c.target_doi"""
        return self._fetch_citations(sql, [paper_id], paper_ids)

    def citing(self, paper_id: str, *, paper_ids: set[str] | None = None) -> list[dict]:
        """Get incoming citations (what cites this paper)."""
        conn = self._ensure_connection()
        row = conn.execute(
            "SELECT doi FROM papers_registry WHERE id = ?", (paper_id,)
        ).fetchone()
        target_doi = row["doi"] if row else ""

        params: list = [paper_id]
        doi_clause = ""
        if target_doi:
            doi_clause = " OR LOWER(c.target_doi) = LOWER(?)"
            params.append(target_doi)

        sql = f"""SELECT c.source_id as paper_id,
                         pr.dir_name, pr.title, pr.year, pr.first_author
                  FROM citations c
                  JOIN papers_registry pr ON c.source_id = pr.id
                  WHERE (c.target_id = ?{doi_clause})
                  ORDER BY pr.year DESC"""
        return self._fetch_citations(sql, params, paper_ids)

    def shared_citations(
        self,
        paper_id_list: list[str],
        min_count: int = 2,
        *,
        paper_ids: set[str] | None = None,
    ) -> list[dict]:
        """Find citations shared by multiple papers."""
        if not paper_id_list:
            return []

        placeholders = ",".join("?" for _ in paper_id_list)
        sql = f"""SELECT c.target_doi,
                          COUNT(DISTINCT c.source_id) AS shared_count,
                          c.target_id,
                          pr.title, pr.dir_name, pr.year
                   FROM citations c
                   LEFT JOIN papers_registry pr ON c.target_id = pr.id
                   WHERE c.source_id IN ({placeholders})
                   GROUP BY LOWER(c.target_doi)
                   HAVING shared_count >= ?
                   ORDER BY shared_count DESC, c.target_doi"""
        return self._fetch_citations(sql, [*paper_id_list, min_count], paper_ids)

    # -------------------------------------------------------------------------
    # Index Build Methods (Unified Pattern)
    # -------------------------------------------------------------------------

    def _ensure_schemas(self) -> None:
        conn = self._ensure_connection()
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_SCHEMA)
        conn.execute(_HASH_SCHEMA)
        conn.execute(_REGISTRY_SCHEMA)
        conn.execute(_CITATIONS_SCHEMA)
        try:
            conn.execute(_REGISTRY_DOI_INDEX)
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute(_CITATIONS_IDX_TARGET_DOI)
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute(_CITATIONS_IDX_TARGET_ID)
        except sqlite3.OperationalError:
            pass

    def _index_paper(
        self, conn: sqlite3.Connection, pdir: Path, meta: dict, paper_id: str, h: str
    ) -> bool:
        """Index single paper. Returns True if indexed."""
        best_cite = best_citation(meta)
        md_file = pdir / "paper.md"

        conn.execute(
            """
            INSERT INTO papers
                (paper_id, title, authors, year, journal, abstract, conclusion,
                 doi, paper_type, citation_count, md_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                paper_id,
                meta.get("title") or "",
                ", ".join(meta.get("authors") or []),
                str(meta.get("year") or ""),
                meta.get("journal") or "",
                meta.get("abstract") or "",
                meta.get("l3_conclusion") or "",
                meta.get("doi") or "",
                meta.get("paper_type") or "",
                str(best_cite) if best_cite is not None else "",
                str(md_file) if md_file.exists() else "",
            ),
        )
        conn.execute(
            "INSERT OR REPLACE INTO papers_hash (paper_id, content_hash) VALUES (?, ?)",
            (paper_id, h),
        )

        dir_name = pdir.name
        conn.execute(
            """INSERT OR REPLACE INTO papers_registry
               (id, dir_name, title, doi, year, first_author)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                paper_id,
                dir_name,
                meta.get("title") or "",
                meta.get("doi") or "",
                meta.get("year"),
                meta.get("first_author_lastname") or "",
            ),
        )

        refs = meta.get("references") or []
        if refs:
            conn.execute("DELETE FROM citations WHERE source_id = ?", (paper_id,))
            conn.executemany(
                "INSERT OR IGNORE INTO citations (source_id, target_doi, target_id) VALUES (?, ?, NULL)",
                [(paper_id, doi) for doi in refs],
            )

        return True

    def _resolve_citations(self, conn: sqlite3.Connection) -> None:
        """Bulk resolve target_id for citations where target paper is in library."""
        conn.execute("""
            UPDATE citations SET target_id = (
                SELECT pr.id FROM papers_registry pr
                WHERE LOWER(pr.doi) = LOWER(citations.target_doi)
            ) WHERE target_id IS NULL
        """)

    def rebuild(self, store) -> int:
        """Full rebuild of search index.

        Args:
            store: PaperStore instance.
        """
        self._ensure_schemas()
        conn = self._ensure_connection()

        # Clear existing data
        conn.execute("DROP TABLE IF EXISTS papers")
        conn.execute(_SCHEMA)
        conn.execute("DELETE FROM papers_hash")
        conn.execute("DELETE FROM papers_registry")
        conn.execute("DELETE FROM citations")

        count = 0
        for pdir in store.iter_papers():
            try:
                meta: dict[str, Any] = store.read_meta(pdir)
            except (ValueError, FileNotFoundError):
                continue
            paper_id: str = meta.get("id") or pdir.name
            h = compute_full_hash(meta)
            if self._index_paper(conn, pdir, meta, paper_id, h):
                count += 1

        self._resolve_citations(conn)
        conn.commit()
        return count

    def update(self, store) -> int:
        """Incrementally update search index.

        Args:
            store: PaperStore instance.
        """
        self._ensure_schemas()
        conn = self._ensure_connection()

        # Load existing hashes
        existing_hashes: dict[str, str] = {}
        for row in conn.execute(
            "SELECT paper_id, content_hash FROM papers_hash"
        ).fetchall():
            existing_hashes[row[0]] = row[1]

        count = 0
        for pdir in store.iter_papers():
            try:
                meta: dict[str, Any] = store.read_meta(pdir)
            except (ValueError, FileNotFoundError):
                continue
            paper_id: str = meta.get("id") or pdir.name
            h = compute_full_hash(meta)

            if existing_hashes.get(paper_id) == h:
                continue  # unchanged

            conn.execute("DELETE FROM papers WHERE paper_id = ?", (paper_id,))
            if self._index_paper(conn, pdir, meta, paper_id, h):
                count += 1

        self._resolve_citations(conn)
        conn.commit()
        return count

    # -------------------------------------------------------------------------
    # Connection Management
    # -------------------------------------------------------------------------

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "SearchIndex":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
