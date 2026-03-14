"""sources/zotero.py — Zotero Web API / Local SQLite import.

Refactored to use ZoteroSource class with PaperSource Protocol.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

from scholaraio.papers import PaperMetadata, _extract_lastname
from scholaraio.log import get_logger

if TYPE_CHECKING:
    from scholaraio.http import HTTPClient

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


def _item_to_dict(item_data: dict, source_label: str) -> dict:
    """Convert Zotero item to standardized dict."""
    authors = _creators_to_authors(item_data.get("creators", []))
    first_author = authors[0] if authors else ""
    first_author_lastname = _extract_lastname(first_author) if first_author else ""

    journal = (
        item_data.get("publicationTitle")
        or item_data.get("proceedingsTitle")
        or item_data.get("bookTitle")
        or ""
    )

    item_type = item_data.get("itemType", "")
    paper_type = ITEM_TYPE_MAP.get(item_type, item_type)

    return {
        "id": _clean_doi(item_data.get("DOI", "")) or item_data.get("title", ""),
        "title": item_data.get("title", ""),
        "authors": authors,
        "first_author": first_author,
        "first_author_lastname": first_author_lastname,
        "year": _parse_zotero_date(item_data.get("date", "")),
        "doi": _clean_doi(item_data.get("DOI", "")),
        "journal": journal,
        "abstract": item_data.get("abstractNote", ""),
        "paper_type": paper_type,
        "volume": item_data.get("volume", "") or "",
        "issue": item_data.get("issue", "") or "",
        "pages": item_data.get("pages", "") or "",
        "publisher": item_data.get("publisher", "") or "",
        "issn": item_data.get("ISSN", "") or "",
        "source_file": source_label,
        "extraction_method": "zotero",
    }


# ============================================================================
#  ZoteroSource class (PaperSource Protocol)
# ============================================================================


@dataclass(frozen=True)
class ZoteroSource:
    """Import from Zotero API or local SQLite as paper source.

    Implements PaperSource Protocol for unified access to Zotero data.

    Example:
        from scholaraio.http import RequestsClient
        client = RequestsClient()
        source = ZoteroSource(http_client=client, library_id="123456", api_key="xxx")
        for paper in source.fetch():
            print(paper["title"])
    """

    library_id: str = ""
    api_key: str = ""
    library_type: str = "user"
    http_client: HTTPClient | None = None

    @property
    def name(self) -> str:
        return "zotero"

    def fetch(
        self,
        db_path: Path | None = None,
        collection_key: str | None = None,
        item_types: list[str] | None = None,
        **kwargs,
    ) -> Iterator[dict]:
        """Fetch papers from Zotero.

        If db_path is provided, use local SQLite mode.
        Otherwise, use API mode if library_id and api_key are set.
        """
        if db_path and db_path.exists():
            yield from self._fetch_local(db_path, collection_key, item_types)
            return

        if self.library_id and self.api_key:
            yield from self._fetch_api(collection_key, item_types)
            return

        _log.warning("No db_path or library_id/api_key provided")

    def _fetch_local(
        self,
        db_path: Path,
        collection_key: str | None = None,
        item_types: list[str] | None = None,
    ) -> Iterator[dict]:
        """Fetch from local SQLite database."""
        conn = sqlite3.connect(f"file:{db_path}?immutable=1", uri=True)
        conn.row_factory = sqlite3.Row

        try:
            # Get collection filter
            item_id_filter = self._get_collection_filter(conn, collection_key)

            # Get items
            items = self._query_items(conn, item_types, item_id_filter)

            for item_id, item_type in items:
                item_data = self._fetch_item_data(conn, item_id, item_type)
                yield _item_to_dict(item_data, "zotero.sqlite")

        finally:
            conn.close()

    def _get_collection_filter(
        self,
        conn: sqlite3.Connection,
        collection_key: str | None,
    ) -> set[int] | None:
        """Get item IDs for a collection."""
        if not collection_key:
            return None
        rows = conn.execute(
            "SELECT itemID FROM collectionItems ci "
            "JOIN collections c ON ci.collectionID = c.collectionID "
            "WHERE c.key = ?",
            (collection_key,),
        ).fetchall()
        return {r["itemID"] for r in rows}

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

    def _fetch_api(
        self,
        collection_key: str | None = None,
        item_types: list[str] | None = None,
    ) -> Iterator[dict]:
        """Fetch from Zotero Web API."""
        from pyzotero import zotero as pyzotero

        zot = pyzotero.Zotero(self.library_id, self.library_type, self.api_key)

        query_kwargs: dict = {}
        if item_types:
            query_kwargs["itemType"] = " || ".join(item_types)

        if collection_key:
            items = zot.everything(zot.collection_items(collection_key, **query_kwargs))
        else:
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
            yield _item_to_dict(data, "zotero-api")

    def count(self, db_path: Path | None = None, **kwargs) -> int:
        """Count papers in Zotero source."""
        return sum(1 for _ in self.fetch(db_path=db_path))
