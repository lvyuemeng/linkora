# Synapse Design

> Ideal architecture for a general-purpose local knowledge network.

## Core Concept

**Synapse** is a local knowledge network that enables AI-powered research and knowledge management. It provides:

- **Unified knowledge base** with multiple workspaces
- **Layered content loading** (L1-L4) for progressive access
- **Semantic retrieval** via embeddings and vector search
- **Source-agnostic** paper ingestion from multiple formats

---

## Workspace

Each workspace is an independent knowledge environment.

```
<workspace>/
├── workspace.json    # workspace configuration
├── index.db         # fast metadata lookup
├── papers/          # canonical storage
├── vectors.faiss    # optional: semantic retrieval
└── vector_ids.json  # optional: FAISS id mapping
```

### workspace.json

```json
{
  "name": "physics",
  "description": "physics research workspace",
  "embedding_model": "qwen3-embedding",
  "chunk_size": 800,
  "chunk_overlap": 150,
  "sources": ["local", "arxiv", "openalex"]
}
```

| Field | Meaning |
|-------|---------|
| name | workspace identifier |
| description | workspace purpose |
| embedding_model | embedding generator for semantic search |
| chunk_size | chunk length for AI retrieval |
| chunk_overlap | overlap for chunk splitting |
| sources | enabled paper sources |

---

## Layered Loading (L1-L4)

| Level | Content | Source |
|-------|---------|--------|
| L1 | title, authors, year, journal, doi | SQLite index.db |
| L2 | abstract | meta.json |
| L3 | structural sections | chunks.jsonl |
| L4 | full markdown | paper.md |

**Design Principle**: Metadata queries should never require filesystem scanning.

---

## papers/ Directory

```
papers/
└── <AuthorYear-ShortTitle>/
    ├── meta.json
    ├── paper.md
    ├── chunks.jsonl
    └── images/
```

Each directory represents one paper object.

- Directory names are human-readable and may change
- UUID in metadata remains stable across renames

### meta.json

```json
{
  "id": "<uuid>",
  "title": "...",
  "authors": [...],
  "year": 2024,
  "journal": "...",
  "doi": "...",
  "abstract": "...",
  "source": "arxiv"
}
```

| Field | Meaning |
|-------|---------|
| id | stable UUID (never changes) |
| title | paper title |
| authors | author list |
| year | publication year |
| journal | journal/conference name |
| doi | DOI identifier (optional) |
| abstract | paper abstract |
| source | ingestion source (local/arxiv/openalex/zotero/endnote) |

### chunks.jsonl

```json
{"chunk_id": "1", "section": "intro", "text": "..."}
{"chunk_id": "2", "section": "method", "text": "..."}
```

**Purpose**:
- Semantic search
- RAG retrieval for AI agents
- Section extraction

Chunks replace the need for separate sections.json.

---

## Index and Vectors

```
workspace/
├── index.db        # SQLite with FTS5 for fast metadata queries
├── vectors.faiss  # FAISS index for semantic similarity search
└── vector_ids.json # mapping: FAISS index → paper_id
```

**Design Principle**: Use index.db for metadata queries, vectors.faiss for semantic retrieval.

---

## Configuration

Configuration located at:

- `~/.config/synapse/` - user config directory
- `~/.synapse` - workspace location and global settings

---

## Module Architecture

```
Layer 0: Foundation
├── config.py       # Config loading
├── log.py          # Logging
└── papers.py       # PaperStore, metadata handling

Layer 1: Core Data
├── loader.py       # L1-L4 layered loading
├── index.py        # FTS5 search
└── vectors.py      # FAISS + embeddings

Layer 2: Features
├── topics.py       # BERTopic clustering
└── sources/        # PaperSource Protocol

Layer 3: Entry Points
├── cli/            # CLI commands
├── mcp_server.py   # MCP tools
└── export.py       # BibTeX export
```

---

## Data Sources (PaperSource Protocol)

All sources implement unified interface:

```python
class PaperSource(Protocol):
    @property
    def name(self) -> str: ...
    
    def fetch(self, **kwargs) -> Iterator[dict]: ...
    
    def count(self, **kwargs) -> int: ...
```

**Implementations**:
- `LocalSource` - scan workspace papers/
- `ArxivSource` - fetch from arXiv
- `OpenAlexSource` - fetch from OpenAlex API
- `ZoteroSource` - import from Zotero
- `EndnoteSource` - parse Endnote XML/RIS
