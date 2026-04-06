"""linkora.pipeline — Document processing pipeline (v2 design).

Pipeline: path in → extract_text → enrich → store in DB.
Does not know about sources or CLI.
"""

from linkora.pipeline.ingest import ingest, IngestResult
from linkora.pipeline.enrich import enrich, EnrichResult, enrich_store, EnrichPlan
from linkora.pipeline.extract import extract_text, ExtractionResult, ExtractionCache

__all__ = [
    "ingest",
    "IngestResult",
    "enrich",
    "EnrichResult",
    "enrich_store",
    "EnrichPlan",
    "extract_text",
    "ExtractionResult",
    "ExtractionCache",
]
