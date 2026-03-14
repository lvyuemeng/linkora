# extract.py Pipeline Redesign (Final)

> Complete redesign based on data + pipe flow philosophy.
> Reuses existing data structures from `papers.py` and `llm.py`.

---

## 1. Existing Data Structures to Reuse

### From `scholaraio/papers.py`

| Data Structure | Purpose |
|----------------|---------|
| `PaperMetadata` | Paper metadata (NOT frozen - mutable fields) |
| `_extract_lastname(full_name: str) -> str` | Pure function |

### From `scholaraio/llm.py`

| Data Structure | Purpose |
|----------------|---------|
| `LLMConfig` | LLM configuration (frozen dataclass) |
| `LLMRequest` | LLM request (frozen dataclass) |
| `LLMResult` | LLM response (frozen dataclass) |
| `LLMRunner` | LLM execution (class with DI) |
| `PromptTemplate` | Prompt template (frozen dataclass) |
| `HTTPHeaders` | HTTP headers (frozen dataclass) |
| `LLMPayload` | LLM payload (frozen dataclass) |
| `LLMClient` | Protocol for LLM clients |

---

## 2. New Data Structures (Only What's Missing)

### 2.1 Extraction Types

```python
# scholaraio/extract/types.py

from dataclasses import dataclass
from pathlib import Path
import hashlib


@dataclass(frozen=True)
class ExtractionInput:
    """Immutable input - no path leakage.
    
    Reuses nothing - this is new.
    """
    source_name: str
    raw_text: str
    header: str
    file_hash: str = ""
    
    @classmethod
    def from_file(cls, filepath: Path, header_size: int = 50000) -> ExtractionInput:
        """Factory: create from file."""
        text = filepath.read_text(encoding="utf-8", errors="replace")
        return cls(
            source_name=filepath.name,
            raw_text=text,
            header=text[:header_size],
            file_hash=hashlib.md5(text.encode()).hexdigest()
        )


@dataclass(frozen=True)
class ExtractionOutput:
    """Immutable output with confidence metadata.
    
    Uses PaperMetadata from papers.py.
    """
    metadata: "PaperMetadata"  # Reuse from papers.py
    method: str
    confidence: float
    fallback_used: bool
```

### 2.2 Extractor Config (No Mode String!)

```python
# scholaraio/extract/config.py

from dataclasses import dataclass


@dataclass(frozen=True)
class ExtractorConfig:
    """Data object for extractor selection - no string dispatch.
    
    Reuses nothing - this is new.
    """
    use_llm: bool = False
    fallback: bool = False  # regex → LLM
    robust: bool = False    # regex + LLM dual run
```

---

## 3. Protocol + Implementations

### 3.1 Extractor Protocol

```python
# scholaraio/extract/protocol.py

from typing import Protocol
from scholaraio.extract.types import ExtractionInput, ExtractionOutput


class Extractor(Protocol):
    """Protocol for metadata extractors."""
    
    @property
    def name(self) -> str:
        """Extractor name."""
        ...
    
    def extract(self, input: ExtractionInput) -> ExtractionOutput:
        """Extract metadata from input."""
        ...
```

### 3.2 Regex Extractor

```python
# scholaraio/extract/regex.py

from dataclasses import dataclass
from scholaraio.papers import PaperMetadata, _extract_lastname
from scholaraio.extract.protocol import Extractor
from scholaraio.extract.types import ExtractionInput, ExtractionOutput


@dataclass(frozen=True)
class RegexExtractor:
    """Regex-only extractor - stateless, frozen.
    
    Uses PaperMetadata from papers.py.
    """
    name: str = "regex"
    
    def extract(self, input: ExtractionInput) -> ExtractionOutput:
        # Run regex patterns
        meta = _run_regex_patterns(input.raw_text)
        meta.source_file = input.source_name
        
        # Filename fallback
        fallback_used = False
        fb = _extract_from_filename(input.source_name)
        
        if not meta.title:
            meta.title = fb.title
            fallback_used = True
        if not meta.year:
            meta.year = fb.year
            fallback_used = True
        if not meta.first_author:
            meta.first_author = fb.first_author
            meta.first_author_lastname = fb.first_author_lastname
            fallback_used = True
        
        return ExtractionOutput(
            metadata=meta,
            method="regex",
            confidence=0.8,
            fallback_used=fallback_used
        )


def _run_regex_patterns(text: str) -> PaperMetadata:
    """Run regex patterns - pure function using PaperMetadata."""
    # TODO: Implement regex extraction
    return PaperMetadata(source_file="")


# Module singleton
regex_extractor = RegexExtractor()
```

### 3.3 LLM Extractor

```python
# scholaraio/extract/llm.py

from dataclasses import dataclass
from scholaraio.llm import LLMRunner, LLMRequest, LLMConfig, PromptTemplate
from scholaraio.http import HTTPClient
from scholaraio.papers import PaperMetadata, _extract_lastname
from scholaraio.extract.protocol import Extractor
from scholaraio.extract.types import ExtractionInput, ExtractionOutput


# Prompt templates - use PromptTemplate from llm.py
_EXTRACT_PROMPT = PromptTemplate(
    system="You are a scientific paper metadata extractor.",
    user_template="""从以下学术论文页面提取元数据，以 JSON 格式返回：
{{
  "title": "论文完整标题，找不到填 null",
  "authors": ["姓名1", "姓名2", ...],
  "year": 2024,
  "doi": "10.xxx/xxx",
  "journal": "期刊名"
}}

--- 论文内容 ---
{header}"""
)


@dataclass(frozen=True)
class LLMExtractor:
    """LLM-based extractor - frozen with Protocol DI.
    
    Uses:
    - LLMConfig from llm.py
    - LLMRunner from llm.py
    - HTTPClient Protocol from http.py
    - PaperMetadata from papers.py
    """
    name: str = "llm"
    llm_config: LLMConfig = None
    http_client: HTTPClient = None
    api_key: str = ""
    
    def extract(self, input: ExtractionInput) -> ExtractionOutput:
        runner = LLMRunner(
            config=self.llm_config,
            http_client=self.http_client,
            api_key=self.api_key
        )
        
        request = LLMRequest(
            prompt=_EXTRACT_PROMPT.render(header=input.header),
            config=self.llm_config,
            purpose="extract.llm",
            json_mode=True
        )
        
        result = runner.execute(request)
        meta = _parse_llm_response(result.content, input.source_name)
        
        return ExtractionOutput(
            metadata=meta,
            method="llm",
            confidence=0.9,
            fallback_used=False
        )


def _parse_llm_response(content: str, source_name: str) -> PaperMetadata:
    """Parse LLM JSON response - uses PaperMetadata."""
    import json
    
    data = json.loads(content)
    meta = PaperMetadata(source_file=source_name)
    
    # Clean LLM "null" strings
    def clean(val):
        if val is None:
            return ""
        s = str(val).strip()
        if s.lower() in ("null", "none", "n/a", ""):
            return ""
        return s
    
    meta.title = clean(data.get("title"))
    meta.authors = [a for a in (data.get("authors") or []) if a]
    meta.year = data.get("year") if isinstance(data.get("year"), int) else None
    meta.doi = clean(data.get("doi"))
    meta.journal = clean(data.get("journal"))
    
    if meta.authors:
        meta.first_author = meta.authors[0]
        meta.first_author_lastname = _extract_lastname(meta.first_author)
    
    return meta
```

---

## 4. Legacy Helper Functions

### 4.1 Filename Extraction

```python
# scholaraio/extract/filename.py

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class FilenameMetadata:
    """Metadata from filename - frozen dataclass."""
    title: str = ""
    year: int | None = None
    first_author: str = ""
    first_author_lastname: str = ""


# Patterns
_YEAR_RE = re.compile(r"(19|20)\d{2}")
_AUTHOR_RE = re.compile(r"^([A-Z][a-z]+)")


def _extract_from_filename(filename: str) -> FilenameMetadata:
    """Extract metadata from filename - pure function.
    
    Uses _extract_lastname from papers.py.
    """
    from scholaraio.papers import _extract_lastname
    
    name = filename.split(".")[0]  # Remove extension
    
    # Extract year
    year_match = _YEAR_RE.search(name)
    year = int(year_match.group()) if year_match else None
    
    # Extract author (first capitalized word)
    author_match = _AUTHOR_RE.match(name)
    first_author = author_match.group() if author_match else ""
    lastname = _extract_lastname(first_author) if first_author else ""
    
    # Title is remaining
    title = name
    if year_match:
        title = title.replace(str(year), "").strip("_- ")
    if first_author:
        title = title.replace(first_author, "").strip("_- ")
    
    return FilenameMetadata(
        title=title,
        year=year,
        first_author=first_author,
        first_author_lastname=lastname
    )
```

---

## 5. Factory (Data Object Dispatch)

```python
# scholaraio/extract/__init__.py

from scholaraio.config import Config
from scholaraio.http import RequestsClient, HTTPClient
from scholaraio.llm import LLMConfig
from scholaraio.papers import PaperMetadata

from scholaraio.extract.protocol import Extractor
from scholaraio.extract.types import ExtractionInput, ExtractionOutput
from scholaraio.extract.config import ExtractorConfig
from scholaraio.extract.regex import RegexExtractor, regex_extractor
from scholaraio.extract.llm import LLMExtractor
from scholaraio.extract.auto import AutoExtractor
from scholaraio.extract.robust import RobustExtractor


def create_extractor(
    config: ExtractorConfig,
    llm_config: LLMConfig = None,
    http_client: HTTPClient = None,
    api_key: str = ""
) -> Extractor:
    """Factory: create extractor via data object dispatch."""
    
    if config.robust:
        return RobustExtractor(
            regex=regex_extractor,
            llm=LLMExtractor(
                llm_config=llm_config,
                http_client=http_client,
                api_key=api_key
            ) if api_key else None
        )
    
    if config.fallback:
        return AutoExtractor(
            regex=regex_extractor,
            llm=LLMExtractor(
                llm_config=llm_config,
                http_client=http_client,
                api_key=api_key
            ) if api_key else None
        )
    
    if config.use_llm:
        return LLMExtractor(
            llm_config=llm_config,
            http_client=http_client,
            api_key=api_key
        )
    
    return regex_extractor


def extract(input: ExtractionInput, config: Config) -> ExtractionOutput:
    """Main entry point."""
    http_client = RequestsClient()
    
    # Map config string to ExtractorConfig
    mode = config.ingest.extractor
    extractor_config = ExtractorConfig(
        use_llm=mode == "llm",
        fallback=mode == "auto",
        robust=mode == "robust"
    )
    
    extractor = create_extractor(
        config=extractor_config,
        llm_config=config.llm,
        http_client=http_client,
        api_key=config.resolve_llm_api_key()
    )
    
    return extractor.extract(input)


def extract_file(filepath: str | Path, config: Config) -> ExtractionOutput:
    """Convenience: extract from file path."""
    input = ExtractionInput.from_file(Path(filepath))
    return extract(input, config)
```

---

## 6. Data Structure Summary

| What We Create | Source | Type |
|----------------|--------|------|
| `ExtractionInput` | NEW | frozen dataclass |
| `ExtractionOutput` | NEW | frozen dataclass |
| `ExtractorConfig` | NEW | frozen dataclass |
| `Extractor` Protocol | NEW | Protocol |
| `RegexExtractor` | NEW | frozen dataclass |
| `LLMExtractor` | NEW | frozen dataclass |
| `AutoExtractor` | NEW | frozen dataclass |
| `RobustExtractor` | NEW | frozen dataclass |
| `_extract_from_filename` | NEW | pure function |
| `PromptTemplate` | REUSE from llm.py | frozen dataclass |
| `LLMConfig` | REUSE from llm.py | frozen dataclass |
| `LLMRequest` | REUSE from llm.py | frozen dataclass |
| `LLMResult` | REUSE from llm.py | frozen dataclass |
| `LLMRunner` | REUSE from llm.py | class |
| `HTTPClient` | REUSE from http.py | Protocol |
| `PaperMetadata` | REUSE from papers.py | dataclass |
| `_extract_lastname` | REUSE from papers.py | pure function |

---

## 7. File Structure

```
scholaraio/extract/
├── __init__.py          # extract(), extract_file(), create_extractor()
├── protocol.py          # Extractor Protocol
├── types.py             # ExtractionInput, ExtractionOutput
├── config.py            # ExtractorConfig
├── regex.py             # RegexExtractor
├── llm.py               # LLMExtractor, _EXTRACT_PROMPT
├── filename.py          # _extract_from_filename, FilenameMetadata
├── auto.py              # AutoExtractor
├── robust.py            # RobustExtractor
└── adapter.py           # LegacyAdapter
```

---

## 8. Key Design Points

1. **No new data structures** - Reuse from `papers.py` and `llm.py`
2. **No string dispatch** - Uses `ExtractorConfig` dataclass
3. **Protocol-based DI** - `HTTPClient` Protocol injected
4. **Pure functions** - `_extract_from_filename`, `_parse_llm_response`
5. **Frozen dataclasses** - All extractors are immutable
