from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from ashare_factor_research.llm.prompts import EVENT_TYPES, IMPACT_HORIZONS, SENTIMENTS
from ashare_factor_research.utils.helpers import require_columns


RAW_EVENT_COLUMNS = ["event_id", "stock_code", "title", "content", "source", "publish_time"]
LABEL_COLUMNS = [
    "event_id", "stock_code", "publish_date", "event_type", "sentiment", "impact_horizon",
    "confidence", "reason", "raw_text", "text_source", "prompt_version", "model",
    "output_json", "cache_key", "created_at",
]


def validate_llm_label_payload(payload: Mapping[str, Any]) -> None:
    required = {"event_type", "sentiment", "impact_horizon", "confidence", "reason"}
    missing = sorted(required - set(payload))
    if missing:
        raise ValueError(f"LLM label payload missing required keys: {missing}")
    if payload["event_type"] not in EVENT_TYPES:
        raise ValueError(f"Invalid event_type: {payload['event_type']}")
    if payload["sentiment"] not in SENTIMENTS:
        raise ValueError(f"Invalid sentiment: {payload['sentiment']}")
    if payload["impact_horizon"] not in IMPACT_HORIZONS:
        raise ValueError(f"Invalid impact_horizon: {payload['impact_horizon']}")
    confidence = float(payload["confidence"])
    if not 0 <= confidence <= 1:
        raise ValueError("confidence must be within [0, 1]")


def validate_raw_events(events: pd.DataFrame) -> None:
    require_columns(events, RAW_EVENT_COLUMNS, "news_raw")
    if events["event_id"].duplicated().any():
        raise ValueError("news_raw event_id must be unique")


def validate_llm_event_labels(labels: pd.DataFrame, signal_date: pd.Timestamp | None = None) -> None:
    require_columns(labels, LABEL_COLUMNS, "llm_event_label")
    for col, values in [("event_type", EVENT_TYPES), ("sentiment", SENTIMENTS), ("impact_horizon", IMPACT_HORIZONS)]:
        invalid = set(labels[col].dropna().unique()) - set(values)
        if invalid:
            raise ValueError(f"Invalid {col} labels: {sorted(invalid)}")
    confidence = pd.to_numeric(labels["confidence"], errors="coerce")
    if confidence.isna().any() or (~confidence.between(0, 1)).any():
        raise ValueError("confidence must be numeric and within [0, 1]")
    if signal_date is not None and (pd.to_datetime(labels["publish_date"]) > pd.Timestamp(signal_date)).any():
        raise ValueError("publish_date must not be later than signal_date")
    if labels["cache_key"].duplicated().any():
        raise ValueError("cache_key must be unique")

