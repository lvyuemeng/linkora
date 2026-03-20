# linkora Justfile
# Provides useful commands for development workflow
# Usage: just <recipe>

# Default recipe - show help
default:
    @just --list

# ============================================================================
# Development Setup
# ============================================================================
#
#
# Create virtual environment and sync dependencies
setup:
    uv venv
    uv sync --extra full

# Add a dependency
add pkg:
    uv add {{pkg}}

# Add a dev dependency
add-dev pkg:
    uv add -dev {{pkg}}

# ============================================================================
# Testing
# ============================================================================

# Run all tests
test:
    uv run -m pytest -v

# Run tests with coverage
test-cov:
    uv run -m pytest --cov=linkora

# Run specific test file
test-file file:
    uv run -m pytest {{file}} -v

# Run integration tests only
test-integration:
    uv run -m pytest tests/integration/ -v

# Run unit tests only
test-unit:
    uv run -m pytest tests/unit/ -v

# ============================================================================
# Linting & Formatting
# ============================================================================

# Auto-fix linting issues
lint:
    uv run ruff check --fix .

# Format code
format:
    uv run ruff format .

# Run full linting (check + format)
lint-full: lint format

# ============================================================================
# Type Checking
# ============================================================================

# Run type checker
type:
    uv run ty check

# ============================================================================
# Code Quality (all checks)
# ============================================================================

# Run all quality checks (lint, format, typecheck)
quality: lint-full type

# ============================================================================
# CI Pipeline
# ============================================================================

# Run CI pipeline locally (lint + typecheck + test)
ci: quality test


# ============================================================================
# Development
# ============================================================================

# Install as editable tool
install:
    uv tool install -e .