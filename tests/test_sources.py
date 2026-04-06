"""Integration tests for sources module."""

from linkora.sources import LocalSource, SourceRequest


def test_local_source_returns_existing_files(tmp_path):
    """Test LocalSource returns existing files without modification."""
    # Create test PDF
    pdf_dir = tmp_path / "papers"
    pdf_dir.mkdir()
    (pdf_dir / "test.pdf").write_bytes(b"%PDF-1.4 test")

    source = LocalSource(roots=[pdf_dir], recursive=False)

    request = SourceRequest(scheme="local", value="test", params={}, raw="test")
    results = list(source.fetch(request, output_path=tmp_path / "out"))

    assert len(results) == 1
    assert results[0].path.name == "test.pdf"
    assert results[0].raw_metadata == {}


def test_local_source_count(tmp_path):
    """Test LocalSource.count() returns correct count."""
    pdf_dir = tmp_path / "papers"
    pdf_dir.mkdir()
    (pdf_dir / "a.pdf").write_bytes(b"%PDF-1.4")
    (pdf_dir / "b.pdf").write_bytes(b"%PDF-1.4")

    source = LocalSource(roots=[pdf_dir])

    assert source.count(SourceRequest(scheme="local", value="", params={}, raw="")) == 2
    assert (
        source.count(SourceRequest(scheme="local", value="a", params={}, raw="a")) == 1
    )


def test_local_source_empty_dir(tmp_path):
    """Test LocalSource handles empty directory."""
    pdf_dir = tmp_path / "empty"
    pdf_dir.mkdir()

    source = LocalSource(roots=[pdf_dir])

    results = list(
        source.fetch(
            SourceRequest(scheme="local", value="", params={}, raw=""),
            output_path=tmp_path,
        )
    )
    assert len(results) == 0


def test_local_source_recursive(tmp_path):
    """Test LocalSource recursive scanning."""
    # Create nested structure
    papers = tmp_path / "papers"
    papers.mkdir()
    (papers / "root.pdf").write_bytes(b"%PDF-1.4")
    (papers / "sub").mkdir()
    (papers / "sub" / "nested.pdf").write_bytes(b"%PDF-1.4")

    source = LocalSource(roots=[papers], recursive=True)
    results = list(
        source.fetch(
            SourceRequest(scheme="local", value="", params={}, raw=""),
            output_path=tmp_path,
        )
    )

    assert len(results) == 2


def test_local_source_name_property(tmp_path):
    """Test LocalSource.name returns 'local'."""
    source = LocalSource(roots=[])
    assert source.name == "local"
