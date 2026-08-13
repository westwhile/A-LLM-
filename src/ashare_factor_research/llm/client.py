from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from ashare_factor_research.llm.cache import JsonlLabelCache, label_cache_key
from ashare_factor_research.llm.prompts import EventPromptInput, PROMPT_VERSION, build_event_label_prompt
from ashare_factor_research.llm.rule_lexicon import RuleLexicon, default_rule_lexicon
from ashare_factor_research.llm.schema import (
    LABEL_COLUMNS,
    label_schema_sha256,
    validate_llm_label_payload,
    validate_raw_events,
)


class EventLabeler(Protocol):
    model: str
    def label_event(self, prompt: str, raw_event: Mapping[str, Any]) -> Mapping[str, Any]: ...


class RuleBasedEventLabeler:
    """Deterministic dry-run labeler; no external API is called.

    规则词表来自显式 RuleLexicon（默认 default_rule_lexicon()，与历史硬编码一致）。
    词典哈希通过 ``cache_fingerprint`` 自动进入 cache key；替换 lexicon 后不会
    沿用旧词典的缓存。
    """

    model = "rule-based-event-labeler-v1"

    def __init__(self, lexicon: RuleLexicon | None = None) -> None:
        self.lexicon = lexicon or default_rule_lexicon()

    @property
    def cache_fingerprint(self) -> str:
        from ashare_factor_research.llm.rule_lexicon import lexicon_sha256

        return lexicon_sha256(self.lexicon)

    def label_event(self, prompt: str, raw_event: Mapping[str, Any]) -> Mapping[str, Any]:
        del prompt
        lexicon = self.lexicon
        text = f"{raw_event.get('title', '')} {raw_event.get('content', '')}".lower()
        if any(word in text for word in lexicon.growth_keywords):
            return {"event_type": "earnings_growth", "sentiment": "positive", "impact_horizon": "medium", "confidence": 0.78, "reason": "Positive growth or contract keyword matched."}
        if any(word in text for word in lexicon.negative_keywords):
            is_litigation = any(word in text for word in lexicon.litigation_keywords)
            return {"event_type": "litigation" if is_litigation else "earnings_decline", "sentiment": "negative", "impact_horizon": "medium", "confidence": 0.76, "reason": "Negative earnings or risk keyword matched."}
        return {"event_type": "other", "sentiment": "neutral", "impact_horizon": "unknown", "confidence": 0.55, "reason": "No high-signal keyword matched."}


def batch_label_events(
    news_raw: pd.DataFrame,
    labeler: EventLabeler | None = None,
    cache_path: str | Path | None = None,
    prompt_version: str = PROMPT_VERSION,
    max_retries: int = 2,
) -> pd.DataFrame:
    validate_raw_events(news_raw)
    if news_raw.empty:
        return pd.DataFrame(columns=LABEL_COLUMNS)
    client = labeler or RuleBasedEventLabeler()
    configuration_fingerprint = str(getattr(client, "cache_fingerprint", client.model))
    schema_fingerprint = label_schema_sha256()
    cache = JsonlLabelCache(cache_path) if cache_path else None
    cached = cache.load() if cache else {}
    labels: list[dict[str, Any]] = []
    raw = news_raw.copy()
    raw["publish_time"] = pd.to_datetime(raw["publish_time"])
    for row in raw.sort_values(["publish_time", "event_id"]).to_dict("records"):
        raw_text = f"{row['title']}\n{row['content']}"
        key = label_cache_key(
            str(row["event_id"]),
            client.model,
            prompt_version,
            raw_text,
            configuration_fingerprint=configuration_fingerprint,
            schema_fingerprint=schema_fingerprint,
        )
        if key in cached:
            labels.append(cached[key])
            continue
        prompt = build_event_label_prompt(EventPromptInput(
            event_id=str(row["event_id"]), stock_code=str(row["stock_code"]), title=str(row["title"]),
            content=str(row["content"]), source=str(row["source"]), publish_time=str(row["publish_time"]),
            url=str(row.get("url", "")),
        ))
        last_error: Exception | None = None
        for _ in range(max_retries + 1):
            try:
                payload = dict(client.label_event(prompt, row))
                validate_llm_label_payload(payload)
                break
            except Exception as exc:  # pragma: no cover - external clients only
                last_error = exc
        else:
            raise RuntimeError(f"Event labeling failed for {row['event_id']}") from last_error
        labels.append({
            "event_id": str(row["event_id"]), "stock_code": str(row["stock_code"]),
            "publish_date": pd.Timestamp(row["publish_time"]).date().isoformat(),
            "event_type": payload["event_type"], "sentiment": payload["sentiment"],
            "impact_horizon": payload["impact_horizon"], "confidence": float(payload["confidence"]),
            "reason": str(payload["reason"]), "raw_text": raw_text, "text_source": str(row["source"]),
            "prompt_version": prompt_version, "model": client.model,
            "output_json": json.dumps(payload, ensure_ascii=False, sort_keys=True), "cache_key": key,
            "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        })
    if cache:
        cache.write_all(labels)
    return pd.DataFrame(labels, columns=LABEL_COLUMNS)
