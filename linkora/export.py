"""
export.py — 论文导出（BibTeX 等格式）
======================================

将 meta.json 转换为标准引用格式输出。
"""

from __future__ import annotations

import re
from pathlib import Path


def _bibtex_escape(text: str) -> str:
    """Escape special LaTeX characters in text."""
    for ch in ("&", "%", "#", "_"):
        text = text.replace(ch, f"\\{ch}")
    return text


def _make_cite_key(meta: dict) -> str:
    """Generate a BibTeX citation key: LastName2023Title."""
    last = meta.get("first_author_lastname") or "Unknown"
    last = re.sub(r"[^a-zA-Z]", "", last)
    year = str(meta.get("year") or "")
    title = meta.get("title") or ""
    # first meaningful word of title (skip short words)
    word = ""
    for w in title.split():
        cleaned = re.sub(r"[^a-zA-Z]", "", w)
        if len(cleaned) > 3:
            word = cleaned.capitalize()
            break
    return f"{last}{year}{word}"


def _type_to_bibtex(paper_type: str) -> str:
    """Map paper_type to BibTeX entry type."""
    mapping = {
        "journal-article": "article",
        "review": "article",
        "book-chapter": "inbook",
        "book": "book",
        "proceedings-article": "inproceedings",
        "conference-paper": "inproceedings",
        "thesis": "phdthesis",
        "dissertation": "phdthesis",
        "preprint": "misc",
    }
    return mapping.get(paper_type or "", "article")


def meta_to_bibtex(meta: dict) -> str:
    """Convert a single meta.json dict to a BibTeX entry string.

    Args:
        meta: Paper metadata dictionary.

    Returns:
        Formatted BibTeX entry string.
    """
    entry_type = _type_to_bibtex(meta.get("paper_type") or "")
    key = _make_cite_key(meta)

    fields: list[tuple[str, str]] = []

    if meta.get("title"):
        fields.append(("title", "{" + _bibtex_escape(meta["title"]) + "}"))
    if meta.get("authors"):
        fields.append(("author", _bibtex_escape(" and ".join(meta["authors"]))))
    if meta.get("year"):
        fields.append(("year", str(meta["year"])))
    if meta.get("journal"):
        fields.append(("journal", _bibtex_escape(meta["journal"])))
    if meta.get("volume"):
        fields.append(("volume", meta["volume"]))
    if meta.get("issue"):
        fields.append(("number", meta["issue"]))
    if meta.get("pages"):
        fields.append(("pages", meta["pages"]))
    if meta.get("publisher"):
        fields.append(("publisher", _bibtex_escape(meta["publisher"])))
    if meta.get("issn"):
        fields.append(("issn", meta["issn"]))
    if meta.get("doi"):
        fields.append(("doi", meta["doi"]))
    if meta.get("abstract"):
        fields.append(("abstract", "{" + _bibtex_escape(meta["abstract"]) + "}"))

    lines = [f"@{entry_type}{{{key},"]
    for name, val in fields:
        lines.append(f"  {name} = {{{val}}},")
    lines.append("}")
    return "\n".join(lines)


def export_bibtex(
    papers_dir: Path,
    *,
    paper_ids: list[str] | None = None,
    year: str | None = None,
    journal: str | None = None,
) -> str:
    """Export papers to BibTeX format.

    Args:
        papers_dir: Root papers directory.
        paper_ids: Specific paper dir names to export. None = all.
        year: Year filter (e.g. "2023", "2020-2024").
        journal: Journal name filter (case-insensitive substring).

    Returns:
        Complete BibTeX string with all matching entries.
    """
    from linkora.papers import iter_paper_dirs, parse_year_range, read_meta

    year_start, year_end = parse_year_range(year) if year else (None, None)

    entries: list[str] = []
    for d in iter_paper_dirs(papers_dir):
        if paper_ids and d.name not in paper_ids:
            continue

        meta = read_meta(d)

        # filters
        if year_start is not None and (meta.get("year") or 0) < year_start:
            continue
        if year_end is not None and (meta.get("year") or 9999) > year_end:
            continue
        if journal and journal.lower() not in (meta.get("journal") or "").lower():
            continue

        entries.append(meta_to_bibtex(meta))

    return "\n\n".join(entries) + "\n" if entries else ""
