from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml


FactorCategory = Literal["price_volume", "risk", "fundamental", "quality", "growth", "money_flow", "event"]
NeutralizeMode = Literal["none", "industry", "size", "industry_size"]


@dataclass(frozen=True)
class FactorSpec:
    name: str
    category: FactorCategory
    direction: int
    window: int | None
    input_columns: tuple[str, ...]
    requires_pit: bool
    neutralize: NeutralizeMode
    description: str

    def __post_init__(self) -> None:
        if self.direction not in (-1, 1):
            raise ValueError(f"FactorSpec.direction must be 1 or -1: {self.name}")


def _spec(
    name: str,
    category: FactorCategory,
    direction: int,
    window: int | None,
    input_columns: tuple[str, ...],
    description: str,
    requires_pit: bool = False,
    neutralize: NeutralizeMode = "industry_size",
) -> FactorSpec:
    return FactorSpec(name, category, direction, window, input_columns, requires_pit, neutralize, description)


DEFAULT_FACTOR_REGISTRY: dict[str, FactorSpec] = {
    "mom_20": _spec("mom_20", "price_volume", 1, 20, ("adj_close",), "20-day adjusted-price momentum."),
    "mom_60_skip5": _spec("mom_60_skip5", "price_volume", 1, 60, ("adj_close",), "60-day momentum skipping the most recent 5 trading days."),
    "mom_120": _spec("mom_120", "price_volume", 1, 120, ("adj_close",), "120-day adjusted-price momentum."),
    "rev_5": _spec("rev_5", "price_volume", 1, 5, ("adj_close",), "Short-term 5-day reversal."),
    "rev_20": _spec("rev_20", "price_volume", 1, 20, ("adj_close",), "20-day reversal."),
    "vol_20": _spec("vol_20", "risk", -1, 20, ("return_1d",), "20-day realized volatility."),
    "vol_60": _spec("vol_60", "risk", -1, 60, ("return_1d",), "60-day realized volatility."),
    "beta_60": _spec("beta_60", "risk", -1, 60, ("return_1d",), "60-day beta to the cross-sectional market proxy."),
    "idio_vol_60": _spec("idio_vol_60", "risk", -1, 60, ("return_1d",), "60-day idiosyncratic volatility versus the market proxy."),
    "turnover_20": _spec("turnover_20", "price_volume", -1, 20, ("turnover_rate",), "20-day average turnover."),
    "turnover_chg_20": _spec("turnover_chg_20", "price_volume", 1, 20, ("turnover_rate",), "20-day turnover change versus previous 20-day average."),
    "amount_mom_20": _spec("amount_mom_20", "price_volume", 1, 20, ("amount",), "20-day traded-amount momentum."),
    "amihud_20": _spec("amihud_20", "risk", -1, 20, ("return_1d", "amount"), "20-day Amihud illiquidity."),
    "size": _spec("size", "fundamental", -1, None, ("total_mv",), "Log market capitalization.", neutralize="industry"),
    "bp": _spec("bp", "fundamental", 1, None, ("pb",), "Book-to-price ratio."),
    "ep": _spec("ep", "fundamental", 1, None, ("pe_ttm",), "Earnings-to-price ratio."),
    "sp": _spec("sp", "fundamental", 1, None, ("ps",), "Sales-to-price ratio."),
    "cfp": _spec("cfp", "fundamental", 1, None, ("operating_cash_flow", "total_mv"), "Operating cash flow to market capitalization.", requires_pit=True),
    "roe": _spec("roe", "quality", 1, None, ("roe",), "Return on equity.", requires_pit=True),
    "roa": _spec("roa", "quality", 1, None, ("roa",), "Return on assets.", requires_pit=True),
    "gross_margin": _spec("gross_margin", "quality", 1, None, ("gross_margin",), "Gross margin.", requires_pit=True),
    "gross_margin_stability": _spec("gross_margin_stability", "quality", 1, 4, ("gross_margin",), "Negative rolling gross-margin volatility.", requires_pit=True),
    "debt_ratio": _spec("debt_ratio", "quality", -1, None, ("debt_ratio",), "Debt ratio.", requires_pit=True),
    "asset_turnover": _spec("asset_turnover", "quality", 1, None, ("operating_revenue", "total_assets"), "Operating revenue to total assets.", requires_pit=True),
    "revenue_yoy": _spec("revenue_yoy", "growth", 1, None, ("revenue_yoy",), "Revenue year-over-year growth.", requires_pit=True),
    "profit_yoy": _spec("profit_yoy", "growth", 1, None, ("profit_yoy",), "Profit year-over-year growth.", requires_pit=True),
    "roe_delta": _spec("roe_delta", "growth", 1, 1, ("roe",), "ROE change versus prior report.", requires_pit=True),
    "mf_5": _spec("mf_5", "money_flow", 1, 5, ("net_mf_amount", "amount"), "5-day net money-flow ratio."),
    "mf_20": _spec("mf_20", "money_flow", 1, 20, ("net_mf_amount", "amount"), "20-day net money-flow ratio."),
    "large_order_mf_20": _spec("large_order_mf_20", "money_flow", 1, 20, ("large_order_net_mf_amount", "amount"), "20-day large-order money-flow ratio."),
    "event_sentiment_20": _spec("event_sentiment_20", "event", 1, 20, ("news_event",), "20-day event sentiment signal.", requires_pit=True, neutralize="none"),
}


CONFIG_SECTIONS = {
    "price_volume_factors",
    "risk_factors",
    "fundamental_factors",
    "quality_factors",
    "growth_factors",
    "money_flow_factors",
    "llm_event_factors",
}


def load_factor_config(config_path: str | Path) -> dict[str, object]:
    with Path(config_path).open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Factor config must be a mapping: {config_path}")
    return data


def enabled_factor_names(config: dict[str, object]) -> list[str]:
    names: list[str] = []
    for section in CONFIG_SECTIONS:
        values = config.get(section, [])
        if values is None:
            continue
        if not isinstance(values, list):
            raise ValueError(f"Factor config section must be a list: {section}")
        names.extend(str(value) for value in values)
    return list(dict.fromkeys(names))


def get_factor_specs(
    names: list[str] | None = None,
    registry: dict[str, FactorSpec] | None = None,
) -> list[FactorSpec]:
    specs = registry or DEFAULT_FACTOR_REGISTRY
    selected = names if names is not None else list(specs)
    missing = [name for name in selected if name not in specs]
    if missing:
        raise ValueError(f"Unknown factors in config: {missing}")
    return [specs[name] for name in selected]


def apply_factor_directions(df, specs: list[FactorSpec]):
    out = df.copy()
    for spec in specs:
        if spec.name in out and spec.direction == -1:
            out[spec.name] = -out[spec.name]
    return out
