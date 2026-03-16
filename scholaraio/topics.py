"""
topics.py — BERTopic Topic Modeling
===================================

Uses Qwen3 embeddings from paper_vectors table for BERTopic clustering.
Supports topic overview, paper lists, hierarchy visualization.

Pipe Flow:
    Input + Config -> TopicTrainer -> TopicModelOutput

Usage:
    from scholaraio.topics import train_topics, TopicConfig, TopicModelOutput

    # Create config with embedder
    config = TopicConfig(embedder=embedder)

    # Train model (loads data, fits BERTopic, returns output)
    output = train_topics(config, db_path, papers_dir)

    # Query methods on output
    overview = output.get_topic_overview()
    papers = output.get_topic_papers(topic_id=0)

    # Visualizations on output
    html = output.visualize_topic_hierarchy()
"""

from __future__ import annotations

import pickle
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

import numpy as np
from bertopic import BERTopic

from scholaraio.log import get_logger

if TYPE_CHECKING:
    from scholaraio.index import Embedder

_log = get_logger(__name__)

# ============================================================================
# Data Structures (Pure Data, No Side Effects)
# ============================================================================


@dataclass(frozen=True)
class TopicMeta:
    """Single paper metadata for topic modeling."""

    paper_id: str
    title: str
    authors: str
    year: str
    journal: str
    citation_count: dict


@dataclass(frozen=True)
class TopicInfo:
    """Topic information."""

    topic_id: int
    count: int
    name: str
    keywords: list[str]
    representative_papers: list[TopicMeta]


@dataclass(frozen=True)
class RelatedTopic:
    """Related topic information."""

    topic_id: int
    similarity: float
    keywords: list[str]


# ============================================================================
# Config and Data Containers
# ============================================================================


@dataclass(frozen=True)
class TopicConfig:
    """Configuration for topic model - immutable, no path exposure.

    Args:
        embedder: Embedder instance for BERTopic (injected dependency).
        min_topic_size: Minimum topic size for HDBSCAN clustering.
        nr_topics: Target number of topics ("auto", None, or int).
    """

    embedder: "Embedder"
    min_topic_size: int = 5
    nr_topics: int | str | None = "auto"


@dataclass(frozen=True)
class TopicInputData:
    """Input data for topic modeling - immutable container.

    This is the data that gets fed into the trainer. No DB/path dependencies.
    """

    paper_ids: list[str]
    docs: list[str]
    metas: list[TopicMeta]
    embeddings: "np.ndarray"


@dataclass(frozen=True)
class TopicModelOutput:
    """Immutable container for built topic model data - output from Trainer.

    This is the final output after training. All fields are immutable.
    Includes query and visualization methods.
    """

    bertopic_model: "BERTopic"
    paper_ids: list[str]
    metas: list[TopicMeta]
    topics: list[int]
    embeddings: "np.ndarray | None" = None
    docs: list[str | None] | None = None

    def get_papers(self, topic_id: int) -> list[TopicMeta]:
        """Get papers for a specific topic."""
        return [m for m, t in zip(self.metas, self.topics) if t == topic_id]

    @property
    def topic_ids(self) -> set[int]:
        """All topic IDs (excluding outliers)."""
        return set(self.topics) - {-1}

    @property
    def outliers(self) -> list[TopicMeta]:
        """Papers not assigned to any topic."""
        return self.get_papers(-1)

    # -------------------------------------------------------------------------
    # Query Methods
    # -------------------------------------------------------------------------

    def get_topic_overview(self) -> list[TopicInfo]:
        """Get overview of all topics."""
        bertopic = self.bertopic_model
        info = bertopic.get_topic_info()

        overview = []
        for _, row in info.iterrows():
            tid = row["Topic"]
            if tid == -1:
                continue

            topic_words = bertopic.get_topic(tid)
            keywords = [w for w, _ in topic_words[:10]] if topic_words else []

            papers = self.get_papers(tid)
            papers.sort(key=lambda m: _best_cite_key(m), reverse=True)
            rep_papers = papers[:5]

            overview.append(
                TopicInfo(
                    topic_id=tid,
                    count=int(row["Count"]),
                    name=row.get("Name", ""),
                    keywords=keywords,
                    representative_papers=rep_papers,
                )
            )

        overview.sort(key=lambda x: x.count, reverse=True)
        return overview

    def get_topic_papers(self, topic_id: int) -> list[TopicMeta]:
        """Get all papers in a topic."""
        papers = self.get_papers(topic_id)
        papers.sort(key=lambda m: _best_cite_key(m), reverse=True)
        return papers

    def find_related_topics(self, paper_id: str) -> list[RelatedTopic]:
        """Find topics related to a paper."""
        bertopic = self.bertopic_model
        paper_ids = self.paper_ids
        topics_list = self.topics

        if paper_id not in paper_ids:
            return []

        idx = paper_ids.index(paper_id)
        current_topic = topics_list[idx]

        if current_topic == -1:
            return []

        try:
            sim_matrix = bertopic.topic_similarities_
        except AttributeError:
            try:
                from sklearn.metrics.pairwise import cosine_similarity

                sim_matrix = cosine_similarity(bertopic.c_tf_idf_.toarray())
            except Exception as e:
                _log.debug("failed to compute topic similarities: %s", e)
                return []

        topic_ids = sorted(set(topics_list) - {-1})
        if current_topic not in topic_ids:
            return []

        tid_to_idx = {t: i for i, t in enumerate(topic_ids)}
        cur_idx = tid_to_idx[current_topic]

        related = []
        for tid in topic_ids:
            if tid == current_topic:
                continue
            sim = float(sim_matrix[cur_idx][tid_to_idx[tid]])
            topic_words = bertopic.get_topic(tid)
            keywords = [w for w, _ in topic_words[:5]] if topic_words else []
            related.append(
                RelatedTopic(topic_id=tid, similarity=sim, keywords=keywords)
            )

        related.sort(key=lambda x: x.similarity, reverse=True)
        return related

    # -------------------------------------------------------------------------
    # Visualization Methods
    # -------------------------------------------------------------------------

    def visualize_topic_hierarchy(self) -> str:
        """Generate topic hierarchy HTML visualization."""
        bertopic = self.bertopic_model
        fig = bertopic.visualize_hierarchy()
        return fig.to_html(include_plotlyjs="cdn")

    def visualize_topics_2d(self) -> str:
        """Generate 2D topic scatter plot."""
        bertopic = self.bertopic_model
        embeddings = self.embeddings
        docs = self.docs
        metas = self.metas

        if embeddings is None or not docs:
            _log.warning("No embeddings stored; falling back to topic-level viz")
            fig = bertopic.visualize_topics()
            return fig.to_html(include_plotlyjs="cdn")

        from umap import UMAP

        reduced = UMAP(
            n_components=2, min_dist=0.0, metric="cosine", random_state=42
        ).fit_transform(embeddings)

        hover_labels = []
        for i, d in enumerate(docs):
            if i < len(metas):
                m = metas[i]
                author = (m.authors or "").split(",")[0].strip()
                year = m.year or "?"
                title = (m.title or "")[:60]
                hover_labels.append(f"{author} ({year}) {title}")
            else:
                hover_labels.append(d[:60] if d else "")

        topic_info = bertopic.get_topic_info()
        custom_labels = {}
        for _, row in topic_info.iterrows():
            tid = row["Topic"]
            top_words = bertopic.get_topic(tid)
            if top_words and isinstance(top_words, list):
                kw = ", ".join(w for w, _ in top_words[:3])
            else:
                kw = ""
            custom_labels[tid] = f"Topic {tid}: {kw}" if kw else f"Topic {tid}"

        bertopic.set_topic_labels(custom_labels)
        fig = bertopic.visualize_documents(
            docs=hover_labels,
            reduced_embeddings=reduced,
            hide_document_hover=False,
            custom_labels=True,
        )

        for ann in fig.layout.annotations:
            if ann.text and ann.text.startswith("Topic "):
                short = ann.text.split(":")[0]
                ann.text = f"<b>{short}</b>"

        bertopic.custom_labels_ = None
        return fig.to_html(include_plotlyjs="cdn")

    def visualize_barchart(self, top_n_topics: int = 10) -> str:
        """Generate topic keyword bar chart."""
        bertopic = self.bertopic_model
        fig = bertopic.visualize_barchart(
            top_n_topics=top_n_topics, n_words=8, width=280, height=280
        )
        return fig.to_html(include_plotlyjs="cdn")

    def visualize_heatmap(self) -> str:
        """Generate topic similarity heatmap."""
        bertopic = self.bertopic_model
        n_topics = len(bertopic.get_topic_freq())
        fig = bertopic.visualize_heatmap(top_n_topics=min(n_topics, 64))
        return fig.to_html(include_plotlyjs="cdn")

    def visualize_term_rank(self) -> str:
        """Generate term rank curve."""
        bertopic = self.bertopic_model
        fig = bertopic.visualize_term_rank()
        return fig.to_html(include_plotlyjs="cdn")

    # -------------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------------

    def save(self, path: Path) -> None:
        """Save model to path."""

        path.mkdir(parents=True, exist_ok=True)

        bertopic = self.bertopic_model
        bertopic.save(
            str(path / "bertopic_model.pkl"),
            serialization="pickle",
            save_embedding_model=False,
        )

        custom_path = path / "scholaraio_meta.pkl"
        with open(custom_path, "wb") as f:
            pickle.dump(
                {
                    "paper_ids": self.paper_ids,
                    "metas": self.metas,
                    "topics": self.topics,
                    "embeddings": self.embeddings,
                    "docs": self.docs,
                },
                f,
            )
        _log.info("Model saved: %s", path)

    @classmethod
    def load(cls, path: Path) -> "TopicModelOutput":
        """Load model from path."""
        from bertopic import BERTopic

        model_file = path / "bertopic_model.pkl"
        if not model_file.exists():
            legacy = path / "model.pkl"
            if legacy.exists():
                model_file = legacy
            else:
                raise FileNotFoundError(
                    f"Topic model not found: {path}\nRun `scholaraio topics --build` first."
                )

        bertopic = BERTopic.load(str(model_file))

        custom_path = path / "scholaraio_meta.pkl"
        if custom_path.exists():
            with open(custom_path, "rb") as f:
                custom = pickle.load(f)
        else:
            custom = {}

        return cls(
            bertopic_model=bertopic,
            paper_ids=custom.get("paper_ids", []),
            metas=custom.get("metas", []),
            topics=custom.get("topics", []),
            embeddings=custom.get("embeddings", None),
            docs=custom.get("docs", []),
        )


# ============================================================================
# Data Layer Functions (Pure Data)
# ============================================================================


def _best_cite_key(meta: TopicMeta) -> int:
    """Get best citation count for sorting."""
    cc = meta.citation_count
    if not cc or not isinstance(cc, dict):
        return 0
    return int(max((v for v in cc.values() if isinstance(v, (int, float))), default=0))


def filter_topics_by_keyword(topics: list[TopicInfo], keyword: str) -> list[TopicInfo]:
    """Filter topics by keyword in keywords."""
    kw_lower = keyword.lower()
    return [t for t in topics if any(kw_lower in k.lower() for k in t.keywords)]


# ============================================================================
# Topic Trainer (Builder Pattern)
# ============================================================================


class TopicTrainer:
    """Trainer for topic model - loads input data and fits BERTopic.

    Pipe flow: Input + Config -> Trainer -> Output
    - __init__: loads input data from database
    - fit(): produces TopicModelOutput with query/visualization methods
    """

    def __init__(
        self,
        config: TopicConfig,
        db_path: Path,
        papers_dir: Path | None = None,
        papers_map: dict[str, dict] | None = None,
    ) -> None:
        """Initialize trainer - loads input data from database.

        Args:
            config: TopicConfig with embedder and parameters.
            db_path: SQLite database path with paper_vectors table.
            papers_dir: Papers directory (main library mode).
            papers_map: paper_id -> metadata dict (explore mode).
        """
        self._config = config
        self._input_data = self._load_input_data(db_path, papers_dir, papers_map)

    def _load_input_data(
        self,
        db_path: Path,
        papers_dir: Path | None = None,
        papers_map: dict[str, dict] | None = None,
    ) -> TopicInputData:
        """Load input data from database."""
        from scholaraio.index import _unpack

        conn = sqlite3.connect(db_path)
        try:
            has_vectors = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='paper_vectors'"
            ).fetchone()
            if not has_vectors:
                raise FileNotFoundError(
                    "Vector index not found. Run `scholaraio embed` first."
                )

            rows = conn.execute(
                "SELECT paper_id, embedding FROM paper_vectors"
            ).fetchall()
        finally:
            conn.close()

        paper_ids = []
        docs = []
        metas = []
        vecs = []

        if papers_map is not None:
            # Explore mode: metadata from papers_map
            for paper_id, blob in rows:
                p = papers_map.get(paper_id)
                if p is None:
                    continue

                title = (p.get("title") or "").strip()
                abstract = (p.get("abstract") or "").strip()
                text = f"{title}. {abstract}" if abstract else title
                if not text.strip():
                    continue

                cite = p.get("citation_count")
                if cite is None:
                    cbc = p.get("cited_by_count", 0)
                    cite = {"openalex": cbc} if cbc else {}

                authors = p.get("authors", [])
                if isinstance(authors, list):
                    authors = ", ".join(authors)

                paper_ids.append(paper_id)
                docs.append(text)
                metas.append(
                    TopicMeta(
                        paper_id=paper_id,
                        title=title,
                        authors=authors,
                        year=str(p.get("year", "")),
                        journal=p.get("journal", ""),
                        citation_count=cite,
                    )
                )
                vecs.append(_unpack(blob))
        else:
            # Main library mode: metadata from meta.json
            from scholaraio.papers import PaperStore

            if papers_dir is None:
                raise ValueError("papers_dir required when papers_map is not provided")

            store = PaperStore(papers_dir)
            id_to_dir: dict[str, str] = {}

            try:
                reg_conn = sqlite3.connect(db_path)
                for row in reg_conn.execute(
                    "SELECT id, dir_name FROM papers_registry"
                ).fetchall():
                    id_to_dir[row[0]] = row[1]
                reg_conn.close()
            except Exception as e:
                _log.debug("failed to load papers_registry: %s", e)

            for paper_id, blob in rows:
                dir_name = id_to_dir.get(paper_id, paper_id)
                paper_d = papers_dir / dir_name  # type: ignore[operator]

                try:
                    meta = store.read_meta(paper_d)
                except (ValueError, FileNotFoundError) as e:
                    _log.debug("failed to read meta.json in %s: %s", paper_d.name, e)
                    continue

                title = (meta.get("title") or "").strip()
                abstract = (meta.get("abstract") or "").strip()
                text = f"{title}. {abstract}" if abstract else title
                if not text.strip():
                    continue

                paper_ids.append(paper_id)
                docs.append(text)
                metas.append(
                    TopicMeta(
                        paper_id=paper_id,
                        title=title,
                        authors=", ".join(meta.get("authors") or []),
                        year=str(meta.get("year", "")),
                        journal=meta.get("journal", ""),
                        citation_count=meta.get("citation_count", {}),
                    )
                )
                vecs.append(_unpack(blob))

        embeddings = np.array(vecs, dtype="float32")
        _log.info("Loaded vectors and text for %d papers", len(docs))

        return TopicInputData(
            paper_ids=paper_ids,
            docs=docs,
            metas=metas,
            embeddings=embeddings,
        )

    def fit(
        self,
        *,
        n_neighbors: int | None = None,
        n_components: int = 5,
        min_samples: int = 2,
        ngram_range: tuple[int, int] = (1, 3),
        min_df: int = 2,
        top_n_words: int = 10,
    ) -> TopicModelOutput:
        """Fit BERTopic model on loaded input data.

        Args:
            n_neighbors: UMAP neighbors (auto-calculated if None).
            n_components: UMAP components.
            min_samples: HDBSCAN min_samples.
            ngram_range: N-gram range for vectorizer.
            min_df: Minimum document frequency.
            top_n_words: Top words per topic.

        Returns:
            TopicModelOutput with fitted model and query/visualization methods.
        """
        return self._fit(
            n_neighbors=n_neighbors,
            n_components=n_components,
            min_samples=min_samples,
            ngram_range=ngram_range,
            min_df=min_df,
            top_n_words=top_n_words,
        )

    def fit_and_save(
        self,
        save_path: Path,
        *,
        n_neighbors: int | None = None,
        n_components: int = 5,
        min_samples: int = 2,
        ngram_range: tuple[int, int] = (1, 3),
        min_df: int = 2,
        top_n_words: int = 10,
    ) -> TopicModelOutput:
        """Fit model and save to disk.

        Args:
            save_path: Directory to save model.
            **fit_kwargs: Additional fit parameters.

        Returns:
            TopicModelOutput with fitted model.
        """
        output = self.fit(
            n_neighbors=n_neighbors,
            n_components=n_components,
            min_samples=min_samples,
            ngram_range=ngram_range,
            min_df=min_df,
            top_n_words=top_n_words,
        )

        # Save model
        output.save(save_path)
        _log.info("Model saved: %s", save_path)
        return output

    def _fit(
        self,
        *,
        n_neighbors: int | None = None,
        n_components: int = 5,
        min_samples: int = 2,
        ngram_range: tuple[int, int] = (1, 3),
        min_df: int = 2,
        top_n_words: int = 10,
    ) -> TopicModelOutput:
        """Internal fit implementation."""
        import numpy as np

        from bertopic import BERTopic
        from bertopic.representation import KeyBERTInspired, MaximalMarginalRelevance
        from hdbscan import HDBSCAN
        from sklearn.feature_extraction.text import CountVectorizer
        from umap import UMAP

        input_data = self._input_data
        docs = input_data.docs
        embeddings = input_data.embeddings
        n = len(docs)

        # Auto-calculate neighbors if not provided
        if n_neighbors is None:
            n_neighbors = min(15, max(5, n // 10))

        # Build UMAP model
        umap_model = UMAP(
            n_neighbors=n_neighbors,
            n_components=n_components,
            min_dist=0.0,
            metric="cosine",
            random_state=42,
        )

        # Build HDBSCAN model
        hdbscan_model = HDBSCAN(
            min_cluster_size=self._config.min_topic_size,
            min_samples=min_samples,
            metric="euclidean",
            prediction_data=True,
        )

        # Build vectorizer
        effective_min_df = min(min_df, max(1, n // 4))
        vectorizer_model = CountVectorizer(
            stop_words="english",
            ngram_range=ngram_range,
            min_df=effective_min_df,
        )

        # Representation models
        representation_model = [
            KeyBERTInspired(),
            MaximalMarginalRelevance(diversity=0.3),
        ]

        # Create and fit BERTopic
        topic_model = BERTopic(
            embedding_model=self._config.embedder,
            umap_model=umap_model,
            hdbscan_model=hdbscan_model,
            vectorizer_model=vectorizer_model,
            representation_model=representation_model,
            nr_topics=self._config.nr_topics,
            top_n_words=top_n_words,
            verbose=True,
        )

        topics, _ = topic_model.fit_transform(docs, embeddings=embeddings)

        # Reduce outliers
        n_outliers_before = sum(1 for t in topics if t == -1)
        n_real_topics = len(set(topics) - {-1})
        if n_outliers_before > 0 and n_real_topics > 0:
            topics = topic_model.reduce_outliers(
                docs, topics, strategy="embeddings", embeddings=embeddings
            )
            topic_model.update_topics(
                docs,
                topics=topics,
                vectorizer_model=vectorizer_model,
                representation_model=representation_model,
            )
            n_outliers_after = sum(1 for t in topics if t == -1)
            _log.info(
                "Outlier reduction: %d -> %d", n_outliers_before, n_outliers_after
            )

        n_topics = len(set(topics)) - (1 if -1 in topics else 0)
        n_outliers = (
            topics.count(-1)
            if isinstance(topics, list)
            else sum(1 for t in topics if t == -1)
        )
        _log.info("Found %d topics, %d outliers", n_topics, n_outliers)

        # Return immutable output
        return TopicModelOutput(
            bertopic_model=topic_model,
            paper_ids=input_data.paper_ids,
            metas=input_data.metas,
            topics=list(topics) if not isinstance(topics, list) else topics,
            embeddings=np.array(embeddings, dtype="float32"),
            docs=cast(list[str | None] | None, docs),
        )
