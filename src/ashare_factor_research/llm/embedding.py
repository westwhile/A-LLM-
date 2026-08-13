"""Model-neutral, auditable embedding adapter for R1-E3.

No model is downloaded or selected here.  A caller supplies an explicitly
approved embedder and a fully versioned :class:`EmbeddingSpec`.  The cache key
contains the text hash and the complete spec so changing pooling, tokenizer,
revision or preprocessing cannot reuse an old vector.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Protocol, Sequence

import numpy as np
import pandas as pd

from ashare_factor_research.llm.text_dataset import validate_prepared_text_events


EMBEDDING_PIPELINE_VERSION = "r1_embedding_pipeline_v1"
EMBEDDING_COLUMNS = [
    "event_id",
    "stock_code",
    "available_time",
    "raw_text_sha256",
    "dedup_group_id",
    "entity_mapping_status",
    "representation_type",
    "representation_version",
    "model_id",
    "model_revision",
    "spec_sha256",
    "cache_key",
    "dimension",
    "vector_json",
    "created_at",
]


@dataclass(frozen=True)
class EmbeddingSpec:
    model_id: str
    model_revision: str
    tokenizer_revision: str
    preprocessing_version: str
    pooling: str
    dimension: int
    max_length: int
    license_status: str
    intended_use: str = "R1 text-representation research only"


class TextEmbedder(Protocol):
    spec: EmbeddingSpec

    def encode(self, texts: Sequence[str]) -> np.ndarray: ...


class JsonlEmbeddingCache:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        rows: dict[str, dict[str, Any]] = {}
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    item = json.loads(line)
                    rows[str(item["cache_key"])] = item
        return rows

    def write_all(self, rows: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        merged = self.load()
        merged.update({str(item["cache_key"]): item for item in rows})
        with self.path.open("w", encoding="utf-8") as handle:
            for key in sorted(merged):
                handle.write(json.dumps(merged[key], ensure_ascii=False, sort_keys=True) + "\n")


def validate_embedding_spec(spec: EmbeddingSpec) -> None:
    string_fields = (
        "model_id",
        "model_revision",
        "tokenizer_revision",
        "preprocessing_version",
        "pooling",
        "license_status",
        "intended_use",
    )
    for field in string_fields:
        value = getattr(spec, field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"EmbeddingSpec.{field} must be non-empty")
    if spec.dimension <= 0:
        raise ValueError("EmbeddingSpec.dimension must be positive")
    if spec.max_length <= 0:
        raise ValueError("EmbeddingSpec.max_length must be positive")
    if spec.license_status not in {"approved", "research_only", "internal_only"}:
        raise ValueError("EmbeddingSpec.license_status must be explicitly approved for the intended use")


def embedding_spec_sha256(spec: EmbeddingSpec) -> str:
    validate_embedding_spec(spec)
    payload = {"pipeline_version": EMBEDDING_PIPELINE_VERSION, **asdict(spec)}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def embedding_cache_key(raw_text_sha256: str, spec: EmbeddingSpec) -> str:
    if not re_full_sha256(raw_text_sha256):
        raise ValueError("raw_text_sha256 must be a lowercase SHA-256 digest")
    payload = f"{raw_text_sha256}|{embedding_spec_sha256(spec)}"
    return "embedding-v1|" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def batch_embed_events(
    events: pd.DataFrame,
    embedder: TextEmbedder,
    *,
    cache_path: str | Path | None = None,
    batch_size: int = 64,
) -> pd.DataFrame:
    """Embed prepared events with deterministic ordering and cache auditing."""

    validate_prepared_text_events(events)
    validate_embedding_spec(embedder.spec)
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    spec_hash = embedding_spec_sha256(embedder.spec)
    cache = JsonlEmbeddingCache(cache_path) if cache_path else None
    cached = cache.load() if cache else {}
    rows: list[dict[str, Any]] = []
    new_cache_rows: list[dict[str, Any]] = []
    ordered = events.sort_values(["available_time", "event_id"], kind="mergesort").reset_index(drop=True)

    for start in range(0, len(ordered), batch_size):
        batch = ordered.iloc[start : start + batch_size]
        keys = [embedding_cache_key(value, embedder.spec) for value in batch["raw_text_sha256"]]
        missing_positions = [index for index, key in enumerate(keys) if key not in cached]
        if missing_positions:
            texts = batch.iloc[missing_positions]["raw_text"].astype(str).tolist()
            encoded = np.asarray(embedder.encode(texts), dtype=float)
            if encoded.ndim != 2 or encoded.shape != (len(texts), embedder.spec.dimension):
                raise ValueError(
                    "embedder output shape mismatch: "
                    f"expected {(len(texts), embedder.spec.dimension)}, got {encoded.shape}"
                )
            if not np.isfinite(encoded).all():
                raise ValueError("embedder output contains non-finite values")
            for position, vector in zip(missing_positions, encoded, strict=True):
                key = keys[position]
                item = {
                    "cache_key": key,
                    "raw_text_sha256": str(batch.iloc[position]["raw_text_sha256"]),
                    "spec_sha256": spec_hash,
                    "dimension": int(embedder.spec.dimension),
                    "vector": vector.tolist(),
                }
                cached[key] = item
                new_cache_rows.append(item)

        for position, (_, event) in enumerate(batch.iterrows()):
            key = keys[position]
            cached_item = cached[key]
            vector = np.asarray(cached_item.get("vector", []), dtype=float)
            if (
                cached_item.get("spec_sha256") != spec_hash
                or cached_item.get("raw_text_sha256") != event["raw_text_sha256"]
                or vector.shape != (embedder.spec.dimension,)
                or not np.isfinite(vector).all()
            ):
                raise ValueError(f"invalid embedding cache entry: {key}")
            rows.append(
                {
                    "event_id": str(event["event_id"]),
                    "stock_code": str(event["stock_code"]),
                    "available_time": pd.Timestamp(event["available_time"]),
                    "raw_text_sha256": str(event["raw_text_sha256"]),
                    "dedup_group_id": str(event["dedup_group_id"]),
                    "entity_mapping_status": str(event["entity_mapping_status"]),
                    "representation_type": "embedding",
                    "representation_version": spec_hash,
                    "model_id": embedder.spec.model_id,
                    "model_revision": embedder.spec.model_revision,
                    "spec_sha256": spec_hash,
                    "cache_key": key,
                    "dimension": int(embedder.spec.dimension),
                    "vector_json": json.dumps(vector.tolist(), separators=(",", ":")),
                    "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
                }
            )
    if cache and new_cache_rows:
        cache.write_all(new_cache_rows)
    return pd.DataFrame(rows, columns=EMBEDDING_COLUMNS)


def expand_embedding_features(embeddings: pd.DataFrame, *, prefix: str = "text_emb_") -> pd.DataFrame:
    """Expand audited JSON vectors into numeric columns for a frozen evaluator."""

    required = set(EMBEDDING_COLUMNS)
    missing = sorted(required - set(embeddings.columns))
    if missing:
        raise ValueError(f"embedding rows missing columns: {missing}")
    vectors = [json.loads(value) for value in embeddings["vector_json"].astype(str)]
    dimensions = set(pd.to_numeric(embeddings["dimension"], errors="coerce").dropna().astype(int))
    if len(dimensions) != 1:
        raise ValueError("embedding rows must have one fixed dimension")
    dimension = next(iter(dimensions))
    matrix = np.asarray(vectors, dtype=float)
    if matrix.shape != (len(embeddings), dimension) or not np.isfinite(matrix).all():
        raise ValueError("embedding vectors do not match the declared dimension")
    features = pd.DataFrame(matrix, columns=[f"{prefix}{index:04d}" for index in range(dimension)])
    metadata = embeddings.drop(columns=["vector_json"]).reset_index(drop=True)
    return pd.concat([metadata, features], axis=1)


def re_full_sha256(value: object) -> bool:
    text = str(value)
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)
