# Loader Integration Plan: Where and How to Use loader.py

> Analysis of where `linkora/loader.py` should be used in the workflow.
> Based on analysis of papers.py, loader.py, ingest-connection-plan.md, and AGENT.md philosophy.

---

## 1. Current Data Flow Analysis

### 1.1 Existing Pipeline (from ingest/pipeline.py)

```
PaperCandidate
    ↓
get_pdf_path()          [download/cached PDF]
    ↓
client.call()           [MinerU API - PDF parsing]
    ↓
_extract_markdown()     [extract MD from response]
    ↓
_extract_metadata()    [extract.py - regex extraction]
    ↓
_save_to_store()       [PaperStore - meta.json + paper.md]
    ↓
IngestResult
```

### 1.2 What loader.py Does (L1-L4 Layers)

| Layer | Content | Source | Handled By |
|-------|---------|--------|-------------|
| L1 | title, authors, year, journal, doi | meta.json | ingest (extract.py) |
| L2 | abstract | meta.json | ingest (extract.py) |
| L3 | conclusion | meta.json | **loader (enrichment)** |
| L4 | full markdown | paper.md | Direct read |

---

## 2. Integration Points for loader.py

### 2.1 When to Use loader

The loader should be used **after ingestion** for enriching papers with:
1. **TOC extraction** - Extract table of contents from markdown
2. **Conclusion extraction** - Extract conclusion section from markdown

### 2.2 Not for Ingest Pipeline

The loader should NOT be part of the main ingest pipeline because:
- **L3 enrichment requires LLM calls** - expensive, optional
- **Can be done asynchronously** - not blocking ingestion
- **Can be retried** - enrichment failures shouldn't block paper availability

---

## 3. Completed Implementation

### 3.1 Two-Phase Workflow

```mermaid
graph TD
    subgraph Phase 1: Ingestion (Core)
        A[PaperCandidate] --> B[get_pdf_path]
        B --> C[MinerU API]
        C --> D[extract.py]
        D --> E[PaperStore]
        E --> F[Paper available for search]
    end

    subgraph Phase 2: Enrichment (Optional)
        F --> G[PaperEnricher.enrich_toc]
        G --> H[PaperEnricher.enrich_conclusion]
        H --> I[Enhanced metadata]
    end
```

### 3.2 PaperEnricher Design (Completed)

The `PaperEnricher` class provides:

```python
class PaperEnricher:
    """Orchestrates TOC and conclusion extraction."""

    def __init__(
        self,
        papers_dir: Path,
        config: Config,
        runner: LLMRunner,
    ) -> None:
        """Initialize with papers directory, config, and runner."""
        ...

    def enrich_toc(
        self,
        paper_id: str,
        *,
        force: bool = False,
    ) -> bool:
        """Enrich TOC for a paper."""
        ...

    def enrich_conclusion(
        self,
        paper_id: str,
        *,
        force: bool = False,
    ) -> bool:
        """Enrich conclusion for a paper."""
        ...
```

### 3.3 Usage Pattern

```python
from linkora.loader import PaperEnricher
from linkora.llm import LLMRunner
from linkora.http import RequestsClient

# Create dependencies externally (context injection)
http_client = RequestsClient()
api_key = config.resolve_llm_api_key()
runner = LLMRunner(config.llm, http_client, api_key)

# Initialize enricher with dependencies
enricher = PaperEnricher(papers_dir, config, runner)

# Use simpler API
enricher.enrich_toc(paper_id)
enricher.enrich_conclusion(paper_id)
```

---

## 4. Implementation Changes Summary

### 4.1 Completed Changes

| Item | Status | Description |
|------|--------|-------------|
| TYPE_CHECKING fix | ✅ Done | Import Config directly in loader.py |
| Context injection | ✅ Done | PaperEnricher accepts config and runner in __init__ |
| Dictionary dispatch | ✅ Done | Added StrategyKey enum and dict-based dispatch |
| Path helpers | ✅ Done | Added paper_dir(), meta_path(), md_path() to PaperStore |
| Legacy removal | ✅ Done | Removed iter_paper_dirs, read_meta, write_meta from papers.py |

### 4.2 What Was NOT Needed

Based on analysis, these were not needed:
- **EnrichmentConfig dataclass** - PaperEnricher already has config and force parameters
- **EnrichmentResult dataclass** - Methods return bool (success/failure)
- **enrich_paper() function** - PaperEnricher class handles this
- **enrich_all_papers() function** - Can iterate over PaperEnricher

---

## 5. Key Design Points (AGENT.md Compliant)

1. **Context Injection** - Dependencies (config, runner) passed to __init__, not created internally
2. **Single Responsibility** - PaperEnricher only handles TOC and conclusion extraction
3. **Layered Loading** - L1/L2 via ingest, L3/L4 via loader
4. **Two-Phase Workflow** - Phase 1: ingest, Phase 2: enrich (optional)

---

## 6. Remaining Items (Optional)

### 6.1 CLI Integration (Optional)

If CLI enrich command is needed:

```python
# In cli/commands.py
def cmd_enrich(args, ctx):
    runner = LLMRunner(ctx.config.llm, ctx.http_client, ctx.config.resolve_llm_api_key())
    enricher = PaperEnricher(ctx.config.papers_dir, ctx.config, runner)
    
    # Process papers
    for paper_id in ctx.paper_store().iter_papers():
        enricher.enrich_toc(paper_id)
        enricher.enrich_conclusion(paper_id)
```

### 6.2 AppContext Integration (Optional)

If loader needs to be accessed via AppContext:

```python
# In cli/context.py
class AppContext:
    def paper_enricher(self) -> PaperEnricher:
        if not hasattr(self, '_enricher'):
            runner = LLMRunner(self._config.llm, self._http_client, self._config.resolve_llm_api_key())
            self._enricher = PaperEnricher(self._config.papers_dir, self._config, runner)
        return self._enricher
```

---

## 7. Summary

| Category | Status |
|----------|--------|
| loader.py refactoring | ✅ Complete |
| papers.py path helpers | ✅ Complete |
| Context injection | ✅ Complete |
| CLI integration | ⬜ Optional |
| AppContext integration | ⬜ Optional |

The core refactoring is complete. PaperEnricher can be used directly with context injection pattern.
