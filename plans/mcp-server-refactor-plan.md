# mcp.py Redesign Plan

> Complete redesign of MCP API for maximum simplicity.

---

## 0. Current State (Problem)

### 20+ Separate Tools (996 lines)
```
search, search_author, vsearch, unified_search, top_cited
show_paper, lookup_paper
get_references, get_citing_papers
build_index, build_vectors
topic_overview, topic_papers, build_topics
workspace_list, workspace_show, workspace_add, workspace_remove
export_bibtex, export_citations
attach_pdf
enrich_toc, enrich_l3, refetch, backfill_abstract, rename_paper
```

---

## 1. Redesign: Unified Tools with Mode Parameter

### Principle: One tool per domain, mode parameter for variation

| Domain | Current Tools | Redesigned Tools |
|--------|---------------|------------------|
| Search | 5 separate | **1 unified** |
| Index | 2 separate | **1 unified** |
| Paper | 2 separate | **1 unified** |
| Citation | 2 separate | **1 unified** |
| Topic | 3 separate | **1 unified** |
| Workspace | 4 separate | **1 unified** |
| Export | 2 separate | **1 unified** |

### New API (Target: ~150 lines)

```python
"""linkora MCP - Unified API Design."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from linkora.config import get_config
from linkora.log import get_logger
from linkora.index import SearchIndex, VectorIndex
from linkora.papers import PaperStore

mcp = FastMCP("linkora")
_log = get_logger(__name__)

_config = None

def _get_config():
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
    mode: str = "fts",  # fts, author, vector, hybrid, cited
    top_k: int = 20,
    year: str | None = None,
    journal: str | None = None,
    paper_type: str | None = None,
    workspace: str | None = None,
) -> str:
    """Unified search - mode determines search type."""
    try:
        cfg = _get_config()
        paper_ids = _resolve_workspace(workspace, cfg) if workspace else None

        with SearchIndex(cfg.index_db) as idx:
            if mode == "fts":
                results = idx.search(query, top_k, year, journal, paper_type, paper_ids)
            elif mode == "author":
                results = idx.search_author(query, top_k, year, journal, paper_type, paper_ids)
            elif mode == "cited":
                results = idx.top_cited(top_k, year, journal, paper_type, paper_ids)
            elif mode in ("vector", "hybrid"):
                return json.dumps({"error": "Use vector_search tool", "mode": mode})
            else:
                return json.dumps({"error": "Invalid mode", "valid_modes": ["fts", "author", "cited"]})

        return json.dumps(results, ensure_ascii=False)
    except FileNotFoundError:
        return json.dumps({"error": "index_not_found", "message": "Run: linkora index"})
    except Exception as e:
        _log.exception("search failed")
        return json.dumps({"error": "internal", "message": str(e)})


@mcp.tool()
def vector_search(
    query: str,
    top_k: int = 10,
    year: str | None = None,
    journal: str | None = None,
    paper_type: str | None = None,
    workspace: str | None = None,
) -> str:
    """Semantic vector search."""
    try:
        cfg = _get_config()
        with VectorIndex(cfg.index_db) as vidx:
            results = vidx.search(query, top_k, year, journal, paper_type)
        return json.dumps(results, ensure_ascii=False)
    except ImportError:
        return json.dumps({"error": "missing_dependency", "install_hint": "pip install linkora[embed]"})
    except FileNotFoundError:
        return json.dumps({"error": "vectors_not_found", "message": "Run: linkora embed"})
    except Exception as e:
        return json.dumps({"error": "internal", "message": str(e)})


# ============================================================================
#  Unified Index Tool
# ============================================================================

@mcp.tool()
def index(
    mode: str = "fts",  # fts, vector
    rebuild: bool = False,
) -> str:
    """Build search index."""
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
            return json.dumps({"error": "Invalid mode", "valid_modes": ["fts", "vector"]})
    except ImportError:
        return json.dumps({"error": "missing_dependency", "install_hint": "pip install linkora[embed]"})
    except Exception as e:
        return json.dumps({"error": "internal", "message": str(e)})


# ============================================================================
#  Unified Paper Tool
# ============================================================================

@mcp.tool()
def paper(
    ref: str,
    action: str = "show",  # show, lookup
    layer: int = 2,
) -> str:
    """Show or lookup paper."""
    try:
        cfg = _get_config()

        if action == "show":
            from linkora.loader import PaperData
            paper_d = _resolve_paper(ref, cfg)
            p = PaperData.from_dir(paper_d)
            result = {"title": p.title, "authors": p.authors, "year": p.year, "journal": p.journal}
            if layer >= 2:
                result["abstract"] = p.abstract
            if layer >= 3:
                result["conclusion"] = p.conclusion
            if layer >= 4:
                result["full_text"] = p.content
            return json.dumps(result, ensure_ascii=False)

        elif action == "lookup":
            from linkora.index import lookup_paper
            result = lookup_paper(cfg.index_db, ref)
            return json.dumps(result, ensure_ascii=False)

        else:
            return json.dumps({"error": "Invalid action", "valid_actions": ["show", "lookup"]})
    except Exception as e:
        return json.dumps({"error": "internal", "message": str(e)})


# ============================================================================
#  Unified Citation Tool
# ============================================================================

@mcp.tool()
def citation(
    ref: str,
    direction: str = "references",  # references, citing
) -> str:
    """Get citation relationships."""
    try:
        cfg = _get_config()
        paper_d = _resolve_paper(ref, cfg)
        meta = PaperStore(cfg.papers_dir).read_meta(paper_d)
        uuid = meta["id"]

        if direction == "references":
            from linkora.index import get_references
            results = get_references(uuid, cfg.index_db)
        elif direction == "citing":
            from linkora.index import get_citing_papers
            results = get_citing_papers(uuid, cfg.index_db)
        else:
            return json.dumps({"error": "Invalid direction", "valid_directions": ["references", "citing"]})

        return json.dumps(results, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": "internal", "message": str(e)})


# ============================================================================
#  Unified Topic Tool
# ============================================================================

@mcp.tool()
def topic(
    action: str = "overview",  # overview, build, papers
    topic_id: int | None = None,
    rebuild: bool = False,
    min_topic_size: int = 5,
    nr_topics: int = 0,
) -> str:
    """Topic modeling tools."""
    try:
        from linkora.topics import load_model, get_topic_overview, get_topic_papers
        from linkora.topics import build_topics as _build_topics
    except ImportError:
        return json.dumps({"error": "missing_dependency", "install_hint": "pip install linkora[topics]"})

    try:
        cfg = _get_config()
        model_dir = cfg.topics_model_dir

        if action == "build":
            if not rebuild and (model_dir / "bertopic_model.pkl").exists():
                model = load_model(model_dir)
            else:
                store = PaperStore(cfg.papers_dir)
                model = _build_topics(cfg.index_db, cfg.papers_dir, min_topic_size, nr_topics, model_dir, cfg)
            overview = get_topic_overview(model)
            n_outliers = sum(1 for t in overview if t.get("topic_id") == -1)
            return json.dumps({"topics": len(overview) - (1 if n_outliers else 0), "outliers": n_outliers})

        elif action == "overview":
            if not (model_dir / "bertopic_model.pkl").exists():
                return json.dumps({"error": "model_not_found", "message": "Run topic action=build first"})
            model = load_model(model_dir)
            overview = get_topic_overview(model)
            return json.dumps(overview, ensure_ascii=False)

        elif action == "papers":
            if topic_id is None:
                return json.dumps({"error": "missing_param", "message": "topic_id required"})
            if not (model_dir / "bertopic_model.pkl").exists():
                return json.dumps({"error": "model_not_found"})
            model = load_model(model_dir)
            papers = get_topic_papers(model, topic_id)
            return json.dumps(papers, ensure_ascii=False)

        else:
            return json.dumps({"error": "Invalid action", "valid_actions": ["overview", "build", "papers"]})
    except Exception as e:
        return json.dumps({"error": "internal", "message": str(e)})


# ============================================================================
#  Unified Workspace Tool
# ============================================================================

@mcp.tool()
def workspace(
    name: str,
    action: str = "list",  # list, show, add, remove
    refs: list[str] | None = None,
) -> str:
    """Workspace operations."""
    try:
        from linkora import workspace as ws_mod

        cfg = _get_config()
        ws_root = cfg._root / "workspace"

        if action == "list":
            names = ws_mod.list_workspaces(ws_root)
            return json.dumps(names, ensure_ascii=False)

        ws_dir = ws_root / name

        if action == "show":
            if not ws_dir.exists():
                return json.dumps({"error": "not_found", "message": f"Workspace: {name}"})
            papers = ws_mod.show(ws_dir, cfg.index_db)
            return json.dumps(papers, ensure_ascii=False)

        elif action == "add":
            if refs is None:
                return json.dumps({"error": "missing_param", "message": "refs required"})
            if not ws_dir.exists():
                ws_mod.create(ws_dir)
            added = ws_mod.add(ws_dir, refs, cfg.index_db)
            return json.dumps({"added": added}, ensure_ascii=False)

        elif action == "remove":
            if refs is None:
                return json.dumps({"error": "missing_param", "message": "refs required"})
            if not ws_dir.exists():
                return json.dumps({"error": "not_found", "message": f"Workspace: {name}"})
            removed = ws_mod.remove(ws_dir, refs, cfg.index_db)
            return json.dumps({"removed": removed}, ensure_ascii=False)

        else:
            return json.dumps({"error": "Invalid action", "valid_actions": ["list", "show", "add", "remove"]})
    except Exception as e:
        return json.dumps({"error": "internal", "message": str(e)})


# ============================================================================
#  Helpers
# ============================================================================

def _resolve_paper(ref: str, cfg) -> "Path":
    """Resolve paper reference to directory."""
    from pathlib import Path
    from linkora.index import lookup_paper
    from linkora.papers import iter_paper_dirs, read_meta

    papers_dir = cfg.papers_dir
    d = papers_dir / ref
    if (d / "meta.json").exists():
        return d

    try:
        reg = lookup_paper(cfg.index_db, ref)
        if reg:
            d = papers_dir / reg["dir_name"]
            if (d / "meta.json").exists():
                return d
    except FileNotFoundError:
        pass

    for pdir in iter_paper_dirs(papers_dir):
        try:
            data = read_meta(pdir)
            if data.get("id") == ref or data.get("doi") == ref:
                return pdir
        except:
            continue
    raise ValueError(f"Paper not found: {ref}")


def _resolve_workspace(name: str, cfg) -> "set[str] | None":
    """Resolve workspace to paper IDs."""
    from linkora import workspace as ws_mod
    ws_dir = cfg._root / "workspace" / name
    return ws_mod.read_paper_ids(ws_dir) or None


# ============================================================================
#  Entry point
# ============================================================================

def main():
    mcp.run()


if __name__ == "__main__":
    main()
```

---

## 2. API Comparison

### Before (20+ tools)
```
search, search_author, vsearch, unified_search, top_cited
show_paper, lookup_paper
get_references, get_citing_papers
build_index, build_vectors
topic_overview, topic_papers, build_topics
workspace_list, workspace_show, workspace_add, workspace_remove
```

### After (7 unified tools)
```
search          (mode: fts|author|vector|cited)
vector_search   (separate for import reasons)
index           (mode: fts|vector)
paper           (action: show|lookup)
citation        (direction: references|citing)
topic           (action: overview|build|papers)
workspace       (action: list|show|add|remove)
```

---

## 3. Line Reduction

| Metric | Before | After | Reduction |
|--------|--------|-------|-----------|
| Tools | 20+ | 7 | **65%** |
| Lines | ~996 | ~300 | **70%** |
| Helpers | Multiple | 2 | **80%** |

---

## 4. Valid Parameters by Tool

### search(query, mode, top_k, year, journal, paper_type, workspace)
- `mode`: "fts" | "author" | "cited"
- Note: "vector" and "hybrid" redirect to vector_search

### index(mode, rebuild)
- `mode`: "fts" | "vector"

### paper(ref, action, layer)
- `action`: "show" | "lookup"
- `layer`: 1-4 (for show)

### citation(ref, direction)
- `direction`: "references" | "citing"

### topic(action, topic_id, rebuild, min_topic_size, nr_topics)
- `action`: "overview" | "build" | "papers"

### workspace(name, action, refs)
- `action`: "list" | "show" | "add" | "remove"

---

## 5. Next Steps

1. **Approve** → Implementation
2. **Design matches CLI patterns**: Uses same underlying APIs but unified interface
