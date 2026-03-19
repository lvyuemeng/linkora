"""sources/local.py — Scan user's downloaded PDFs on filesystem.

Redesigned from scratch - no backward compatibility.
Features:
- Read-only: does NOT modify or move user PDF files
- Recursive scanning: supports nested directories
- Efficient: caches directory index for fast repeated queries
- Change detection: file hashing to avoid unnecessary re-scans
- Progress tracking: optional tqdm support for large directories
"""

from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from linkora.log import get_logger
from linkora.sources.protocol import PaperCandidate, PaperQuery, matches_query

_log = get_logger(__name__)

# Pattern to extract DOI from filename
DOI_FILENAME_RE = re.compile(r"10\.\d{4,}/[\w\-\.]+")

# Pattern to extract year from directory/file name
YEAR_RE = re.compile(r"(19|20)\d{2}")

# tqdm availability
try:
    from tqdm import tqdm

    _has_tqdm = True
except ImportError:
    tqdm = None  # type: ignore[misc,assignment]
    _has_tqdm = False


# ============================================================================
#  Internal Helpers
# ============================================================================


def _extract_doi_from_filename(filename: str) -> str | None:
    """Extract DOI from filename if present."""
    match = DOI_FILENAME_RE.search(filename)
    if match:
        return match.group(0)
    return None


def _extract_year_from_path(path: Path) -> int | None:
    """Extract year from path components."""
    for part in path.parts:
        match = YEAR_RE.match(part)
        if match:
            return int(match.group(0))
    return None


def _read_metadata_json(pdf_path: Path) -> dict | None:
    """Try to read metadata from sidecar JSON file."""
    # Check for meta.json in same directory
    meta_path = pdf_path.parent / "meta.json"
    if meta_path.exists():
        try:
            return json.loads(meta_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    # Check for meta/{filename}.json
    meta_dir = pdf_path.parent / "meta"
    if meta_dir.is_dir():
        meta_path = meta_dir / f"{pdf_path.stem}.json"
        if meta_path.exists():
            try:
                return json.loads(meta_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass

    return None


def _compute_file_hash(pdf_path: Path) -> str:
    """Compute MD5 hash of PDF file for change detection."""
    hasher = hashlib.md5()
    with open(pdf_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()[:12]


def _pdf_to_candidate(pdf_path: Path, source_name: str = "local") -> PaperCandidate:
    """Convert PDF path to PaperCandidate."""
    filename = pdf_path.stem

    # Try to read metadata
    meta = _read_metadata_json(pdf_path)

    # Extract DOI from filename
    doi = meta.get("doi") if meta else None
    if not doi:
        doi = _extract_doi_from_filename(filename)

    # Extract title from metadata or use filename
    title = meta.get("title") if meta else None
    if not title:
        title = filename.replace("_", " ").replace("-", " ")

    # Extract authors
    authors = meta.get("authors", []) if meta else []

    # Extract year
    year = meta.get("year") if meta else None
    if not year:
        year = _extract_year_from_path(pdf_path)

    # Use DOI or filename as ID
    paper_id = doi if doi else filename

    return PaperCandidate(
        id=paper_id,
        doi=doi or "",
        title=title,
        authors=authors,
        year=year,
        journal=meta.get("journal") if meta else None,
        abstract=meta.get("abstract") if meta else None,
        cited_by_count=0,
        paper_type=meta.get("paper_type") if meta else None,
        pdf_url=str(pdf_path.absolute()),
        source=source_name,
        source_id=paper_id,
    )


# ============================================================================
#  LocalSource Implementation
# ============================================================================


@dataclass
class LocalSource:
    """Scan user's downloaded PDFs on filesystem (read-only).

    This is for user PDFs outside the workspace, not the workspace paper store.
    Uses PaperSource Protocol - redesigned from scratch.
    Supports multiple paths with unified indexing for efficiency.

    Features:
    - Read-only: does NOT modify or move user PDF files
    - Multiple paths: supports scanning multiple directories
    - Unified index: single cache for all paths (memory efficient)
    - Recursive scanning: supports nested directories
    - Efficient: caches directory index for fast repeated queries
    - Change detection: file hashing to avoid unnecessary re-scans
    - Progress tracking: optional tqdm support

    Directory structure (recursive):
        pdf_dir/
        ├── papers/
        │   ├── 2023/
        │   │   ├── 10.1234_example.pdf
        │   │   └── meta/
        │   │       └── 10.1234_example.json
        │   └── 2024/
        │       └── 10.5678_other.pdf
        └── archive/
            └── old_paper.pdf
    """

    pdf_dir: Path | None = None  # Deprecated: use pdf_dirs
    pdf_dirs: list[Path] = field(default_factory=list)  # Multiple paths support
    recursive: bool = True  # Enable recursive scanning

    # Cached state - initialized lazily via _get_index()
    _index: dict[str, Path] = field(default_factory=dict, init=False, repr=False)
    _file_hashes: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    _path_sources: dict[Path, str] = field(
        default_factory=dict, init=False, repr=False
    )  # Track source path

    def __post_init__(self) -> None:
        """Normalize paths - handle both single pdf_dir and pdf_dirs list."""
        # Handle legacy single pdf_dir parameter
        if self.pdf_dir is not None:
            if not self.pdf_dirs:
                self.pdf_dirs = [self.pdf_dir]
            else:
                # Both provided - include pdf_dir at start
                if self.pdf_dir not in self.pdf_dirs:
                    self.pdf_dirs = [self.pdf_dir] + self.pdf_dirs

        # Filter out invalid paths
        self.pdf_dirs = [p for p in self.pdf_dirs if p is not None and p.exists()]

        # Ensure we have at least one valid path
        if not self.pdf_dirs and self.pdf_dir is not None and self.pdf_dir.exists():
            self.pdf_dirs = [self.pdf_dir]

    @property
    def _index_dict(self) -> dict[str, Path]:
        """Cached index - initialized on first access."""
        return self._index

    @property
    def _hash_dict(self) -> dict[str, str]:
        """Cached file hashes - initialized on first access."""
        return self._file_hashes

    def _set_index(self, value: dict[str, Path]) -> None:
        """Set cached index."""
        self._index = value

    def _set_hashes(self, value: dict[str, str]) -> None:
        """Set cached file hashes."""
        self._file_hashes = value

    def _build_index(self) -> dict[str, Path]:
        """Build unified index across all paths: DOI/filename → file path."""
        index: dict[str, Path] = {}
        hashes: dict[str, str] = {}

        if not self.pdf_dirs:
            _log.warning("No PDF directories configured")
            return index

        # Collect all PDF files from all paths
        all_pdf_files: list[tuple[Path, Path]] = []  # (pdf_path, source_dir)

        for pdf_dir in self.pdf_dirs:
            if not pdf_dir.exists():
                _log.warning("PDF directory does not exist: %s", pdf_dir)
                continue

            pattern = "**/*.pdf" if self.recursive else "*.pdf"
            pdf_files = list(pdf_dir.glob(pattern))
            pdf_files = [p for p in pdf_files if p.is_file()]

            for pdf_path in pdf_files:
                all_pdf_files.append((pdf_path, pdf_dir))

        if not all_pdf_files:
            _log.debug("No PDF files found in any directory")
            return index

        # Show progress with tqdm if available
        if _has_tqdm and len(all_pdf_files) > 10:
            pdf_iter: Iterator = tqdm(all_pdf_files, desc="Indexing PDFs", unit="pdf")  # type: ignore[valid-type]
        else:
            pdf_iter = iter(all_pdf_files)

        for pdf_path, source_dir in pdf_iter:
            filename = pdf_path.stem

            # Compute hash for change detection
            try:
                file_hash = _compute_file_hash(pdf_path)
            except Exception as e:
                _log.debug("Failed to hash %s: %s", pdf_path, e)
                file_hash = ""

            # Track source path for identification
            self._path_sources[pdf_path] = str(source_dir)

            # Index by DOI if present
            doi = _extract_doi_from_filename(filename)
            if doi:
                index[doi] = pdf_path
                hashes[doi] = file_hash

            # Also index by filename for fallback
            index[filename] = pdf_path
            hashes[filename] = file_hash

        _log.debug(
            "Built index with %d PDFs from %d directories",
            len(index) // 2,
            len(self.pdf_dirs),
        )

        # Update hashes
        self._set_hashes(hashes)

        return index

    def _get_index(self) -> dict[str, Path]:
        """Get cached index, rebuild if needed."""
        if not self._index_dict:
            self._set_index(self._build_index())
        return self._index_dict

    def _has_changes(self) -> bool:
        """Check if any files have changed since last index."""
        current_hashes = self._hash_dict
        if not current_hashes:
            return True

        index = self._get_index()

        for key, stored_hash in current_hashes.items():
            pdf_path = index.get(key)
            if not pdf_path or not pdf_path.exists():
                return True
            try:
                current_hash = _compute_file_hash(pdf_path)
                if current_hash != stored_hash:
                    return True
            except Exception:
                return True

        return False

    def _invalidate_index(self) -> None:
        """Invalidate cached index (call after external changes)."""
        self._set_index({})
        self._set_hashes({})

    @property
    def name(self) -> str:
        return "local"

    def search(self, query: PaperQuery) -> Iterator[PaperCandidate]:
        """Search user PDFs by DOI, title, or author.

        Uses cached index for efficiency.
        Supports parallel processing for large directories.
        """
        index = self._get_index()

        if _has_tqdm and len(index) > 50:
            yield from self._search_parallel(index, query)
        else:
            yield from self._search_sequential(index, query)

    def _search_parallel(
        self, index: dict[str, Path], query: PaperQuery
    ) -> Iterator[PaperCandidate]:
        """Search using parallel processing for large directories."""
        with ThreadPoolExecutor() as executor:
            futures = {
                executor.submit(_pdf_to_candidate, pdf_path, self.name): pdf_path
                for pdf_path in index.values()
                if pdf_path.exists()
            }

            tqdm_iter = self._create_progress_iter(futures)

            for future in tqdm_iter:
                candidate = self._process_future(future)
                if candidate and matches_query(candidate, query):
                    yield candidate

    def _create_progress_iter(self, futures: dict[Future, Path]) -> Iterator[Future]:
        """Create progress iterator for futures."""
        # Get a display name for progress (first path name or 'pdfs')
        display_name = self.pdf_dirs[0].name if self.pdf_dirs else "pdfs"
        if _has_tqdm and tqdm is not None:
            return tqdm(
                as_completed(futures),
                total=len(futures),
                desc=f"Searching {display_name}",
                unit="paper",
            )  # type: ignore[return-value]
        return as_completed(futures)

    def _process_future(self, future: Future) -> PaperCandidate | None:
        """Process a single future result."""
        try:
            return future.result()
        except Exception as e:
            _log.debug("Failed to process PDF: %s", e)
            return None

    def _search_sequential(
        self, index: dict[str, Path], query: PaperQuery
    ) -> Iterator[PaperCandidate]:
        """Search using sequential processing for small directories."""
        for paper_id, pdf_path in index.items():
            if not pdf_path.exists():
                continue
            candidate = _pdf_to_candidate(pdf_path, self.name)
            if matches_query(candidate, query):
                yield candidate

    def fetch_by_id(self, paper_id: str) -> PaperCandidate | None:
        """Fetch user PDF by DOI or filename."""
        index = self._get_index()

        pdf_path = index.get(paper_id)
        if pdf_path and pdf_path.exists():
            return _pdf_to_candidate(pdf_path, self.name)

        # Try partial match
        for key, path in index.items():
            if paper_id.lower() in key.lower():
                if path.exists():
                    return _pdf_to_candidate(path, self.name)

        return None

    def count(self) -> int:
        """Count total PDFs in directory."""
        return len(self._get_index())
