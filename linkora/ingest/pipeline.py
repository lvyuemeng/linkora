"""ingest_pipeline.py — Functional data pipe for paper ingestion.

Uses types directly from mineru module, no factory functions.
No class overhead - pure functional approach.
"""

from dataclasses import dataclass
from pathlib import Path

from linkora.ingest.download import get_pdf_path
from linkora.mineru import (
    ParseOptions,
    PDFClient,
)
from linkora.papers import PaperStore, PaperMetadata, generate_uuid
from linkora.sources.protocol import PaperCandidate
from linkora.log import get_logger

_log = get_logger(__name__)


# Default parse options
_DEFAULT_PARSE_OPTIONS = ParseOptions(
    backend="pipeline",
    lang="en",
    formula_enable=True,
    table_enable=True,
)


@dataclass(frozen=True)
class IngestResult:
    """Final result of paper ingestion."""

    paper_id: str
    title: str
    doi: str
    success: bool
    error: str | None = None
    pdf_path: Path | None = None
    md_path: Path | None = None


def ingest(
    candidate: PaperCandidate,
    client: PDFClient,
    papers_dir: Path,
    http_client=None,
    parse_options: ParseOptions | None = None,
) -> IngestResult:
    """Process candidate through data pipe consuming flow.

    Pipeline (consuming types directly):
        1. PaperCandidate → PDF path (download or cache)
        2. PDF path → client.call() → response dict
        3. Extract markdown from response
        4. PaperMetadata from markdown + candidate
        5. Save to PaperStore

    Args:
        candidate: Paper candidate from source
        client: PDFClient (LocalClient or CloudClient) - passed directly, no factory
        papers_dir: Target directory for papers
        http_client: HTTP client for downloading PDFs
        parse_options: MinerU parse options

    Returns:
        IngestResult with success/failure info
    """
    opts = parse_options or _DEFAULT_PARSE_OPTIONS

    try:
        # Stage 1: Get PDF path
        pdf_path = get_pdf_path(candidate, papers_dir, http_client)
        if pdf_path is None:
            return IngestResult(
                paper_id=candidate.id,
                title=candidate.title,
                doi=candidate.doi,
                success=False,
                error="No PDF available",
            )

        # Stage 2: Call API directly (no PDFInput wrapper needed)
        response = client.call(pdf_path, opts)

        # Stage 3: Extract markdown from response
        md_content = _extract_markdown(response)
        if md_content is None:
            return IngestResult(
                paper_id=candidate.id,
                title=candidate.title,
                doi=candidate.doi,
                success=False,
                error="Failed to extract markdown",
            )

        # Stage 4: Extract metadata
        metadata = _extract_metadata(md_content, candidate)

        # Stage 5: Save to store
        result = _save_to_store(metadata, md_content, papers_dir)
        _log.info("Ingested: %s", result.title)
        return result

    except Exception as e:
        _log.exception("Ingest failed for %s", candidate.id)
        return IngestResult(
            paper_id=candidate.id,
            title=candidate.title,
            doi=candidate.doi,
            success=False,
            error=str(e),
        )


def _extract_markdown(data: dict) -> str | None:
    """Extract markdown from API response dict."""
    if not isinstance(data, dict):
        return None

    # Primary: results -> {filename} -> md_content
    results = data.get("results")
    if isinstance(results, dict):
        for entry in results.values():
            if isinstance(entry, dict) and (md := entry.get("md_content")):
                if isinstance(md, str) and md.strip():
                    return md

    # Fallback: direct md_content
    for key in ("md_content", "md", "markdown", "content"):
        if (value := data.get(key)) and isinstance(value, str) and value.strip():
            return value

    return None


def _extract_metadata(md_content: str, candidate: PaperCandidate) -> PaperMetadata:
    """Extract metadata from markdown, merge with candidate."""
    from linkora.extract import (
        ExtractionInput,
        ExtractionContext,
        extract_regex,
        merge_to_output,
    )

    # Extract using regex
    input = ExtractionInput.from_text(
        name=candidate.title or "unknown",
        text=md_content,
    )
    ctx_extraction = ExtractionContext(input=input)
    ctx_extraction = extract_regex(ctx_extraction)
    output = merge_to_output(ctx_extraction)
    meta = output.metadata

    # Merge with candidate data (prefer source data)
    if candidate.doi and not meta.doi:
        meta.doi = candidate.doi
    if candidate.title and not meta.title:
        meta.title = candidate.title
    if candidate.authors:
        meta.authors = candidate.authors
    if candidate.year:
        meta.year = candidate.year
    if candidate.journal:
        meta.journal = candidate.journal

    # Generate ID if needed
    if not meta.id:
        meta.id = generate_uuid()

    return meta


def _save_to_store(
    metadata: PaperMetadata,
    md_content: str,
    papers_dir: Path,
) -> IngestResult:
    """Save paper to store."""
    store = PaperStore(papers_dir)

    # Generate directory name
    dir_name = _generate_dir_name(metadata)
    paper_d = papers_dir / dir_name

    # Handle duplicates
    if paper_d.exists():
        dir_name = f"{dir_name}_{metadata.id[:8]}"
        paper_d = papers_dir / dir_name

    paper_d.mkdir(parents=True, exist_ok=True)

    # Write metadata
    meta_dict = {
        "id": metadata.id,
        "title": metadata.title,
        "authors": metadata.authors,
        "first_author": metadata.first_author,
        "first_author_lastname": metadata.first_author_lastname,
        "year": metadata.year,
        "doi": metadata.doi,
        "journal": metadata.journal,
        "abstract": metadata.abstract,
        "paper_type": metadata.paper_type,
        "source_file": metadata.source_file,
    }
    store.write_meta(paper_d, meta_dict)

    # Write markdown
    md_path = paper_d / "paper.md"
    md_path.write_text(md_content, encoding="utf-8")

    return IngestResult(
        paper_id=metadata.id,
        title=metadata.title,
        doi=metadata.doi,
        success=True,
        pdf_path=None,
        md_path=md_path,
    )


def _generate_dir_name(meta: PaperMetadata) -> str:
    """Generate directory name from metadata."""
    import re
    from linkora.hash import compute_content_hash

    lastname = meta.first_author_lastname or "unknown"
    year = str(meta.year) if meta.year else "unknown"
    lastname = re.sub(r"[^a-zA-Z]", "", lastname) or "unknown"
    title_hash = compute_content_hash(meta.title)[:4]

    return f"{lastname}_{year}_{title_hash}"


__all__ = ["ingest"]
