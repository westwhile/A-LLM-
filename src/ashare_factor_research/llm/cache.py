from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def label_cache_key(event_id: str, model: str, prompt_version: str, raw_text: str = "") -> str:
    content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()[:16]
    return f"{event_id}|{model}|{prompt_version}|{content_hash}"


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
        deduped = {str(item["cache_key"]): item for item in labels}
        with self.path.open("w", encoding="utf-8") as handle:
            for key in sorted(deduped):
                handle.write(json.dumps(deduped[key], ensure_ascii=False, sort_keys=True) + "\n")

