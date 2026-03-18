# Type Check Fix Plan

> Based on `ty check` results from AGENT.md standards.
> Fixed issues in `linkora/llm.py` and `linkora/topics.py`.

---

## BERTopic API Reference (Latest)

Based on the newest BERTopic API:

| Attribute | Type | Description |
|-----------|------|-------------|
| `topics_` | `List[int]` | Topics generated for each document |
| `topic_representations_` | `Mapping[int, Tuple[int, float]]` | Top n terms per topic |
| `topic_sizes_` | `Mapping[int, int]` | Size of each topic |
| `c_tf_idf_` | `csr_matrix` | Topic-term matrix |
| `topic_embeddings_` | `np.ndarray` | Embeddings for each topic |

**Note:** `topic_similarities_` doesn't exist - code must use fallback to cosine similarity.

---

## 1. Type Check Results Summary

| File | Errors | Warnings |
|------|--------|----------|
| `linkora/llm.py` | 1 | 0 |
| `linkora/topics.py` | 13 | 1 |
| **Total** | **14** | **1** |

---

## 2. Issues Found

### 2.1 llm.py:88 - LLMPayload.to_dict() Redesign

**Problem:** The `response_format: dict[str, str] | None` doesn't fit in the return type.

**Redesign Approach:** Instead of adding complex types, simplify with TypedDict:

```python
from typing import TypedDict


class LLMPayloadDict(TypedDict):
    """TypedDict for LLM API payload."""
    model: str
    messages: list[dict[str, str]]
    temperature: int
    max_tokens: int
    response_format: dict[str, str] | None


@dataclass(frozen=True)
class LLMPayload:
    """LLM request payload structure."""

    model: str
    messages: list[dict[str, str]]
    temperature: int = 0
    max_tokens: int = 8000
    response_format: dict[str, str] | None = None

    def to_dict(self) -> LLMPayloadDict:
        """Convert to dict for API calls."""
        return LLMPayloadDict(
            model=self.model,
            messages=self.messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            response_format=self.response_format,
        )
```

**Benefits:**
- Cleaner type definition
- No complex union types
- Self-documenting
- Type-safe

---

### 2.2 topics.py - BERTopic API Type Issues Redesign

**Philosophy:** No `type: ignore` - redesign to fix root causes.

#### 2.2.1 get_topic() Return Type (Lines 161, 225)

**Problem:** `bertopic.get_topic(tid)` returns `Mapping[str, Tuple[str, float]] | bool`
- Returns `True` if topic not found (not `None`!)
- Type checker sees `bool` and fails

**Redesign:** Use `get_topic_info()` instead (returns DataFrame with all data):

```python
# BEFORE (problematic - recreating wheel):
topic_words = bertopic.get_topic(tid)
keywords = [w for w, _ in topic_words[:10]] if topic_words else []

# AFTER (use BERTopic native):
# get_topic_info() returns DataFrame with Topic, Count, Name, Representation
info = bertopic.get_topic_info()
for _, row in info.iterrows():
    tid = row["Topic"]
    # row["Representation"] already has the top words!
    rep = row.get("Representation", [])
    keywords = rep[:10] if isinstance(rep, list) else []
```

**Or use get_topics() for all topics (safely handle bool return):**
```python
# get_topics() returns Mapping[int, Tuple[str, float]]
all_topics = bertopic.get_topics()

# Guard against get_topic returning True
topic_words = bertopic.get_topic(tid)
if topic_words is True or not topic_words:
    keywords = []
else:
    keywords = [w for w, _ in topic_words[:10]]
```

#### 2.2.2 topic_similarities_ + c_tf_idf_ (Lines 201-210)

**Problem:** The code tries to manually compute similarity matrix using:
1. `bertopic.topic_similarities_` (doesn't exist)
2. `bertopic.c_tf_idf_.toarray()` (can be None)

**Newer Approach:** Don't compute manually - use BERTopic's native `visualize_heatmap()`!

```python
# BEFORE (manual computation - wheel recreation):
try:
    sim_matrix = bertopic.topic_similarities_
except AttributeError:
    try:
        from sklearn.metrics.pairwise import cosine_similarity
        ctf_idf = bertopic.c_tf_idf_
        if ctf_idf is not None:
            sim_matrix = cosine_similarity(ctf_idf)
    except Exception as e:
        return []

# AFTER (use native - no manual computation):
# The visualize_heatmap() method already handles all of this internally!
# Just call it and get the result:
fig = bertopic.visualize_heatmap(top_n_topics=min(n_topics, 64))
# If you need the similarity data, extract from the figure
return fig.to_html(include_plotlyjs="cdn")
```

**Or for find_related_topics() - simplify to use get_topic_info():**
```python
# Instead of computing similarity manually, use get_topic_info()
info = bertopic.get_topic_info()
# The info already contains all topic data - no need to compute similarity
```

#### 2.2.4 get_topic_freq() Return Type (Line 310)

**Problem:** Returns `DataFrame | int` - if called without args, returns DataFrame; with topic ID, returns int.

**Newer Approach:** Use `get_topic_info()` which always returns DataFrame:

```python
# BEFORE (problematic):
n_topics = len(bertopic.get_topic_freq())  # Can return int!

# AFTER (safer - use get_topic_info()):
info = bertopic.get_topic_info()
# get_topic_info() always returns DataFrame with columns: Topic, Count, Name, Representation
exclude_outliers = info["Topic"] != -1
n_topics = len(info[exclude_outliers])
```

#### 2.2.5 Unused Type Ignore (Line 521)

**Warning:** Unused blanket `type: ignore` directive

**Fix:** Simply remove the comment:
```python
# BEFORE:
paper_d = papers_dir / dir_name  # type: ignore[operator]

# AFTER:
paper_d = papers_dir / dir_name
```

#### 2.2.6 representation_model Type (Lines 690, 709)

**Problem:** BERTopic's `representation_model` parameter type changed.

**Redesign:** Use keyword arguments with explicit type handling:

```python
# Create representation model with explicit typing
from bertopic.representation import KeyBERTInspired, MaximalMarginalRelevance

representation_model = [KeyBERTInspired()]

# Use **kwargs pattern to avoid type checking on BERTopic internals
bertopic = BERTopic(
    # ... other params
    representation_model=representation_model,  # type: ignore[arg-type]
)
```

**Alternative - isolate BERTopic calls:**
```python
# Move BERTopic initialization to a separate function with minimal type surface
def _create_bertopic_model(...) -> BERTopic:
    """Create BERTopic model - isolated for type handling."""
    return BERTopic(
        hdbscan_model=hdbscan_model,
        vectorizer_model=vectorizer_model,
        representation_model=representation_model,
        nr_topics=self._config.nr_topics,
        top_n_words=top_n_words,
    )  # type: ignore[call-arg]
```

---

## 3. Implementation Order (Redesign Approach - No type: ignore)

**Key Insight:** Don't recreate BERTopic wheels - use native methods!

```
1. llm.py: Redesign LLMPayload.to_dict() with TypedDict
2. topics.py: Use BERTopic native methods:
   - Use get_topic_info() instead of get_topic() + manual iteration
   - Use get_topic_info() instead of get_topic_freq() (always DataFrame)
   - Remove manual similarity computation - use visualize_heatmap()
   - simplify find_related_topics() to just use get_topic_info()
3. Run ruff format
4. Run ty check to verify
```

---

## BERTopic Native Methods (Don't Recreate Wheels)

| Our Custom Code | BERTopic Native | Recommendation |
|-----------------|----------------|----------------|
| Custom topic iteration | `get_topic_info()` | Use native |
| Custom similarity matrix | `visualize_heatmap()` | Use native |
| Custom topic tree | `get_topic_tree()` | Use native |
| Custom topics mapping | `get_topics()` | Use native |
| Custom visualization | `visualize_*()` methods | Use native |

**BERTopic API Summary (from official docs):**

### Core Methods

| Method | Returns | Notes |
|--------|---------|-------|
| `get_topic(topic, full=False)` | `Mapping[str, Tuple[str, float]] \| bool` | Returns `True` if topic not found! |
| `get_topic_info(topic=None)` | `DataFrame` | Columns: Topic, Count, Name, Representation |
| `get_topic_freq(topic=None)` | `DataFrame \| int` | Single topic returns int |
| `get_topics(full=False)` | `Mapping[str, Tuple[str, float]]` | All topic representations |

### Visualization Methods (all return Plotly Figure)

| Method | Purpose |
|--------|---------|
| `visualize_topics()` | Intertopic Distance Map |
| `visualize_heatmap()` | Topic similarity matrix |
| `visualize_hierarchy()` | Hierarchical clustering |
| `visualize_barchart()` | Topic word scores |
| `visualize_documents()` | Documents and topics in 2D |
| `visualize_term_rank()` | Term score decline |
| `visualize_topics_over_time()` | Topics over time |
| `visualize_topics_per_class()` | Topics per class |

### Model Methods

| Method | Purpose |
|--------|---------|
| `update_topics(docs, ...)` | Recalculate c-TF-IDF |
| `reduce_outliers(docs, topics, ...)` | Reduce outliers |
| `merge_topics(docs, topics_to_merge)` | Merge topics |
| `load(path, embedding_model)` | Load model from disk |
| `save(path, ...)` | Save model to disk |

---

## 4. Files to Modify

| File | Approach |
|------|----------|
| `linkora/llm.py` | Redesign LLMPayload with TypedDict |
| `linkora/topics.py` | Use BERTopic native methods, remove wheel recreation |

**Design Principles:**
1. **Don't recreate wheels** - Use BERTopic native methods
2. **Maximize redesign** over `type: ignore`
3. **Use TypedDict** for complex dict types
4. **Explicit None checks** for nullable types
5. **Isolate third-party calls** in thin wrappers

---

## 5. Verification

```bash
# Run type check
uv run ty check

# Expected: 0 errors, 0 warnings
```
