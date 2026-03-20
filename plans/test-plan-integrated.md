# Integrated Test Plan - Focus on New Functionalities

> Test plan based on current codebase analysis.
> Focus: Integrated tests for new functionalities, not bloated simple tests.
> Principles from pytest-workflow-plan.md: Meaningful coverage, integrated consistency checks.

---

## 1. Current Test Coverage Analysis

### 1.1 Existing Tests (Good Foundation)

| Test File | Coverage | Status |
|-----------|----------|--------|
| `tests/unit/test_filters.py` | QueryFilter.matches() | ✅ Complete |
| `tests/unit/test_audit_rules.py` | Audit rules | ✅ Complete |
| `tests/unit/test_hash.py` | Hash functions | ✅ Complete |
| `tests/integration/test_config_resolution.py` | Config defaults | ✅ Complete |
| `tests/integration/test_paper_store.py` | PaperStore CRUD | ✅ Complete |
| `tests/integration/test_search_flow.py` | FTS search | ✅ Complete |

### 1.2 Missing Coverage (New Functionalities)

| Functionality | Test Status | Priority |
|---------------|-------------|----------|
| Multi-path local source resolution | ❌ Missing | P0 |
| LocalSource multi-path scanning | ❌ Missing | P0 |
| DefaultDispatcher multi-path | ❌ Missing | P0 |
| FilterParams ↔ QueryFilter consistency | ⚠️ Partial | P1 |
| Complete add command flow | ❌ Missing | P1 |
| CLI context integration | ⚠️ Partial | P2 |

---

## 2. Test Plan: Multi-Path Local Source Resolution

### 2.1 Config Resolution Tests

```python
# tests/integration/test_local_source_resolution.py

class TestLocalSourceResolution:
    """Tests for resolve_local_source_paths() - multi-path support."""

    @pytest.fixture
    def config_with_paths(self, tmp_path):
        """Config with multiple local source paths."""
        # Create config with primary + additional paths
        ...

    def test_single_path_resolution(self, config_with_paths):
        """Single papers_dir resolves correctly."""
        paths = config_with_paths.resolve_local_source_paths()
        assert len(paths) == 1

    def test_multiple_paths_resolution(self, config_with_paths):
        """Multiple paths resolve correctly."""
        config.sources.local.paths = ["/data/pdfs", "~/papers"]
        paths = config.resolve_local_source_paths()
        assert len(paths) == 3  # primary + 2 additional

    def test_relative_path_resolution(self, config_with_paths):
        """Relative paths resolved from config root."""
        paths = config_with_paths.resolve_local_source_paths()
        # All paths should be absolute
        assert all(p.is_absolute() for p in paths)

    def test_disabled_source_returns_empty(self, config_with_paths):
        """Disabled local source returns empty list."""
        config.sources.local.enabled = False
        paths = config.resolve_local_source_paths()
        assert paths == []
```

---

## 3. Test Plan: LocalSource Multi-Path

### 3.1 LocalSource Scanning Tests

```python
# tests/integration/test_local_source_multipath.py

class TestLocalSourceMultiPath:
    """Tests for LocalSource with multiple paths."""

    @pytest.fixture
    def multi_path_setup(self, tmp_path):
        """Create multiple directories with PDFs."""
        path1 = tmp_path / "papers1"
        path2 = tmp_path / "papers2"
        path1.mkdir()
        path2.mkdir()
        
        # Add PDFs to each path
        (path1 / "paper1.pdf").write_text("pdf content")
        (path2 / "paper2.pdf").write_text("pdf content")
        
        return [path1, path2]

    def test_single_path_scan(self, multi_path_setup):
        """Scan single path returns correct candidates."""
        source = LocalSource(pdf_dirs=[multi_path_setup[0]])
        candidates = list(source.fetch(query=PaperQuery()))
        assert len(candidates) == 1

    def test_multi_path_scan(self, multi_path_setup):
        """Scan multiple paths returns unified candidates."""
        source = LocalSource(pdf_dirs=multi_path_setup)
        candidates = list(source.fetch(query=PaperQuery()))
        assert len(candidates) == 2

    def test_multi_path_deduplication(self, multi_path_setup):
        """Same PDF in multiple paths is deduplicated."""
        # Copy same file to both paths
        import shutil
        shutil.copy(multi_path_setup[0] / "paper1.pdf", 
                    multi_path_setup[1] / "paper1_copy.pdf")
        
        source = LocalSource(pdf_dirs=multi_path_setup)
        candidates = list(source.fetch(query=PaperQuery()))
        # Should be deduplicated by filename
        assert len(candidates) <= 2
```

---

## 4. Test Plan: DefaultDispatcher Multi-Path

### 4.1 Dispatcher Tests

```python
# tests/integration/test_dispatcher_multipath.py

class TestDefaultDispatcherMultiPath:
    """Tests for DefaultDispatcher with multi-path support."""

    def test_dispatcher_accepts_path_list(self, tmp_path):
        """Dispatcher accepts list of paths."""
        paths = [tmp_path / "p1", tmp_path / "p2"]
        dispatcher = DefaultDispatcher(local_pdf_dirs=paths)
        assert dispatcher._local_pdf_dirs == paths

    def test_dispatcher_empty_paths(self):
        """Dispatcher handles empty path list."""
        dispatcher = DefaultDispatcher(local_pdf_dirs=[])
        assert dispatcher._local_pdf_dirs == []

    def test_dispatcher_creates_single_local_source(self, tmp_path):
        """Dispatcher creates single LocalSource for all paths."""
        paths = [tmp_path / "p1", tmp_path / "p2"]
        dispatcher = DefaultDispatcher(local_pdf_dirs=paths)
        
        # Should create one LocalSource, not multiple
        dispatcher._ensure_sources()
        assert isinstance(dispatcher._local_source, LocalSource)
```

---

## 5. Test Plan: Complete Add Flow Integration

### 5.1 End-to-End Flow Tests

```python
# tests/integration/test_add_flow.py

class TestAddFlowIntegration:
    """Integration tests for complete add command flow."""

    @pytest.fixture
    def complete_setup(self, tmp_path, monkeypatch):
        """Complete setup with all components."""
        # Setup papers directory
        papers_dir = tmp_path / "papers"
        papers_dir.mkdir()
        
        # Setup PDF directory with test file
        pdf_dir = tmp_path / "pdfs"
        pdf_dir.mkdir()
        test_pdf = pdf_dir / "test.pdf"
        test_pdf.write_bytes(b"%PDF-1.4 test")
        
        # Setup config
        config = make_test_config(
            _root=tmp_path,
            sources=SourcesConfig(
                local=LocalSourceConfig(
                    enabled=True,
                    papers_dir="papers",
                    paths=[str(pdf_dir)]
                )
            )
        )
        
        return {"config": config, "pdf_dir": pdf_dir, "papers_dir": papers_dir}

    def test_add_command_flow(self, complete_setup):
        """Test complete add command flow."""
        ctx = AppContext(complete_setup["config"])
        
        # Get dispatcher with multi-path
        dispatcher = ctx.source_dispatcher()
        
        # Query for papers
        candidates = list(dispatcher.match_papers(
            query=PaperQuery(title="test")
        ))
        
        assert isinstance(candidates, list)

    def test_context_dispatcher_lazy_init(self, complete_setup):
        """Test that dispatcher is lazily initialized."""
        ctx = AppContext(complete_setup["config"])
        
        # Should not create dispatcher until accessed
        assert ctx._dispatcher is None
        
        # Access dispatcher
        _ = ctx.source_dispatcher()
        
        # Now should be created
        assert ctx._dispatcher is not None
```

---

## 6. Test Plan: Filter Consistency

### 6.1 FilterParams Consistency Tests

```python
# tests/unit/test_filter_consistency.py

class TestFilterConsistency:
    """Tests for consistency between QueryFilter and FilterParams."""

    def test_filter_params_extends_query_filter(self):
        """FilterParams should extend or use QueryFilter."""
        from linkora.filters import QueryFilter
        from linkora.index.text import FilterParams
        
        # Both should have same fields
        qf = QueryFilter(year="2024", journal="nature")
        fp = FilterParams(year="2024", journal="nature")
        
        # FilterParams.to_sql() should work
        sql, params = fp.to_sql()
        assert "year" in sql or "journal" in sql

    def test_year_range_parsing_consistency(self):
        """Year range parsing should be consistent."""
        from linkora.filters import parse_year_range
        from linkora.papers import parse_year_range as papers_parse
        
        result1 = parse_year_range("2020-2024")
        result2 = papers_parse("2020-2024")
        
        assert result1 == result2

    def test_query_filter_sql_roundtrip(self):
        """QueryFilter should produce valid SQL via FilterParams."""
        qf = QueryFilter(year=">2020", journal="nature")
        fp = FilterParams(year=">2020", journal="nature")
        
        sql, params = fp.to_sql()
        
        # Should produce valid SQL WHERE clause
        assert "WHERE" not in sql  # Just the conditions
        assert len(params) >= 1
```

---

## 7. Implementation Priority

### Phase 1: Core Multi-Path Tests (P0)
1. `test_local_source_resolution.py` - Config multi-path
2. `test_local_source_multipath.py` - LocalSource scanning
3. `test_dispatcher_multipath.py` - Dispatcher multi-path

### Phase 2: Integration Tests (P1)
4. `test_add_flow.py` - Complete add command flow
5. `test_filter_consistency.py` - Filter consistency

### Phase 3: Edge Cases (P2)
6. Error handling tests
7. Performance tests (optional)

---

## 8. Test Files to Create

```
tests/integration/
├── test_local_source_resolution.py   # NEW - Config multi-path
├── test_local_source_multipath.py   # NEW - LocalSource multi-path
├── test_dispatcher_multipath.py     # NEW - Dispatcher multi-path
├── test_add_flow.py                 # NEW - Complete add flow
└── test_filter_consistency.py       # NEW - Filter consistency
```

---

## 9. Summary

| Priority | Test | Focus | New Functionality |
|----------|------|-------|-------------------|
| P0 | test_local_source_resolution | Config multi-path | ✅ resolve_local_source_paths() |
| P0 | test_local_source_multipath | LocalSource multi-path | ✅ pdf_dirs list support |
| P0 | test_dispatcher_multipath | DefaultDispatcher multi-path | ✅ local_pdf_dirs list |
| P1 | test_add_flow | Complete add flow | ✅ End-to-end integration |
| P1 | test_filter_consistency | Filter consistency | ⚠️ Cross-module consistency |

**Total New Test Files**: 5

**Principles Applied**:
- ✅ Focus on integrated tests (not bloated simple tests)
- ✅ Focus on new functionalities (multi-path support)
- ✅ Consistency checks across modules
- ✅ End-to-end flow verification
