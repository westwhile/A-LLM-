from __future__ import annotations

from dataclasses import asdict, replace

import pandas as pd

from ashare_factor_research.analysis.performance import calc_performance
from ashare_factor_research.backtest.backtest_engine import BacktestResult, run_event_backtest
from ashare_factor_research.backtest.cost_model import CostConfig


def summarize_unfilled_orders(orders: pd.DataFrame) -> pd.DataFrame:
    if orders.empty:
        return pd.DataFrame(columns=["reason", "order_count", "requested_value", "filled_value", "unfilled_value"])
    data = orders[orders["status"].ne("filled")].copy()
    if data.empty:
        return pd.DataFrame(columns=["reason", "order_count", "requested_value", "filled_value", "unfilled_value"])
    data["unfilled_value"] = data["requested_value"].astype(float) - data["filled_value"].astype(float)
    return (
        data.groupby("reason", dropna=False)
        .agg(
            order_count=("reason", "size"),
            requested_value=("requested_value", "sum"),
            filled_value=("filled_value", "sum"),
            unfilled_value=("unfilled_value", "sum"),
        )
        .reset_index()
        .sort_values("unfilled_value", ascending=False)
    )


def run_execution_scenarios(
    portfolio: pd.DataFrame,
    market: pd.DataFrame,
    base_cost: CostConfig,
    *,
    delays: tuple[int, ...] = (1, 2, 3),
    participation_rates: tuple[float | None, ...] = (None, 0.01, 0.05, 0.10),
    cost_multipliers: tuple[tuple[str, float], ...] = (("zero", 0.0), ("standard", 1.0), ("high", 2.0)),
    min_trade_amount: float | None = None,
    max_turnover: float | None = 0.5,
    initial_cash_values: tuple[float, ...] = (1_000_000.0,),
    exclude_limit_up_for_buy: bool = True,
    exclude_limit_down_for_sell: bool = True,
) -> tuple[pd.DataFrame, dict[str, BacktestResult]]:
    rows: list[dict[str, object]] = []
    results: dict[str, BacktestResult] = {}
    for cost_name, multiplier in cost_multipliers:
        cfg = replace(base_cost, **{key: value * multiplier for key, value in asdict(base_cost).items()})
        for delay in delays:
            for participation in participation_rates:
                for initial_cash in initial_cash_values:
                    label = (
                        f"cost={cost_name}|delay={delay}|participation={participation or 'none'}|"
                        f"initial_cash={int(initial_cash)}"
                    )
                    result = run_event_backtest(
                        portfolio,
                        market,
                        cost_config=cfg,
                        execution_delay_days=delay,
                        max_participation_rate=participation,
                        min_trade_amount=min_trade_amount,
                        max_turnover=max_turnover,
                        initial_cash=float(initial_cash),
                        exclude_limit_up_for_buy=exclude_limit_up_for_buy,
                        exclude_limit_down_for_sell=exclude_limit_down_for_sell,
                    )
                    metrics = calc_performance(result.nav)
                    unfilled = result.orders["status"].ne("filled").sum() if not result.orders.empty else 0
                    rows.append(
                        {
                            "scenario": label,
                            "cost_case": cost_name,
                            "execution_delay_days": delay,
                            "participation_rate": participation,
                            "initial_cash": float(initial_cash),
                            "total_return": metrics.get("total_return"),
                            "annual_return": metrics.get("annual_return"),
                            "sharpe": metrics.get("sharpe"),
                            "max_drawdown": metrics.get("max_drawdown"),
                            "avg_turnover": metrics.get("avg_turnover"),
                            "unfilled_order_count": int(unfilled),
                        }
                    )
                    results[label] = result
    return pd.DataFrame(rows), results
