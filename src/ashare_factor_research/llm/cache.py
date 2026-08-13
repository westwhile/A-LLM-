from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def label_cache_key(
    event_id: str,
    model: str,
    prompt_version: str,
    raw_text: str = "",
    *,
    configuration_fingerprint: str = "",
    schema_fingerprint: str = "",
) -> str:
    """Return a cache key that invalidates on every label-producing input.

    R1 compares representations, so reusing labels after changing a lexicon,
    model configuration or output schema would silently mix experiments.  The
    optional fingerprints keep backward callers working while allowing each
    labeler to freeze all non-text configuration in the key.
    """

    payload = {
        "event_id": str(event_id),
        "model": str(model),
        "prompt_version": str(prompt_version),
        "raw_text_sha256": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
        "configuration_fingerprint": str(configuration_fingerprint),
        "schema_fingerprint": str(schema_fingerprint),
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"label-v2|{event_id}|{digest}"


class JsonlLabelCache:
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

    def write_all(self, labels: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deduped = self.load()
        deduped.update({str(item["cache_key"]): item for item in labels})
        with self.path.open("w", encoding="utf-8") as handle:
            for key in sorted(deduped):
                handle.write(json.dumps(deduped[key], ensure_ascii=False, sort_keys=True) + "\n")
