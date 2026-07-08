from __future__ import annotations

import numpy as np
import pandas as pd

from ashare_factor_research.utils.helpers import require_columns


def max_drawdown(nav: pd.Series) -> float:
    running_max = nav.cummax()
    drawdown = nav / running_max - 1.0
    return float(drawdown.min())


def calc_performance(
    nav_df: pd.DataFrame,
    benchmark_return: pd.Series | None = None,
    periods_per_year: int = 252,
) -> dict[str, float]:
    require_columns(nav_df, ["trade_date", "nav", "net_return"], "nav_df")
    returns = nav_df["net_return"].fillna(0.0)
    total_return = float(nav_df["nav"].iloc[-1] / nav_df["nav"].iloc[0] - 1.0) if len(nav_df) > 1 else 0.0
    years = max(len(nav_df) / periods_per_year, 1 / periods_per_year)
    annual_return = float((nav_df["nav"].iloc[-1] / nav_df["nav"].iloc[0]) ** (1 / years) - 1.0) if len(nav_df) > 1 else 0.0
    annual_vol = float(returns.std(ddof=1) * np.sqrt(periods_per_year)) if len(returns) > 1 else np.nan
    sharpe = annual_return / annual_vol if annual_vol and not np.isnan(annual_vol) else np.nan
    mdd = max_drawdown(nav_df["nav"])
    calmar = annual_return / abs(mdd) if mdd < 0 else np.nan
    result = {
        "total_return": total_return,
        "annual_return": annual_return,
        "annual_volatility": annual_vol,
        "sharpe": float(sharpe) if not np.isnan(sharpe) else np.nan,
        "max_drawdown": mdd,
        "calmar": float(calmar) if not np.isnan(calmar) else np.nan,
        "avg_turnover": float(nav_df["turnover"].mean()) if "turnover" in nav_df else np.nan,
        "avg_holding_count": float(nav_df["holding_count"].mean()) if "holding_count" in nav_df else np.nan,
    }
    if benchmark_return is not None:
        aligned = pd.concat([returns, benchmark_return.rename("benchmark")], axis=1).dropna()
        if len(aligned) > 1:
            excess = aligned.iloc[:, 0] - aligned["benchmark"]
            te = excess.std(ddof=1) * np.sqrt(periods_per_year)
            result["annual_excess_return"] = float(excess.mean() * periods_per_year)
            result["information_ratio"] = float(result["annual_excess_return"] / te) if te else np.nan
    return result
