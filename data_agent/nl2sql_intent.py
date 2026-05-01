# data_agent/nl2sql_intent.py
"""Intent classification for NL2SQL grounding routing (Phase A)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class IntentLabel(str, Enum):
    ATTRIBUTE_FILTER = "attribute_filter"
    CATEGORY_FILTER = "category_filter"
    SPATIAL_MEASUREMENT = "spatial_measurement"
    SPATIAL_JOIN = "spatial_join"
    KNN = "knn"
    AGGREGATION = "aggregation"
    PREVIEW_LISTING = "preview_listing"
    REFUSAL_INTENT = "refusal_intent"
    UNKNOWN = "unknown"


@dataclass
class IntentResult:
    primary: IntentLabel
    secondary: list[IntentLabel] = field(default_factory=list)
    confidence: float = 0.0
    source: str = "rule"  # "rule" | "llm" | "fallback"
