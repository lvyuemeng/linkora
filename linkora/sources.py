"""sources.py — Retrieval-only document sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Protocol
import re
from urllib.parse import parse_qs, unquote, urlparse
import xml.etree.ElementTree as ET

from linkora.log import get_logger, ui


_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
_WIN_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_ARXIV_ID_RE = re.compile(r"^(?:arxiv:)?(\d{4}\.\d{4,5})(?:v\d+)?$", re.IGNORECASE)
_LOG = get_logger(__name__)


@dataclass(frozen=True)
class SourceRequest:
    """Normalized source request parsed from CLI target."""

    scheme: str
    value: str
    params: dict[str, str]
    raw: str


@dataclass(frozen=True)
class FetchResult:
    """Returned by every source after a successful fetch."""

    path: Path
    raw_metadata: dict


class DocumentSource(Protocol):
    """Protocol for document data sources (v2 design)."""

    @property
    def name(self) -> str: ...

    def fetch(
        self,
        request: SourceRequest,
        output_path: Path,
        **kwargs,
    ) -> Iterator[FetchResult]: ...

    def count(self, request: SourceRequest, **kwargs) -> int: ...


class SourceError(Exception):
    """Base exception for source errors."""


@dataclass(frozen=True)
class SourceIngestRequest:
    targets: list[str]
    source: str | None
    output_dir: Path
    workspace_id: str
    doc_type_hint: str | None
    dry_run: bool


@dataclass(frozen=True)
class SourceIngestResult:
    target: str
    scheme: str
    status: str
    count: int
    message: str | None = None


@dataclass(frozen=True)
class ParsedTarget:
    target: str
    request: SourceRequest


@dataclass(frozen=True)
class ResolvedSource:
    parsed: ParsedTarget
    source: DocumentSource | None
    error: str | None = None


@dataclass(frozen=True)
class FetchOutcome:
    fetched: list[FetchResult]
    error: str | None = None


@dataclass(frozen=True)
class IngestOutcome:
    count: int
    failed: int
    messages: list[str] = field(default_factory=list)
    error: str | None = None


def parse_source_request(
    target: str, preferred_scheme: str | None = None
) -> SourceRequest:
    """Parse a CLI target into a structured SourceRequest."""
    raw = target.strip()
    if not raw:
        return SourceRequest(scheme="unknown", value="", params={}, raw=target)

    if preferred_scheme:
        pref = preferred_scheme.lower()
        if raw.lower().startswith(f"{pref}:"):
            raw = raw.split(":", 1)[1]
        if "?" in raw:
            base, _, qs = raw.partition("?")
            params = {k: v[-1] for k, v in parse_qs(qs).items()}
            return SourceRequest(scheme=pref, value=base, params=params, raw=target)
        return SourceRequest(scheme=pref, value=raw, params={}, raw=target)

    if _looks_like_path(raw) or Path(raw).exists():
        return SourceRequest(scheme="file", value=raw, params={}, raw=target)

    if raw.startswith(("http://", "https://")):
        return SourceRequest(scheme="web", value=raw, params={}, raw=target)

    if _DOI_RE.match(raw):
        return SourceRequest(scheme="doi", value=raw, params={}, raw=target)

    if _ARXIV_ID_RE.match(raw):
        return SourceRequest(
            scheme="arxiv", value=_ARXIV_ID_RE.sub(r"\1", raw), params={}, raw=target
        )

    parsed = urlparse(raw)
    scheme = parsed.scheme.lower() if parsed.scheme else ""

    if scheme in {
        "doi",
        "web",
        "local",
        "file",
        "arxiv",
    }:
        params = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
        value = parsed.netloc + parsed.path if parsed.netloc else parsed.path
        value = unquote(value)
        if scheme == "web" and not value:
            value = raw[len(parsed.scheme) + 1 :]
        return SourceRequest(scheme=scheme, value=value, params=params, raw=target)

    if scheme in {"http", "https"}:
        return SourceRequest(scheme="web", value=raw, params={}, raw=target)

    return SourceRequest(scheme="auto", value=raw, params={}, raw=target)


def _looks_like_path(value: str) -> bool:
    if _WIN_DRIVE_RE.match(value):
        return True
    return value.startswith(("/", "\\", "./", "../", "~"))


@dataclass
class LocalSource:
    """Reference existing files without copying them."""

    roots: list[Path] | None = None
    recursive: bool = True
    suffixes: set[str] | None = None

    @property
    def name(self) -> str:
        return "local"

    def _scan(
        self,
        roots: list[Path],
        recursive: bool,
        pattern: str | None,
    ) -> Iterator[Path]:
        for root in roots:
            if not root.exists():
                continue
            if pattern:
                for path in root.glob(pattern):
                    if path.is_file():
                        yield path
                continue
            glob_pat = "**/*" if recursive else "*"
            for path in root.glob(glob_pat):
                if path.is_file():
                    yield path

    def _matches(self, path: Path, query: str) -> bool:
        if not query:
            return True
        return query.lower() in path.stem.lower()

    def _match_suffix(self, path: Path, suffixes: set[str] | None) -> bool:
        if not suffixes:
            return True
        return path.suffix.lower() in suffixes

    def fetch(
        self, request: SourceRequest, output_path: Path, **_
    ) -> Iterator[FetchResult]:
        query = request.value
        roots = [root.expanduser() for root in self.roots] if self.roots else []
        if not roots:
            raw_path = request.value.strip()
            if not raw_path:
                raise SourceError("Local source requires a path")
            resolved = Path(raw_path).expanduser()
            if not resolved.exists():
                raise SourceError(f"Path not found: {resolved}")
            if resolved.is_file():
                if not self._match_suffix(resolved, self.suffixes):
                    raise SourceError(f"Unsupported file type: {resolved.name}")
                yield FetchResult(path=resolved, raw_metadata={})
                return
            roots = [resolved]
            query = request.params.get("query", "")

        pattern = request.params.get("pattern")
        recursive = _parse_bool(request.params.get("recursive"), self.recursive)
        suffixes = _parse_suffixes(request.params.get("suffixes"), self.suffixes)
        limit = _parse_int(request.params.get("limit"))
        count = 0

        for path in self._scan(roots=roots, recursive=recursive, pattern=pattern):
            if not self._match_suffix(path, suffixes):
                continue
            if not self._matches(path, query):
                continue
            yield FetchResult(path=path, raw_metadata={})
            count += 1
            if limit and count >= limit:
                return

    def count(self, request: SourceRequest, **_) -> int:
        return sum(1 for _ in self.fetch(request, Path(".")))


def _parse_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _parse_suffixes(raw: str | None, fallback: set[str] | None) -> set[str] | None:
    if raw is None:
        return fallback
    items = [s.strip().lower() for s in raw.split(",") if s.strip()]
    return {s if s.startswith(".") else f".{s}" for s in items}


@dataclass
class DOISource:
    """Resolve DOI and download PDF."""

    @property
    def name(self) -> str:
        return "doi"

    def fetch(
        self, request: SourceRequest, output_path: Path, **kwargs
    ) -> Iterator[FetchResult]:
        import httpx

        doi = request.value.strip()
        if not doi:
            return

        url = f"https://api.unpaywall.org/v2/{doi}?email=linkora@example.com"
        try:
            resp = httpx.get(url, timeout=30, follow_redirects=True)
            resp.raise_for_status()
            data = resp.json()

            pdf_url = data.get("best_oa_location", {}).get("url_for_pdf")
            if not pdf_url:
                return

            pdf_resp = httpx.get(pdf_url, timeout=60, follow_redirects=True)
            pdf_resp.raise_for_status()

            filename = request.params.get("filename") or f"{doi.replace('/', '_')}.pdf"
            if not filename.lower().endswith(".pdf"):
                filename = f"{filename}.pdf"
            output_path.mkdir(parents=True, exist_ok=True)
            file_path = output_path / filename

            with open(file_path, "wb") as f:
                f.write(pdf_resp.content)

            raw_metadata = {
                "doi": doi,
                "title": data.get("title", ""),
                "authors": [a.get("author", "") for a in data.get("authors", [])],
                "year": data.get("published_date", ""),
                "journal": data.get("container_title", ""),
            }

            yield FetchResult(path=file_path, raw_metadata=raw_metadata)

        except Exception:
            return

    def count(self, request: SourceRequest, **kwargs) -> int:
        if not request.value:
            return 0
        return 1


@dataclass
class WebSource:
    """Fetch web page content as markdown."""

    @property
    def name(self) -> str:
        return "web"

    def fetch(
        self, request: SourceRequest, output_path: Path, **kwargs
    ) -> Iterator[FetchResult]:
        import asyncio
        import httpx
        import shutil
        import tempfile
        from datetime import datetime, timezone

        url = request.value.strip()
        if not url:
            return

        if not url.startswith(("http://", "https://")):
            return

        try:
            resp = httpx.get(
                url,
                timeout=30,
                headers={"User-Agent": "Mozilla/5.0 (compatible; Linkora/2.0)"},
                follow_redirects=True,
            )
            resp.raise_for_status()

            from kreuzberg import extract_file, ExtractionConfig

            temp_dir = Path(tempfile.mkdtemp(prefix="linkora_web_"))
            temp_path = temp_dir / "page.html"
            temp_path.write_text(
                resp.text,
                encoding=resp.encoding or "utf-8",
                errors="ignore",
            )
            try:
                result = asyncio.run(
                    extract_file(
                        temp_path,
                        ExtractionConfig(
                            extract_tables=False,
                        ),
                    )
                )
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)

            markdown_content = result.content or ""

            from urllib.parse import urlparse

            parsed = urlparse(url)
            filename = request.params.get("filename")
            if not filename:
                filename = parsed.netloc + parsed.path
                filename = filename.replace("/", "_")[:100]
            if not filename.lower().endswith(".md"):
                filename = filename + ".md"
            if filename.startswith("_"):
                filename = filename[1:]

            output_path.mkdir(parents=True, exist_ok=True)
            file_path = output_path / filename

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(markdown_content)

            raw_metadata = {
                "url": url,
                "title": result.metadata.title
                if hasattr(result.metadata, "title")
                else "",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }

            yield FetchResult(path=file_path, raw_metadata=raw_metadata)

        except Exception:
            return

    def count(self, request: SourceRequest, **kwargs) -> int:
        if not request.value:
            return 0
        if request.value.startswith(("http://", "https://")):
            return 1
        return 0


@dataclass
class ArxivSource:
    """Fetch arXiv PDFs and metadata via the arXiv API."""

    @property
    def name(self) -> str:
        return "arxiv"

    def fetch(
        self, request: SourceRequest, output_path: Path, **kwargs
    ) -> Iterator[FetchResult]:
        import httpx

        query = request.value.strip()
        if not query:
            return

        arxiv_id = _normalize_arxiv_id(query)
        if arxiv_id:
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
            yield from _download_arxiv_pdf(arxiv_id, pdf_url, output_path)
            return

        max_results = int(request.params.get("max_results", "1"))
        params = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": max_results,
        }
        resp = httpx.get(
            "https://export.arxiv.org/api/query",
            params=params,
            timeout=30,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            return

        root = ET.fromstring(resp.text)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        entries = root.findall("a:entry", ns)
        for entry in entries:
            id_node = entry.find("a:id", ns)
            if id_node is None or not id_node.text:
                continue
            arxiv_id = id_node.text.rsplit("/", 1)[-1]
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
            results = list(_download_arxiv_pdf(arxiv_id, pdf_url, output_path))
            if results:
                title = _get_text(entry, "a:title", ns)
                authors = []
                for a in entry.findall("a:author", ns):
                    name_node = a.find("a:name", ns)
                    if name_node is not None and name_node.text:
                        authors.append(name_node.text)
                published = _get_text(entry, "a:published", ns)
                results[0].raw_metadata.update(
                    {
                        "arxiv_id": arxiv_id,
                        "title": title.strip() if title else "",
                        "authors": authors,
                        "published": published or "",
                        "source": "arxiv",
                    }
                )
                yield results[0]

    def count(self, request: SourceRequest, **kwargs) -> int:
        if not request.value:
            return 0
        return 1


def _normalize_arxiv_id(value: str) -> str | None:
    match = _ARXIV_ID_RE.match(value)
    if not match:
        return None
    return match.group(1)


def _download_arxiv_pdf(
    arxiv_id: str, pdf_url: str, output_path: Path
) -> Iterator[FetchResult]:
    import httpx

    pdf_resp = httpx.get(pdf_url, timeout=60, follow_redirects=True)
    if pdf_resp.status_code != 200:
        return
    filename = f"{arxiv_id.replace('/', '_')}.pdf"
    output_path.mkdir(parents=True, exist_ok=True)
    file_path = output_path / filename
    with open(file_path, "wb") as f:
        f.write(pdf_resp.content)
    yield FetchResult(
        path=file_path, raw_metadata={"arxiv_id": arxiv_id, "source": "arxiv"}
    )


def _get_text(entry: ET.Element, path: str, ns: dict) -> str:
    node = entry.find(path, ns)
    return node.text or "" if node is not None else ""


def run_source_ingest(request: SourceIngestRequest) -> list[SourceIngestResult]:
    from linkora.files import SUPPORTED_SUFFIXES
    from linkora.pipeline.ingest import ingest as run_ingest

    source_registry = _build_source_registry(SUPPORTED_SUFFIXES)
    parsed_targets = _parse_targets(request)
    results: list[SourceIngestResult] = []
    output_dir = request.output_dir.expanduser()

    for parsed in parsed_targets:
        resolved = _resolve_source(parsed, source_registry)
        fetch_outcome = _fetch_source(resolved, output_dir)
        if fetch_outcome.error:
            _log(fetch_outcome.error)

        doc_type_hint = _resolve_doc_type_hint(
            request.doc_type_hint,
            parsed.request.scheme,
        )
        ingest_outcome = _ingest_results(
            fetch_outcome.fetched,
            request,
            run_ingest,
            doc_type_hint,
        )
        for message in ingest_outcome.messages:
            _log(message)

        result_message = fetch_outcome.error or ingest_outcome.error
        results.append(
            SourceIngestResult(
                target=parsed.target,
                scheme=parsed.request.scheme or "unknown",
                status=_resolve_status(
                    count=ingest_outcome.count,
                    failed=ingest_outcome.failed,
                    dry_run=request.dry_run,
                    message=result_message,
                ),
                count=ingest_outcome.count,
                message=result_message,
            )
        )

    return results


def _build_source_registry(supported_suffixes: set[str]) -> dict[str, DocumentSource]:
    return {
        "file": LocalSource(suffixes=supported_suffixes),
        "local": LocalSource(suffixes=supported_suffixes),
        "doi": DOISource(),
        "arxiv": ArxivSource(),
        "web": WebSource(),
    }


def _parse_targets(request: SourceIngestRequest) -> list[ParsedTarget]:
    return [
        ParsedTarget(
            target=target,
            request=parse_source_request(target, request.source),
        )
        for target in request.targets
    ]


def _resolve_source(
    parsed: ParsedTarget,
    registry: dict[str, DocumentSource],
) -> ResolvedSource:
    source = registry.get(parsed.request.scheme)
    if source is None:
        return ResolvedSource(
            parsed=parsed,
            source=None,
            error=f"Unrecognized target: {parsed.request.raw}",
        )
    return ResolvedSource(parsed=parsed, source=source)


def _fetch_source(resolved: ResolvedSource, output_dir: Path) -> FetchOutcome:
    if resolved.source is None:
        return FetchOutcome(fetched=[], error=resolved.error)
    try:
        fetched = list(resolved.source.fetch(resolved.parsed.request, output_dir))
    except SourceError as exc:
        return FetchOutcome(fetched=[], error=str(exc))
    if fetched:
        return FetchOutcome(fetched=fetched)
    scheme = resolved.parsed.request.scheme
    label = scheme.upper() if scheme else "source"
    return FetchOutcome(
        fetched=[],
        error=f"Failed to fetch {label}: {resolved.parsed.request.value}",
    )


def _resolve_doc_type_hint(base_hint: str | None, scheme: str) -> str | None:
    if base_hint:
        return base_hint
    if scheme in {"doi", "arxiv"}:
        return "paper"
    return None


def _ingest_results(
    fetched: list[FetchResult],
    request: SourceIngestRequest,
    run_ingest,
    doc_type_hint: str | None,
) -> IngestOutcome:
    count = 0
    failed = 0
    messages: list[str] = []
    first_error: str | None = None

    for result in fetched:
        if request.dry_run:
            messages.append(f"[DRY RUN] Would add: {result.path}")
            count += 1
            continue
        try:
            ingest_result = _run_async(
                run_ingest,
                path=result.path,
                workspace_id=request.workspace_id,
                metadata_hint=result.raw_metadata or None,
                doc_type_hint=doc_type_hint,
            )
        except Exception as exc:
            error_message = f"Failed to ingest {result.path.name}: {exc}"
            messages.append(error_message)
            if first_error is None:
                first_error = error_message
            failed += 1
            continue
        messages.append(f"Added: {result.path.name} (ID: {ingest_result.doc_id})")
        count += 1

    return IngestOutcome(
        count=count, failed=failed, messages=messages, error=first_error
    )


def _run_async(async_func, *args, **kwargs):
    import asyncio

    return asyncio.run(async_func(*args, **kwargs))


def _log(message: str) -> None:
    ui(message, logger=_LOG)


def _resolve_status(
    count: int,
    failed: int,
    dry_run: bool,
    message: str | None,
) -> str:
    if dry_run:
        return "dry_run"
    if count > 0 and failed == 0:
        return "added"
    if count > 0 and failed > 0:
        return "partial"
    if failed > 0:
        return "failed"
    if not message:
        return "skipped"
    lowered = message.lower()
    if lowered.startswith("no "):
        return "skipped"
    if "unsupported" in lowered:
        return "skipped"
    if "failed" in lowered or "not found" in lowered:
        return "failed"
    return "skipped"


__all__ = [
    "DocumentSource",
    "FetchResult",
    "SourceError",
    "SourceRequest",
    "parse_source_request",
    "LocalSource",
    "DOISource",
    "WebSource",
    "ArxivSource",
    "SourceIngestRequest",
    "SourceIngestResult",
    "run_source_ingest",
]
