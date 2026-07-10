from __future__ import annotations

from dataclasses import dataclass


PROMPT_VERSION = "llm_event_v1"
EVENT_TYPES = (
    "earnings_growth", "earnings_decline", "contract_win", "policy_support",
    "regulatory_risk", "financing", "management_change", "litigation", "other",
)
SENTIMENTS = ("positive", "neutral", "negative")
IMPACT_HORIZONS = ("short", "medium", "long", "unknown")


@dataclass(frozen=True)
class EventPromptInput:
    event_id: str
    stock_code: str
    title: str
    content: str
    source: str
    publish_time: str
    url: str = ""


def build_event_label_prompt(item: EventPromptInput) -> str:
    return (
        "You label A-share company news for quantitative research. Use only supplied text; "
        "do not forecast prices or give trading instructions. Return one JSON object with "
        "event_type, sentiment, impact_horizon, confidence, reason.\n"
        f"event_type: {', '.join(EVENT_TYPES)}\n"
        f"sentiment: {', '.join(SENTIMENTS)}\n"
        f"impact_horizon: {', '.join(IMPACT_HORIZONS)}\n"
        f"event_id: {item.event_id}\nstock_code: {item.stock_code}\nsource: {item.source}\n"
        f"publish_time: {item.publish_time}\ntitle: {item.title}\ncontent: {item.content}\n"
    )

