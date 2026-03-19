"""sources/zotero.py — Zotero Web API / Local SQLite import.

Redesigned with separated contexts - local (SQLite) and remote (API).
Implements PaperSource Protocol with unified search() + fetch_by_id() API.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

from linkora.log import get_logger
from linkora.sources.protocol import PaperCandidate, PaperQuery, matches_query

if TYPE_CHECKING:
    from linkora.http import HTTPClient

_log = get_logger(__name__)

DOI_PREFIX_RE = re.compile(r"^https?://(?:dx\.)?doi\.org/", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")

# Zotero itemType → Crossref-style paper_type
ITEM_TYPE_MAP: dict[str, str] = {
    "journalArticle": "journal-article",
    "conferencePaper": "conference-paper",
    "thesis": "thesis",
    "book": "book",
    "bookSection": "book-chapter",
    "report": "report",
    "preprint": "preprint",
    "document": "",
}


# ============================================================================
#  Internal helpers
# ============================================================================


def _clean_doi(raw: str) -> str:
    """Strip URL prefix from DOI, return bare DOI."""
    if not raw:
        return ""
    return DOI_PREFIX_RE.sub("", raw).strip()


def _parse_zotero_date(date_str: str) -> int | None:
    """Extract 4-digit year from Zotero date string."""
    if not date_str:
        return None
    m = YEAR_RE.search(date_str)
    return int(m.group(1)) if m else None


def _creators_to_authors(creators: list[dict]) -> list[str]:
    """Convert Zotero creators list to author name strings."""
    authors: list[str] = []
    for c in creators:
        if c.get("creatorType", "author") != "author":
            continue
        if "name" in c:
            authors.append(c["name"])
        else:
            first = c.get("firstName", "").strip()
            last = c.get("lastName", "").strip()
            if first and last:
                authors.append(f"{first} {last}")
            elif last:
                authors.append(last)
            elif first:
                authors.append(first)
    return authors


def _item_to_candidate(item_data: dict, source_label: str) -> PaperCandidate:
    """Convert Zotero item to PaperCandidate."""
    authors = _creators_to_authors(item_data.get("creators", []))
    doi = _clean_doi(item_data.get("DOI", ""))
    paper_id = doi or item_data.get("title", "")

    journal = (
        item_data.get("publicationTitle")
        or item_data.get("proceedingsTitle")
        or item_data.get("bookTitle")
        or ""
    )

    item_type = item_data.get("itemType", "")
    paper_type = ITEM_TYPE_MAP.get(item_type, item_type)

    return PaperCandidate(
        id=paper_id,
        doi=doi,
        title=item_data.get("title", ""),
        authors=authors,
        year=_parse_zotero_date(item_data.get("date", "")),
        journal=journal or None,
        abstract=item_data.get("abstractNote") or None,
        cited_by_count=0,
        paper_type=paper_type,
        pdf_url=None,
        source="zotero",
        source_id=item_data.get("key"),
    )


# ============================================================================
#  ZoteroSource class (PaperSource Protocol)
# ============================================================================


@dataclass(frozen=True)
class ZoteroSource:
    """Zotero source with separated contexts.

    Two operating modes:
    - Local: SQLite database (file-based, offline)
    - Remote: Zotero Web API (network-based, requires library_id/api_key)

    Usage:
        # Local mode (SQLite)
        source = ZoteroSource(db_path=Path("zotero.sqlite"))
        for paper in source.search(query):
            ...

        # Remote mode (API)
        from linkora.http import RequestsClient
        client = RequestsClient()
        source = ZoteroSource(
            http_client=client,
            library_id="123456",
            api_key="xxx"
        )
        for paper in source.search(query):
            ...
    """

    # === Local Context (SQLite mode) ===
    db_path: Path | None = None

    # === Remote Context (API mode) ===
    library_id: str = ""
    api_key: str = ""
    library_type: str = "user"

    # === Shared ===
    http_client: HTTPClient | None = None

    # === Context Detection ===
    @property
    def _is_local_mode(self) -> bool:
        """Check if using local SQLite mode."""
        return self.db_path is not None and self.db_path.exists()

    @property
    def _is_remote_mode(self) -> bool:
        """Check if using remote API mode."""
        return bool(self.library_id and self.api_key)

    @property
    def name(self) -> str:
        return "zotero"

    # === PaperSource Protocol ===

    def search(self, query: PaperQuery) -> Iterator[PaperCandidate]:
        """Search papers matching query.

        Delegates to appropriate context based on configuration.

        Args:
            query: PaperQuery with search criteria

        Yields:
            PaperCandidate instances matching the query
        """
        if not self._is_local_mode and not self._is_remote_mode:
            _log.warning("No active Zotero context (local or remote)")
            return

        if self._is_local_mode:
            yield from self._search_local(query)
        elif self._is_remote_mode:
            yield from self._search_remote(query)

    def fetch_by_id(self, paper_id: str) -> PaperCandidate | None:
        """Fetch paper by DOI or Zotero item key.

        Delegates to appropriate context based on configuration.

        Args:
            paper_id: DOI (preferred) or Zotero item key

        Returns:
            PaperCandidate if found, None otherwise
        """
        if not self._is_local_mode and not self._is_remote_mode:
            _log.warning("No active Zotero context (local or remote)")
            return None

        if self._is_local_mode:
            return self._fetch_local_by_id(paper_id)
        elif self._is_remote_mode:
            return self._fetch_remote_by_id(paper_id)
        return None

    # === Local Context Implementation ===

    def _search_local(self, query: PaperQuery) -> Iterator[PaperCandidate]:
        """Search papers from local SQLite database."""
        if not self.db_path:
            return

        conn = sqlite3.connect(f"file:{self.db_path}?immutable=1", uri=True)
        conn.row_factory = sqlite3.Row

        try:
            # Get all items
            items = self._query_items(conn, None, None)

            for item_id, item_type in items:
                item_data = self._fetch_item_data(conn, item_id, item_type)
                candidate = _item_to_candidate(item_data, "zotero.sqlite")

                # Filter by query
                if matches_query(candidate, query):
                    yield candidate

        finally:
            conn.close()

    def _fetch_local_by_id(self, paper_id: str) -> PaperCandidate | None:
        """Fetch paper by ID from local SQLite database."""
        if not self.db_path:
            return None

        conn = sqlite3.connect(f"file:{self.db_path}?immutable=1", uri=True)
        conn.row_factory = sqlite3.Row

        try:
            # Try to find by DOI
            candidate = self._fetch_by_doi(conn, paper_id)
            if candidate:
                return candidate

            # Try by title
            return self._fetch_by_title(conn, paper_id)

        finally:
            conn.close()

    def _fetch_by_doi(
        self, conn: sqlite3.Connection, paper_id: str
    ) -> PaperCandidate | None:
        """Fetch paper by DOI from local database."""
        # Single optimized query: JOIN items, itemTypes with DOI filter
        row = conn.execute(
            """
            SELECT i.itemID, it.typeName
            FROM items i
            JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
            JOIN itemData id_doi ON i.itemID = id_doi.itemID
            JOIN fields f_doi ON id_doi.fieldID = f_doi.fieldID
            JOIN itemDataValues idv_doi ON id_doi.valueID = idv_doi.valueID
            WHERE f_doi.fieldName = 'DOI' AND idv_doi.value LIKE ?
            """,
            (f"%{paper_id}%",),
        ).fetchone()

        if not row:
            return None

        item_id, item_type = row
        item_data = self._fetch_item_data(conn, item_id, item_type)
        return _item_to_candidate(item_data, "zotero.sqlite")

    def _fetch_by_title(
        self, conn: sqlite3.Connection, paper_id: str
    ) -> PaperCandidate | None:
        """Fetch paper by title from local database."""
        rows = conn.execute(
            "SELECT i.itemID, it.typeName "
            "FROM items i "
            "JOIN itemTypes it ON i.itemTypeID = it.itemTypeID "
            "JOIN itemData id ON i.itemID = id.itemID "
            "JOIN fields f ON id.fieldID = f.fieldID "
            "JOIN itemDataValues idv ON id.valueID = idv.valueID "
            "WHERE f.fieldName = 'title' AND idv.value LIKE ?",
            (f"%{paper_id}%",),
        ).fetchall()

        if not rows:
            return None

        item_id, item_type = rows[0]
        item_data = self._fetch_item_data(conn, item_id, item_type)
        return _item_to_candidate(item_data, "zotero.sqlite")

    def _query_items(
        self,
        conn: sqlite3.Connection,
        item_types: list[str] | None,
        item_id_filter: set[int] | None,
    ) -> list[tuple[int, str]]:
        """Query items from database."""
        type_filter = ""
        if item_types:
            placeholders = ",".join("?" for _ in item_types)
            type_filter = f"AND it.typeName IN ({placeholders})"

        query = f"""
            SELECT i.itemID, it.typeName
            FROM items i
            JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
            WHERE it.typeName NOT IN ('attachment', 'note')
            AND i.itemID NOT IN (SELECT itemID FROM deletedItems)
            {type_filter}
        """
        params: list = list(item_types) if item_types else []
        rows = conn.execute(query, params).fetchall()

        items = [(r["itemID"], r["typeName"]) for r in rows]
        if item_id_filter:
            items = [(i, t) for i, t in items if i in item_id_filter]
        return items

    def _fetch_item_data(
        self,
        conn: sqlite3.Connection,
        item_id: int,
        item_type: str,
    ) -> dict:
        """Fetch item data from database."""
        # Get fields
        field_rows = conn.execute(
            "SELECT f.fieldName, idv.value "
            "FROM itemData id "
            "JOIN fields f ON id.fieldID = f.fieldID "
            "JOIN itemDataValues idv ON id.valueID = idv.valueID "
            "WHERE id.itemID = ?",
            (item_id,),
        ).fetchall()
        item_data: dict = {r["fieldName"]: r["value"] for r in field_rows}
        item_data["itemType"] = item_type

        # Get creators
        creator_rows = conn.execute(
            "SELECT c.firstName, c.lastName, ct.creatorType "
            "FROM itemCreators ic "
            "JOIN creators c ON ic.creatorID = c.creatorID "
            "JOIN creatorTypes ct ON ic.creatorTypeID = ct.creatorTypeID "
            "WHERE ic.itemID = ? "
            "ORDER BY ic.orderIndex",
            (item_id,),
        ).fetchall()
        item_data["creators"] = [
            {
                "firstName": r["firstName"] or "",
                "lastName": r["lastName"] or "",
                "creatorType": r["creatorType"],
            }
            for r in creator_rows
        ]
        return item_data

    # === Remote Context Implementation ===

    def _search_remote(self, query: PaperQuery) -> Iterator[PaperCandidate]:
        """Search papers from Zotero Web API."""
        from pyzotero import zotero as pyzotero

        if not self.http_client:
            _log.warning("http_client required for remote mode")
            return

        zot = pyzotero.Zotero(self.library_id, self.library_type, self.api_key)

        # Build query - limited search capabilities
        query_kwargs: dict = {}

        if query.title:
            # Zotero API doesn't support full-text search, use itemType filter only
            pass

        try:
            items = zot.everything(zot.items(**query_kwargs))

            # Filter out attachments and notes
            items = [
                it
                for it in items
                if it.get("data", {}).get("itemType")
                not in ("attachment", "note", "linkAttachment")
            ]

            for item in items:
                data = item.get("data", {})
                candidate = _item_to_candidate(data, "zotero-api")

                if matches_query(candidate, query):
                    yield candidate

        except Exception as e:
            _log.error("Zotero API error: %s", e)

    def _fetch_remote_by_id(self, paper_id: str) -> PaperCandidate | None:
        """Fetch paper by DOI or key from Zotero Web API."""
        from pyzotero import zotero as pyzotero

        if not self.http_client:
            _log.warning("http_client required for remote mode")
            return None

        zot = pyzotero.Zotero(self.library_id, self.library_type, self.api_key)

        try:
            # Check if it's a DOI
            if paper_id.startswith("10."):
                # Search by DOI
                items = zot.everything(zot.items(filter={"DOI": paper_id}))
                if items:
                    data = items[0].get("data", {})
                    return _item_to_candidate(data, "zotero-api")
            else:
                # Assume it's a Zotero key
                item = zot.item(paper_id)
                if item:
                    data = item.get("data", {})
                    return _item_to_candidate(data, "zotero-api")

        except Exception as e:
            _log.debug("Failed to fetch Zotero item: %s", e)

        return None
