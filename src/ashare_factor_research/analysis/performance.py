from __future__ import annotations

import numpy as np
import pandas as pd

from ashare_factor_research.utils.helpers import require_columns


def max_drawdown(nav: pd.Series) -> float:
    nav = nav.dropna().astype(float)
    if nav.empty:
        return np.nan
    running_max = nav.cummax()
    drawdown = nav / running_max - 1.0
    return float(drawdown.min())


def annualized_return_from_returns(returns: pd.Series, periods_per_year: int = 252) -> float:
    returns = returns.dropna().astype(float)
    if returns.empty:
        return 0.0
    years = max(len(returns) / periods_per_year, 1 / periods_per_year)
    total = float((1.0 + returns).prod() - 1.0)
    return float((1.0 + total) ** (1.0 / years) - 1.0)


def sortino_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    returns = returns.dropna().astype(float)
    if returns.empty:
        return np.nan
    rf_per_period = risk_free_rate / periods_per_year
    downside = (returns - rf_per_period).clip(upper=0.0)
    downside_deviation = float(np.sqrt((downside**2).mean()) * np.sqrt(periods_per_year))
    if downside_deviation == 0.0:
        return np.nan
    annual_return = annualized_return_from_returns(returns, periods_per_year)
    return float((annual_return - risk_free_rate) / downside_deviation)


def tracking_error(
    strategy_return: pd.Series,
    benchmark_return: pd.Series,
    periods_per_year: int = 252,
) -> float:
    aligned = align_benchmark_returns(strategy_return, benchmark_return)
    if len(aligned) <= 1:
        return np.nan
    excess = aligned["strategy_return"] - aligned["benchmark_return"]
    return float(excess.std(ddof=1) * np.sqrt(periods_per_year))


def information_ratio(
    strategy_return: pd.Series,
    benchmark_return: pd.Series,
    periods_per_year: int = 252,
) -> float:
    aligned = align_benchmark_returns(strategy_return, benchmark_return)
    if aligned.empty:
        return np.nan
    excess = aligned["strategy_return"] - aligned["benchmark_return"]
    te = tracking_error(strategy_return, benchmark_return, periods_per_year)
    if te == 0.0 or np.isnan(te):
        return np.nan
    return float(excess.mean() * periods_per_year / te)


def beta(
    strategy_return: pd.Series,
    benchmark_return: pd.Series,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    aligned = align_benchmark_returns(strategy_return, benchmark_return)
    if len(aligned) <= 1:
        return np.nan
    rf_per_period = risk_free_rate / periods_per_year
    strategy_excess = aligned["strategy_return"] - rf_per_period
    benchmark_excess = aligned["benchmark_return"] - rf_per_period
    benchmark_var = float(benchmark_excess.var(ddof=1))
    if benchmark_var == 0.0 or np.isnan(benchmark_var):
        return np.nan
    cov = float(strategy_excess.cov(benchmark_excess))
    return float(cov / benchmark_var)


def alpha(
    strategy_return: pd.Series,
    benchmark_return: pd.Series,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    aligned = align_benchmark_returns(strategy_return, benchmark_return)
    if aligned.empty:
        return np.nan
    b = beta(strategy_return, benchmark_return, risk_free_rate, periods_per_year)
    if np.isnan(b):
        return np.nan
    rf_per_period = risk_free_rate / periods_per_year
    strategy_excess = aligned["strategy_return"] - rf_per_period
    benchmark_excess = aligned["benchmark_return"] - rf_per_period
    return float((strategy_excess.mean() - b * benchmark_excess.mean()) * periods_per_year)


def excess_max_drawdown(strategy_return: pd.Series, benchmark_return: pd.Series) -> float:
    aligned = align_benchmark_returns(strategy_return, benchmark_return)
    if aligned.empty:
        return np.nan
    excess_nav = (1.0 + aligned["strategy_return"] - aligned["benchmark_return"]).cumprod()
    return max_drawdown(excess_nav)


def monthly_win_rate(returns: pd.Series) -> float:
    monthly = periodic_returns(returns, "ME")
    if monthly.empty:
        return np.nan
    return float((monthly > 0.0).mean())


def periodic_returns(returns: pd.Series, freq: str) -> pd.Series:
    returns = returns.dropna().astype(float)
    if returns.empty:
        return pd.Series(dtype=float)
    if not isinstance(returns.index, pd.DatetimeIndex):
        raise ValueError("returns must use a DatetimeIndex for periodic aggregation")
    return returns.resample(freq).apply(lambda x: float((1.0 + x).prod() - 1.0)).dropna()


def yearly_returns(returns: pd.Series) -> pd.Series:
    out = periodic_returns(returns, "YE")
    out.index = out.index.year
    out.name = "return"
    return out


def monthly_return_matrix(returns: pd.Series) -> pd.DataFrame:
    monthly = periodic_returns(returns, "ME")
    if monthly.empty:
        return pd.DataFrame()
    matrix = monthly.to_frame("return")
    matrix["year"] = matrix.index.year
    matrix["month"] = matrix.index.month
    return matrix.pivot(index="year", columns="month", values="return").sort_index()


def rolling_volatility(
    returns: pd.Series,
    window: int = 63,
    periods_per_year: int = 252,
) -> pd.Series:
    return returns.astype(float).rolling(window).std(ddof=1) * np.sqrt(periods_per_year)


def rolling_sharpe(
    returns: pd.Series,
    window: int = 63,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> pd.Series:
    rf_per_period = risk_free_rate / periods_per_year
    excess = returns.astype(float) - rf_per_period
    roll_mean = excess.rolling(window).mean() * periods_per_year
    roll_vol = returns.astype(float).rolling(window).std(ddof=1) * np.sqrt(periods_per_year)
    return roll_mean / roll_vol.replace(0.0, np.nan)


def yearly_performance(nav_df: pd.DataFrame, periods_per_year: int = 252) -> pd.DataFrame:
    require_columns(nav_df, ["trade_date", "net_return"], "nav_df")
    data = nav_df.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"])
    yearly = yearly_returns(_return_series(data, "net_return")).rename("annual_return")
    rows = []
    for year, part in data.groupby(data["trade_date"].dt.year):
        part_returns = _return_series(part, "net_return")
        rows.append(
            {
                "year": int(year),
                "return": float(yearly.loc[year]) if year in yearly.index else np.nan,
                "annual_volatility": float(part_returns.std(ddof=1) * np.sqrt(periods_per_year))
                if len(part_returns) > 1
                else np.nan,
                "max_drawdown": max_drawdown((1.0 + part_returns).cumprod()),
                "turnover": float(part["turnover"].mean()) if "turnover" in part else np.nan,
            }
        )
    return pd.DataFrame(rows)


def align_benchmark_returns(strategy_return: pd.Series, benchmark_return: pd.Series) -> pd.DataFrame:
    strategy = strategy_return.dropna().astype(float).rename("strategy_return")
    benchmark = benchmark_return.dropna().astype(float).rename("benchmark_return")
    if not isinstance(strategy.index, pd.DatetimeIndex):
        raise ValueError("strategy_return must use a DatetimeIndex before benchmark alignment")
    if not isinstance(benchmark.index, pd.DatetimeIndex):
        raise ValueError("benchmark_return must use a DatetimeIndex before benchmark alignment")
    strategy.index = pd.to_datetime(strategy.index)
    benchmark.index = pd.to_datetime(benchmark.index)
    aligned = pd.concat([strategy, benchmark], axis=1, join="inner").dropna()
    if len(aligned) != len(strategy) or len(aligned) != len(benchmark):
        raise ValueError(
            "benchmark_return dates must exactly match strategy return dates; "
            "implicit forward-fill or positional alignment is not allowed"
        )
    return aligned


def calc_performance(
    nav_df: pd.DataFrame,
    benchmark_return: pd.Series | None = None,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> dict[str, float]:
    require_columns(nav_df, ["trade_date", "nav", "net_return"], "nav_df")
    nav = nav_df.copy()
    nav["trade_date"] = pd.to_datetime(nav["trade_date"])
    nav = nav.sort_values("trade_date")
    returns = _return_series(nav, "net_return").fillna(0.0)
    gross_returns = _return_series(nav, "gross_return").fillna(0.0) if "gross_return" in nav else None
    total_return = float(nav["nav"].iloc[-1] / nav["nav"].iloc[0] - 1.0) if len(nav) > 1 else 0.0
    years = max(len(nav) / periods_per_year, 1 / periods_per_year)
    annual_return = float((nav["nav"].iloc[-1] / nav["nav"].iloc[0]) ** (1 / years) - 1.0) if len(nav) > 1 else 0.0
    annual_vol = float(returns.std(ddof=1) * np.sqrt(periods_per_year)) if len(returns) > 1 else np.nan
    sharpe = (annual_return - risk_free_rate) / annual_vol if annual_vol and not np.isnan(annual_vol) else np.nan
    mdd = max_drawdown(nav["nav"])
    calmar = annual_return / abs(mdd) if mdd < 0 else np.nan
    result = {
        "total_return": total_return,
        "annual_return": annual_return,
        "annual_volatility": annual_vol,
        "sharpe": float(sharpe) if not np.isnan(sharpe) else np.nan,
        "sortino": sortino_ratio(returns, risk_free_rate, periods_per_year),
        "max_drawdown": mdd,
        "calmar": float(calmar) if not np.isnan(calmar) else np.nan,
        "monthly_win_rate": monthly_win_rate(returns),
        "avg_turnover": float(nav["turnover"].mean()) if "turnover" in nav else np.nan,
        "avg_holding_count": float(nav["holding_count"].mean()) if "holding_count" in nav else np.nan,
        "total_cost": float(nav["cost"].sum()) if "cost" in nav else np.nan,
    }
    result.update({
        "full_period_total_return": total_return,
        "full_period_annual_return": annual_return,
        "full_period_annual_volatility": annual_vol,
        "full_period_sharpe": float(sharpe) if not np.isnan(sharpe) else np.nan,
        "full_period_max_drawdown": mdd,
    })
    active_returns: pd.Series | None = None
    if "holding_count" in nav:
        invested = nav["holding_count"].gt(0)
        result["invested_days"] = float(invested.sum())
        result["avg_holding_count_invested_days"] = (
            float(nav.loc[invested, "holding_count"].mean()) if invested.any() else np.nan
        )
        if "cash_weight" in nav:
            result["avg_cash_weight_invested_days"] = (
                float(nav.loc[invested, "cash_weight"].mean()) if invested.any() else np.nan
            )
            result["max_cash_weight_invested_days"] = (
                float(nav.loc[invested, "cash_weight"].max()) if invested.any() else np.nan
            )
        if invested.any():
            first_active = int(np.flatnonzero(invested.to_numpy())[0])
            result["pre_investment_days"] = float(first_active)
            active_nav = nav.iloc[first_active:].copy()
            result["inactive_days_after_start"] = float((~active_nav["holding_count"].gt(0)).sum())
            active_returns = _return_series(active_nav, "net_return").fillna(0.0)
            active_total = float((1.0 + active_returns).prod() - 1.0)
            active_annual = annualized_return_from_returns(active_returns, periods_per_year)
            active_vol = float(active_returns.std(ddof=1) * np.sqrt(periods_per_year)) if len(active_returns) > 1 else np.nan
            active_curve = (1.0 + active_returns).cumprod()
            result.update({
                "active_period_start": str(pd.to_datetime(active_nav["trade_date"].iloc[0]).date()),
                "active_period_days": float(len(active_returns)),
                "active_total_return": active_total,
                "active_annual_return": active_annual,
                "active_annual_volatility": active_vol,
                "active_sharpe": float((active_annual - risk_free_rate) / active_vol)
                if active_vol and not np.isnan(active_vol) else np.nan,
                "active_max_drawdown": max_drawdown(active_curve),
            })
        else:
            result["pre_investment_days"] = float(len(nav))
            result["inactive_days_after_start"] = 0.0
    if gross_returns is not None:
        result["gross_total_return"] = float((1.0 + gross_returns).prod() - 1.0)
        result["net_total_return"] = float((1.0 + returns).prod() - 1.0)
        result["cost_drag"] = result["gross_total_return"] - result["net_total_return"]
    if benchmark_return is not None:
        aligned = align_benchmark_returns(returns, benchmark_return)
        if len(aligned) > 1:
            excess = aligned["strategy_return"] - aligned["benchmark_return"]
            te = float(excess.std(ddof=1) * np.sqrt(periods_per_year))
            full_excess = float(excess.mean() * periods_per_year)
            result["full_period_annual_excess_return"] = full_excess
            result["full_period_information_ratio"] = float(full_excess / te) if te else np.nan
            result["full_period_tracking_error"] = te
            relative_strategy = returns
            relative_benchmark = benchmark_return
            if active_returns is not None and len(active_returns) > 1:
                relative_strategy = active_returns
                relative_benchmark = benchmark_return.reindex(active_returns.index)
            comparable = align_benchmark_returns(relative_strategy, relative_benchmark)
            comparable_excess = comparable["strategy_return"] - comparable["benchmark_return"]
            comparable_te = float(comparable_excess.std(ddof=1) * np.sqrt(periods_per_year))
            result["annual_excess_return"] = float(comparable_excess.mean() * periods_per_year)
            result["information_ratio"] = (
                float(result["annual_excess_return"] / comparable_te) if comparable_te else np.nan
            )
            result["tracking_error"] = comparable_te
            result["beta"] = beta(relative_strategy, relative_benchmark, risk_free_rate, periods_per_year)
            result["alpha"] = alpha(relative_strategy, relative_benchmark, risk_free_rate, periods_per_year)
            result["excess_max_drawdown"] = excess_max_drawdown(relative_strategy, relative_benchmark)
            if active_returns is not None:
                result["active_annual_excess_return"] = result["annual_excess_return"]
                result["active_information_ratio"] = result["information_ratio"]
                result["active_tracking_error"] = result["tracking_error"]
    return result


def _return_series(nav_df: pd.DataFrame, return_col: str) -> pd.Series:
    if return_col not in nav_df:
        return pd.Series(dtype=float)
    out = nav_df.set_index(pd.to_datetime(nav_df["trade_date"]))[return_col].astype(float)
    out.index.name = "trade_date"
    return out.sort_index()
