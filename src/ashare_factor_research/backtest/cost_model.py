from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class CostConfig:
    commission_buy: float = 0.0003
    commission_sell: float = 0.0003
    stamp_tax_sell: float = 0.0005
    slippage: float = 0.0005
    impact_coef: float = 0.0002


def estimate_rebalance_cost(
    previous_weights: pd.Series,
    target_weights: pd.Series,
    config: CostConfig | None = None,
) -> dict[str, float]:
    cfg = config or CostConfig()
    all_codes = previous_weights.index.union(target_weights.index)
    prev = previous_weights.reindex(all_codes, fill_value=0.0)
    target = target_weights.reindex(all_codes, fill_value=0.0)
    delta = target - prev
    buy_turnover = float(delta.clip(lower=0).sum())
    sell_turnover = float((-delta.clip(upper=0)).sum())
    gross_turnover = buy_turnover + sell_turnover
    cost = (
        buy_turnover * cfg.commission_buy
        + sell_turnover * (cfg.commission_sell + cfg.stamp_tax_sell)
        + gross_turnover * cfg.slippage
        + gross_turnover * cfg.impact_coef
    )
    return {
        "buy_turnover": buy_turnover,
        "sell_turnover": sell_turnover,
        "gross_turnover": gross_turnover,
        "portfolio_turnover": gross_turnover / 2.0,
        "cost": float(cost),
    }
