from __future__ import annotations

import numpy as np
import pandas as pd

from ashare_factor_research.backtest.cost_model import CostConfig
from ashare_factor_research.utils.helpers import require_columns


def industry_exposure(weights: pd.DataFrame, industry: pd.DataFrame) -> pd.DataFrame:
    if weights.empty:
        return pd.DataFrame(columns=["trade_date", "industry_code", "target_weight"])
    merged = weights.merge(industry, on=["trade_date", "ts_code"], how="left")
    return (
        merged.groupby(["trade_date", "industry_code"], as_index=False)["target_weight"]
        .sum()
        .sort_values(["trade_date", "industry_code"])
    )


def security_return_contribution(
    weights: pd.DataFrame,
    returns: pd.DataFrame,
    date_col: str = "trade_date",
    weight_col: str = "target_weight",
    return_col: str = "return_1d",
) -> pd.DataFrame:
    require_columns(weights, [date_col, "ts_code", weight_col], "weights")
    require_columns(returns, [date_col, "ts_code", return_col], "returns")
    merged = weights[[date_col, "ts_code", weight_col]].merge(
        returns[[date_col, "ts_code", return_col]],
        on=[date_col, "ts_code"],
        how="inner",
    )
    merged["return_contribution"] = merged[weight_col].astype(float) * merged[return_col].astype(float)
    return merged.sort_values([date_col, "ts_code"]).reset_index(drop=True)


def top_bottom_contributors(
    contributions: pd.DataFrame,
    group_col: str = "ts_code",
    contribution_col: str = "return_contribution",
    top_n: int = 10,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    require_columns(contributions, [group_col, contribution_col], "contributions")
    grouped = (
        contributions.groupby(group_col, as_index=False)[contribution_col]
        .sum()
        .sort_values(contribution_col, ascending=False)
    )
    top = grouped.head(top_n).reset_index(drop=True)
    bottom = grouped.tail(top_n).sort_values(contribution_col).reset_index(drop=True)
    return top, bottom


def industry_return_attribution(
    weights: pd.DataFrame,
    returns: pd.DataFrame,
    industry: pd.DataFrame,
    date_col: str = "trade_date",
    weight_col: str = "target_weight",
    return_col: str = "return_1d",
) -> pd.DataFrame:
    contributions = security_return_contribution(weights, returns, date_col, weight_col, return_col)
    require_columns(industry, [date_col, "ts_code", "industry_code"], "industry")
    merged = contributions.merge(industry[[date_col, "ts_code", "industry_code"]], on=[date_col, "ts_code"], how="left")
    return (
        merged.groupby("industry_code", dropna=False)
        .agg(
            avg_weight=(weight_col, "mean"),
            return_contribution=("return_contribution", "sum"),
            observation_count=("return_contribution", "size"),
        )
        .reset_index()
        .sort_values("return_contribution", ascending=False)
    )


def market_cap_bucket_attribution(
    weights: pd.DataFrame,
    returns: pd.DataFrame,
    market_cap: pd.DataFrame,
    n_buckets: int = 5,
    date_col: str = "trade_date",
    weight_col: str = "target_weight",
    return_col: str = "return_1d",
    market_cap_col: str = "total_mv",
) -> pd.DataFrame:
    require_columns(market_cap, [date_col, "ts_code", market_cap_col], "market_cap")
    contributions = security_return_contribution(weights, returns, date_col, weight_col, return_col)
    merged = contributions.merge(market_cap[[date_col, "ts_code", market_cap_col]], on=[date_col, "ts_code"], how="left")
    valid = merged.dropna(subset=[market_cap_col]).copy()
    if valid.empty:
        return pd.DataFrame(columns=["market_cap_bucket", "avg_weight", "return_contribution", "observation_count"])
    valid["market_cap_bucket"] = valid.groupby(date_col)[market_cap_col].transform(
        lambda x: pd.qcut(x.rank(method="first"), q=min(n_buckets, len(x)), labels=False, duplicates="drop") + 1
    )
    return (
        valid.groupby("market_cap_bucket")
        .agg(
            avg_weight=(weight_col, "mean"),
            return_contribution=("return_contribution", "sum"),
            observation_count=("return_contribution", "size"),
        )
        .reset_index()
        .sort_values("market_cap_bucket")
    )


def cost_attribution(
    trades: pd.DataFrame,
    nav_df: pd.DataFrame | None = None,
    cost_config: CostConfig | None = None,
) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(
            [
                {
                    "commission": 0.0,
                    "stamp_tax": 0.0,
                    "slippage": 0.0,
                    "impact": 0.0,
                    "total_cost": 0.0,
                    "cost_to_gross_return": np.nan,
                }
            ]
        )
    require_columns(trades, ["buy_turnover", "sell_turnover", "gross_turnover", "cost"], "trades")
    cfg = cost_config or CostConfig()
    commission = float(
        (trades["buy_turnover"] * cfg.commission_buy + trades["sell_turnover"] * cfg.commission_sell).sum()
    )
    stamp_tax = float((trades["sell_turnover"] * cfg.stamp_tax_sell).sum())
    slippage = float((trades["gross_turnover"] * cfg.slippage).sum())
    impact = float((trades["gross_turnover"] * cfg.impact_coef).sum())
    total_cost = float(trades["cost"].sum())
    gross_total_return = np.nan
    if nav_df is not None and "gross_return" in nav_df:
        gross_total_return = float((1.0 + nav_df["gross_return"].astype(float)).prod() - 1.0)
    return pd.DataFrame(
        [
            {
                "commission": commission,
                "stamp_tax": stamp_tax,
                "slippage": slippage,
                "impact": impact,
                "total_cost": total_cost,
                "cost_to_gross_return": float(total_cost / gross_total_return) if gross_total_return else np.nan,
            }
        ]
    )
