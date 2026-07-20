from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Any

import numpy as np
import pandas as pd

from ashare_factor_research.backtest.cost_model import CostConfig, estimate_rebalance_cost
from ashare_factor_research.data.trading_calendar import next_trade_date
from ashare_factor_research.factor_testing.inference import benjamini_hochberg, newey_west_mean_test
from ashare_factor_research.factors.factor_processor import neutralize_factor
from ashare_factor_research.time_series.models import (
    MODEL_VERSION,
    GaussianHMM,
    dcc_covariance,
    diebold_mariano_test,
    expanding_forecast_comparison,
    gjr_garch_forecast,
    kalman_local_level,
    superior_predictive_ability_test,
)
from ashare_factor_research.utils.helpers import require_columns


OUTPUT_NAMES = (
    "time_series_diagnostics",
    "regime_probabilities",
    "dynamic_factor_weights",
    "volatility_forecasts",
    "forecast_comparison",
    "model_selection_audit",
    "monthly_factor_ic",
    "monthly_factor_returns",
    "dynamic_covariance",
    "exposure_scalars",
)

EMPTY_SCHEMAS = {
    "regime_probabilities": ["as_of_date", "training_end", "forecast_target", "observation_count", "status", "model_version"],
    "dynamic_factor_weights": ["test_date", "factor", "direction", "weight", "filtered_ic", "forecast_ic", "forecast_variance", "p_value", "fdr_q_value", "observation_count", "train_label_end_max", "model_version"],
    "volatility_forecasts": ["as_of_date", "training_end", "forecast_target", "model", "status", "observation_count", "annualized_volatility_forecast", "model_version"],
    "forecast_comparison": [
        "target_series", "train_start", "train_end", "training_end", "forecast_origin", "forecast_target",
        "availability_date", "model", "forecast", "actual", "error", "squared_error",
        "absolute_error", "direction_hit", "point_in_time_valid", "model_version",
    ],
    "monthly_factor_ic": ["signal_date", "execution_date", "label_end_date", "availability_date", "factor", "rank_ic", "valid_stock_count", "universe_denominator", "coverage", "interval"],
    "monthly_factor_returns": [
        "signal_date", "execution_date", "label_end_date", "availability_date", "factor", "interval",
        "Q1_raw", "Q2_raw", "Q3_raw", "Q4_raw", "Q5_raw", "Q5_minus_Q1_raw",
        "Q1_neutral", "Q2_neutral", "Q3_neutral", "Q4_neutral", "Q5_neutral", "Q5_minus_Q1_neutral",
        "Q5_long_only_return", "relative_csi500_return",
        "gross_return", "cost", "net_return", "turnover", "tradable_count",
        "portfolio_type", "is_diagnostic",
    ],
    "dynamic_covariance": ["as_of_date", "factor_left", "factor_right", "conditional_covariance", "model", "model_version"],
    "exposure_scalars": ["trade_date", "exposure_scalar", "model_version"],
    "economic_comparison": ["scheme", "signal_date", "availability_date", "gross_return", "cost", "net_return", "turnover"],
}


@dataclass(frozen=True)
class TimeSeriesResearchResult:
    frames: dict[str, pd.DataFrame]
    dynamic_scores: pd.DataFrame
    status: str


def _rank_correlation(part: pd.DataFrame, factor: str, return_col: str) -> float:
    use = part[[factor, return_col]].dropna()
    if len(use) < 3:
        return np.nan
    return float(use[factor].rank(method="average").corr(use[return_col].rank(method="average")))


def _neutralize_panel(
    panel: pd.DataFrame,
    factor_cols: list[str],
    date_col: str = "trade_date",
    size_col: str = "size",
    industry_col: str = "industry_code",
) -> pd.DataFrame:
    """Return a panel with industry/size-neutral factor columns."""

    out = panel.copy()
    for factor in factor_cols:
        if factor not in out or size_col not in out or industry_col not in out:
            continue
        neutral_col = f"{factor}_neutral"
        out[neutral_col] = out[factor]
        out = neutralize_factor(
            out,
            neutral_col,
            size_col=size_col,
            industry_col=industry_col,
            date_col=date_col,
            use_size=True,
            use_industry=True,
        )
    return out


def _quintile_returns(part: pd.DataFrame, factor: str, return_col: str) -> dict[str, float]:
    """Mean return of Q1..Q5 plus Q5-Q1 spread for one factor on one signal date."""

    use = part[[factor, return_col]].dropna().copy()
    result: dict[str, float] = {f"Q{i}": np.nan for i in range(1, 6)}
    result["Q5_minus_Q1"] = np.nan
    if len(use) < 10:
        return result
    try:
        use["bucket"] = pd.qcut(use[factor].rank(method="first"), 5, labels=False)
        bucket_return = use.groupby("bucket", observed=True)[return_col].mean()
        for bucket_id, label in enumerate(["Q1", "Q2", "Q3", "Q4", "Q5"]):
            if bucket_id in bucket_return.index:
                result[label] = float(bucket_return.loc[bucket_id])
        if 0 in bucket_return.index and 4 in bucket_return.index:
            result["Q5_minus_Q1"] = float(bucket_return.loc[4] - bucket_return.loc[0])
    except ValueError:
        pass
    return result


def _portfolio_turnover(
    previous_codes: set[str] | None,
    current_codes: set[str],
) -> float:
    if not current_codes:
        return np.nan
    if previous_codes is None or not previous_codes:
        return 1.0
    union = previous_codes | current_codes
    if not union:
        return np.nan
    return 1.0 - len(previous_codes & current_codes) / len(union)


def _interval_benchmark_return(
    benchmark_return: pd.Series | None,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> float:
    if benchmark_return is None:
        return np.nan
    clean = benchmark_return.copy().astype(float)
    clean.index = pd.to_datetime(clean.index)
    mask = (clean.index > pd.Timestamp(start)) & (clean.index <= pd.Timestamp(end))
    segment = clean.loc[mask]
    if segment.empty:
        return np.nan
    return float(np.log1p(segment.clip(lower=-0.999999)).sum())


def _timing_for_part(part: pd.DataFrame, signal_date: pd.Timestamp) -> dict[str, pd.Timestamp] | None:
    label_values = pd.to_datetime(part["target_return_end_date"], errors="coerce").dropna().unique()
    if len(label_values) == 0:
        return None
    if len(label_values) != 1:
        raise ValueError(f"Monthly sample requires one label_end_date at {signal_date}; got {len(label_values)}")
    label_end = pd.Timestamp(label_values[0])
    if "execution_date" in part:
        execution_values = pd.to_datetime(part["execution_date"], errors="coerce").dropna().unique()
        if len(execution_values) > 1:
            raise ValueError(f"Monthly sample requires one execution_date at {signal_date}")
        execution = pd.Timestamp(execution_values[0]) if len(execution_values) else pd.Timestamp(signal_date) + pd.offsets.BDay(1)
    else:
        execution = pd.Timestamp(signal_date) + pd.offsets.BDay(1)
    if "availability_date" in part:
        availability_values = pd.to_datetime(part["availability_date"], errors="coerce").dropna().unique()
        if len(availability_values) > 1:
            raise ValueError(f"Monthly sample requires one availability_date at {signal_date}")
        availability = pd.Timestamp(availability_values[0]) if len(availability_values) else label_end + pd.offsets.BDay(1)
    else:
        availability = label_end + pd.offsets.BDay(1)
    if not (pd.Timestamp(signal_date) < execution <= label_end < availability):
        raise ValueError(
            f"Invalid monthly timing at {signal_date}: execution={execution}, "
            f"label_end={label_end}, availability={availability}"
        )
    return {
        "execution_date": execution,
        "label_end_date": label_end,
        "availability_date": availability,
    }


def build_monthly_factor_ic(
    panel: pd.DataFrame,
    factor_cols: list[str],
    return_col: str,
    rebalance_dates: pd.DatetimeIndex,
    *,
    interval: str = "1M",
) -> pd.DataFrame:
    """Build non-overlapping factor IC history with point-in-time coverage."""

    require_columns(panel, ["trade_date", "target_return_end_date", return_col, *factor_cols], "factor_panel")
    data = panel.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"])
    data["target_return_end_date"] = pd.to_datetime(data["target_return_end_date"])
    requested = set(pd.to_datetime(rebalance_dates))
    data = data[data["trade_date"].isin(requested)]
    neutral_data = _neutralize_panel(data, factor_cols)
    rows: list[dict[str, object]] = []
    for signal_date, part in data.groupby("trade_date"):
        timing = _timing_for_part(part, pd.Timestamp(signal_date))
        if timing is None:
            continue
        universe_denominator = int(len(part))
        for factor in factor_cols:
            valid = part[[factor, return_col]].dropna()
            valid_count = int(len(valid))
            rank_ic = _rank_correlation(part, factor, return_col)
            neutral_col = f"{factor}_neutral"
            neutral_ic = _rank_correlation(neutral_data[neutral_data["trade_date"].eq(signal_date)], neutral_col, return_col) if neutral_col in neutral_data else np.nan
            rows.append({
                "signal_date": pd.Timestamp(signal_date),
                **timing,
                "factor": factor,
                "rank_ic": rank_ic,
                "neutral_rank_ic": neutral_ic,
                "valid_stock_count": valid_count,
                "universe_denominator": universe_denominator,
                "coverage": valid_count / universe_denominator if universe_denominator else np.nan,
                "interval": interval,
            })
    return pd.DataFrame(rows)


def build_monthly_factor_returns(
    panel: pd.DataFrame,
    factor_cols: list[str],
    return_col: str,
    rebalance_dates: pd.DatetimeIndex,
    benchmark_return: pd.Series | None,
    cost_config: CostConfig | None = None,
    *,
    interval: str = "1M",
) -> pd.DataFrame:
    """Build raw and neutral Q1-Q5 returns with gross/net/cost/turnover."""

    require_columns(panel, ["trade_date", "target_return_end_date", return_col, *factor_cols], "factor_panel")
    cfg = cost_config or CostConfig()
    data = panel.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"])
    data["target_return_end_date"] = pd.to_datetime(data["target_return_end_date"])
    requested = set(pd.to_datetime(rebalance_dates))
    data = data[data["trade_date"].isin(requested)]
    neutral_data = _neutralize_panel(data, factor_cols)
    rows: list[dict[str, object]] = []
    previous_q5: dict[str, set[str] | None] = {factor: None for factor in factor_cols}
    previous_q1: dict[str, set[str] | None] = {factor: None for factor in factor_cols}
    for signal_date, part in data.groupby("trade_date"):
        timing = _timing_for_part(part, pd.Timestamp(signal_date))
        if timing is None:
            continue
        benchmark_interval = _interval_benchmark_return(
            benchmark_return, signal_date, timing["label_end_date"]
        )
        for factor in factor_cols:
            raw = _quintile_returns(part, factor, return_col)
            neutral_col = f"{factor}_neutral"
            neutral_part = neutral_data[neutral_data["trade_date"].eq(signal_date)] if neutral_col in neutral_data else part
            neutral = _quintile_returns(neutral_part, neutral_col if neutral_col in neutral_part else factor, return_col)
            q5_long_only = raw.get("Q5", np.nan)
            relative_csi500 = q5_long_only - benchmark_interval if np.isfinite(q5_long_only) and np.isfinite(benchmark_interval) else np.nan
            q5_codes = set(
                part.assign(_bucket=pd.qcut(part[factor].rank(method="first"), 5, labels=False))
                .loc[lambda df: df["_bucket"] == 4, "ts_code"]
                .astype(str)
            ) if factor in part and part[factor].notna().sum() >= 10 else set()
            q1_codes = set(
                part.assign(_bucket=pd.qcut(part[factor].rank(method="first"), 5, labels=False))
                .loc[lambda df: df["_bucket"] == 0, "ts_code"]
                .astype(str)
            ) if factor in part and part[factor].notna().sum() >= 10 else set()
            turnover_q5 = _portfolio_turnover(previous_q5.get(factor), q5_codes)
            turnover_q1 = _portfolio_turnover(previous_q1.get(factor), q1_codes)
            finite_turnovers = [value for value in [turnover_q5, turnover_q1] if np.isfinite(value)]
            turnover = float(np.mean(finite_turnovers)) if finite_turnovers else np.nan
            # Equal-weight long-short cost on both legs, assuming full rebalance each period.
            cost_q5 = turnover_q5 * (cfg.commission_buy + cfg.commission_sell + cfg.stamp_tax_sell + cfg.slippage + cfg.impact_coef) if np.isfinite(turnover_q5) else np.nan
            cost_q1 = turnover_q1 * (cfg.commission_buy + cfg.commission_sell + cfg.stamp_tax_sell + cfg.slippage + cfg.impact_coef) if np.isfinite(turnover_q1) else np.nan
            cost = np.nanmean([cost_q5, cost_q1]) if np.isfinite(cost_q5) and np.isfinite(cost_q1) else (cost_q5 if np.isfinite(cost_q5) else cost_q1)
            gross = raw.get("Q5_minus_Q1", np.nan)
            net = gross - cost if np.isfinite(gross) and np.isfinite(cost) else np.nan
            if np.isfinite(gross) and np.isfinite(cost):
                rounded_identity = round(gross - cost - net, 10)
                if rounded_identity != 0.0:
                    raise ValueError(f"gross_return - cost != net_return for {factor} at {signal_date}: {gross}-{cost}={net}")
            previous_q5[factor] = q5_codes
            previous_q1[factor] = q1_codes
            rows.append({
                "signal_date": pd.Timestamp(signal_date),
                **timing,
                "factor": factor,
                "interval": interval,
                "Q1_raw": raw.get("Q1", np.nan),
                "Q2_raw": raw.get("Q2", np.nan),
                "Q3_raw": raw.get("Q3", np.nan),
                "Q4_raw": raw.get("Q4", np.nan),
                "Q5_raw": raw.get("Q5", np.nan),
                "Q5_minus_Q1_raw": raw.get("Q5_minus_Q1", np.nan),
                "Q1_neutral": neutral.get("Q1", np.nan),
                "Q2_neutral": neutral.get("Q2", np.nan),
                "Q3_neutral": neutral.get("Q3", np.nan),
                "Q4_neutral": neutral.get("Q4", np.nan),
                "Q5_neutral": neutral.get("Q5", np.nan),
                "Q5_minus_Q1_neutral": neutral.get("Q5_minus_Q1", np.nan),
                "Q5_long_only_return": q5_long_only,
                "relative_csi500_return": relative_csi500,
                "gross_return": gross,
                "cost": cost,
                "net_return": net,
                "turnover": turnover,
                "tradable_count": int(part[[factor, return_col]].dropna().shape[0]) if factor in part else 0,
                "portfolio_type": "diagnostic_long_short",
                "is_diagnostic": True,
            })
    return pd.DataFrame(rows)


def build_monthly_factor_history(
    panel: pd.DataFrame,
    factor_cols: list[str],
    return_col: str,
    rebalance_dates: pd.DatetimeIndex,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Backward-compatible wrapper returning the old IC and Q5-Q1 schemas."""

    monthly_ic = build_monthly_factor_ic(panel, factor_cols, return_col, rebalance_dates)
    monthly_returns = build_monthly_factor_returns(panel, factor_cols, return_col, rebalance_dates, benchmark_return=None)
    ic = monthly_ic[["signal_date", "availability_date", "factor", "valid_stock_count", "rank_ic"]].rename(
        columns={"valid_stock_count": "asset_count"}
    )
    returns = monthly_returns[["signal_date", "availability_date", "factor", "tradable_count", "Q5_minus_Q1_raw"]].rename(
        columns={"tradable_count": "asset_count", "Q5_minus_Q1_raw": "q5_minus_q1"}
    )
    return ic, returns


def build_standard_series(
    panel: pd.DataFrame,
    market: pd.DataFrame,
    benchmark_return: pd.Series | None,
) -> pd.DataFrame:
    """Create stationary or economically interpretable daily research series."""

    require_columns(panel, ["trade_date", "return_1d"], "factor_panel")
    data = panel.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"])
    daily = data.groupby("trade_date").agg(
        breadth=("return_1d", lambda values: float((values > 0).mean())),
        cross_sectional_dispersion=("return_1d", lambda values: float(values.std(ddof=1))),
    )
    market_data = market.copy()
    market_data["trade_date"] = pd.to_datetime(market_data["trade_date"])
    if "amount" in market_data:
        liquidity = market_data.groupby("trade_date")["amount"].median().replace(0.0, np.nan)
        daily["log_median_amount"] = np.log(liquidity)
    if "turnover_rate" in market_data:
        daily["median_turnover_rate"] = market_data.groupby("trade_date")["turnover_rate"].median()
    if benchmark_return is not None:
        benchmark = benchmark_return.copy().astype(float)
        benchmark.index = pd.to_datetime(benchmark.index)
        daily["benchmark_log_return"] = np.log1p(benchmark.reindex(daily.index).clip(lower=-0.999999))
        daily["realized_volatility_20"] = (
            daily["benchmark_log_return"].rolling(20, min_periods=10).std(ddof=1) * sqrt(252.0)
        )
    return daily.sort_index()


def build_monthly_state_variables(
    panel: pd.DataFrame,
    market: pd.DataFrame,
    benchmark_return: pd.Series | None,
    labels: pd.DataFrame,
) -> pd.DataFrame:
    """Aggregate state variables using only observations available by signal close."""

    daily = build_standard_series(panel, market, benchmark_return)
    if daily.empty or labels.empty:
        return pd.DataFrame(columns=[
            "signal_date", "availability_date", "benchmark_log_return",
            "realized_volatility_20", "breadth", "log_median_amount",
            "median_turnover_rate", "cross_sectional_dispersion",
        ])
    label_frame = labels.copy()
    for column in ["signal_date", "execution_date", "label_end_date", "availability_date"]:
        label_frame[column] = pd.to_datetime(label_frame[column])
    rows: list[dict[str, object]] = []
    for label in label_frame.itertuples(index=False):
        signal = pd.Timestamp(label.signal_date)
        month_start = signal.to_period("M").start_time
        history = daily[(daily.index >= month_start) & (daily.index <= signal)]
        if history.empty:
            continue
        row: dict[str, object] = {
            "signal_date": signal,
            "execution_date": pd.Timestamp(label.execution_date),
            "label_end_date": pd.Timestamp(label.label_end_date),
            "availability_date": signal,
        }
        if "benchmark_log_return" in history:
            row["benchmark_log_return"] = float(history["benchmark_log_return"].sum(min_count=1))
        for column, aggregator in {
            "realized_volatility_20": "last",
            "breadth": "mean",
            "log_median_amount": "mean",
            "median_turnover_rate": "mean",
            "cross_sectional_dispersion": "mean",
        }.items():
            if column in history:
                values = history[column].dropna()
                row[column] = float(
                    values.iloc[-1] if aggregator == "last" and not values.empty else values.mean()
                ) if not values.empty else np.nan
        for column in [
            "benchmark_log_return", "realized_volatility_20", "breadth",
            "log_median_amount", "median_turnover_rate", "cross_sectional_dispersion",
        ]:
            row.setdefault(column, np.nan)
        rows.append(row)
    return pd.DataFrame(rows).sort_values("signal_date").reset_index(drop=True)


def _diagnostic_rows(series_name: str, series: pd.Series, max_lag: int) -> list[dict[str, object]]:
    clean = series.dropna().astype(float)
    missing_count = int(series.isna().sum())
    outlier_info = _detect_outliers(series)
    rows: list[dict[str, object]] = [{
        "series": series_name,
        "test": "missing_values",
        "statistic": float(missing_count),
        "p_value": np.nan,
        "observations": int(len(series)),
        "status": "ok" if missing_count == 0 else "handled_by_dropna",
        "detail": f"missing_count={missing_count}; decision=drop_for_this_fit",
        "model_version": MODEL_VERSION,
    }, {
        "series": series_name,
        "test": "outlier_check",
        "statistic": float(outlier_info["outlier_count"]),
        "p_value": np.nan,
        "observations": int(len(clean)),
        "status": str(outlier_info["decision"]),
        "detail": f"outlier_rate={outlier_info['outlier_rate']}; decision=no_automatic_winsorization",
        "model_version": MODEL_VERSION,
    }, {
        "series": series_name,
        "test": "summary",
        "statistic": float(clean.mean()) if len(clean) else np.nan,
        "p_value": np.nan,
        "observations": int(len(clean)),
        "status": "ok" if len(clean) else "empty",
        "detail": f"std={float(clean.std(ddof=1)) if len(clean) > 1 else np.nan}",
        "model_version": MODEL_VERSION,
    }]
    if len(clean) < max(20, max_lag + 5):
        rows.append({
            "series": series_name, "test": "statistical_suite", "statistic": np.nan, "p_value": np.nan,
            "observations": int(len(clean)), "status": "insufficient_history",
            "detail": "ADF/KPSS/Ljung-Box/ARCH/Zivot-Andrews require more observations", "model_version": MODEL_VERSION,
        })
        return rows
    try:
        from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch
        from statsmodels.tsa.stattools import acf, adfuller, kpss, pacf, zivot_andrews

        adf = adfuller(clean.to_numpy(), autolag="AIC")
        kpss_result = kpss(clean.to_numpy(), regression="c", nlags="auto")
        lb = acorr_ljungbox(clean.to_numpy(), lags=[min(max_lag, len(clean) // 4)], return_df=True).iloc[-1]
        arch = het_arch(clean.to_numpy(), nlags=min(max_lag, max(1, len(clean) // 5)))
        za = zivot_andrews(clean.to_numpy(), regression="c", autolag="AIC")
        acf_values = acf(clean.to_numpy(), nlags=min(max_lag, len(clean) // 4), fft=False)
        pacf_values = pacf(clean.to_numpy(), nlags=min(max_lag, len(clean) // 4), method="ywm")
        tests = [
            ("adf", adf[0], adf[1], "unit-root null"),
            ("kpss", kpss_result[0], kpss_result[1], "stationarity null"),
            ("ljung_box", lb["lb_stat"], lb["lb_pvalue"], "serial-correlation null"),
            ("arch_lm", arch[0], arch[1], "homoskedasticity null"),
            ("zivot_andrews", za[0], za[1], "unit-root with structural-break null"),
            ("acf_lag1", acf_values[1], np.nan, "lag-1 autocorrelation"),
            ("pacf_lag1", pacf_values[1], np.nan, "lag-1 partial autocorrelation"),
        ]
        rows.extend({
            "series": series_name, "test": name, "statistic": float(stat), "p_value": float(pvalue),
            "observations": int(len(clean)), "status": "ok", "detail": detail, "model_version": MODEL_VERSION,
        } for name, stat, pvalue, detail in tests)
    except (ImportError, ValueError, np.linalg.LinAlgError) as exc:
        rows.append({
            "series": series_name, "test": "statistical_suite", "statistic": np.nan, "p_value": np.nan,
            "observations": int(len(clean)), "status": "unavailable", "detail": str(exc),
            "model_version": MODEL_VERSION,
        })
    return rows


def build_time_series_diagnostics(
    standard_series: pd.DataFrame,
    monthly_ic: pd.DataFrame,
    *,
    max_lag: int = 12,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for column in standard_series:
        rows.extend(_diagnostic_rows(column, standard_series[column], max_lag))
    if not monthly_ic.empty:
        for factor, part in monthly_ic.groupby("factor"):
            series = part.set_index("availability_date")["rank_ic"]
            rows.extend(_diagnostic_rows(f"factor_ic:{factor}", series, min(max_lag, 4)))
    return pd.DataFrame(rows)


def build_regime_probabilities(
    standard_series: pd.DataFrame,
    rebalance_dates: pd.DatetimeIndex,
    *,
    n_states: int = 3,
    min_observations: int = 36,
    max_iterations: int = 50,
) -> pd.DataFrame:
    required = ["benchmark_log_return", "realized_volatility_20", "breadth", "log_median_amount"]
    if any(column not in standard_series for column in required):
        return pd.DataFrame()
    source = standard_series[required].dropna().copy()
    if source.empty:
        return pd.DataFrame()
    source["month"] = source.index.to_period("M")
    monthly = source.groupby("month").agg({
        "benchmark_log_return": "sum",
        "realized_volatility_20": "last",
        "breadth": "mean",
        "log_median_amount": "mean",
    })
    dated = source.assign(as_of_date=source.index)
    monthly["as_of_date"] = dated.groupby("month")["as_of_date"].max()
    monthly = monthly.reset_index(drop=True).sort_values("as_of_date")
    rows: list[dict[str, object]] = []
    for as_of_date in pd.DatetimeIndex(pd.to_datetime(rebalance_dates)).sort_values():
        history = monthly[monthly["as_of_date"].le(as_of_date)].copy()
        later_observations = source.index[source.index > as_of_date]
        forecast_target = (
            pd.Timestamp(later_observations.min())
            if len(later_observations)
            else pd.Timestamp(as_of_date) + pd.offsets.BDay(1)
        )
        base = {
            "as_of_date": as_of_date,
            "training_end": history["as_of_date"].max() if not history.empty else pd.NaT,
            "forecast_target": forecast_target,
            "observation_count": int(len(history)),
            "model_version": MODEL_VERSION,
        }
        if len(history) < min_observations:
            rows.append({**base, "status": "insufficient_history"})
            continue
        values = history[required].to_numpy(dtype=float)
        try:
            model = GaussianHMM(n_states=n_states, max_iter=max_iterations).fit(values)
            probabilities = model.filtered_probabilities(values)[-1]
            state_means = model.state_means_original_scale()[:, 0]
            row = {**base, "status": "ok", "log_likelihood": model.log_likelihood_}
            for state in range(n_states):
                row[f"state_{state}_probability"] = float(probabilities[state])
                row[f"state_{state}_mean_return"] = float(state_means[state])
            rows.append(row)
        except (ValueError, FloatingPointError, np.linalg.LinAlgError) as exc:
            rows.append({**base, "status": "fit_failed", "detail": str(exc)})
    return pd.DataFrame(rows)


def _cap_and_normalize(raw: pd.Series, max_weight: float) -> pd.Series:
    positive = raw.clip(lower=0.0).astype(float)
    if positive.sum() <= 0:
        return positive
    max_weight = max(float(max_weight), 1.0 / len(positive))
    weights = positive / positive.sum()
    for _ in range(20):
        excess = (weights - max_weight).clip(lower=0.0)
        if excess.sum() <= 1e-12:
            break
        weights = weights.clip(upper=max_weight)
        room = (max_weight - weights).clip(lower=0.0)
        if room.sum() <= 1e-12:
            break
        weights += excess.sum() * room / room.sum()
    return weights / weights.sum() if weights.sum() > 0 else weights


def build_dynamic_factor_weights(
    monthly_ic: pd.DataFrame,
    rebalance_dates: pd.DatetimeIndex,
    *,
    min_observations: int = 12,
    min_asset_count: int = 30,
    max_factors: int = 10,
    max_factor_weight: float = 0.20,
    max_fdr_q_value: float = 0.05,
    process_variance: float = 0.001,
    observation_variance: float = 0.01,
    turnover_penalty: float = 0.20,
) -> pd.DataFrame:
    if monthly_ic.empty:
        return pd.DataFrame()
    data = monthly_ic.copy()
    data["availability_date"] = pd.to_datetime(data["availability_date"])
    rows: list[dict[str, object]] = []
    previous = pd.Series(dtype=float)
    for test_date in pd.DatetimeIndex(pd.to_datetime(rebalance_dates)).sort_values():
        candidates: list[dict[str, object]] = []
        for factor, part in data[data["availability_date"].lt(test_date)].groupby("factor"):
            eligible_part = part[part["asset_count"].ge(min_asset_count)].sort_values("availability_date")
            history = eligible_part["rank_ic"].dropna()
            if len(history) < min_observations:
                continue
            forecast = kalman_local_level(
                history,
                process_variance=process_variance,
                observation_variance=observation_variance,
            )
            strength = abs(forecast.forecast_mean) / sqrt(max(forecast.forecast_variance, 1e-12))
            inference = newey_west_mean_test(history, max_lag=min(3, len(history) - 1))
            p_value = float(inference["p_value"])
            if not np.isfinite(p_value) and float(history.std(ddof=1)) == 0:
                p_value = 0.0 if abs(float(history.mean())) > 0 else 1.0
            candidates.append({
                "factor": factor,
                "direction": 1.0 if forecast.forecast_mean >= 0 else -1.0,
                "raw_strength": strength,
                "filtered_ic": forecast.filtered_mean,
                "forecast_ic": forecast.forecast_mean,
                "forecast_variance": forecast.forecast_variance,
                "observation_count": forecast.observation_count,
                "p_value": p_value,
                "train_label_end_max": eligible_part["availability_date"].max(),
            })
        if candidates:
            adjusted = benjamini_hochberg(pd.Series([item["p_value"] for item in candidates], dtype=float))
            for item, q_value in zip(candidates, adjusted):
                item["fdr_q_value"] = float(q_value) if pd.notna(q_value) else np.nan
            candidates = [item for item in candidates if pd.notna(item["fdr_q_value"]) and item["fdr_q_value"] <= max_fdr_q_value]
        candidates = sorted(candidates, key=lambda item: float(item["raw_strength"]), reverse=True)[:max_factors]
        if not candidates:
            continue
        raw = pd.Series({str(item["factor"]): float(item["raw_strength"]) for item in candidates})
        weights = _cap_and_normalize(raw, max_factor_weight)
        if not previous.empty and turnover_penalty > 0:
            blended = (1.0 - turnover_penalty) * weights
            blended += turnover_penalty * previous.reindex(weights.index, fill_value=0.0)
            weights = _cap_and_normalize(blended, max_factor_weight)
        previous = weights.copy()
        metadata = {str(item["factor"]): item for item in candidates}
        for factor, weight in weights[weights.gt(0)].items():
            item = metadata.get(str(factor))
            if item is None:
                continue
            rows.append({
                "test_date": test_date,
                "factor": factor,
                "direction": item["direction"],
                "weight": float(weight),
                "filtered_ic": item["filtered_ic"],
                "forecast_ic": item["forecast_ic"],
                "forecast_variance": item["forecast_variance"],
                "observation_count": item["observation_count"],
                "p_value": item["p_value"],
                "fdr_q_value": item["fdr_q_value"],
                "train_label_end_max": item["train_label_end_max"],
                "model_version": MODEL_VERSION,
            })
    return pd.DataFrame(rows)


def build_dynamic_scores(panel: pd.DataFrame, weights: pd.DataFrame) -> pd.DataFrame:
    if weights.empty:
        return pd.DataFrame(columns=["trade_date", "ts_code", "score", "score_source"])
    require_columns(panel, ["trade_date", "ts_code"], "factor_panel")
    data = panel.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"])
    rows: list[pd.DataFrame] = []
    for test_date, date_weights in weights.groupby("test_date"):
        part = data[data["trade_date"].eq(pd.Timestamp(test_date))].copy()
        if part.empty:
            continue
        part["score"] = 0.0
        part["available_weight"] = 0.0
        for _, item in date_weights.iterrows():
            factor = str(item["factor"])
            if factor not in part:
                continue
            available = part[factor].notna()
            signed_weight = float(item["weight"]) * float(item["direction"])
            part.loc[available, "score"] += part.loc[available, factor].astype(float) * signed_weight
            part.loc[available, "available_weight"] += abs(float(item["weight"]))
        valid = part["available_weight"].gt(0)
        part.loc[valid, "score"] /= part.loc[valid, "available_weight"]
        part.loc[~valid, "score"] = np.nan
        part["score_source"] = "time_series_dynamic"
        rows.append(part[["trade_date", "ts_code", "score", "score_source"]])
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(
        columns=["trade_date", "ts_code", "score", "score_source"]
    )


def build_volatility_forecasts(
    benchmark_return: pd.Series | None,
    rebalance_dates: pd.DatetimeIndex,
    *,
    min_observations: int = 60,
) -> pd.DataFrame:
    if benchmark_return is None:
        return pd.DataFrame()
    returns = benchmark_return.dropna().astype(float).sort_index()
    returns.index = pd.to_datetime(returns.index)
    rows: list[dict[str, object]] = []
    for test_date in pd.DatetimeIndex(pd.to_datetime(rebalance_dates)).sort_values():
        history = returns[returns.index <= test_date]
        later_observations = returns.index[returns.index > test_date]
        forecast_target = (
            pd.Timestamp(later_observations.min())
            if len(later_observations)
            else pd.Timestamp(test_date) + pd.offsets.BDay(1)
        )
        base = {
            "as_of_date": test_date,
            "training_end": history.index.max() if len(history) else pd.NaT,
            "forecast_target": forecast_target,
            "observation_count": int(len(history)),
            "model_version": MODEL_VERSION,
        }
        if len(history) < min_observations:
            rows.append({**base, "model": "gjr_garch_1_1", "status": "insufficient_history"})
            continue
        fitted = gjr_garch_forecast(history)
        variance = fitted.get("forecast_variance", np.nan)
        rows.append({
            **base,
            **fitted,
            "annualized_volatility_forecast": sqrt(float(variance) * 252.0) if np.isfinite(variance) else np.nan,
        })
    return pd.DataFrame(rows)


def build_exposure_scalars(
    regime: pd.DataFrame,
    volatility: pd.DataFrame,
    *,
    target_annual_volatility: float = 0.15,
    min_exposure: float = 0.90,
    max_exposure: float = 1.0,
) -> pd.DataFrame:
    dates = sorted(
        date for date in (
            set(pd.to_datetime(regime.get("as_of_date", pd.Series(dtype="datetime64[ns]"))))
            | set(pd.to_datetime(volatility.get("as_of_date", pd.Series(dtype="datetime64[ns]"))))
        ) if pd.notna(date)
    )
    rows: list[dict[str, object]] = []
    for date in dates:
        risk_multiplier = 1.0
        regime_row = regime[regime.get("as_of_date", pd.Series(dtype="datetime64[ns]")).eq(date)]
        if not regime_row.empty and regime_row.iloc[0].get("status") == "ok":
            bear_probability = float(regime_row.iloc[0].get("state_0_probability", 0.0))
            risk_multiplier *= 1.0 - (1.0 - min_exposure) * bear_probability
        vol_row = volatility[volatility.get("as_of_date", pd.Series(dtype="datetime64[ns]")).eq(date)]
        if not vol_row.empty and vol_row.iloc[0].get("status") == "ok":
            forecast = float(vol_row.iloc[0].get("annualized_volatility_forecast", np.nan))
            if np.isfinite(forecast) and forecast > 0:
                risk_multiplier *= min(1.0, target_annual_volatility / forecast)
        rows.append({
            "trade_date": date,
            "exposure_scalar": float(np.clip(risk_multiplier, min_exposure, max_exposure)),
            "model_version": MODEL_VERSION,
        })
    return pd.DataFrame(rows)


def _direction_accuracy(forecast: pd.Series, actual: pd.Series) -> float:
    clean = pd.DataFrame({"forecast": forecast, "actual": actual}).dropna()
    if clean.empty:
        return np.nan
    return float((np.sign(clean["forecast"]) == np.sign(clean["actual"])).mean())


def _rank_correlation_series(forecast: pd.Series, actual: pd.Series) -> float:
    clean = pd.DataFrame({"forecast": forecast, "actual": actual}).dropna()
    if len(clean) < 3:
        return np.nan
    return float(clean["forecast"].rank(method="average").corr(clean["actual"].rank(method="average")))


def build_model_selection_audit(
    forecasts: pd.DataFrame,
    *,
    min_oos_months: int = 36,
) -> pd.DataFrame:
    columns = [
        "target_series", "model", "train_start", "train_end", "observations", "rmse", "mae", "direction_accuracy", "rank_correlation",
        "dm_stat", "dm_p_value", "spa_stat", "spa_p_value", "sample_eligibility", "status",
        "trial_count", "model_version",
    ]
    if forecasts.empty:
        return pd.DataFrame([{
            "target_series": "all", "model": "all", "train_start": pd.NaT, "train_end": pd.NaT,
            "observations": 0, "rmse": np.nan, "mae": np.nan,
            "direction_accuracy": np.nan, "rank_correlation": np.nan,
            "dm_stat": np.nan, "dm_p_value": np.nan, "spa_stat": np.nan, "spa_p_value": np.nan,
            "sample_eligibility": False, "status": "insufficient_history",
            "trial_count": 0, "model_version": MODEL_VERSION,
        }], columns=columns)
    rows: list[dict[str, object]] = []
    for (target_series, model), part in forecasts.groupby(["target_series", "model"]):
        part = part.sort_values("forecast_target")
        target_forecasts = forecasts[forecasts["target_series"].eq(target_series)]
        benchmark = target_forecasts[target_forecasts["model"].eq("historical_mean")].sort_values("forecast_target")
        loss_table = target_forecasts.pivot(index="forecast_target", columns="model", values="squared_error")
        candidate_columns = [column for column in loss_table.columns if column != "historical_mean"]
        spa = superior_predictive_ability_test(
            loss_table[candidate_columns].subtract(loss_table["historical_mean"], axis=0)
            if "historical_mean" in loss_table and candidate_columns else pd.DataFrame()
        )
        count = len(part)
        direction_accuracy = _direction_accuracy(part["forecast"], part["actual"])
        rank_corr = _rank_correlation_series(part["forecast"], part["actual"])
        dm_stat, dm_p_value = np.nan, np.nan
        if model != "historical_mean" and not benchmark.empty:
            aligned = benchmark[["forecast_target", "error"]].merge(
                part[["forecast_target", "error"]], on="forecast_target", suffixes=("_benchmark", "_candidate")
            )
            dm = diebold_mariano_test(aligned["error_benchmark"], aligned["error_candidate"], max_lag=1)
            dm_stat = dm.get("dm_stat")
            dm_p_value = dm.get("p_value")
        eligible = count >= min_oos_months
        rows.append({
            "target_series": target_series,
            "model": model,
            "train_start": pd.to_datetime(part["train_start"]).min(),
            "train_end": pd.to_datetime(part["train_end"]).max(),
            "observations": count,
            "rmse": float(np.sqrt(part["squared_error"].mean())),
            "mae": float(part["absolute_error"].mean()),
            "direction_accuracy": direction_accuracy,
            "rank_correlation": rank_corr,
            "dm_stat": dm_stat,
            "dm_p_value": dm_p_value,
            "spa_stat": spa.get("spa_stat"),
            "spa_p_value": spa.get("spa_p_value"),
            "sample_eligibility": eligible,
            "status": "eligible" if eligible else "insufficient_history",
            "trial_count": int(target_forecasts["model"].nunique()),
            "model_version": MODEL_VERSION,
        })
    return pd.DataFrame(rows, columns=columns)


def _dynamic_covariance(monthly_factor_returns: pd.DataFrame, max_factors: int) -> pd.DataFrame:
    if monthly_factor_returns.empty:
        return pd.DataFrame()
    pivot = monthly_factor_returns.pivot(index="availability_date", columns="factor", values="q5_minus_q1")
    selected = pivot.count().sort_values(ascending=False).head(max_factors).index
    covariance = dcc_covariance(pivot[list(selected)])
    if covariance.empty:
        return pd.DataFrame()
    rows = []
    for left in covariance.index:
        for right in covariance.columns:
            rows.append({
                "as_of_date": pivot.index.max(), "factor_left": left, "factor_right": right,
                "conditional_covariance": float(covariance.loc[left, right]), "model": "dcc_0.02_0.97",
                "model_version": MODEL_VERSION,
            })
    return pd.DataFrame(rows)


def build_time_series_diagnostics_by_origin(
    standard_series: pd.DataFrame,
    rebalance_dates: pd.DatetimeIndex,
    *,
    max_lag: int = 12,
) -> pd.DataFrame:
    """Run ADF/KPSS/ACF/PACF/Ljung-Box/ARCH/Zivot-Andrews at each forecast origin."""

    all_rows: list[dict[str, object]] = []
    dates = pd.DatetimeIndex(pd.to_datetime(rebalance_dates)).sort_values().unique()
    for as_of in dates:
        history = standard_series[standard_series.index <= pd.Timestamp(as_of)]
        if history.empty:
            continue
        for column in history.columns:
            series = history[column]
            for row in _diagnostic_rows(column, series, max_lag):
                row["as_of_date"] = pd.Timestamp(as_of)
                row["training_end"] = series.index.max()
                all_rows.append(row)
    columns = ["as_of_date", "training_end", "series", "test", "statistic", "p_value", "observations", "status", "detail", "model_version"]
    if not all_rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(all_rows, columns=columns)


def _detect_outliers(series: pd.Series, n_mad: float = 5.0) -> dict[str, object]:
    clean = series.dropna().astype(float)
    if len(clean) < 5:
        return {"outlier_count": 0, "outlier_rate": 0.0, "decision": "insufficient_history"}
    median = clean.median()
    mad = (clean - median).abs().median()
    threshold = n_mad * 1.4826 * mad if mad > 0 else np.inf
    outliers = clean[(clean - median).abs() > threshold]
    rate = len(outliers) / len(clean)
    decision = "flag_for_review" if rate > 0.01 else "ok"
    return {"outlier_count": int(len(outliers)), "outlier_rate": float(rate), "decision": decision}


def run_time_series_baselines(
    standard_series: pd.DataFrame,
    monthly_ic: pd.DataFrame,
    rebalance_dates: pd.DatetimeIndex | None = None,
    *,
    config: dict[str, Any] | None = None,
    final_holdout_start: str = "2024-01-01",
) -> dict[str, pd.DataFrame]:
    """Run lag-1, mean, rolling means, EWMA, AR(1), ARIMAX baselines on monthly series.

    Default evaluation window is 2018-2023; any forecast target or label availability
    on or after ``final_holdout_start`` is rejected.
    """

    cfg = config or {}
    evaluation_start = pd.Timestamp(str(cfg.get("evaluation_start", "2018-01-01")))
    evaluation_end = pd.Timestamp(str(cfg.get("evaluation_end", "2023-12-31")))
    holdout = pd.Timestamp(final_holdout_start)
    if evaluation_end >= holdout:
        raise ValueError(f"evaluation_end {evaluation_end.date()} must be before final_holdout_start {holdout.date()}")

    standard = standard_series.copy().sort_index()
    standard.index = pd.to_datetime(standard.index)
    standard = standard.drop(
        columns=["execution_date", "label_end_date", "availability_date"], errors="ignore"
    )
    standard = standard.apply(pd.to_numeric, errors="coerce").dropna(axis=1, how="all")
    standard = standard.loc[standard.index < holdout]

    aggregation = {
        "benchmark_log_return": "sum",
        "realized_volatility_20": "last",
        "breadth": "mean",
        "log_median_amount": "mean",
        "median_turnover_rate": "mean",
        "cross_sectional_dispersion": "mean",
    }
    monthly = standard.resample("ME").agg({k: v for k, v in aggregation.items() if k in standard}).dropna(how="all")
    monthly = monthly.loc[monthly.index <= evaluation_end]

    if not monthly_ic.empty:
        ic_data = monthly_ic.copy()
        ic_data["availability_month"] = pd.to_datetime(ic_data["availability_date"]).dt.to_period("M").dt.to_timestamp("M")
        ic_pivot = ic_data.pivot_table(index="availability_month", columns="factor", values="rank_ic", aggfunc="mean")
    else:
        ic_pivot = pd.DataFrame()
    if not ic_pivot.empty:
        monthly["mean_rank_ic"] = ic_pivot.mean(axis=1).reindex(monthly.index)

    exogenous_candidates = [
        "benchmark_log_return", "realized_volatility_20", "breadth", "log_median_amount"
    ]
    target_series_list = ["benchmark_log_return", "realized_volatility_20", "mean_rank_ic"]
    target_series_list = [name for name in target_series_list if name in monthly]

    forecast_rows: list[pd.DataFrame] = []
    for target_name in target_series_list:
        target = monthly[target_name].dropna()
        if len(target) < 12:
            continue
        exog = monthly[[col for col in exogenous_candidates if col in monthly and col != target_name]]
        forecasts = expanding_forecast_comparison(
            target,
            min_train=int(cfg.get("min_train_observations", 12)),
            ewma_alpha=float(cfg.get("ewma_alpha", 0.20)),
            exogenous=exog if not exog.empty else None,
            target_series=target_name,
            trade_dates=None,
        )
        forecast_rows.append(forecasts)
    forecasts = pd.concat(forecast_rows, ignore_index=True) if forecast_rows else pd.DataFrame(columns=EMPTY_SCHEMAS["forecast_comparison"])

    if not forecasts.empty:
        forecasts = forecasts[
            pd.to_datetime(forecasts["forecast_target"]).between(evaluation_start, evaluation_end)
            & pd.to_datetime(forecasts["forecast_target"]).lt(holdout)
            & pd.to_datetime(forecasts["availability_date"]).lt(holdout)
        ].copy()
        invalid_pit = ~(
            pd.to_datetime(forecasts["train_end"]).lt(pd.to_datetime(forecasts["forecast_target"]))
            & pd.to_datetime(forecasts["forecast_origin"]).lt(pd.to_datetime(forecasts["availability_date"]))
            & forecasts["point_in_time_valid"].fillna(False).astype(bool)
        )
        if invalid_pit.any():
            raise ValueError(f"Forecast timing leakage detected: {forecasts.loc[invalid_pit].head(3).to_dict('records')}")

    diagnostics = build_time_series_diagnostics_by_origin(
        standard,
        rebalance_dates=pd.DatetimeIndex(pd.to_datetime(forecasts["forecast_origin"].unique())) if not forecasts.empty else monthly.index,
        max_lag=int(cfg.get("diagnostics", {}).get("max_lag", 12)),
    )

    audit = build_model_selection_audit(forecasts, min_oos_months=int(cfg.get("min_oos_months", 36)))

    outlier_rows: list[dict[str, object]] = []
    for column in standard.columns:
        info = _detect_outliers(standard[column])
        outlier_rows.append({"series": column, **info})
    outlier_decisions = pd.DataFrame(outlier_rows)

    return {
        "forecast_comparison": forecasts,
        "model_selection_audit": audit,
        "time_series_diagnostics": diagnostics,
        "outlier_decisions": outlier_decisions,
    }


def compare_preregistered_weight_schemes(
    monthly_ic: pd.DataFrame,
    monthly_returns: pd.DataFrame,
    rebalance_dates: pd.DatetimeIndex,
    cost_config: CostConfig | None = None,
) -> pd.DataFrame:
    """Compare static_equal, rolling_ic_12m, rolling_ic_24m, ewma_ic economic results."""

    cfg = cost_config or CostConfig()
    cost_rate = cfg.commission_buy + cfg.commission_sell + cfg.stamp_tax_sell + cfg.slippage + cfg.impact_coef
    ic = monthly_ic.copy()
    ic["signal_date"] = pd.to_datetime(ic["signal_date"])
    ic["availability_date"] = pd.to_datetime(ic["availability_date"])
    rets = monthly_returns.copy()
    rets["signal_date"] = pd.to_datetime(rets["signal_date"])
    rets["availability_date"] = pd.to_datetime(rets["availability_date"])
    returns_pivot = rets.pivot(index="signal_date", columns="factor", values="Q5_minus_Q1_raw")
    turnover_pivot = rets.pivot(index="signal_date", columns="factor", values="turnover")
    dates = pd.DatetimeIndex(pd.to_datetime(rebalance_dates)).sort_values().unique()
    dates = dates[dates.isin(returns_pivot.index)]

    previous_weights: dict[str, pd.Series] = {}
    rows: list[dict[str, object]] = []
    for signal_date in dates:
        eligible_ic_rows = ic[ic["availability_date"].lt(pd.Timestamp(signal_date))]
        available_ic = eligible_ic_rows.pivot_table(
            index="signal_date", columns="factor", values="rank_ic", aggfunc="last"
        ).sort_index()
        available_returns = returns_pivot.loc[signal_date]
        available_turnover = turnover_pivot.loc[signal_date]
        valid_factors = [f for f in available_returns.index if pd.notna(available_returns[f])]
        if len(valid_factors) < 2:
            continue
        schemes: dict[str, pd.Series] = {}
        # static_equal
        schemes["static_equal"] = pd.Series(1.0 / len(valid_factors), index=valid_factors)
        # rolling_ic_12m
        if len(available_ic) >= 6:
            rolling12 = available_ic.tail(12).mean()
            schemes["rolling_ic_12m"] = _ic_to_weights(rolling12.reindex(valid_factors))
        # rolling_ic_24m
        if len(available_ic) >= 12:
            rolling24 = available_ic.tail(24).mean()
            schemes["rolling_ic_24m"] = _ic_to_weights(rolling24.reindex(valid_factors))
        # ewma_ic
        if len(available_ic) >= 6:
            ewma = available_ic.ewm(alpha=0.20, adjust=False).mean().iloc[-1]
            schemes["ewma_ic"] = _ic_to_weights(ewma.reindex(valid_factors))
        for scheme, weights in schemes.items():
            weights = weights.dropna()
            weights = weights / weights.sum() if weights.sum() > 0 else weights
            gross = float((available_returns.reindex(weights.index) * weights).sum())
            weighted_turnover = float((available_turnover.reindex(weights.index) * weights).sum())
            prior = previous_weights.get(scheme, pd.Series(dtype=float))
            if not prior.empty:
                all_factors = prior.index.union(weights.index)
                turnover_from_weights = 1.0 - (prior.reindex(all_factors, fill_value=0.0) * weights.reindex(all_factors, fill_value=0.0)).sum() / (
                    (prior ** 2).sum() ** 0.5 * (weights ** 2).sum() ** 0.5
                ) if (prior ** 2).sum() > 0 and (weights ** 2).sum() > 0 else 0.0
            else:
                turnover_from_weights = 0.0
            turnover = np.nanmean([weighted_turnover, turnover_from_weights]) if np.isfinite(weighted_turnover) else turnover_from_weights
            cost = turnover * cost_rate
            net = gross - cost
            availability = rets.loc[rets["signal_date"].eq(signal_date), "availability_date"]
            rows.append({
                "scheme": scheme,
                "signal_date": pd.Timestamp(signal_date),
                "availability_date": availability.iloc[0] if not availability.empty else pd.NaT,
                "gross_return": gross,
                "cost": cost,
                "net_return": net,
                "turnover": turnover,
            })
            previous_weights[scheme] = weights
    return pd.DataFrame(rows)


def _ic_to_weights(ic_series: pd.Series) -> pd.Series:
    """Convert mean IC values into normalized signed weights."""

    clean = ic_series.dropna()
    if clean.empty:
        return pd.Series(dtype=float)
    weights = clean.abs()
    if weights.sum() <= 0:
        return pd.Series(dtype=float)
    weights = weights / weights.sum()
    return weights * np.sign(clean)


def run_time_series_research(
    panel: pd.DataFrame,
    factor_cols: list[str],
    market: pd.DataFrame,
    benchmark_return: pd.Series | None,
    rebalance_dates: pd.DatetimeIndex,
    return_col: str,
    config: dict[str, Any] | None = None,
) -> TimeSeriesResearchResult:
    cfg = config or {}
    if not bool(cfg.get("enabled", True)):
        empty = {name: pd.DataFrame() for name in OUTPUT_NAMES}
        return TimeSeriesResearchResult(empty, pd.DataFrame(), "disabled")
    monthly_ic, monthly_returns = build_monthly_factor_history(panel, factor_cols, return_col, rebalance_dates)
    standard = build_standard_series(panel, market, benchmark_return)
    diagnostics_cfg = cfg.get("diagnostics", {})
    diagnostics = build_time_series_diagnostics(
        standard, monthly_ic, max_lag=int(diagnostics_cfg.get("max_lag", 12))
    )
    regime_cfg = cfg.get("regime", {})
    regime = build_regime_probabilities(
        standard,
        rebalance_dates,
        n_states=int(regime_cfg.get("states", 3)),
        min_observations=int(regime_cfg.get("min_observations", 36)),
        max_iterations=int(regime_cfg.get("max_iterations", 50)),
    )
    weight_cfg = cfg.get("dynamic_weights", {})
    weights = build_dynamic_factor_weights(
        monthly_ic,
        rebalance_dates,
        min_observations=int(weight_cfg.get("min_observations", 12)),
        min_asset_count=int(weight_cfg.get("min_asset_count", 30)),
        max_factors=int(weight_cfg.get("max_factors", 10)),
        max_factor_weight=float(weight_cfg.get("max_factor_weight", 0.20)),
        max_fdr_q_value=float(weight_cfg.get("max_fdr_q_value", 0.05)),
        process_variance=float(weight_cfg.get("process_variance", 0.001)),
        observation_variance=float(weight_cfg.get("observation_variance", 0.01)),
        turnover_penalty=float(weight_cfg.get("turnover_penalty", 0.20)),
    )
    dynamic_scores = build_dynamic_scores(panel, weights)
    volatility_cfg = cfg.get("volatility", {})
    volatility = build_volatility_forecasts(
        benchmark_return,
        rebalance_dates,
        min_observations=int(volatility_cfg.get("min_observations", 60)),
    )
    forecast_cfg = cfg.get("forecast", {})
    forecast_series = standard.get("realized_volatility_20", pd.Series(dtype=float))
    monthly_forecast_series = forecast_series.resample("ME").last().dropna() if not forecast_series.empty else pd.Series(dtype=float)
    exogenous_columns = [column for column in ["breadth", "log_median_amount"] if column in standard]
    monthly_exogenous = (
        standard[exogenous_columns].resample("ME").mean().reindex(monthly_forecast_series.index)
        if exogenous_columns else None
    )
    forecasts = expanding_forecast_comparison(
        monthly_forecast_series,
        min_train=int(forecast_cfg.get("min_train_observations", 12)),
        ewma_alpha=float(forecast_cfg.get("ewma_alpha", 0.20)),
        exogenous=monthly_exogenous,
    )
    audit = build_model_selection_audit(forecasts, min_oos_months=int(cfg.get("min_oos_months", 36)))
    exposure = build_exposure_scalars(
        regime,
        volatility,
        target_annual_volatility=float(volatility_cfg.get("target_annual_volatility", 0.15)),
        min_exposure=float(volatility_cfg.get("min_exposure", 0.90)),
        max_exposure=float(volatility_cfg.get("max_exposure", 1.0)),
    )
    covariance = _dynamic_covariance(monthly_returns, int(weight_cfg.get("max_factors", 10)))
    frames = {
        "time_series_diagnostics": diagnostics,
        "regime_probabilities": regime,
        "dynamic_factor_weights": weights,
        "volatility_forecasts": volatility,
        "forecast_comparison": forecasts,
        "model_selection_audit": audit,
        "monthly_factor_ic": monthly_ic,
        "monthly_factor_returns": monthly_returns,
        "dynamic_covariance": covariance,
        "exposure_scalars": exposure,
    }
    for name, columns in EMPTY_SCHEMAS.items():
        if name not in frames:
            continue
        if frames[name].empty and len(frames[name].columns) == 0:
            frames[name] = pd.DataFrame(columns=columns)
    status = "dynamic_ready" if not dynamic_scores.empty else "insufficient_history"
    return TimeSeriesResearchResult(frames, dynamic_scores, status)
