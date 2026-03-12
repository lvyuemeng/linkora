"""CLI output formatting utilities."""

from __future__ import annotations


def ui(message: str = "") -> None:
    """Print a UI message (wrapper around log.ui for CLI use)."""
    from scholaraio.log import ui as _ui

    _ui(message)


def print_search_result(idx: int, r: dict, extra: str = "") -> None:
    """Print a search result with consistent formatting."""
    authors = r.get("authors") or ""
    author_display = authors.split(",")[0].strip() + (
        " et al." if "," in authors else ""
    )
    cite = r.get("citation_count") or ""
    cite_suffix = f"  [cited: {cite}]" if cite else ""
    extra_suffix = f"  ({extra})" if extra else ""
    display_id = r.get("dir_name") or r["paper_id"]

    ui(f"[{idx}] {display_id}{extra_suffix}")
    ui(
        f"     {author_display} | {r.get('year', '?')} | {r.get('journal', '?')}{cite_suffix}"
    )
    ui(f"     {r['title']}")
    ui()


def format_citations(cc: dict) -> str:
    """Format citation counts from multiple sources."""
    if not cc:
        return ""
    parts = []
    for src in ("semantic_scholar", "openalex", "crossref"):
        if src in cc:
            label = {"semantic_scholar": "S2", "openalex": "OA", "crossref": "CR"}[src]
            parts.append(f"{label}:{cc[src]}")
    return " | ".join(parts)


def print_header(paper_data) -> None:
    """Print paper header info from PaperData object."""
    l1 = paper_data.to_dict()
    authors = l1.get("authors") or []
    author_str = ", ".join(authors[:3])
    if len(authors) > 3:
        author_str += f" et al. ({len(authors)} total)"

    ui(f"paper_id : {paper_data.paper_id}")
    ui(f"title    : {paper_data.title}")
    ui(f"authors  : {author_str}")
    ui(f"year     : {paper_data.year or '?'}  |  journal: {paper_data.journal or '?'}")

    if paper_data.DOI:
        ui(f"doi      : {paper_data.DOI}")
    if paper_data.paper_type:
        ui(f"type     : {paper_data.paper_type}")

    cite_str = format_citations(paper_data.citation_count)
    if cite_str:
        ui(f"cited    : {cite_str}")

    ids = l1.get("ids") or {}
    if ids.get("semantic_scholar_url"):
        ui(f"S2       : {ids['semantic_scholar_url']}")
    if ids.get("openalex_url"):
        ui(f"OpenAlex : {ids['openalex_url']}")


def print_results_list(results: list[dict], title: str | None = None) -> None:
    """Print a list of search results."""
    if title:
        ui(f"{title}\n")

    if not results:
        ui("No results found.")
        return

    for i, r in enumerate(results, start=1):
        print_search_result(i, r)


__all__ = [
    "ui",
    "print_search_result",
    "format_citations",
    "print_header",
    "print_results_list",
]
