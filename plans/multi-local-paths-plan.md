# Implementation Plan: Multi-Path Local Sources

> Plan for implementing multiple local path support with efficiency focus.
> Based on updated `docs/design.md`.

---

## Summary of Changes

| File | Change Type | Description |
|------|-------------|-------------|
| `linkora/cli/commands.py` | Bug Fix | Fix broken method call |
| `linkora/sources/local.py` | Breaking Change | Support `pdf_dirs: list[Path]` |
| `linkora/ingest/matching.py` | Breaking Change | Accept `local_pdf_dirs: list[Path]` |
| `linkora/cli/context.py` | Enhancement | Add `source_dispatcher()` method |
| `docs/design.md` | Documentation | Updated architecture |

---

## Phase 1: Fix Broken Code

### 1.1 Fix cmd_add in commands.py

**File:** `linkora/cli/commands.py`

**Current (broken):**
```python
config = ctx.config
local_pdf_dir = config.resolve_local_source_dir()  # ERROR: doesn't exist!
```

**Fix:**
```python
config = ctx.config
local_pdf_dirs = config.resolve_local_source_paths()  # Returns list[Path]
```

**Also update dispatcher creation:**
```python
# Old (single path)
dispatcher = DefaultDispatcher(
    local_pdf_dir=local_pdf_dir, 
    http_client=http_client
)

# New (multiple paths)
dispatcher = DefaultDispatcher(
    local_pdf_dirs=local_pdf_dirs, 
    http_client=http_client
)
```

---

## Phase 2: Update LocalSource

### 2.1 Modify Constructor

**File:** `linkora/sources/local.py`

**Changes to `LocalSource` class:**

```python
@dataclass
class LocalSource:
    """Scan user's downloaded PDFs on filesystem (read-only).
    
    Supports multiple paths with unified indexing for efficiency.
    """
    
    # Changed from single pdf_dir to list
    pdf_dirs: list[Path]  # Required, non-empty list
    recursive: bool = True
    
    # Add path source tracking
    _path_sources: dict[Path, str] = field(default_factory=dict, init=False, repr=False)
    
    def __post_init__(self):
        """Validate and normalize paths."""
        # Ensure pdf_dirs is a list
        if isinstance(self.pdf_dirs, Path):
            self.pdf_dirs = [self.pdf_dirs]
        # Filter invalid paths
        self.pdf_dirs = [p for p in self.pdf_dirs if p and p.exists()]
```

### 2.2 Update Index Building

**Changes to `_build_index()` method:**

```python
def _build_index(self) -> dict[str, Path]:
    """Build unified index across all paths."""
    index: dict[str, Path] = {}
    hashes: dict[str, str] = {}
    
    for pdf_dir in self.pdf_dirs:
        if not pdf_dir.exists():
            _log.warning("PDF directory does not exist: %s", pdf_dir)
            continue
            
        pattern = "**/*.pdf" if self.recursive else "*.pdf"
        pdf_files = list(pdf_dir.glob(pattern))
        pdf_files = [p for p in pdf_files if p.is_file()]
        
        for pdf_path in pdf_files:
            # Track source path for identification
            self._path_sources[pdf_path] = str(pdf_dir)
            
            # ... existing indexing logic (by DOI, by filename)
    
    return index
```

### 2.3 Update Search Methods

**Changes to `_search_sequential()` and `_search_parallel()`:**
- Already work with unified index - no major changes needed
- Add source path info to candidate if needed

---

## Phase 3: Update Dispatcher

### 3.1 Modify DefaultDispatcher

**File:** `linkora/ingest/matching.py`

**Changes:**

```python
class DefaultDispatcher:
    def __init__(
        self,
        local_pdf_dirs: list[Path] | None = None,  # Changed!
        http_client=None,
    ):
        self._local_pdf_dirs = local_pdf_dirs or []  # Changed!
        self._http_client = http_client
        # ... other fields
    
    def _ensure_sources(self) -> None:
        """Initialize and cache source instances."""
        if self._initialized:
            return
            
        from linkora.sources import LocalSource
        
        # Create ONE local source with all paths (efficiency!)
        if self._local_pdf_dirs:
            try:
                self._local_source = LocalSource(pdf_dirs=self._local_pdf_dirs)
            except Exception as e:
                _log.debug("LocalSource failed: %s", e)
        
        # ... other sources unchanged
```

---

## Phase 4: Update Context

### 4.1 Add source_dispatcher Method

**File:** `linkora/cli/context.py`

**Add to AppContext:**

```python
@dataclass
class AppContext:
    config: "Config"
    _http_client: "HTTPClient | None" = field(default=None, repr=False)
    _llm_runner: "LLMRunner | None" = field(default=None, repr=False)
    _paper_store: "PaperStore | None" = field(default=None, repr=False)
    _dispatcher: "DefaultDispatcher | None" = field(default=None, repr=False)  # NEW
    
    # ... existing methods ...
    
    def source_dispatcher(self) -> "DefaultDispatcher":
        """Get or create source dispatcher with multi-path support."""
        if self._dispatcher is None:
            from linkora.ingest.matching import DefaultDispatcher
            
            paths = self.config.resolve_local_source_paths()
            self._dispatcher = DefaultDispatcher(
                local_pdf_dirs=paths,
                http_client=self.http_client()
            )
        return self._dispatcher
    
    def close(self) -> None:
        """Close all resources."""
        self._http_client = None
        self._llm_runner = None
        self._paper_store = None
        self._dispatcher = None  # NEW
```

---

## Phase 5: Testing

### 5.1 Test Scenarios

1. **Single path (backward compatibility)**
   ```bash
   linkora add "test"  # Should work with papers_dir only
   ```

2. **Multiple paths**
   ```yaml
   # config
   sources:
     local:
       papers_dir: papers
       paths:
         - /data/pdfs
         - ~/other_papers
   ```
   ```bash
   linkora add "test"  # Should search both paths
   ```

3. **Empty paths**
   ```yaml
   sources:
     local:
       papers_dir: papers
       paths: []  # Empty
   ```
   Should work with just papers_dir

4. **Non-existent paths**
   Should log warning, skip invalid paths, continue with valid ones

---

## Code Changes Summary

### linkora/cli/commands.py
```diff
- local_pdf_dir = config.resolve_local_source_dir()
+ local_pdf_dirs = config.resolve_local_source_paths()

- dispatcher = DefaultDispatcher(
-     local_pdf_dir=local_pdf_dir, http_client=http_client
- )
+ dispatcher = DefaultDispatcher(
+     local_pdf_dirs=local_pdf_dirs, http_client=http_client
+ )
```

### linkora/sources/local.py
```diff
  @dataclass
  class LocalSource:
-     pdf_dir: Path  # Single path
+     pdf_dir: Path  # Keep for backward compat
+     pdf_dirs: list[Path]  # NEW: multiple paths
      recursive: bool = True
+     _path_sources: dict[Path, str] = field(default_factory=dict)
```

### linkora/ingest/matching.py
```diff
  class DefaultDispatcher:
      def __init__(
          self,
-         local_pdf_dir: Path | None = None,
+         local_pdf_dirs: list[Path] | None = None,
          http_client=None,
      ):
-         self._local_pdf_dir = local_pdf_dir
+         self._local_pdf_dirs = local_pdf_dirs or []
```

### linkora/cli/context.py
```diff
  @dataclass
  class AppContext:
+     _dispatcher: "DefaultDispatcher | None" = field(default=None)
      
+     def source_dispatcher(self) -> "DefaultDispatcher":
+         ...
      
      def close(self):
+         self._dispatcher = None
```

---

## Verification Commands

```bash
# Run tests
uv run -m pytest tests/

# Check types
uv run ty check linkora/

# Check formatting
uv run ruff check --fix linkora/
uv run ruff format linkora/
```
