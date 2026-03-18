# metrics.py Refactoring Plan

> Refactor `linkora/metrics.py` to align with AGENT.md philosophy and module patterns from `config.py`, `llm.py`, and `index/text.py`.
> Based on `docs/AGENT.md` coding standards and `plans/implementation-plan.md` principles.

---

## 0. Data Pipe Flow Analysis (CRITICAL)

### Current Fragile Arguments

**record() function** (lines 135-146):
```python
def record(
    self,
    category: str,
    name: str,
    *,
    duration_s: float | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    model: str | None = None,
    status: str = "ok",
    detail: dict | None = None,
) -> None:
```

**Problems:**
1. 9 separate parameters with no semantic grouping
2. `duration_s`, `tokens_in`, `tokens_out`, `model` should be grouped as LLM metrics
3. `status` and `detail` are metadata that should be grouped
4. No type safety - any string can be passed as category/name

**query() function** (lines 178-184):
```python
def query(
    self,
    category: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 200,
) -> list[dict]:
```

**Problems:**
1. 4 scattered parameters - no grouping
2. Returns `list[dict]` - no type safety (should use typed dataclass)
3. Time filter should use proper datetime type

### Target: Semantic Grouping with Pipe Flow

Following `index/text.py` pattern (`FilterParams` with `to_sql()`) and `extract.py` pattern (`ExtractionInput` → `ExtractionOutput`):

```python
# Data pipe flow (aligned with extract.py):
MetricsEvent → record() → MetricsBackend → query() → MetricsResult
                          ↓
                     MetricsQuery (filter)
```

---

## 1. New Data Structures (Immutable) - Single File

### 1.1 Event Data Classes

```python
# linkora/metrics/types.py

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from typing import Any


class EventCategory(Enum):
    """Event category - type-safe enum."""
    LLM = auto()
    API = auto()
    STEP = auto()


class EventStatus(Enum):
    """Event status - type-safe enum."""
    OK = "ok"
    ERROR = "error"
    SKIP = "skip"


@dataclass(frozen=True)
class LLMMetrics:
    """Immutable LLM usage metrics - grouped semantically."""
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""
    duration_s: float = 0.0

    @property
    def tokens_total(self) -> int:
        return self.tokens_in + self.tokens_out


@dataclass(frozen=True)
class EventMetadata:
    """Immutable event metadata."""
    status: EventStatus = EventStatus.OK
    detail: dict[str, Any] | None = None


@dataclass(frozen=True)
class MetricsEvent:
    """Immutable metrics event - complete record."""
    category: EventCategory
    name: str
    timestamp: datetime
    llm_metrics: LLMMetrics | None = None
    metadata: EventMetadata | None = None

    @classmethod
    def create_llm(
        cls,
        name: str,
        llm_metrics: LLMMetrics,
        status: EventStatus = EventStatus.OK,
        detail: dict[str, Any] | None = None,
    ) -> "MetricsEvent":
        """Factory for LLM event."""
        return cls(
            category=EventCategory.LLM,
            name=name,
            timestamp=datetime.now(),
            llm_metrics=llm_metrics,
            metadata=EventMetadata(status=status, detail=detail),
        )

    @classmethod
    def create_step(
        cls,
        name: str,
        duration_s: float,
        status: EventStatus = EventStatus.OK,
        detail: dict[str, Any] | None = None,
    ) -> "MetricsEvent":
        """Factory for step/timing event."""
        return cls(
            category=EventCategory.STEP,
            name=name,
            timestamp=datetime.now(),
            llm_metrics=LLMMetrics(duration_s=duration_s),
            metadata=EventMetadata(status=status, detail=detail),
        )
```

### 1.2 Query Data Classes

```python
# linkora/metrics/types.py (continued)

@dataclass(frozen=True)
class TimeRange:
    """Immutable time range for queries."""
    since: datetime | None = None
    until: datetime | None = None

    def to_sql(self) -> tuple[str, list[Any]]:
        """Convert to SQL WHERE clause - aligned with FilterParams pattern."""
        clauses = []
        params = []
        if self.since:
            clauses.append("timestamp >= ?")
            params.append(self.since.isoformat())
        if self.until:
            clauses.append("timestamp <= ?")
            params.append(self.until.isoformat())
        return (" AND ".join(clauses), params) if clauses else ("", [])


@dataclass(frozen=True)
class MetricsQuery:
    """Immutable query parameters - grouped semantically."""
    category: EventCategory | None = None
    time_range: TimeRange | None = None
    limit: int = 200

    def to_sql(self) -> tuple[str, list[Any]]:
        """Convert to SQL WHERE clause."""
        clauses = []
        params: list[Any] = []
        
        if self.category:
            clauses.append("category = ?")
            params.append(self.category.name.lower())
        
        if self.time_range:
            time_sql, time_params = self.time_range.to_sql()
            clauses.append(time_sql)
            params.extend(time_params)
        
        return (" AND ".join(clauses), params) if clauses else ("", [])
```

### 1.3 Result Data Class

```python
@dataclass(frozen=True)
class MetricsResult:
    """Immutable query result - not list[dict]."""
    events: tuple[MetricsEvent, ...]
    total_count: int


@dataclass(frozen=True)
class LLMSummary:
    """Immutable LLM usage summary."""
    call_count: int
    total_tokens_in: int
    total_tokens_out: int
    total_duration_s: float
```

---

## 2. Refactored Interface (Data Pipe Flow)

### 2.1 MetricsStore with Semantic Grouping

```python
# linkora/metrics.py - refactor in place

class MetricsStore:
    """SQLite-backed metrics store - uses typed data classes."""

    def record(self, event: MetricsEvent) -> None:
        """Record a metrics event - single typed parameter."""
        # Internally converts to SQL
        ...

    def query(self, query: MetricsQuery) -> MetricsResult:
        """Query with typed parameters - returns typed result."""
        # Returns MetricsResult, not list[dict]
        ...

    def summary(self, session_id: str | None = None) -> LLMSummary:
        """Get LLM usage summary - returns typed result."""
        ...
```

### 2.2 Convenience Factory Functions

```python
# linkora/metrics/__init__.py

def record_llm(
    name: str,
    tokens_in: int,
    tokens_out: int,
    model: str,
    duration_s: float,
    status: str = "ok",
    detail: dict | None = None,
) -> None:
    """Convenience: record LLM event with flat parameters."""
    event = MetricsEvent.create_llm(
        name=name,
        llm_metrics=LLMMetrics(
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            model=model,
            duration_s=duration_s,
        ),
        status=EventStatus(status),
        detail=detail,
    )
    _store.record(event)
```

---

## 3. Efficiency Improvements

### 3.1 Batch Operations

```python
def record_batch(self, events: list[MetricsEvent]) -> None:
    """Batch insert for efficiency - single transaction."""
    self._conn.executemany(
        "INSERT INTO events ...",
        [self._event_to_row(e) for e in events]
    )
    self._conn.commit()
```

### 3.2 Lazy Connection

```python
class MetricsStore:
    """SQLite-backed metrics store - lazy connection."""

    def __init__(self, db_path: Path, session_id: str) -> None:
        self._db_path = db_path
        self._session_id = session_id
        self._conn: sqlite3.Connection | None = None

    def _ensure_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._ensure_schemas()
        return self._conn
```

### 3.3 Prepared Statements

```python
# Cache prepared statements for repeated queries
class MetricsStore:
    def _ensure_connection(self) -> sqlite3.Connection:
        conn = super()._ensure_connection()
        if not hasattr(self, '_stmt_insert'):
            self._stmt_insert = conn.prepare(
                "INSERT INTO events ..."
            )
        return conn
```

---

## 4. Implementation Order

```
1. Add data classes at top of metrics.py (EventCategory, LLMMetrics, MetricsEvent, MetricsQuery, etc.)
2. Refactor MetricsStore.record() to accept MetricsEvent
3. Refactor MetricsStore.query() to accept MetricsQuery, return typed result
4. Add batch operations for efficiency
5. Add lazy connection initialization
6. Fix logging pattern, TYPE_CHECKING
7. Remove duplicate LLMResult, import from llm.py
8. Replace call_llm with LLMRunner usage
9. Test that metrics command still works
```

---

## 5. Files Structure

```
linkora/metrics.py  # Single file - refactor in place
```

---

## Summary: Key Improvements

| Aspect | Before | After |
|--------|-------|-------|
| record() args | 9 separate params | Single `MetricsEvent` |
| query() args | 4 scattered params | Single `MetricsQuery` |
| Return type | `list[dict]` | `MetricsResult` |
| Data flow | Fragile, no pipe | Event → Store → Query → Result |
| Efficiency | Individual commits | Batch operations |
| Connection | Eager | Lazy |
| Type safety | String enums | Proper Enums |
