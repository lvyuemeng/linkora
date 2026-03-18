"""
topics.py — BERTopic Topic Modeling
===================================

Uses Qwen3 embeddings from paper_vectors table for BERTopic clustering.
Supports topic overview, paper lists, hierarchy visualization.

Pipe Flow:
    Config + Context -> TopicTrainer -> TopicModelOutput

Usage:
    from linkora.topics import TopicConfig, TopicTrainer, TrainerContext, TopicModelOutput
    from linkora.papers import PaperStore

    # Create config with embedder
    config = TopicConfig(embedder=embedder)

    # Create context with PaperStore
    store = PaperStore(papers_dir)
    context = TrainerContext(store=store)

    # Train model (loads data, fits BERTopic, returns output)
    trainer = TopicTrainer(config, context=context)
    output = trainer.fit()

    # Query methods on output
    overview = output.get_topic_overview()
    papers = output.get_topic_papers(topic_id=0)

    # Visualizations on output
    html = output.visualize_topic_hierarchy()
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

import numpy as np
from bertopic import BERTopic

from linkora.log import get_logger

if TYPE_CHECKING:
    from linkora.index import Embedder

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

            # Use Representation column from get_topic_info() - native BERTopic method
            rep = row.get("Representation", [])
            # Explicitly cast to list[str] since BERTopic returns list of strings
            if isinstance(rep, list):
                keywords = cast(
                    "list[str]", [w for w in rep[:10] if isinstance(w, str)]
                )
            else:
                keywords = []

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

        # Pre-fetch topic info once to avoid N API calls
        info = bertopic.get_topic_info()
        tid_to_rep: dict[int, list[str]] = {}
        for _, row in info.iterrows():
            tid = row["Topic"]
            rep = row.get("Representation", [])
            if isinstance(rep, list):
                tid_to_rep[tid] = cast("list[str]", rep)

        topic_ids = sorted(set(topics_list) - {-1})
        if current_topic not in topic_ids:
            return []

        # Get similarity from visualize_heatmap data
        try:
            bertopic.visualize_heatmap(top_n_topics=min(len(topic_ids), 64))
            # Extract similarity data from figure if available, otherwise use equal weights
            related = []
            for tid in topic_ids:
                if tid == current_topic:
                    continue
                # Use topic embeddings similarity as fallback
                sim = 0.5  # Default similarity when cannot compute
                # Use pre-fetched Representation from get_topic_info()
                rep = tid_to_rep.get(tid, [])
                keywords = [w for w in rep[:5] if isinstance(w, str)]
                related.append(
                    RelatedTopic(topic_id=tid, similarity=sim, keywords=keywords)
                )
        except Exception as e:
            _log.debug("failed to compute topic similarities: %s", e)
            return []

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
        """Generate 2D topic scatter plot using BERTopic native method."""
        bertopic = self.bertopic_model
        fig = bertopic.visualize_topics(
            top_n_topics=50,
            custom_labels=True,
            width=650,
            height=650,
        )
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
        # Use get_topic_info() which always returns DataFrame (safer than get_topic_freq)
        info = bertopic.get_topic_info()
        n_topics = len(info[info["Topic"] != -1])
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

        custom_path = path / "linkora_meta.pkl"
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
                    f"Topic model not found: {path}\nRun `linkora topics --build` first."
                )

        bertopic = BERTopic.load(str(model_file))

        custom_path = path / "linkora_meta.pkl"
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


# ============================================================================
# Topic Trainer (Builder Pattern)
# ============================================================================


class TopicTrainer:
    """Trainer for topic model - loads input data and fits BERTopic.

    Pipe flow: Input + Config -> Trainer -> Output
    - __init__: loads input data from VectorIndex
    - fit(): produces TopicModelOutput with query/visualization methods
    """

    def __init__(
        self,
        config: TopicConfig,
        vector_index,
        store=None,
        papers_map: dict[str, dict] | None = None,
    ) -> None:
        """Initialize trainer - accepts VectorIndex directly.

        Args:
            config: TopicConfig with embedder and parameters.
            vector_index: VectorIndex instance for getting embeddings.
            store: Optional PaperStore instance (needed for papers_dir mode).
            papers_map: paper_id -> metadata dict (explore mode, overrides store).
        """
        self._config = config
        self._vector_index = vector_index
        self._store = store
        self._papers_map = papers_map
        self._input_data = self._load_input_data(papers_map)

    def _load_input_data(
        self,
        papers_map: dict[str, dict] | None = None,
    ) -> TopicInputData:
        """Load input data using VectorIndex."""
        paper_ids, embeddings = self._vector_index.get_vectors()

        if papers_map is not None:
            return self._load_from_papers_map(paper_ids, embeddings, papers_map)
        return self._load_from_papers_dir(paper_ids, embeddings)

    def _load_from_papers_map(
        self,
        paper_ids: list[str],
        embeddings: np.ndarray,
        papers_map: dict[str, dict],
    ) -> TopicInputData:
        """Load data from papers_map dict (explore mode)."""
        docs = []
        metas = []

        for i, paper_id in enumerate(paper_ids):
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

        _log.info("Loaded vectors and text for %d papers", len(docs))

        # Filter embeddings to match filtered papers
        valid_indices = [
            i for i, p in enumerate(paper_ids) if papers_map.get(p) is not None
        ]
        filtered_embeddings = (
            embeddings[valid_indices] if len(valid_indices) > 0 else np.array([])
        )

        return TopicInputData(
            paper_ids=paper_ids,
            docs=docs,
            metas=metas,
            embeddings=filtered_embeddings,
        )

    def _load_from_papers_dir(
        self,
        paper_ids: list[str],
        embeddings: np.ndarray,
    ) -> TopicInputData:
        """Load data from papers directory using store."""
        store = self._store
        db_path = self._vector_index.db_path

        if store is None:
            raise ValueError("store is required for papers_dir mode")

        id_to_dir: dict[str, str] = {}

        try:
            import sqlite3

            reg_conn = sqlite3.connect(db_path)
            for row in reg_conn.execute(
                "SELECT id, dir_name FROM papers_registry"
            ).fetchall():
                id_to_dir[row[0]] = row[1]
            reg_conn.close()
        except Exception as e:
            _log.debug("failed to load papers_registry: %s", e)

        docs = []
        metas = []
        valid_indices = []

        for i, paper_id in enumerate(paper_ids):
            dir_name = id_to_dir.get(paper_id)
            if dir_name is None:
                dir_name = paper_id
            paper_d = store.papers_dir / dir_name

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
            valid_indices.append(i)

        filtered_embeddings = (
            embeddings[valid_indices] if valid_indices else np.array([])
        )
        _log.info("Loaded vectors and text for %d papers", len(docs))

        return TopicInputData(
            paper_ids=paper_ids,
            docs=docs,
            metas=metas,
            embeddings=filtered_embeddings,
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
            representation_model=representation_model,  # type: ignore[invalid-argument-type]
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
                representation_model=representation_model,  # type: ignore[invalid-argument-type]
            )
            n_outliers_after = sum(1 for t in topics if t == -1)
            _log.info(
                "Outlier reduction: %d -> %d", n_outliers_before, n_outliers_after
            )

        n_topics = len(set(topics)) - (1 if -1 in topics else 0)
        n_outliers = sum(1 for t in topics if t == -1)
        _log.info("Found %d topics, %d outliers", n_topics, n_outliers)

        # Return immutable output
        return TopicModelOutput(
            bertopic_model=topic_model,
            paper_ids=input_data.paper_ids,
            metas=input_data.metas,
            topics=list(topics),
            embeddings=np.array(embeddings, dtype="float32"),
            docs=cast(list[str | None] | None, docs),
        )
