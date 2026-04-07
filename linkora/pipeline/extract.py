from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

from linkora import content_hash


@dataclass(frozen=True)
class ExtractionResult:
    content: str
    metadata: dict
    tables: list[dict] | None = None


@dataclass(frozen=True)
class ExtractionCache:
    cache_dir: Path

    def path_for(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def load(self, key: str) -> ExtractionResult | None:
        cache_file = self.path_for(key)
        if not cache_file.exists():
            return None
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            return None
        try:
            return ExtractionResult(**data)
        except Exception:
            return None

    def save(self, key: str, result: ExtractionResult) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = self.path_for(key)
        payload = {
            "content": result.content,
            "metadata": result.metadata,
            "tables": result.tables,
        }
        try:
            cache_file.write_text(json.dumps(payload), encoding="utf-8")
        except Exception:
            return


async def extract_text(
    path: Path, cache: ExtractionCache | None = None
) -> ExtractionResult:
    """Extract text from a file using Kreuzberg with content-hash caching."""
    key = content_hash(path)
    if cache is not None:
        cached = cache.load(key)
        if cached:
            return cached

    from kreuzberg import ExtractionConfig, extract_file

    result = await extract_file(path, config=ExtractionConfig(use_cache=True))
    extraction = ExtractionResult(
        content=result.content or "",
        metadata={
            "title": result.metadata.title
            if hasattr(result.metadata, "title")
            else None,
            "author": result.metadata.author
            if hasattr(result.metadata, "author")
            else None,
            "page_count": result.metadata.page_count
            if hasattr(result.metadata, "page_count")
            else None,
        },
        tables=result.tables if hasattr(result, "tables") else None,
    )
    if cache is not None:
        cache.save(key, extraction)
    return extraction


__all__ = ["ExtractionResult", "ExtractionCache", "extract_text"]
