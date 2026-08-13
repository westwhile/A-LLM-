"""Fail-closed preparation utilities for the R1 financial-text dataset.

This module does not acquire text or decide whether a licence is acceptable.
It turns an already authorised input table into auditable engineering
artifacts: normalized events, exact-duplicate groups, near-duplicate review
candidates, entity review rows and a content-hashed quality report.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable
import unicodedata

import pandas as pd

from ashare_factor_research.data.provenance import dataframe_sha256
from ashare_factor_research.utils.helpers import require_columns


TEXT_PREPARATION_VERSION = "r1_text_preparation_v1"
TEXT_EVENT_INPUT_COLUMNS = [
    "event_id",
    "stock_code",
    "title",
    "content",
    "source",
    "publish_time",
    "available_time",
]
PREPARED_TEXT_EVENT_COLUMNS = [
    *TEXT_EVENT_INPUT_COLUMNS,
    "first_seen_time",
    "revision_time",
    "source_url",
    "language",
    "license_category",
    "raw_text",
    "normalized_text",
    "raw_text_sha256",
    "normalized_text_sha256",
    "dedup_group_id",
    "is_exact_duplicate",
    "entity_mapping_status",
    "preparation_version",
]
ENTITY_STATUSES = ("matched", "reviewed_matched", "unmatched", "provided_unverified")


@dataclass(frozen=True)
class TextPreparationResult:
    events: pd.DataFrame
    near_duplicate_candidates: pd.DataFrame
    entity_review_queue: pd.DataFrame
    quality_report: dict[str, object]


def normalize_financial_text(value: object) -> str:
    """NFKC-normalize text and collapse whitespace without rewriting content."""

    text = unicodedata.normalize("NFKC", "" if value is None else str(value))
    return re.sub(r"\s+", " ", text).strip()


def prepare_text_events(
    events: pd.DataFrame,
    *,
    stock_registry: Iterable[str] | None = None,
    near_duplicate_threshold: float = 0.85,
    near_duplicate_window_days: int = 7,
) -> TextPreparationResult:
    """Normalize and audit an event table while preserving PIT semantics.

    ``available_time`` is required instead of inferred.  The collector or a
    reviewed market-calendar rule must produce it before this function is
    called.  This prevents a convenient publication-date fallback from being
    mistaken for point-in-time availability.
    """

    require_columns(events, TEXT_EVENT_INPUT_COLUMNS, "text_events")
    out = events.copy()
    if out["event_id"].astype("string").duplicated().any():
        raise ValueError("text_events event_id must be unique")

    for column in ("event_id", "stock_code", "title", "content", "source"):
        out[column] = out[column].fillna("").astype(str).map(normalize_financial_text)
    if out["event_id"].eq("").any():
        raise ValueError("event_id must be non-empty")
    if out["stock_code"].eq("").any():
        raise ValueError("stock_code must be non-empty; unresolved entities belong in a separate intake queue")
    if (out["title"].eq("") & out["content"].eq("")).any():
        raise ValueError("each text event must contain a title or content")

    _parse_required_time(out, "publish_time")
    _parse_required_time(out, "available_time")
    if (out["available_time"] < out["publish_time"]).any():
        raise ValueError("available_time must not be earlier than publish_time")

    for column in ("first_seen_time", "revision_time"):
        if column not in out:
            out[column] = pd.NaT
        else:
            out[column] = pd.to_datetime(out[column], errors="coerce")
        known = out[column].notna()
        if known.any() and (out.loc[known, "available_time"] < out.loc[known, column]).any():
            raise ValueError(f"available_time must not be earlier than {column}")

    defaults = {
        "source_url": "",
        "language": "undetermined",
        "license_category": "undecided",
    }
    for column, default in defaults.items():
        if column not in out:
            out[column] = default
        out[column] = out[column].fillna(default).astype(str).map(normalize_financial_text)

    out["raw_text"] = out["title"] + "\n" + out["content"]
    out["normalized_text"] = out["raw_text"].map(normalize_financial_text).str.casefold()
    out["raw_text_sha256"] = out["raw_text"].map(_sha256_text)
    out["normalized_text_sha256"] = out["normalized_text"].map(_sha256_text)
    out["dedup_group_id"] = "exact:" + out["normalized_text_sha256"]
    duplicate_key = ["stock_code", "dedup_group_id"]
    out["is_exact_duplicate"] = out.duplicated(duplicate_key, keep=False)

    if "entity_mapping_status" in events:
        status = events["entity_mapping_status"].fillna("").astype(str)
        invalid = sorted(set(status) - set(ENTITY_STATUSES))
        if invalid:
            raise ValueError(f"invalid entity_mapping_status values: {invalid}")
        out["entity_mapping_status"] = status
    elif stock_registry is None:
        out["entity_mapping_status"] = "provided_unverified"
    else:
        registry = {str(value).strip() for value in stock_registry}
        out["entity_mapping_status"] = out["stock_code"].map(
            lambda value: "matched" if value in registry else "unmatched"
        )
    out["preparation_version"] = TEXT_PREPARATION_VERSION

    out = out.sort_values(["available_time", "event_id"], kind="mergesort").reset_index(drop=True)
    out = out[PREPARED_TEXT_EVENT_COLUMNS]
    validate_prepared_text_events(out)
    near = find_near_duplicate_candidates(
        out,
        threshold=near_duplicate_threshold,
        window_days=near_duplicate_window_days,
    )
    entity_queue = out[out["entity_mapping_status"].isin(["unmatched", "provided_unverified"])][
        ["event_id", "stock_code", "source", "publish_time", "available_time", "entity_mapping_status"]
    ].reset_index(drop=True)
    quality = build_text_quality_report(out, near)
    return TextPreparationResult(out, near, entity_queue, quality)


def validate_prepared_text_events(events: pd.DataFrame) -> None:
    require_columns(events, PREPARED_TEXT_EVENT_COLUMNS, "prepared_text_events")
    if events["event_id"].duplicated().any():
        raise ValueError("prepared_text_events event_id must be unique")
    publish = pd.to_datetime(events["publish_time"], errors="coerce")
    available = pd.to_datetime(events["available_time"], errors="coerce")
    if publish.isna().any() or available.isna().any():
        raise ValueError("prepared text timestamps must be parseable")
    if (available < publish).any():
        raise ValueError("prepared events contain future/PIT timing violations")
    invalid_status = set(events["entity_mapping_status"].dropna().astype(str)) - set(ENTITY_STATUSES)
    if invalid_status:
        raise ValueError(f"invalid entity mapping statuses: {sorted(invalid_status)}")
    for column in ("raw_text_sha256", "normalized_text_sha256"):
        if not events[column].astype(str).str.fullmatch(r"[0-9a-f]{64}").all():
            raise ValueError(f"{column} must contain lowercase SHA-256 digests")


def select_signal_ready_events(
    events: pd.DataFrame,
    signal_cutoff: str | pd.Timestamp,
    *,
    allow_unverified_entities: bool = False,
    deduplicate: bool = True,
) -> pd.DataFrame:
    """Select only events available by the cutoff; exact duplicates keep first arrival."""

    validate_prepared_text_events(events)
    cutoff = pd.Timestamp(signal_cutoff)
    out = events[pd.to_datetime(events["available_time"]) <= cutoff].copy()
    if not allow_unverified_entities:
        out = out[out["entity_mapping_status"].isin(["matched", "reviewed_matched"])]
    if deduplicate:
        out = out.sort_values(["available_time", "publish_time", "event_id"], kind="mergesort")
        out = out.drop_duplicates(["stock_code", "dedup_group_id"], keep="first")
    return out.reset_index(drop=True)


def find_near_duplicate_candidates(
    events: pd.DataFrame,
    *,
    threshold: float = 0.85,
    window_days: int = 7,
) -> pd.DataFrame:
    """Generate deterministic same-stock review candidates using trigram Jaccard.

    It deliberately produces candidates instead of deleting rows.  Human
    adjudication remains necessary for rewritten or multi-company stories.
    """

    validate_prepared_text_events(events)
    if not 0 <= threshold <= 1:
        raise ValueError("near-duplicate threshold must be within [0, 1]")
    if window_days < 0:
        raise ValueError("near-duplicate window_days must be non-negative")
    rows: list[dict[str, object]] = []
    for stock_code, group in events.sort_values("available_time").groupby("stock_code", sort=True):
        records = group.to_dict("records")
        for left_index, left in enumerate(records):
            left_time = pd.Timestamp(left["available_time"])
            left_grams = _character_ngrams(str(left["normalized_text"]))
            for right in records[left_index + 1 :]:
                right_time = pd.Timestamp(right["available_time"])
                if right_time - left_time > pd.Timedelta(days=window_days):
                    break
                if left["dedup_group_id"] == right["dedup_group_id"]:
                    continue
                similarity = _jaccard(left_grams, _character_ngrams(str(right["normalized_text"])))
                if similarity >= threshold:
                    rows.append(
                        {
                            "stock_code": str(stock_code),
                            "left_event_id": str(left["event_id"]),
                            "right_event_id": str(right["event_id"]),
                            "left_available_time": left_time,
                            "right_available_time": right_time,
                            "similarity": float(similarity),
                            "threshold": float(threshold),
                            "window_days": int(window_days),
                            "review_status": "pending",
                        }
                    )
    columns = [
        "stock_code",
        "left_event_id",
        "right_event_id",
        "left_available_time",
        "right_available_time",
        "similarity",
        "threshold",
        "window_days",
        "review_status",
    ]
    return pd.DataFrame(rows, columns=columns)


def build_text_quality_report(
    events: pd.DataFrame,
    near_duplicate_candidates: pd.DataFrame | None = None,
) -> dict[str, object]:
    validate_prepared_text_events(events)
    near = near_duplicate_candidates if near_duplicate_candidates is not None else pd.DataFrame()
    timestamps = pd.to_datetime(events["available_time"])
    return {
        "schema_version": 1,
        "preparation_version": TEXT_PREPARATION_VERSION,
        "status": "engineering_complete_human_review_pending",
        "rows": int(len(events)),
        "unique_stocks": int(events["stock_code"].nunique()),
        "first_available_time": timestamps.min().isoformat() if len(events) else None,
        "last_available_time": timestamps.max().isoformat() if len(events) else None,
        "exact_duplicate_rows": int(events["is_exact_duplicate"].sum()),
        "near_duplicate_candidates": int(len(near)),
        "entity_status_counts": {
            str(key): int(value)
            for key, value in events["entity_mapping_status"].value_counts().sort_index().items()
        },
        "events_sha256": dataframe_sha256(events),
        "near_duplicate_candidates_sha256": dataframe_sha256(near),
        "human_gates": ["license_signoff", "entity_mapping_review", "near_duplicate_review"],
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def write_text_preparation_artifacts(
    result: TextPreparationResult,
    output_dir: str | Path,
) -> dict[str, str]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    paths = {
        "events": root / "prepared_text_events.csv",
        "near_duplicates": root / "near_duplicate_candidates.csv",
        "entity_review": root / "entity_review_queue.csv",
        "quality": root / "text_quality_report.json",
    }
    result.events.to_csv(paths["events"], index=False, encoding="utf-8")
    result.near_duplicate_candidates.to_csv(paths["near_duplicates"], index=False, encoding="utf-8")
    result.entity_review_queue.to_csv(paths["entity_review"], index=False, encoding="utf-8")
    paths["quality"].write_text(
        json.dumps(result.quality_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {key: str(value) for key, value in paths.items()}


def _parse_required_time(frame: pd.DataFrame, column: str) -> None:
    parsed = pd.to_datetime(frame[column], errors="coerce")
    if parsed.isna().any():
        bad = frame.loc[parsed.isna(), "event_id"].astype(str).tolist()[:5]
        raise ValueError(f"{column} contains missing/unparseable values for events: {bad}")
    frame[column] = parsed


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _character_ngrams(text: str, size: int = 3) -> set[str]:
    compact = text.replace(" ", "")
    if not compact:
        return set()
    if len(compact) <= size:
        return {compact}
    return {compact[index : index + size] for index in range(len(compact) - size + 1)}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0
