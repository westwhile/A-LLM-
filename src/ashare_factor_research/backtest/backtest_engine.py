from __future__ import annotations

import pandas as pd

from ashare_factor_research.backtest.cost_model import CostConfig, estimate_rebalance_cost
from ashare_factor_research.data.trading_calendar import next_trade_date
from ashare_factor_research.utils.helpers import require_columns


def run_backtest(
    portfolio_df: pd.DataFrame,
    returns_df: pd.DataFrame,
    cost_config: CostConfig | None = None,
    date_col: str = "trade_date",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run daily close-to-close backtest with next-trade-date execution.

    Signals dated T become active from the next available trading date. The
    function uses daily close-to-close returns as a proxy when open execution
    prices are unavailable in the sample dataset.
    """

    require_columns(portfolio_df, [date_col, "ts_code", "target_weight"], "portfolio_df")
    require_columns(returns_df, [date_col, "ts_code", "return_1d"], "returns_df")
    returns = returns_df[[date_col, "ts_code", "return_1d"]].copy()
    returns[date_col] = pd.to_datetime(returns[date_col])
    trade_dates = pd.DatetimeIndex(sorted(returns[date_col].dropna().unique()))

    effective_targets: dict[pd.Timestamp, pd.Series] = {}
    for signal_date, part in portfolio_df.groupby(date_col):
        eff_date = next_trade_date(trade_dates, pd.Timestamp(signal_date))
        if eff_date is None:
            continue
        effective_targets[eff_date] = part.set_index("ts_code")["target_weight"].astype(float)

    current_weights = pd.Series(dtype=float)
    nav = 1.0
    nav_rows = []
    trade_rows = []
    return_pivot = returns.pivot(index=date_col, columns="ts_code", values="return_1d").sort_index()

    for date in trade_dates:
        cost = 0.0
        turnover = 0.0
        if date in effective_targets:
            target = effective_targets[date]
            cost_info = estimate_rebalance_cost(current_weights, target, cost_config)
            cost = cost_info["cost"]
            turnover = cost_info["portfolio_turnover"]
            current_weights = target
            trade_rows.append({"trade_date": date, **cost_info})

        day_returns = return_pivot.loc[date].reindex(current_weights.index).fillna(0.0)
        gross_return = float((current_weights * day_returns).sum()) if not current_weights.empty else 0.0
        net_return = gross_return - cost
        nav *= 1.0 + net_return
        nav_rows.append(
            {
                "trade_date": date,
                "gross_return": gross_return,
                "cost": cost,
                "net_return": net_return,
                "nav": nav,
                "turnover": turnover,
                "holding_count": float((current_weights > 0).sum()),
            }
        )

    return pd.DataFrame(nav_rows), pd.DataFrame(trade_rows)
