"""
mcp.py — ScholarAIO MCP Protocol Adapter

Unified API design: 4 tools instead of 20+ separate tools.
Each tool uses mode/action parameters for variation.

Entry point: scholaraio-mcp
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from scholaraio.config import get_config
from scholaraio.log import get_logger
from scholaraio.index import SearchIndex, VectorIndex
from scholaraio.papers import PaperStore

mcp = FastMCP("scholaraio")
_log = get_logger(__name__)

_config = None


def _get_config():
    """Get cached config."""
    global _config
    if _config is None:
        _config = get_config()
    return _config


# ============================================================================
#  Unified Search Tool
# ============================================================================


@mcp.tool()
def search(
    query: str = "",
    mode: str = "fts",
    top_k: int = 20,
    year: str | None = None,
    journal: str | None = None,
    paper_type: str | None = None,
    workspace: str | None = None,
) -> str:
    """Unified search - mode determines search type.

    Modes:
        fts     - Full-text search using FTS5
        author  - Search by author name
        cited   - Top cited papers
    """
    try:
        cfg = _get_config()
        paper_ids = _resolve_workspace(workspace, cfg) if workspace else None

        with SearchIndex(cfg.index_db) as idx:
            if mode == "fts":
                results = idx.search(
                    query,
                    top_k,
                    year=year,
                    journal=journal,
                    paper_type=paper_type,
                    paper_ids=paper_ids,
                )
            elif mode == "author":
                results = idx.search_author(
                    query,
                    top_k,
                    year=year,
                    journal=journal,
                    paper_type=paper_type,
                    paper_ids=paper_ids,
                )
            elif mode == "cited":
                results = idx.top_cited(
                    top_k,
                    year=year,
                    journal=journal,
                    paper_type=paper_type,
                    paper_ids=paper_ids,
                )
            else:
                return json.dumps(
                    {"error": "Invalid mode", "valid_modes": ["fts", "author", "cited"]}
                )

        return json.dumps(results, ensure_ascii=False)
    except FileNotFoundError:
        return json.dumps(
            {"error": "index_not_found", "message": "Run: scholaraio index"}
        )
    except Exception as e:
        _log.exception("search failed")
        return json.dumps({"error": "internal", "message": str(e)})


@mcp.tool()
def vector_search(
    query: str = "",
    top_k: int = 10,
    year: str | None = None,
    journal: str | None = None,
    paper_type: str | None = None,
    workspace: str | None = None,
) -> str:
    """Semantic vector search using Qwen3-Embedding."""
    try:
        cfg = _get_config()
        paper_ids = _resolve_workspace(workspace, cfg) if workspace else None

        with VectorIndex(cfg.index_db) as vidx:
            results = vidx.search(
                query,
                top_k,
                year=year,
                journal=journal,
                paper_type=paper_type,
                paper_ids=paper_ids,
            )
        return json.dumps(results, ensure_ascii=False)
    except ImportError:
        return json.dumps(
            {
                "error": "missing_dependency",
                "install_hint": "pip install scholaraio[embed]",
            }
        )
    except FileNotFoundError:
        return json.dumps(
            {"error": "vectors_not_found", "message": "Run: scholaraio embed"}
        )
    except Exception as e:
        return json.dumps({"error": "internal", "message": str(e)})


# ============================================================================
#  Unified Index Tool
# ============================================================================


@mcp.tool()
def index(
    mode: str = "fts",
    rebuild: bool = False,
) -> str:
    """Build search index.

    Modes:
        fts     - Build FTS5 full-text index
        vector  - Build FAISS vector index
    """
    try:
        cfg = _get_config()
        store = PaperStore(cfg.papers_dir)

        if mode == "fts":
            with SearchIndex(cfg.index_db) as idx:
                count = idx.rebuild(store) if rebuild else idx.update(store)
            return json.dumps({"status": "ok", "indexed": count, "type": "fts"})
        elif mode == "vector":
            with VectorIndex(cfg.index_db) as vidx:
                count = vidx.rebuild(store) if rebuild else vidx.update(store)
            return json.dumps({"status": "ok", "embedded": count, "type": "vector"})
        else:
            return json.dumps(
                {"error": "Invalid mode", "valid_modes": ["fts", "vector"]}
            )
    except ImportError:
        return json.dumps(
            {
                "error": "missing_dependency",
                "install_hint": "pip install scholaraio[embed]",
            }
        )
    except Exception as e:
        return json.dumps({"error": "internal", "message": str(e)})


# ============================================================================
#  Unified Paper Tool
# ============================================================================


@mcp.tool()
def paper(
    ref: str,
    action: str = "show",
    layer: int = 2,
) -> str:
    """Show paper content or list papers.

    Actions:
        show    - Show paper content (layer 1-4 detail level)
        list    - List all papers
    """
    try:
        cfg = _get_config()
        store = PaperStore(cfg.papers_dir)

        if action == "list":
            papers = list(store.iter_papers())
            # Convert to list of dicts
            results = []
            for pdir in papers:
                try:
                    data = store.read_meta(pdir)
                    results.append(data)
                except Exception:
                    continue
            return json.dumps(results, ensure_ascii=False)

        if action == "show":
            paper_d = _resolve_paper(ref, cfg)
            data = store.read_meta(paper_d)

            result = {
                "title": data.get("title"),
                "authors": data.get("authors", []),
                "year": data.get("year"),
                "journal": data.get("journal"),
                "doi": data.get("doi"),
                "paper_type": data.get("paper_type"),
            }

            if layer >= 2:
                result["abstract"] = data.get("abstract")
            if layer >= 3:
                # Try to read conclusion from paper.md if available
                md_path = paper_d / "paper.md"
                if md_path.exists():
                    content = md_path.read_text(encoding="utf-8")
                    # Simple extraction - find conclusion section
                    if "## Conclusion" in content:
                        conclusion_start = content.find("## Conclusion")
                        result["conclusion"] = content[conclusion_start:]
                    else:
                        result["conclusion"] = ""
            if layer >= 4:
                md_path = paper_d / "paper.md"
                if md_path.exists():
                    result["full_text"] = md_path.read_text(encoding="utf-8")

            return json.dumps(result, ensure_ascii=False)

        else:
            return json.dumps(
                {"error": "Invalid action", "valid_actions": ["show", "list"]}
            )
    except Exception as e:
        return json.dumps({"error": "internal", "message": str(e)})


# ============================================================================
#  Helpers
# ============================================================================


def _resolve_paper(ref: str, cfg) -> Path:
    """Resolve paper reference to directory."""
    from scholaraio.papers import iter_paper_dirs, read_meta

    papers_dir = cfg.papers_dir
    d = papers_dir / ref
    if (d / "meta.json").exists():
        return d

    # Scan by id or doi
    for pdir in iter_paper_dirs(papers_dir):
        try:
            data = read_meta(pdir)
            if data.get("id") == ref or data.get("doi") == ref:
                return pdir
        except Exception:
            continue
    raise ValueError(f"Paper not found: {ref}")


def _resolve_workspace(name: str, cfg) -> "set[str] | None":
    """Resolve workspace to paper IDs."""
    ws_dir = cfg._root / "workspace" / name
    if not ws_dir.exists():
        return None
    # Read paper_ids file if exists
    ids_file = ws_dir / "paper_ids.txt"
    if ids_file.exists():
        ids = ids_file.read_text(encoding="utf-8").strip().split("\n")
        return set(ids)
    return None


# ============================================================================
#  Entry point
# ============================================================================


def main():
    """Entry point for scholaraio-mcp command."""
    mcp.run()


if __name__ == "__main__":
    main()
