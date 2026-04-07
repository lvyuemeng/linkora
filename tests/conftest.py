"""Shared pytest fixtures for v2 tests."""

import pytest
from pathlib import Path
import tempfile


@pytest.fixture
def tmp_db():
    """Create temporary database with schema."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        from linkora.db import Database

        db = Database(db_path)
        db.connect()
        yield db
        db.close()


@pytest.fixture
def temp_workspace():
    """Create temporary workspace directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_pdf(tmp_path):
    """Create minimal valid PDF file."""
    pdf_content = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>>>endobj
xref
0 4
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
trailer<</Size 4/Root 1 0 R>>
startxref
193
%%EOF"""
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(pdf_content)
    return pdf


@pytest.fixture
def sample_markdown(tmp_path):
    """Create sample markdown file."""
    md_content = """# Sample Document

This is a test document for linkora.

## Section 1
Some content here.

## Section 2
More content.
"""
    md = tmp_path / "sample.md"
    md.write_text(md_content)
    return md


@pytest.fixture
def test_workspace_name():
    """Return test workspace name."""
    return "test-workspace"


@pytest.fixture
def fixtures_dir():
    """Return path to test fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def reset_db_singleton():
    """Reset database singleton between tests."""
    import linkora.cli.setup as setup

    setup.reset_runtime_state()
    yield
    setup.reset_runtime_state()
