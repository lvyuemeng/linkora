# linkora Justfile
# Provides useful commands for development workflow
# Usage: just <recipe>

# Default recipe - show help
default:
    @just --list

# ============================================================================
# Development Setup
# ============================================================================

# Create virtual environment and sync dependencies
setup:
    uv venv
    uv sync

# Sync with all extras
setup-full:
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

# Check linting
lint:
    uv run ruff check .

# Auto-fix linting issues
lint-fix:
    uv run ruff check --fix .

# Check code formatting
format-check:
    uv run ruff format --check

# Format code
format:
    uv run ruff format .

# Run full linting (check + format)
lint-full: lint format-check

# ============================================================================
# Type Checking
# ============================================================================

# Run type checker
typecheck:
    uv run ty check

# ============================================================================
# Code Quality (all checks)
# ============================================================================

# Run all quality checks (lint, format, typecheck)
check: lint format typecheck

# ============================================================================
# CI Pipeline
# ============================================================================

# Run CI pipeline locally (lint + typecheck + test)
ci: lint-full typecheck test

# ============================================================================
# CLI Commands
# ============================================================================

# Show help
help:
    uv run linkora --help

# Show design context
context:
    uv run linkora --context

# Initialize workspace
init:
    uv run linkora init

# Build search index
index:
    uv run linkora index

# Search papers
search query:
    uv run linkora search "{{query}}"

# Run MCP server
mcp:
    uv run linkora-mcp

# ============================================================================
# Development
# ============================================================================

# Install as editable tool
install:
    uv tool install -e .

# Run audit
audit:
    uv run linkora audit

# Run doctor (health check)
doctor:
    uv run linkora doctor
