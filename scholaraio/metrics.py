"""
metrics.py -- ScholarAIO Metrics Collection and Persistence
==========================================

Three main features:
  1. MetricsStore -- SQLite persistence (data/metrics.db)
  2. timer / timed -- timing context manager / decorator
  3. call_llm -- unified LLM call entry, auto-tracks token usage
"""

from __future__ import annotations

import json as _json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from functools import wraps
from pathlib import Path
from typing import Any, Generator


from scholaraio.log import get_logger

_log = get_logger(__name__)

# ============================================================================
#  Event Enums and Data Classes (Immutable)
# ============================================================================


class EventCategory(Enum):
    """Event category - type-safe enum."""

    LLM = "llm"
    API = "api"
    STEP = "step"


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
            timestamp=datetime.now(timezone.utc),
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
            timestamp=datetime.now(timezone.utc),
            llm_metrics=LLMMetrics(duration_s=duration_s),
            metadata=EventMetadata(status=status, detail=detail),
        )


@dataclass(frozen=True)
class TimeRange:
    """Immutable time range for queries."""

    since: datetime | None = None
    until: datetime | None = None

    def to_sql(self) -> tuple[str, list[Any]]:
        """Convert to SQL WHERE clause."""
        clauses = []
        params: list[Any] = []
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
            params.append(self.category.value)

        if self.time_range:
            time_sql, time_params = self.time_range.to_sql()
            clauses.append(time_sql)
            params.extend(time_params)

        return (" AND ".join(clauses), params) if clauses else ("", [])


@dataclass(frozen=True)
class MetricsResult:
    """Immutable query result."""

    events: tuple[dict[str, Any], ...]
    total_count: int


@dataclass(frozen=True)
class LLMSummary:
    """Immutable LLM usage summary."""

    call_count: int
    total_tokens_in: int
    total_tokens_out: int
    total_duration_s: float


# ============================================================================
#  TimerResult
# ============================================================================


@dataclass
class TimerResult:
    """Timing result yielded by :func:`timer` context manager.

    Read ``elapsed`` inside the ``with`` block for real-time elapsed time;
    after exit, returns the final elapsed time.
    """

    def __init__(self) -> None:
        self._t0: float = 0.0
        self._final: float | None = None

    @property
    def elapsed(self) -> float:
        if self._final is not None:
            return self._final
        if self._t0:
            return time.monotonic() - self._t0
        return 0.0

    @elapsed.setter
    def elapsed(self, value: float) -> None:
        self._final = value


# ============================================================================
#  MetricsStore
# ============================================================================


_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT    NOT NULL,
    timestamp  TEXT    NOT NULL,
    category   TEXT    NOT NULL,
    name       TEXT    NOT NULL,
    duration_s REAL,
    tokens_in  INTEGER,
    tokens_out INTEGER,
    model      TEXT,
    status     TEXT    DEFAULT 'ok',
    detail     TEXT
);
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);",
    "CREATE INDEX IF NOT EXISTS idx_events_category ON events(category);",
]


class MetricsStore:
    """SQLite-backed metrics store with lazy connection.

    Args:
        db_path: Database file path, use ``":memory:"`` for testing.
        session_id: Current session ID.
    """

    def __init__(self, db_path: Path | str, session_id: str) -> None:
        self._session_id = session_id
        self._db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    def _ensure_connection(self) -> sqlite3.Connection:
        """Lazy connection initialization."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(_CREATE_TABLE)
            for idx_sql in _CREATE_INDEXES:
                self._conn.execute(idx_sql)
            self._conn.commit()
        return self._conn

    @property
    def session_id(self) -> str:
        return self._session_id

    def record_event(self, event: MetricsEvent) -> None:
        """Record a metrics event using typed interface.

        Args:
            event: MetricsEvent instance.
        """
        conn = self._ensure_connection()
        llm = event.llm_metrics
        meta = event.metadata

        conn.execute(
            "INSERT INTO events (session_id, timestamp, category, name, "
            "duration_s, tokens_in, tokens_out, model, status, detail) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                self._session_id,
                event.timestamp.isoformat(),
                event.category.value,
                event.name,
                llm.duration_s if llm else None,
                llm.tokens_in if llm else None,
                llm.tokens_out if llm else None,
                llm.model if llm else None,
                meta.status.value if meta else "ok",
                _json.dumps(meta.detail, ensure_ascii=False) if meta and meta.detail else None,
            ),
        )
        conn.commit()

    def query_events(self, query: MetricsQuery) -> MetricsResult:
        """Query metrics events using typed interface.

        Args:
            query: MetricsQuery instance.

        Returns:
            MetricsResult with events tuple.
        """
        conn = self._ensure_connection()
        filter_sql, filter_params = query.to_sql()
        where = (" WHERE " + filter_sql) if filter_sql else ""

        sql = f"SELECT * FROM events{where} ORDER BY id DESC LIMIT ?"
        filter_params.append(query.limit)

        cur = conn.execute(sql, filter_params)
        cols = [d[0] for d in cur.description]
        events = tuple(dict(zip(cols, row)) for row in cur.fetchall())

        return MetricsResult(events=events, total_count=len(events))

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
        """Record a metrics event (backward compatible interface)."""
        conn = self._ensure_connection()
        conn.execute(
            "INSERT INTO events (session_id, timestamp, category, name, "
            "duration_s, tokens_in, tokens_out, model, status, detail) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                self._session_id,
                datetime.now(timezone.utc).isoformat(),
                category,
                name,
                duration_s,
                tokens_in,
                tokens_out,
                model,
                status,
                _json.dumps(detail, ensure_ascii=False) if detail else None,
            ),
        )
        conn.commit()

    def query(
        self,
        category: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """Query metrics events (backward compatible interface)."""
        conn = self._ensure_connection()
        clauses = []
        params: list[Any] = []
        if category:
            clauses.append("category = ?")
            params.append(category)
        if since:
            clauses.append("timestamp >= ?")
            params.append(since)
        if until:
            clauses.append("timestamp <= ?")
            params.append(until)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM events{where} ORDER BY id DESC LIMIT ?"
        params.append(limit)
        cur = conn.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def summary(self, session_id: str | None = None) -> LLMSummary:
        """Summarize LLM token usage.

        Args:
            session_id: Optional session filter.

        Returns:
            LLMSummary with token counts and duration.
        """
        conn = self._ensure_connection()
        clause = "WHERE category = 'llm'"
        params: list[Any] = []
        if session_id:
            clause += " AND session_id = ?"
            params.append(session_id)
        sql = (
            f"SELECT COUNT(*) as cnt, "
            f"COALESCE(SUM(tokens_in), 0), "
            f"COALESCE(SUM(tokens_out), 0), "
            f"COALESCE(SUM(duration_s), 0) "
            f"FROM events {clause}"
        )
        row = conn.execute(sql, params).fetchone()
        return LLMSummary(
            call_count=row[0] or 0,
            total_tokens_in=row[1] or 0,
            total_tokens_out=row[2] or 0,
            total_duration_s=round(row[3] or 0, 2),
        )

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


# ============================================================================
#  Module-level singleton
# ============================================================================

_store: MetricsStore | None = None


def init(db_path: Path | str, session_id: str) -> MetricsStore:
    """Initialize global MetricsStore singleton.

    Args:
        db_path: SQLite database path.
        session_id: Current session ID.

    Returns:
        Initialized MetricsStore instance.
    """
    global _store
    db = Path(db_path)
    db.parent.mkdir(parents=True, exist_ok=True)
    _store = MetricsStore(db, session_id)
    _log.debug("metrics store initialized: %s (session %s)", db, session_id)
    return _store


def get_store() -> MetricsStore | None:
    """Get global MetricsStore instance, returns None if not initialized."""
    return _store


def reset() -> None:
    """Close and reset global store (for testing only)."""
    global _store
    if _store:
        _store.close()
    _store = None


# ============================================================================
#  Timing utilities
# ============================================================================


@contextmanager
def timer(name: str, category: str = "step") -> Generator[TimerResult, None, None]:
    """Timing context manager, auto-records to MetricsStore.

    Args:
        name: Event name.
        category: Event category.

    Yields:
        :class:`TimerResult`, ``elapsed`` is populated on exit.

    Example::

        with timer("mineru.cloud", category="api") as t:
            do_something()
        print(f"Elapsed {t.elapsed:.1f}s")
    """
    result = TimerResult()
    result._t0 = time.monotonic()
    status = "ok"
    try:
        yield result
    except Exception:
        status = "error"
        raise
    finally:
        result.elapsed = time.monotonic() - result._t0
        if _store:
            _store.record(category, name, duration_s=result.elapsed, status=status)


def timed(name: str = "", category: str = "step"):
    """Timing decorator.

    Args:
        name: Event name, defaults to function qualified name.
        category: Event category.
    """

    def decorator(fn):
        event_name = name or f"{fn.__module__}.{fn.__qualname__}"

        @wraps(fn)
        def wrapper(*args, **kwargs):
            with timer(event_name, category):
                return fn(*args, **kwargs)

        return wrapper

    return decorator