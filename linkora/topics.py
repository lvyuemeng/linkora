"""topics.py - Topic modeling workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, Sequence

from linkora.config import TopicsConfig
from linkora.setup import resolve_data_path
from linkora.store import Document, DocumentTopic, Topic


class TopicsUnavailable(RuntimeError):
    """Raised when topic modeling is requested but not available."""


@dataclass(frozen=True)
class TopicSummary:
    topic_id: int
    label: str
    top_terms: list[str]
    size: int


@dataclass(frozen=True)
class TopicAssignment:
    doc_id: str
    topic_id: int
    score: float


@dataclass(frozen=True)
class TopicsResult:
    workspace_id: str
    topics: list[TopicSummary]
    assignments: list[TopicAssignment]


class TopicStoreLike(Protocol):
    def replace_workspace(
        self,
        workspace_id: str,
        topics: list[Topic],
        assignments: list[DocumentTopic],
    ) -> None: ...

    def list_topics(self, workspace_id: str) -> list[Topic]: ...

    def delete_assignments(self, workspace_id: str, topic_ids: list[int]) -> int: ...

    def delete_topics(self, workspace_id: str, topic_ids: list[int]) -> int: ...


class TopicsStoreLike(Protocol):
    def list_by_workspace(
        self, workspace_id: str, limit: int = 100
    ) -> list[Document]: ...

    def topic_store(self) -> TopicStoreLike: ...


class VectorIndexLike(Protocol):
    def _compute_embedding(self, text: str) -> list[float]: ...


@dataclass(frozen=True)
class TopicModelStore:
    """Encapsulates topic model file IO."""

    model_dir: Path

    @classmethod
    def from_config(cls, cfg: TopicsConfig) -> "TopicModelStore":
        return cls(model_dir=resolve_data_path(cfg.model_dir))

    def path_for(self, workspace_id: str) -> Path:
        return self.model_dir / f"topics_{workspace_id}.bertopic"

    def save(self, model: Any, workspace_id: str) -> Path:
        self.model_dir.mkdir(parents=True, exist_ok=True)
        path = self.path_for(workspace_id)
        model.save(str(path))
        return path

    def load(self, workspace_id: str) -> Any:
        try:
            from bertopic import BERTopic
        except Exception as exc:
            raise TopicsUnavailable("BERTopic dependencies are not installed.") from exc

        path = self.path_for(workspace_id)
        if not path.exists():
            raise TopicsUnavailable("Topic model not found; run topics build first.")
        return BERTopic.load(str(path))


def build_topics(
    store: TopicsStoreLike,
    vector_index: VectorIndexLike,
    workspace_id: str,
    cfg: TopicsConfig,
    limit: int | None = None,
    model_store: TopicModelStore | None = None,
) -> TopicsResult:
    try:
        from bertopic import BERTopic
        import numpy as np
    except Exception as exc:
        raise TopicsUnavailable("BERTopic dependencies are not installed.") from exc

    docs = store.list_by_workspace(workspace_id, limit=limit or 10000)
    texts, doc_ids = _build_corpus(docs)
    if not texts:
        return TopicsResult(workspace_id=workspace_id, topics=[], assignments=[])

    embeddings = [vector_index._compute_embedding(text) for text in texts]
    embedding_matrix = np.asarray(embeddings, dtype=float)
    nr_topics = cfg.nr_topics if cfg.nr_topics > 0 else None
    model = BERTopic(min_topic_size=cfg.min_topic_size, nr_topics=nr_topics)
    topic_ids, probs = model.fit_transform(texts, embedding_matrix)

    model_repo = model_store or TopicModelStore.from_config(cfg)
    model_repo.save(model, workspace_id)

    topic_summaries, topic_records = _collect_topics(model, topic_ids, workspace_id)
    assignments, assignment_records = _build_assignments(
        doc_ids=doc_ids,
        topic_ids=topic_ids,
        probs=probs,
        workspace_id=workspace_id,
    )
    store.topic_store().replace_workspace(
        workspace_id, topic_records, assignment_records
    )
    return TopicsResult(
        workspace_id=workspace_id, topics=topic_summaries, assignments=assignments
    )


def assign_topics(
    store: TopicsStoreLike,
    vector_index: VectorIndexLike,
    workspace_id: str,
    cfg: TopicsConfig,
    limit: int | None = None,
    model_store: TopicModelStore | None = None,
) -> TopicsResult:
    model_repo = model_store or TopicModelStore.from_config(cfg)
    model = model_repo.load(workspace_id)

    docs = store.list_by_workspace(workspace_id, limit=limit or 10000)
    texts, doc_ids = _build_corpus(docs)
    if not texts:
        return TopicsResult(workspace_id=workspace_id, topics=[], assignments=[])

    embeddings = [vector_index._compute_embedding(text) for text in texts]
    topic_ids, probs = model.transform(texts, embeddings)

    topic_summaries, topic_records = _collect_topics(model, topic_ids, workspace_id)
    assignments, assignment_records = _build_assignments(
        doc_ids=doc_ids,
        topic_ids=topic_ids,
        probs=probs,
        workspace_id=workspace_id,
    )
    store.topic_store().replace_workspace(
        workspace_id, topic_records, assignment_records
    )
    return TopicsResult(
        workspace_id=workspace_id, topics=topic_summaries, assignments=assignments
    )


def prune_topics(
    store: TopicsStoreLike, workspace_id: str, min_size: int
) -> tuple[int, int]:
    topic_store = store.topic_store()
    topic_ids = [
        topic.topic_id
        for topic in topic_store.list_topics(workspace_id)
        if topic.size < min_size
    ]
    if not topic_ids:
        return (0, 0)
    removed_assignments = topic_store.delete_assignments(workspace_id, topic_ids)
    removed_topics = topic_store.delete_topics(workspace_id, topic_ids)
    return (removed_topics, removed_assignments)


def _build_corpus(docs: Sequence[Document]) -> tuple[list[str], list[str]]:
    texts: list[str] = []
    doc_ids: list[str] = []
    for doc in docs:
        text = " ".join([doc.title or "", doc.l2_summary or ""]).strip()
        if not text:
            continue
        texts.append(text)
        doc_ids.append(doc.id)
    return texts, doc_ids


def _collect_topics(
    model: Any,
    topic_ids: Sequence[int],
    workspace_id: str,
) -> tuple[list[TopicSummary], list[Topic]]:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    sizes: dict[int, int] = {}
    for tid in topic_ids:
        key = int(tid)
        sizes[key] = sizes.get(key, 0) + 1

    summaries: list[TopicSummary] = []
    records: list[Topic] = []
    for topic_id in sorted({int(t) for t in topic_ids if int(t) != -1}):
        topic_terms = model.get_topic(topic_id) or []
        terms = [str(term) for term, _ in topic_terms]
        label = terms[0] if terms else f"topic-{topic_id}"
        size = sizes.get(topic_id, 0)
        summaries.append(
            TopicSummary(topic_id=topic_id, label=label, top_terms=terms, size=size)
        )
        records.append(
            Topic(
                topic_id=topic_id,
                workspace_id=workspace_id,
                label=label,
                top_terms=terms,
                size=size,
                created_at=now,
            )
        )
    return summaries, records


def _build_assignments(
    doc_ids: list[str],
    topic_ids: Sequence[int],
    probs: Any,
    workspace_id: str,
) -> tuple[list[TopicAssignment], list[DocumentTopic]]:
    assignments: list[TopicAssignment] = []
    records: list[DocumentTopic] = []
    for idx, doc_id in enumerate(doc_ids):
        topic_id = int(topic_ids[idx])
        if topic_id == -1:
            continue
        score = _topic_score(probs, idx, topic_id)
        assignments.append(
            TopicAssignment(doc_id=doc_id, topic_id=topic_id, score=score)
        )
        records.append(
            DocumentTopic(
                doc_id=doc_id,
                workspace_id=workspace_id,
                topic_id=topic_id,
                score=score,
            )
        )
    return assignments, records


def _topic_score(probs: Any, doc_idx: int, topic_id: int) -> float:
    if probs is None:
        return 0.0
    try:
        return float(probs[doc_idx][topic_id])
    except Exception:
        return 0.0


__all__ = [
    "TopicsUnavailable",
    "TopicModelStore",
    "TopicSummary",
    "TopicAssignment",
    "TopicsResult",
    "build_topics",
    "assign_topics",
    "prune_topics",
]
