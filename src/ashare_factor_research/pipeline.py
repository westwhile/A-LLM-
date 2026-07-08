from __future__ import annotations

from pathlib import Path

import pandas as pd

from ashare_factor_research.analysis.performance import calc_performance
from ashare_factor_research.analysis.report_charts import save_placeholder_tables
from ashare_factor_research.backtest.backtest_engine import run_backtest
from ashare_factor_research.backtest.cost_model import CostConfig
from ashare_factor_research.backtest.portfolio_builder import build_portfolio
from ashare_factor_research.data.data_cleaner import add_adjusted_prices, add_forward_returns, filter_universe
from ashare_factor_research.data.data_loader import LocalDataLoader
from ashare_factor_research.data.trading_calendar import get_trade_dates, month_end_rebalance_dates
from ashare_factor_research.factor_testing.group_test import calc_group_returns
from ashare_factor_research.factor_testing.ic_test import calc_factor_ic_table
from ashare_factor_research.factors.factor_processor import factor_correlation, process_factors
from ashare_factor_research.factors.fundamental_factors import compute_fundamental_factors
from ashare_factor_research.factors.llm_event_factors import compute_event_sentiment_factor
from ashare_factor_research.factors.money_flow_factors import compute_money_flow_factors
from ashare_factor_research.factors.price_volume_factors import compute_price_volume_factors


DEFAULT_FACTOR_COLS = [
    "mom_20",
    "mom_60_skip5",
    "rev_5",
    "vol_20",
    "turnover_20",
    "amihud_20",
    "size",
    "bp",
    "ep",
    "roe",
    "gross_margin",
    "revenue_yoy",
    "profit_yoy",
    "mf_20",
    "event_sentiment_20",
]


def build_factor_panel(data: dict[str, pd.DataFrame], horizon: int = 20) -> tuple[pd.DataFrame, list[str]]:
    daily_bar = add_forward_returns(add_adjusted_prices(data["daily_bar"]), horizon=horizon)
    daily_bar = filter_universe(daily_bar)
    trade_dates = get_trade_dates(daily_bar)

    base = daily_bar[["trade_date", "ts_code", "adj_close", "return_1d", f"future_return_{horizon}"]]
    daily_basic = data["daily_basic"]
    price_input = daily_bar.merge(
        daily_basic[["trade_date", "ts_code", "turnover_rate"]],
        on=["trade_date", "ts_code"],
        how="left",
    )
    factors = base.merge(compute_price_volume_factors(price_input), on=["trade_date", "ts_code"], how="left")
    factors = factors.merge(
        compute_fundamental_factors(daily_basic, data["financial_indicator"], trade_dates),
        on=["trade_date", "ts_code"],
        how="left",
    )
    factors = factors.merge(
        compute_money_flow_factors(daily_basic, daily_bar),
        on=["trade_date", "ts_code"],
        how="left",
    )
    factors = factors.merge(data["industry"], on=["trade_date", "ts_code"], how="left")
    event_factor = compute_event_sentiment_factor(data["news_event"], trade_dates)
    factors = factors.merge(event_factor, on=["trade_date", "ts_code"], how="left")
    factors["event_sentiment_20"] = factors["event_sentiment_20"].fillna(0.0)
    factor_cols = [c for c in DEFAULT_FACTOR_COLS if c in factors.columns]
    return factors, factor_cols


def run_sample_pipeline(
    data_dir: str | Path = "data/sample",
    output_dir: str | Path = "reports/figures",
    horizon: int = 20,
    top_n: int = 10,
    max_weight: float = 0.2,
) -> dict[str, object]:
    data = LocalDataLoader(data_dir).load_all()
    factor_panel, factor_cols = build_factor_panel(data, horizon=horizon)
    processed = process_factors(
        factor_panel,
        factor_cols,
        size_col="size",
        industry_col="industry_code",
        neutralize=True,
    )
    return_col = f"future_return_{horizon}"
    processed["score"] = processed[factor_cols].mean(axis=1, skipna=True)
    ic_table = calc_factor_ic_table(processed, factor_cols, return_col=return_col)
    group_returns = calc_group_returns(processed, "score", return_col=return_col)
    corr = factor_correlation(processed, factor_cols)

    rebal_dates = month_end_rebalance_dates(get_trade_dates(data["daily_bar"]))
    score_df = processed[processed["trade_date"].isin(rebal_dates)][["trade_date", "ts_code", "score"]].dropna()
    portfolio = build_portfolio(score_df, top_n=top_n, max_weight=max_weight)
    returns_df = add_adjusted_prices(data["daily_bar"])[["trade_date", "ts_code", "return_1d"]]
    nav, trades = run_backtest(portfolio, returns_df, cost_config=CostConfig())
    metrics = calc_performance(nav)

    out = Path(output_dir)
    save_placeholder_tables(out, metrics, ic_table)
    group_returns.to_csv(out / "group_returns.csv")
    corr.to_csv(out / "factor_corr.csv")
    nav.to_csv(out / "sample_nav.csv", index=False)
    trades.to_csv(out / "sample_trades.csv", index=False)
    return {
        "factor_panel": processed,
        "factor_cols": factor_cols,
        "ic_table": ic_table,
        "group_returns": group_returns,
        "portfolio": portfolio,
        "nav": nav,
        "trades": trades,
        "metrics": metrics,
    }
