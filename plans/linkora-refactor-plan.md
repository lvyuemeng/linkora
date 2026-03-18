# linkora Refactoring Plan

> Plan for AI context injection, rename, config examples, publish workflow, and README rewrite.

---

## 1. AI Context Injection (--help and --philosophy)

### Goal
Ensure AI coding agents immediately see context and are driven by it when working on the project.

### Tasks

#### 1.1 Refactor docs/AGENT.md
- [ ] Add prominent project context at top: "linkora - Local Knowledge Network for AI"
- [ ] Add `--help` flag behavior: should show project-specific context
- [ ] Add `--philosophy` flag: prints core design principles
- [ ] Update all `linkora` references to `linkora`

#### 1.2 Add CLI Context Flags
- [ ] Add `--philosophy` flag to CLI that outputs design principles
- [ ] Add `--help` enhancement to show workspace-aware context
- [ ] Ensure `--help` output includes:
  - Current workspace detection
  - Config file locations
  - Quick links to docs

#### 1.3 Context Injection in CLI
```python
# Add to cli/main.py or cli/context.py
def add_context_flags(parser):
    parser.add_argument(
        "--philosophy",
        action="store_true",
        help="Show design philosophy and guiding principles"
    )
    parser.add_argument(
        "--context",
        action="store_true", 
        help="Show current workspace context"
    )
```

#### 1.4 Update docs/design.md
- [ ] Add section on "Context Injection for AI Agents"
- [ ] Document --philosophy and --help behavior

---

## 2. Rename linkora to linkora

### Goal
Rename all references from linkora to linkora throughout the codebase.

### Tasks

#### 2.1 Directory Rename
- [ ] Rename `linkora/` to `linkora/`

#### 2.2 pyproject.toml Updates
- [ ] Change `name = "linkora"` to `name = "linkora"`
- [ ] Update `project.scripts`:
  - `linkora` → `linkora`
  - `linkora-mcp` → `linkora-mcp`
- [ ] Update optional-dependencies keys:
  - `linkora[embed]` → `linkora[embed]`
  - `linkora[topics]` → `linkora[topics]`
  - `linkora[import]` → `linkora[import]`
  - `linkora[full]` → `linkora[full]`

#### 2.3 Source Code Updates
- [ ] Update all imports in `linkora/__init__.py`
- [ ] Update all imports in `linkora/cli/*.py`
- [ ] Update all imports in `linkora/index/*.py`
- [ ] Update all imports in `linkora/sources/*.py`
- [ ] Update module references in docstrings
- [ ] Update `__all__` exports

#### 2.4 Documentation Updates
- [ ] Rename `docs/AGENT.md` → `docs/linkora_AGENT.md`
- [ ] Update all `linkora` references in all docs
- [ ] Update README.md title and references

#### 2.5 Config File Updates
- [ ] Update `docs/config.md` - change `linkora.config` to `linkora.config`
- [ ] Update workspace config references

#### 2.6 Test Module Updates
- [ ] Rename test imports from `linkora` to `linkora`
- [ ] Update test configuration in `tests/conftest.py`
- [ ] Update pytest commands in AGENT.md to use `linkora`
- [ ] Ensure all test files reference new module name

---

## 3. Example Configuration

### Goal
Create user reference configuration files.

### Tasks

#### 3.1 Global Config Template
- [ ] Create `~/.linkora/config.yml` template
- [ ] Include all config sections with defaults
- [ ] Add comments explaining each section

#### 3.2 Workspace-Local Config Examples
- [ ] Create `examples/config/workspace-physics.yml`
- [ ] Create `examples/config/workspace-default.yml`
- [ ] Show override patterns

#### 3.3 Minimal Config
- [ ] Create `examples/config/minimal.yml` - just workspace name
- [ ] Show zero-config default behavior

#### 3.4 Full Config with All Options
- [ ] Create `examples/config/full.yml` - all options
- [ ] Include all sources (local, openalex, zotero, endnote)
- [ ] Include index, llm, ingest, topics, logging

#### 3.5 Environment Variables Guide
- [ ] Create `examples/env/linkora.env`
- [ ] Document all environment variables
- [ ] Show precedence rules

---

## 4. Publish Workflow

### Goal
Create GitHub Actions workflow for uv tool installation and PyPI publishing.

### Tasks

#### 4.1 UV Tool Installation Workflow
- [ ] Create `.github/workflows/install-uv.yml`
- [ ] Use `astral-sh/setup-uv@v7` action (official recommended)
- [ ] Matrix: ubuntu, macos, windows
- [ ] Test uv installation and basic commands

```yaml
# .github/workflows/install-uv.yml
name: Install UV

jobs:
  uv-example:
    name: python
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v6

      - name: Install uv
        uses: astral-sh/setup-uv@v7
        with:
          version: "0.10.9"  # Pin to specific version
```

#### 4.2 PyPI Publishing Workflow
- [ ] Create `.github/workflows/publish.yml`
- [ ] Trigger: on tag push (v*)
- [ ] Use uv for building and publishing
- [ ] Include test PyPI and production PyPI steps

```yaml
# .github/workflows/publish.yml
name: Publish to PyPI

on:
  push:
    tags:
      - 'v*'

jobs:
  publish:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v6
      
      - name: Install uv
        uses: astral-sh/setup-uv@v7
        with:
          version: "0.10.9"
      
      - name: Build package
        run: uv build --no-sources
      
      - name: Publish to PyPI
        run: uv publish
        env:
          UV_PUBLISH_TOKEN: ${{ secrets.PYPI_TOKEN }}
```

#### 4.3 CI/CD Pipeline
- [ ] Create `.github/workflows/ci.yml`
- [ ] Test: uv sync, ruff check, ty check, pytest
- [ ] Run on ubuntu, macos, windows
- [ ] Python version matrix: 3.12, 3.13

```yaml
# .github/workflows/ci.yml
name: CI

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: astral-sh/setup-uv@v7
        with:
          version: "0.10.9"
      - run: uv sync
      - run: uv run ruff check .
      - run: uv run ty check .
      - run: uv run pytest tests/ -v
```

#### 4.4 Version Management with uv
- [ ] Use `uv version` for version bumping
- [ ] Support semantic versioning: major, minor, patch, stable, alpha, beta, rc
- [ ] Auto-generate changelog

```bash
# Version management commands
uv version 1.0.0                    # Exact version
uv version --bump minor             # Semantic bump
uv version --bump patch --bump dev=66463664  # Multiple bumps
uv version --dry-run 2.0.0         # Preview without updating
```

**uv version --bump options:**
- `major`, `minor`, `patch`, `stable` - version components
- `alpha`, `beta`, `rc` - pre-release versions
- `post`, `dev` - post-release versions

---

## 5. Rewrite README

### Goal
Complete overhaul based on new design docs with motive, installation, usage.

### Tasks

#### 5.1 Project Motivation
- [ ] Explain the "why" - local-first knowledge network
- [ ] Problem: fragmented research tools
- [ ] Solution: unified terminal experience
- [ ] Target audience: AI coding agents + researchers

#### 5.2 Installation Section
- [ ] UV-based installation (primary method)
  ```bash
  uv tool install linkora
  # or
  uv pip install linkora
  ```
- [ ] From source
  ```bash
  git clone https://github.com/.../linkora.git
  cd linkora
  uv sync
  uv run linkora --help
  ```
- [ ] Prerequisites: uv, Python 3.12+

#### 5.3 Quick Start
- [ ] Interactive setup: `linkora init`
- [ ] Add papers: `linkora add <pdf>`
- [ ] Search: `linkora search "query"`
- [ ] Build index: `linkora index`

#### 5.4 Core Features
- [ ] Layered reading (L1-L4)
- [ ] Hybrid search (FTS5 + vector)
- [ ] Multi-source import
- [ ] Workspaces
- [ ] MCP server

#### 5.5 Configuration
- [ ] Link to `docs/config.md`
- [ ] Show example config
- [ ] Explain workspace concept
- [ ] Environment variables

#### 5.6 Architecture Overview
- [ ] Link to `docs/design.md`
- [ ] Layer diagram (L0-L3)
- [ ] Key modules

#### 5.7 Commands Reference
- [ ] Table of all CLI commands
- [ ] Common usage examples

#### 5.8 Development
- [ ] Link to `docs/linkora_AGENT.md`
- [ ] UV workflow
- [ ] Testing commands

---

## Execution Order

```
1. Rename (2) - Foundation for everything else
   - 2.1 Rename directory linkora/ → linkora/
   - 2.2 Update pyproject.toml
   - 2.3 Update source code imports
   - 2.4 Update documentation
   - 2.5 Update config references
   - 2.6 Update test imports
2. AI Context (1) - Update docs/linkora_AGENT.md after rename
3. Config Examples (3) - Can be done in parallel with (1)
4. Publish Workflow (4) - After rename and config
   - 4.1 Install uv workflow
   - 4.2 PyPI publish workflow
   - 4.3 CI pipeline with pytest
   - 4.4 Version management
5. README (5) - After everything else is done
```

---

## Files to Create/Modify

### New Files
- `linkora/` (renamed from linkora/)
- `.github/workflows/install-uv.yml`
- `.github/workflows/publish.yml`
- `.github/workflows/ci.yml`
- `.github/workflows/release.yml`
- `docs/linkora_AGENT.md` (renamed and updated)
- `examples/config/workspace-physics.yml`
- `examples/config/workspace-default.yml`
- `examples/config/minimal.yml`
- `examples/config/full.yml`
- `examples/env/linkora.env`

### Files to Modify
- `pyproject.toml`
- `README.md`
- `docs/config.md`
- `docs/design.md`
- All source files in `linkora/` (imports, docstrings)
- `plans/` directory (this plan)

### Existing Tests Module (preserve and update)
The project already has a tests/ directory with the following structure:
- `tests/__init__.py`
- `tests/conftest.py`
- `tests/unit/` - unit tests
  - `tests/unit/__init__.py`
  - `tests/unit/test_hash.py`
  - `tests/unit/test_filters.py`
  - `tests/unit/test_audit_rules.py`
- `tests/integration/` - integration tests
  - `tests/integration/__init__.py`
  - `tests/integration/test_paper_store.py`
  - `tests/integration/test_search_flow.py`
  - `tests/integration/test_config_resolution.py`

#### Testing Tasks (add to plan)
- [ ] Rename test imports from `linkora` to `linkora`
- [ ] Update test configuration in `tests/conftest.py`
- [ ] Update AGENT.md testing commands to use `linkora`
- [ ] Add new tests for renamed modules
- [ ] Ensure CI workflow runs pytest on tests/

### Files to Delete
- `linkora/` directory
- `docs/AGENT.md`
