from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ashare_factor_research.data.trading_calendar import next_trade_date
from ashare_factor_research.utils.helpers import require_columns


SENTIMENT_SCORE = {"positive": 1.0, "neutral": 0.0, "negative": -1.0}


@dataclass(frozen=True)
class EventLabel:
    stock_code: str
    publish_date: pd.Timestamp
    event_type: str
    sentiment: str
    impact_horizon: str
    confidence: float
    reason: str


def validate_event_labels(events: pd.DataFrame) -> None:
    require_columns(
        events,
        ["stock_code", "publish_date", "event_type", "sentiment", "impact_horizon", "confidence", "reason"],
        "news_event",
    )
    invalid = set(events["sentiment"].dropna().unique()) - set(SENTIMENT_SCORE)
    if invalid:
        raise ValueError(f"Invalid event sentiment labels: {sorted(invalid)}")


def compute_event_sentiment_factor(
    events: pd.DataFrame,
    trade_dates: pd.DatetimeIndex,
    lookback_days: int = 20,
) -> pd.DataFrame:
    validate_event_labels(events)
    if events.empty:
        return pd.DataFrame(columns=["trade_date", "ts_code", "event_sentiment_20"])
    ev = events.copy()
    ev["publish_date"] = pd.to_datetime(ev["publish_date"])
    dates = pd.DatetimeIndex(pd.to_datetime(trade_dates).sort_values().unique())
    if "publish_time" in ev and ev["publish_time"].notna().any():
        publish_time = pd.to_datetime(ev["publish_time"], errors="coerce")

        def _available_date(timestamp: pd.Timestamp) -> pd.Timestamp | None:
            if pd.isna(timestamp):
                return None
            date = pd.Timestamp(timestamp).normalize()
            if date in dates and pd.Timestamp(timestamp).time() <= pd.Timestamp("15:00:00").time():
                return date
            return next_trade_date(dates, date)

        ev["available_date"] = [_available_date(value) for value in publish_time]
    else:
        ev["available_date"] = ev["publish_date"].dt.normalize()
    dedupe_cols = ["event_id"] if "event_id" in ev else ["stock_code", "publish_date", "event_type"]
    ev = ev.sort_values(["available_date", "publish_date"]).drop_duplicates(dedupe_cols, keep="last")
    ev["ts_code"] = ev["stock_code"]
    ev["weighted_score"] = ev["sentiment"].map(SENTIMENT_SCORE) * ev["confidence"].astype(float)
    rows = []
    for date in dates:
        start = date - pd.Timedelta(days=lookback_days)
        window = ev[(ev["available_date"] <= date) & (ev["available_date"] >= start)]
        if window.empty:
            continue
        score = window.groupby("ts_code", as_index=False)["weighted_score"].sum()
        score["trade_date"] = date
        rows.append(score.rename(columns={"weighted_score": "event_sentiment_20"}))
    if not rows:
        return pd.DataFrame(columns=["trade_date", "ts_code", "event_sentiment_20"])
    return pd.concat(rows, ignore_index=True)[["trade_date", "ts_code", "event_sentiment_20"]]
