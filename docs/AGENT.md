# ScholarAIO Agent Instructions

> This file provides coding instructions for AI coding agents. **Must use `uv` for all Python operations.**

## Prerequisites

### Install uv (if not installed)

```bash
# Linux/macOS
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
winget install astral-sh.uv
```

**⚠️ Alert**: If `uv` is not installed, stop and instruct the user to install it first.
**⚠️ Alert**: Do not manipulate global environment for developing, including any `pip` related commands! 

---

## Environment Setup

### Using uv (pure uv workflow)

Caution: use `--help` after commands to comprehend if you don't know.

```bash
# Create virtual environment and generate lock file
uv venv
uv lock

# Sync dependencies (install from lock file)
uv sync

# Add dependencies
uv add requests
uv add -D pytest

# Add optional dependencies
uv add -E embed sentence-transformers faiss-cpu
uv add -E topics bertopic pandas

# Run commands without activation
uv run python -m scholaraio --help
uv run scholaraio search "turbulence"

# Or activate (optional)
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\Activate.ps1  # Windows
```

---

## Python Code Style

### Format with ruff (via uv)

```bash
# Check formatting
uv run ruff check .
uv run ruff check scholaraio/

# Auto-fix formatting
uv run ruff check --fix .
uv run ruff check --fix scholaraio/

# Format code
uv run ruff format .
uv run ruff format scholaraio/
```

### Type Checking

```bash
# Install dev dependencies first
uv add -D mypy

# Run type checker
uv run mypy scholaraio/
```

## Testing

```bash
# Run tests
uv run pytest tests/ -v

# Run with coverage
uv run pytest --cov=scholaraio tests/
```

---

## Coding Philosophy

### 1. Local-First
- All data stored locally (privacy, offline capability)
- No cloud sync for core features
- Offline-first design

### 2. AI-Native
- Designed for AI coding agents, not end users
- Machine-friendly output (JSON)
- MCP server integrated
- Clean CLI interface

### 3. Minimal but Complete
- Each module has single responsibility
- Don't add features that duplicate other tools
- Focus on core value

### 4. Zero Config
- Environment variables auto-detected
- Smart defaults
- Cross-platform (Linux/macOS/Windows)

### 5. Functional & Interface-Based Design
- **Pure functions**: Avoid side effects; prefer immutability where possible
- **Interface over implementation**: Use Protocol and abstract base classes
- **Dataclass-driven**: Use dataclasses for structured data, not dictionaries
- **Pipeline composition**: Chain operations functionally, avoid nested callbacks
- **No repetition**: Extract common patterns to shared utilities (e.g., hash computation)
- **No huge argument lists**: Group related parameters into config dataclasses
- **Type safety**: Full type hints, TypedDict for complex structures, Protocol for interfaces
- **Language**: Code comments and docstrings in **English only** (avoid encoding issues)

### 6. Avoid Metaprogramming
- **No getattr for dispatch**: Use explicit function calls or dictionaries instead of `getattr(obj, method_name, default)`
- **No dynamic class creation**: Use dataclasses or explicit classes, avoid `type()` or `make_dataclass`
- **Explicit over implicit**: Prefer clear, readable code over clever shortcuts
- **Example**:
  ```python
  # ✗ Avoid: getattr for method dispatch
  method = getattr(self, f"resolve_{key}", None)
  if method: method()

  # ✓ Prefer: explicit dictionary or function
  RESOLVERS: dict[str, Callable] = {"llm": resolve_llm, "mineru": resolve_mineru}
  resolver = RESOLVERS.get(key, resolve_default)
  ```

---

## Code Standards

Require: `requires-python = ">=3.12"`

### Docstrings

- **Library modules**: Google-style docstrings
  ```python
  def search(query: str, db_path: Path, top_k: int = 20) -> list[dict]:
      """Search papers by keyword.

      Args:
          query: Search query string.
          db_path: Path to SQLite database.
          top_k: Maximum number of results.

      Returns:
          List of paper dictionaries.
      """
  ```

- **CLI handlers** (`cmd_*` in `cli.py`): No docstrings

### Comments

- **English only** (avoid Chinese character encoding issues)
- Add only when logic is not self-evident

### Type Safety

- Use type hints on all public functions
- Use `TypedDict` for complex dict structures
- Use `Protocol` for interface definitions
- Run `uv run mypy scholaraio/` before committing

### User-Facing Text

- CLI output, help text, error messages: **Chinese**

### Naming

- `snake_case` for functions, variables
- `PascalCase` for classes, types
- `SCREAMING_SNAKE_CASE` for constants

### Imports

- Standard library first
- Third-party next
- Local last
- Group by: stdlib → external → local

```python
# ✓ Correct
import argparse
import logging
from pathlib import Path

import yaml

from scholaraio import index
from scholaraio.config import load_config
```

### Error Handling

- Use exceptions for errors
- Provide helpful error messages
- Log errors with context

```python
# ✓ Correct
if not papers_dir.exists():
    raise FileNotFoundError(f"Papers directory not found: {papers_dir}")
```