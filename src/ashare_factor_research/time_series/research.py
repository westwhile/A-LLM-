from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Any

import numpy as np
import pandas as pd

from ashare_factor_research.factor_testing.inference import benjamini_hochberg, newey_west_mean_test
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
    "forecast_comparison": ["training_end", "forecast_target", "model", "forecast", "actual", "error", "squared_error", "absolute_error", "model_version"],
    "monthly_factor_ic": ["signal_date", "availability_date", "factor", "asset_count", "rank_ic"],
    "monthly_factor_returns": ["signal_date", "availability_date", "factor", "asset_count", "q5_minus_q1"],
    "dynamic_covariance": ["as_of_date", "factor_left", "factor_right", "conditional_covariance", "model", "model_version"],
    "exposure_scalars": ["trade_date", "exposure_scalar", "model_version"],
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


def build_monthly_factor_history(
    panel: pd.DataFrame,
    factor_cols: list[str],
    return_col: str,
    rebalance_dates: pd.DatetimeIndex,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build non-overlapping factor IC and Q5-Q1 histories with label availability dates."""

    require_columns(panel, ["trade_date", "target_return_end_date", return_col, *factor_cols], "factor_panel")
    data = panel.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"])
    data["target_return_end_date"] = pd.to_datetime(data["target_return_end_date"])
    requested = set(pd.to_datetime(rebalance_dates))
    data = data[data["trade_date"].isin(requested)]
    ic_rows: list[dict[str, object]] = []
    return_rows: list[dict[str, object]] = []
    for signal_date, part in data.groupby("trade_date"):
        availability = part["target_return_end_date"].dropna().max()
        if pd.isna(availability):
            continue
        for factor in factor_cols:
            rank_ic = _rank_correlation(part, factor, return_col)
            use = part[[factor, return_col]].dropna().copy()
            spread = np.nan
            if len(use) >= 10:
                try:
                    use["bucket"] = pd.qcut(use[factor].rank(method="first"), 5, labels=False)
                    bucket_return = use.groupby("bucket", observed=True)[return_col].mean()
                    if 0 in bucket_return.index and 4 in bucket_return.index:
                        spread = float(bucket_return.loc[4] - bucket_return.loc[0])
                except ValueError:
                    spread = np.nan
            base = {
                "signal_date": pd.Timestamp(signal_date),
                "availability_date": pd.Timestamp(availability),
                "factor": factor,
                "asset_count": int(len(use)),
            }
            ic_rows.append({**base, "rank_ic": rank_ic})
            return_rows.append({**base, "q5_minus_q1": spread})
    return pd.DataFrame(ic_rows), pd.DataFrame(return_rows)


def build_standard_series(
    panel: pd.DataFrame,
    market: pd.DataFrame,
    benchmark_return: pd.Series | None,
) -> pd.DataFrame:
    """Create stationary or economically interpretable daily research series."""

    require_columns(panel, ["trade_date", "return_1d"], "factor_panel")
    data = panel.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"])
    daily = data.groupby("trade_date")["return_1d"].agg(
        breadth=lambda values: float((values > 0).mean()),
        cross_sectional_volatility=lambda values: float(values.std(ddof=1)),
    )
    market_data = market.copy()
    market_data["trade_date"] = pd.to_datetime(market_data["trade_date"])
    if "amount" in market_data:
        liquidity = market_data.groupby("trade_date")["amount"].median().replace(0.0, np.nan)
        daily["log_median_amount"] = np.log(liquidity)
    if benchmark_return is not None:
        benchmark = benchmark_return.copy().astype(float)
        benchmark.index = pd.to_datetime(benchmark.index)
        daily["benchmark_log_return"] = np.log1p(benchmark.reindex(daily.index).clip(lower=-0.999999))
        daily["realized_volatility_20"] = (
            daily["benchmark_log_return"].rolling(20, min_periods=10).std(ddof=1) * sqrt(252.0)
        )
    return daily.sort_index()


def _diagnostic_rows(series_name: str, series: pd.Series, max_lag: int) -> list[dict[str, object]]:
    clean = series.dropna().astype(float)
    rows: list[dict[str, object]] = [{
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


def build_model_selection_audit(
    forecasts: pd.DataFrame,
    *,
    min_oos_months: int = 36,
) -> pd.DataFrame:
    columns = ["model", "observations", "rmse", "mae", "dm_stat", "dm_p_value", "spa_stat", "spa_p_value", "status", "trial_count", "model_version"]
    if forecasts.empty:
        return pd.DataFrame([{
            "model": "all", "observations": 0, "rmse": np.nan, "mae": np.nan,
            "dm_stat": np.nan, "dm_p_value": np.nan, "spa_stat": np.nan, "spa_p_value": np.nan,
            "status": "insufficient_history",
            "trial_count": 0, "model_version": MODEL_VERSION,
        }], columns=columns)
    rows: list[dict[str, object]] = []
    benchmark = forecasts[forecasts["model"].eq("historical_mean")].sort_values("forecast_target")
    loss_table = forecasts.pivot(index="forecast_target", columns="model", values="squared_error")
    candidate_columns = [column for column in loss_table.columns if column != "historical_mean"]
    spa = superior_predictive_ability_test(
        loss_table[candidate_columns].subtract(loss_table["historical_mean"], axis=0)
        if "historical_mean" in loss_table and candidate_columns else pd.DataFrame()
    )
    for model, part in forecasts.groupby("model"):
        part = part.sort_values("forecast_target")
        aligned = benchmark[["forecast_target", "error"]].merge(
            part[["forecast_target", "error"]], on="forecast_target", suffixes=("_benchmark", "_candidate")
        )
        dm = diebold_mariano_test(aligned["error_benchmark"], aligned["error_candidate"], max_lag=1)
        count = len(part)
        rows.append({
            "model": model,
            "observations": count,
            "rmse": float(np.sqrt(part["squared_error"].mean())),
            "mae": float(part["absolute_error"].mean()),
            "dm_stat": dm.get("dm_stat"),
            "dm_p_value": dm.get("p_value"),
            "spa_stat": spa.get("spa_stat"),
            "spa_p_value": spa.get("p_value"),
            "status": "eligible" if count >= min_oos_months else "insufficient_history",
            "trial_count": int(forecasts["model"].nunique()),
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
        if frames[name].empty and len(frames[name].columns) == 0:
            frames[name] = pd.DataFrame(columns=columns)
    status = "dynamic_ready" if not dynamic_scores.empty else "insufficient_history"
    return TimeSeriesResearchResult(frames, dynamic_scores, status)
