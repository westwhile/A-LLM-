"""Strict point-in-time implementation for research stages 4--6.

The functions in this module deliberately separate candidate generation from
model eligibility.  Candidate artifacts may be written with short histories,
but ``dynamic_ready`` is impossible until the non-overlapping OOS gate passes.
"""

from __future__ import annotations

from itertools import product
from math import sqrt
import warnings
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import chi2

from ashare_factor_research.factor_testing.inference import benjamini_hochberg, newey_west_mean_test
from ashare_factor_research.time_series.models import GaussianHMM, MODEL_VERSION, kalman_local_level


KALMAN_Q_GRID = (0.0001, 0.001, 0.01)
KALMAN_R_GRID = (0.005, 0.01, 0.02)
TURNOVER_GRID = (0.0, 0.2, 0.5)
VOLATILITY_MODELS = ("historical_20", "historical_60", "ewma", "garch", "gjr_garch", "egarch")

SCHEMAS: dict[str, list[str]] = {
    "kalman_trial_registry": ["trial_id", "process_variance", "observation_variance", "turnover_penalty", "status", "prediction_count", "model_version"],
    "factor_ic_forecasts": ["test_date", "factor", "trial_id", "process_variance", "observation_variance", "turnover_penalty", "forecast_ic", "filtered_ic", "forecast_variance", "p_value", "fdr_q_value", "coverage", "observation_count", "train_label_end_max", "actual_ic", "model_version"],
    "dynamic_factor_weights": ["test_date", "factor", "trial_id", "direction", "weight", "filtered_ic", "forecast_ic", "forecast_variance", "p_value", "fdr_q_value", "coverage", "observation_count", "train_label_end_max", "model_version"],
    "factor_weight_turnover": ["test_date", "trial_id", "turnover", "identity_l1", "model_version"],
    "factor_weight_stability": ["test_date", "trial_id", "factor_count", "max_weight", "effective_factor_count", "weight_hhi", "model_version"],
    "factor_timing_comparison": ["scheme", "trial_id", "prediction_count", "rmse", "mae", "direction_accuracy", "oos_months", "sample_eligibility", "status", "model_version"],
    "regime_probabilities": ["as_of_date", "training_end", "forecast_target", "model", "state_count", "observation_count", "status", "bear_probability", "neutral_probability", "bull_probability", "log_likelihood", "seed", "model_version"],
    "regime_transition_matrix": ["as_of_date", "model", "from_state", "to_state", "probability", "model_version"],
    "regime_durations": ["as_of_date", "model", "state", "expected_duration", "model_version"],
    "regime_factor_performance": ["as_of_date", "model", "state", "factor", "mean_return", "observation_count", "model_version"],
    "regime_stability": ["as_of_date", "model", "previous_as_of_date", "probability_l1_change", "label_signature", "model_version"],
    "volatility_forecasts": ["as_of_date", "training_end", "forecast_target", "model", "status", "observation_count", "forecast_variance", "annualized_volatility_forecast", "actual_squared_return", "error", "absolute_error", "qlike", "arch_lm_p_value", "extreme_observation", "detail", "model_version"],
    "volatility_model_comparison": ["model", "prediction_count", "rmse", "mae", "mean_qlike", "residual_arch_rejection_rate", "extreme_period_mae", "volatility_target_bias", "status", "model_version"],
    "model_warnings": ["module", "as_of_date", "model", "warning_category", "message", "model_version"],
    "dynamic_covariance": ["as_of_date", "factor_left", "factor_right", "conditional_covariance", "model", "min_eigenvalue", "parameter_stable", "model_version"],
    "dcc_risk_contributions": ["as_of_date", "factor", "risk_contribution", "risk_contribution_fraction", "model", "model_version"],
    "stage46_status": ["module", "status", "sample_eligibility", "oos_months", "data_mode", "synthetic_engineering_only", "detail", "model_version"],
}


def _empty(name: str) -> pd.DataFrame:
    return pd.DataFrame(columns=SCHEMAS[name])


def kalman_trial_registry() -> pd.DataFrame:
    rows = []
    for index, (q, r, penalty) in enumerate(product(KALMAN_Q_GRID, KALMAN_R_GRID, TURNOVER_GRID), start=1):
        rows.append({
            "trial_id": f"FT-KALMAN-{index:03d}",
            "process_variance": q,
            "observation_variance": r,
            "turnover_penalty": penalty,
            "status": "preregistered",
            "prediction_count": 0,
            "model_version": MODEL_VERSION,
        })
    return pd.DataFrame(rows, columns=SCHEMAS["kalman_trial_registry"])


def validate_kalman_registry(registry: pd.DataFrame) -> None:
    required = {"experiment_id", "module", "model", "parameters", "status"}
    missing = required - set(registry.columns)
    if missing:
        raise ValueError(f"experiment registry missing columns: {sorted(missing)}")
    rows = registry[
        registry["module"].eq("factor_timing")
        & registry["model"].eq("kalman_local_level_grid")
        & registry["status"].eq("preregistered")
    ]
    observed: set[tuple[float, float, float]] = set()
    import json
    for _, row in rows.iterrows():
        try:
            params = json.loads(str(row["parameters"]))
            observed.add((float(params["process_variance"]), float(params["observation_variance"]), float(params["turnover_penalty"])))
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError(f"invalid Kalman registry parameters for {row['experiment_id']}: {exc}") from exc
    expected = set(product(KALMAN_Q_GRID, KALMAN_R_GRID, TURNOVER_GRID))
    if observed != expected or len(rows) != 27:
        raise ValueError(f"Kalman registry grid mismatch: expected 27 exact trials, found {len(rows)}")


def _normalize_ic(monthly_ic: pd.DataFrame) -> pd.DataFrame:
    required = {"signal_date", "availability_date", "factor", "rank_ic"}
    missing = required - set(monthly_ic.columns)
    if missing:
        raise ValueError(f"monthly IC missing columns: {sorted(missing)}")
    data = monthly_ic.copy()
    data["signal_date"] = pd.to_datetime(data["signal_date"])
    data["availability_date"] = pd.to_datetime(data["availability_date"])
    if "asset_count" not in data:
        data["asset_count"] = data.get("valid_stock_count", 0)
    if "coverage" not in data:
        denominator = pd.to_numeric(data.get("universe_denominator", np.nan), errors="coerce")
        data["coverage"] = pd.to_numeric(data["asset_count"], errors="coerce") / denominator
        data["coverage"] = data["coverage"].where(np.isfinite(data["coverage"]), 1.0)
    return data.sort_values(["availability_date", "factor"])


def _cap_weights(raw: pd.Series, cap: float) -> pd.Series:
    raw = raw.clip(lower=0.0).replace([np.inf, -np.inf], np.nan).dropna()
    if raw.empty or raw.sum() <= 0:
        return pd.Series(dtype=float)
    if cap * len(raw) < 1.0 - 1e-12:
        raise ValueError("max_factor_weight is infeasible for selected factor count")
    weights = raw / raw.sum()
    for _ in range(100):
        over = weights > cap + 1e-12
        if not over.any():
            break
        fixed = weights.where(over, 0.0).clip(upper=cap)
        free = ~over
        remaining = 1.0 - float(fixed.sum())
        if not free.any() or remaining < -1e-12:
            break
        free_raw = raw.where(free, 0.0)
        weights = fixed + (remaining * free_raw / free_raw.sum() if free_raw.sum() > 0 else 0.0)
    return weights / weights.sum()


def _trial_id(q: float, r: float, penalty: float) -> str:
    combinations = list(product(KALMAN_Q_GRID, KALMAN_R_GRID, TURNOVER_GRID))
    return f"FT-KALMAN-{combinations.index((q, r, penalty)) + 1:03d}"


def run_kalman_stage(
    monthly_ic: pd.DataFrame,
    rebalance_dates: pd.DatetimeIndex,
    *,
    config: dict[str, Any] | None = None,
    min_oos_months: int = 36,
) -> dict[str, pd.DataFrame]:
    cfg = config or {}
    if monthly_ic.empty:
        return {name: _empty(name) for name in (
            "kalman_trial_registry", "factor_ic_forecasts", "dynamic_factor_weights",
            "factor_weight_turnover", "factor_weight_stability", "factor_timing_comparison",
        )}
    data = _normalize_ic(monthly_ic)
    dates = pd.DatetimeIndex(pd.to_datetime(rebalance_dates)).sort_values().unique()
    min_obs = int(cfg.get("min_observations", 12))
    min_assets = int(cfg.get("min_asset_count", 30))
    min_coverage = float(cfg.get("min_coverage", 0.30))
    max_factors = int(cfg.get("max_factors", 10))
    cap = float(cfg.get("max_factor_weight", 0.20))
    max_q = float(cfg.get("max_fdr_q_value", 0.05))
    forecast_rows: list[dict[str, Any]] = []
    weight_rows: list[dict[str, Any]] = []
    turnover_rows: list[dict[str, Any]] = []
    stability_rows: list[dict[str, Any]] = []
    previous: dict[str, pd.Series] = {}

    for test_date in dates:
        eligible = data[data["availability_date"].lt(test_date)]
        actual_map = data[data["signal_date"].eq(test_date)].set_index("factor")["rank_ic"].to_dict()
        base_candidates: dict[tuple[float, float], list[dict[str, Any]]] = {}
        for q, r in product(KALMAN_Q_GRID, KALMAN_R_GRID):
            candidates: list[dict[str, Any]] = []
            for factor, part in eligible.groupby("factor"):
                history_part = part[
                    pd.to_numeric(part["asset_count"], errors="coerce").ge(min_assets)
                    & pd.to_numeric(part["coverage"], errors="coerce").ge(min_coverage)
                ].dropna(subset=["rank_ic"]).sort_values("availability_date")
                if len(history_part) < min_obs:
                    continue
                history = history_part["rank_ic"].astype(float)
                result = kalman_local_level(history, process_variance=q, observation_variance=r)
                inference = newey_west_mean_test(history, max_lag=min(3, len(history) - 1))
                p_value = float(inference["p_value"])
                if not np.isfinite(p_value):
                    p_value = 0.0 if history.std(ddof=1) == 0 and abs(history.mean()) > 0 else 1.0
                candidates.append({
                    "factor": str(factor), "filtered_ic": result.filtered_mean,
                    "forecast_ic": result.forecast_mean, "forecast_variance": result.forecast_variance,
                    "p_value": p_value, "coverage": float(history_part["coverage"].iloc[-1]),
                    "observation_count": result.observation_count,
                    "train_label_end_max": history_part["availability_date"].max(),
                    "actual_ic": actual_map.get(factor, np.nan),
                })
            if candidates:
                adjusted = benjamini_hochberg(pd.Series([row["p_value"] for row in candidates], dtype=float))
                for row, value in zip(candidates, adjusted):
                    row["fdr_q_value"] = float(value) if pd.notna(value) else np.nan
            base_candidates[(q, r)] = candidates

        for q, r, penalty in product(KALMAN_Q_GRID, KALMAN_R_GRID, TURNOVER_GRID):
            trial = _trial_id(q, r, penalty)
            candidates = base_candidates[(q, r)]
            for item in candidates:
                forecast_rows.append({
                    "test_date": test_date, "trial_id": trial, "process_variance": q,
                    "observation_variance": r, "turnover_penalty": penalty, **item,
                    "model_version": MODEL_VERSION,
                })
            selected = [item for item in candidates if np.isfinite(item.get("fdr_q_value", np.nan)) and item["fdr_q_value"] <= max_q]
            selected.sort(key=lambda item: abs(item["forecast_ic"]) / sqrt(max(item["forecast_variance"], 1e-12)), reverse=True)
            selected = selected[:max_factors]
            if len(selected) < max(1, int(np.ceil(1.0 / cap))):
                continue
            raw = pd.Series({item["factor"]: abs(item["forecast_ic"]) * item["coverage"] / sqrt(max(item["forecast_variance"], 1e-12)) for item in selected})
            weights = _cap_weights(raw, cap)
            prior = previous.get(trial, pd.Series(dtype=float))
            if not prior.empty and penalty > 0:
                universe = weights.index.union(prior.index)
                blended = (1.0 - penalty) * weights.reindex(universe, fill_value=0.0) + penalty * prior.reindex(universe, fill_value=0.0)
                positive = blended[blended.gt(0)]
                if len(positive) >= int(np.ceil(1.0 / cap)):
                    weights = _cap_weights(positive, cap)
            universe = weights.index.union(prior.index)
            identity = 0.5 * float((weights.reindex(universe, fill_value=0.0) - prior.reindex(universe, fill_value=0.0)).abs().sum()) if not prior.empty else 0.0
            previous[trial] = weights.copy()
            lookup = {item["factor"]: item for item in selected}
            for factor, weight in weights.items():
                item = lookup[factor]
                weight_rows.append({
                    "test_date": test_date, "factor": factor, "trial_id": trial,
                    "direction": 1.0 if item["forecast_ic"] >= 0 else -1.0, "weight": float(weight),
                    **{key: item[key] for key in ("filtered_ic", "forecast_ic", "forecast_variance", "p_value", "fdr_q_value", "coverage", "observation_count", "train_label_end_max")},
                    "model_version": MODEL_VERSION,
                })
            turnover_rows.append({"test_date": test_date, "trial_id": trial, "turnover": identity, "identity_l1": identity, "model_version": MODEL_VERSION})
            hhi = float((weights ** 2).sum())
            stability_rows.append({
                "test_date": test_date, "trial_id": trial, "factor_count": len(weights),
                "max_weight": float(weights.max()), "effective_factor_count": 1.0 / hhi if hhi > 0 else np.nan,
                "weight_hhi": hhi, "model_version": MODEL_VERSION,
            })

    forecasts = pd.DataFrame(forecast_rows, columns=SCHEMAS["factor_ic_forecasts"])
    weights = pd.DataFrame(weight_rows, columns=SCHEMAS["dynamic_factor_weights"])
    registry = kalman_trial_registry()
    counts = forecasts.groupby("trial_id").size() if not forecasts.empty else pd.Series(dtype=int)
    registry["prediction_count"] = registry["trial_id"].map(counts).fillna(0).astype(int)
    registry["status"] = np.where(registry["prediction_count"].gt(0), "complete", "insufficient_history")

    comparisons: list[dict[str, Any]] = []
    if not forecasts.empty:
        for trial, part in forecasts.dropna(subset=["actual_ic"]).groupby("trial_id"):
            error = part["actual_ic"] - part["forecast_ic"]
            oos = int(part["test_date"].nunique())
            comparisons.append({
                "scheme": "kalman_local_level", "trial_id": trial, "prediction_count": len(part),
                "rmse": sqrt(float(np.mean(error ** 2))), "mae": float(np.mean(abs(error))),
                "direction_accuracy": float((np.sign(part["actual_ic"]) == np.sign(part["forecast_ic"])).mean()),
                "oos_months": oos, "sample_eligibility": oos >= min_oos_months,
                "status": "eligible" if oos >= min_oos_months else "insufficient_history", "model_version": MODEL_VERSION,
            })
    # Training-only benchmark forecasts are generated independently at every origin.
    for scheme, window in (("static_equal", None), ("rolling_ic_12m", 12), ("rolling_ic_24m", 24), ("ewma_ic", None)):
        prediction_rows = []
        for test_date in dates:
            eligible = data[data["availability_date"].lt(test_date)]
            actual = data[data["signal_date"].eq(test_date)].set_index("factor")["rank_ic"]
            for factor, part in eligible.groupby("factor"):
                series = part.dropna(subset=["rank_ic"]).sort_values("availability_date")["rank_ic"].astype(float)
                if series.empty or factor not in actual:
                    continue
                if scheme == "static_equal": pred = 0.0
                elif scheme == "ewma_ic": pred = float(series.ewm(alpha=0.20, adjust=False).mean().iloc[-1])
                else:
                    if len(series) < min(window or 1, min_obs): continue
                    pred = float(series.tail(window).mean())
                prediction_rows.append((test_date, float(actual[factor]), pred))
        if prediction_rows:
            frame = pd.DataFrame(prediction_rows, columns=["date", "actual", "forecast"])
            error = frame["actual"] - frame["forecast"]
            oos = int(frame["date"].nunique())
            comparisons.append({
                "scheme": scheme, "trial_id": "", "prediction_count": len(frame),
                "rmse": sqrt(float(np.mean(error ** 2))), "mae": float(np.mean(abs(error))),
                "direction_accuracy": float((np.sign(frame["actual"]) == np.sign(frame["forecast"])).mean()),
                "oos_months": oos, "sample_eligibility": oos >= min_oos_months,
                "status": "eligible" if oos >= min_oos_months else "insufficient_history", "model_version": MODEL_VERSION,
            })
    return {
        "kalman_trial_registry": registry,
        "factor_ic_forecasts": forecasts,
        "dynamic_factor_weights": weights,
        "factor_weight_turnover": pd.DataFrame(turnover_rows, columns=SCHEMAS["factor_weight_turnover"]),
        "factor_weight_stability": pd.DataFrame(stability_rows, columns=SCHEMAS["factor_weight_stability"]),
        "factor_timing_comparison": pd.DataFrame(comparisons, columns=SCHEMAS["factor_timing_comparison"]),
    }


def _normalize_state_variables(state_variables: pd.DataFrame) -> pd.DataFrame:
    required = ["benchmark_log_return", "realized_volatility_20", "breadth", "log_median_amount"]
    data = state_variables.copy()
    if "signal_date" in data:
        data["signal_date"] = pd.to_datetime(data["signal_date"])
    else:
        data["signal_date"] = pd.to_datetime(data.index)
    if "availability_date" in data:
        data["availability_date"] = pd.to_datetime(data["availability_date"])
    else:
        data["availability_date"] = data["signal_date"]
    missing = [column for column in required if column not in data]
    if missing:
        raise ValueError(f"state variables missing columns: {missing}")
    data = data.dropna(subset=required).sort_values("availability_date")
    if not data.empty and data["signal_date"].dt.to_period("M").duplicated().any():
        data["month"] = data["signal_date"].dt.to_period("M")
        data = data.groupby("month", as_index=False).agg({
            "signal_date": "max", "availability_date": "max",
            "benchmark_log_return": "sum", "realized_volatility_20": "last",
            "breadth": "mean", "log_median_amount": "mean",
        })
    return data.sort_values("availability_date")


def _fit_hmm_multistart(values: np.ndarray, states: int, max_iter: int, seeds: tuple[int, ...]) -> tuple[GaussianHMM, int]:
    fitted: list[tuple[float, int, GaussianHMM]] = []
    for seed in seeds:
        try:
            model = GaussianHMM(
                n_states=states, max_iter=max_iter, tolerance=1e-5, random_state=seed
            ).fit(values)
            if np.isfinite(model.log_likelihood_):
                fitted.append((float(model.log_likelihood_), seed, model))
        except (ValueError, FloatingPointError, np.linalg.LinAlgError):
            continue
    if not fitted:
        raise ValueError("all deterministic HMM initializations failed")
    _, seed, model = max(fitted, key=lambda item: item[0])
    return model, seed


def _hmm_label_order(state_means: np.ndarray) -> tuple[list[int], dict[int, str], str]:
    # Column contract: return, volatility, breadth, liquidity width proxy.
    across_state_scale = np.std(state_means, axis=0)
    across_state_scale = np.where(across_state_scale > 1e-12, across_state_scale, 1.0)
    z = (state_means - np.mean(state_means, axis=0)) / across_state_scale
    stress = -z[:, 0] + z[:, 1] - z[:, 2]
    order = list(np.argsort(stress)[::-1])
    if len(order) == 2:
        labels = {order[0]: "bear", order[1]: "bull"}
    else:
        labels = {order[0]: "bear", order[-1]: "bull"}
        for state in order[1:-1]:
            labels[state] = "neutral"
    signature = "|".join(f"{state}:{labels[state]}" for state in range(len(order)))
    return order, labels, signature


def run_hmm_stage(
    state_variables: pd.DataFrame,
    rebalance_dates: pd.DatetimeIndex,
    monthly_factor_returns: pd.DataFrame | None = None,
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, pd.DataFrame]:
    cfg = config or {}
    if state_variables.empty:
        return {name: _empty(name) for name in (
            "regime_probabilities", "regime_transition_matrix", "regime_durations",
            "regime_factor_performance", "regime_stability",
        )}
    data = _normalize_state_variables(state_variables)
    features = ["benchmark_log_return", "realized_volatility_20", "breadth", "log_median_amount"]
    dates = pd.DatetimeIndex(pd.to_datetime(rebalance_dates)).sort_values().unique()
    state_counts = tuple(int(value) for value in cfg.get("state_counts", (2, 3)))
    seeds = tuple(int(value) for value in cfg.get("initialization_seeds", (17, 29, 43)))
    min_obs = int(cfg.get("min_observations", 36))
    max_iter = int(cfg.get("max_iterations", 50))
    probabilities: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []
    durations: list[dict[str, Any]] = []
    performance: list[dict[str, Any]] = []
    stability: list[dict[str, Any]] = []
    previous: dict[str, tuple[pd.Timestamp, np.ndarray, str]] = {}
    factor_returns = monthly_factor_returns.copy() if monthly_factor_returns is not None else pd.DataFrame()
    if not factor_returns.empty:
        factor_returns["signal_date"] = pd.to_datetime(factor_returns["signal_date"])
        factor_returns["availability_date"] = pd.to_datetime(factor_returns["availability_date"])
        return_column = next((name for name in ("q5_minus_q1", "Q5_minus_Q1_raw", "net_return") if name in factor_returns), None)
    else:
        return_column = None

    for as_of in dates:
        history = data[data["availability_date"].lt(as_of)].copy()
        later = data.loc[data["availability_date"].ge(as_of), "availability_date"]
        target = pd.Timestamp(later.min()) if not later.empty else pd.Timestamp(as_of) + pd.offsets.MonthEnd(1)
        for states in state_counts:
            model_name = f"hmm_{states}_state"
            base = {
                "as_of_date": as_of, "training_end": history["availability_date"].max() if not history.empty else pd.NaT,
                "forecast_target": target, "model": model_name, "state_count": states,
                "observation_count": len(history), "bear_probability": np.nan,
                "neutral_probability": np.nan, "bull_probability": np.nan,
                "log_likelihood": np.nan, "seed": np.nan, "model_version": MODEL_VERSION,
            }
            if len(history) < max(min_obs, states * 3):
                probabilities.append({**base, "status": "insufficient_history"})
                continue
            try:
                values = history[features].to_numpy(dtype=float)
                model, seed = _fit_hmm_multistart(values, states, max_iter, seeds)
                filtered = model.filtered_probabilities(values)
                state_means = model.state_means_original_scale()
                _, labels, signature = _hmm_label_order(state_means)
                latest = filtered[-1]
                label_probs = {"bear": 0.0, "neutral": 0.0, "bull": 0.0}
                for state, probability in enumerate(latest):
                    label_probs[labels[state]] += float(probability)
                probabilities.append({
                    **base, "status": "ok", "bear_probability": label_probs["bear"],
                    "neutral_probability": label_probs["neutral"], "bull_probability": label_probs["bull"],
                    "log_likelihood": model.log_likelihood_, "seed": seed,
                })
                assert model.transition_ is not None
                for from_state in range(states):
                    for to_state in range(states):
                        transitions.append({
                            "as_of_date": as_of, "model": model_name, "from_state": labels[from_state],
                            "to_state": labels[to_state], "probability": float(model.transition_[from_state, to_state]),
                            "model_version": MODEL_VERSION,
                        })
                    diagonal = float(model.transition_[from_state, from_state])
                    durations.append({
                        "as_of_date": as_of, "model": model_name, "state": labels[from_state],
                        "expected_duration": 1.0 / max(1.0 - diagonal, 1e-8), "model_version": MODEL_VERSION,
                    })
                prior = previous.get(model_name)
                if prior is not None:
                    previous_date, previous_probs, previous_signature = prior
                    stability.append({
                        "as_of_date": as_of, "model": model_name, "previous_as_of_date": previous_date,
                        "probability_l1_change": float(np.abs(latest - previous_probs).sum()) if len(latest) == len(previous_probs) else np.nan,
                        "label_signature": f"{previous_signature}->{signature}", "model_version": MODEL_VERSION,
                    })
                previous[model_name] = (pd.Timestamp(as_of), latest.copy(), signature)
                if return_column is not None:
                    assigned = history[["signal_date"]].copy()
                    assigned["state"] = [labels[int(index)] for index in np.argmax(filtered, axis=1)]
                    eligible_returns = factor_returns[factor_returns["availability_date"].lt(as_of)]
                    joined = eligible_returns.merge(assigned, on="signal_date", how="inner")
                    for (state, factor), part in joined.groupby(["state", "factor"]):
                        clean = pd.to_numeric(part[return_column], errors="coerce").dropna()
                        performance.append({
                            "as_of_date": as_of, "model": model_name, "state": state, "factor": factor,
                            "mean_return": float(clean.mean()) if len(clean) else np.nan,
                            "observation_count": len(clean), "model_version": MODEL_VERSION,
                        })
            except (ValueError, FloatingPointError, np.linalg.LinAlgError) as exc:
                probabilities.append({**base, "status": "fit_failed", "detail": str(exc)})
    return {
        "regime_probabilities": pd.DataFrame(probabilities).reindex(columns=SCHEMAS["regime_probabilities"]),
        "regime_transition_matrix": pd.DataFrame(transitions, columns=SCHEMAS["regime_transition_matrix"]),
        "regime_durations": pd.DataFrame(durations, columns=SCHEMAS["regime_durations"]),
        "regime_factor_performance": pd.DataFrame(performance, columns=SCHEMAS["regime_factor_performance"]),
        "regime_stability": pd.DataFrame(stability, columns=SCHEMAS["regime_stability"]),
    }


def _variance_recursion(values: np.ndarray, model: str, parameters: np.ndarray) -> np.ndarray:
    variance = max(float(np.var(values, ddof=1)), 1e-8)
    result = np.full(len(values), variance, dtype=float)
    if model == "garch":
        omega, alpha, beta = parameters
        for index in range(1, len(values)):
            result[index] = omega + alpha * values[index - 1] ** 2 + beta * result[index - 1]
    elif model == "gjr_garch":
        omega, alpha, gamma, beta = parameters
        for index in range(1, len(values)):
            shock = values[index - 1] ** 2
            result[index] = omega + alpha * shock + gamma * (values[index - 1] < 0) * shock + beta * result[index - 1]
    elif model == "egarch":
        omega, alpha, gamma, beta = parameters
        log_variance = np.log(variance)
        expected_abs_normal = sqrt(2.0 / np.pi)
        for index in range(1, len(values)):
            standardized = values[index - 1] / sqrt(max(np.exp(np.clip(log_variance, -30.0, 30.0)), 1e-12))
            log_variance = omega + alpha * (abs(standardized) - expected_abs_normal) + gamma * standardized + beta * log_variance
            result[index] = np.exp(np.clip(log_variance, -30.0, 30.0))
    return np.maximum(result, 1e-12)


def fit_volatility_qml(values: pd.Series | np.ndarray, model: str) -> dict[str, Any]:
    if model not in {"garch", "gjr_garch", "egarch"}:
        raise ValueError(f"unsupported QML model: {model}")
    clean = np.asarray(pd.Series(values).dropna(), dtype=float)
    if len(clean) < 60:
        return {"model": model, "status": "insufficient_history", "observation_count": len(clean)}
    centered = (clean - clean.mean()) * 100.0
    unconditional = max(float(np.var(centered, ddof=1)), 1e-6)
    if model == "garch":
        starts = ([unconditional * 0.05, 0.05, 0.90], [unconditional * 0.10, 0.10, 0.80])
        bounds = ((1e-10, unconditional * 2.0), (1e-6, 0.5), (1e-6, 0.999))
    elif model == "gjr_garch":
        starts = ([unconditional * 0.05, 0.05, 0.05, 0.85], [unconditional * 0.10, 0.08, 0.10, 0.75])
        bounds = ((1e-10, unconditional * 2.0), (1e-6, 0.5), (0.0, 0.8), (1e-6, 0.999))
    else:
        starts = ([np.log(unconditional) * 0.05, 0.10, -0.05, 0.90], [np.log(unconditional) * 0.10, 0.20, 0.0, 0.75])
        bounds = ((-10.0, 10.0), (0.0, 1.5), (-1.5, 1.5), (0.0, 0.999))

    def objective(parameters: np.ndarray) -> float:
        if model == "garch" and parameters[1] + parameters[2] >= 0.999:
            return 1e12 + 1e9 * (parameters[1] + parameters[2] - 0.999)
        if model == "gjr_garch" and parameters[1] + 0.5 * parameters[2] + parameters[3] >= 0.999:
            return 1e12 + 1e9 * (parameters[1] + 0.5 * parameters[2] + parameters[3] - 0.999)
        variance = _variance_recursion(centered, model, parameters)
        value = 0.5 * float(np.sum(np.log(variance) + centered ** 2 / variance))
        return value if np.isfinite(value) else 1e15

    candidates = []
    for start in starts:
        result = minimize(objective, np.asarray(start, dtype=float), method="L-BFGS-B", bounds=bounds, options={"maxiter": 500, "ftol": 1e-10})
        if np.isfinite(result.fun):
            candidates.append(result)
    if not candidates:
        return {"model": model, "status": "fit_failed", "observation_count": len(clean), "detail": "no finite optimization result"}
    best = min(candidates, key=lambda item: float(item.fun))
    params = np.asarray(best.x, dtype=float)
    variance = _variance_recursion(centered, model, params)
    last_variance = float(variance[-1])
    last_return = float(centered[-1])
    if model == "garch":
        forecast = params[0] + params[1] * last_return ** 2 + params[2] * last_variance
        persistence = params[1] + params[2]
    elif model == "gjr_garch":
        forecast = params[0] + params[1] * last_return ** 2 + params[2] * (last_return < 0) * last_return ** 2 + params[3] * last_variance
        persistence = params[1] + 0.5 * params[2] + params[3]
    else:
        standardized = last_return / sqrt(max(last_variance, 1e-12))
        log_forecast = params[0] + params[1] * (abs(standardized) - sqrt(2.0 / np.pi)) + params[2] * standardized + params[3] * np.log(last_variance)
        forecast = np.exp(np.clip(log_forecast, -30.0, 30.0))
        persistence = params[3]
    status = "ok" if bool(best.success) and persistence < 0.999 and forecast > 0 else "fit_failed"
    return {
        "model": model, "status": status, "observation_count": len(clean),
        "parameters": params, "persistence": float(persistence),
        "forecast_variance": float(forecast / 10000.0),
        "conditional_variance": variance / 10000.0,
        "detail": "" if best.success else str(best.message),
    }


def _arch_lm_p_value(residuals: np.ndarray, lags: int = 5) -> float:
    squared = np.asarray(residuals, dtype=float) ** 2
    if len(squared) <= lags + 5:
        return np.nan
    y = squared[lags:]
    x = np.column_stack([np.ones(len(y)), *[squared[lags - lag: len(squared) - lag] for lag in range(1, lags + 1)]])
    beta = np.linalg.lstsq(x, y, rcond=None)[0]
    fitted = x @ beta
    total = float(np.sum((y - y.mean()) ** 2))
    r_squared = 0.0 if total <= 0 else max(0.0, 1.0 - float(np.sum((y - fitted) ** 2)) / total)
    return float(chi2.sf(len(y) * r_squared, lags))


def run_volatility_stage(
    benchmark_return: pd.Series | None,
    rebalance_dates: pd.DatetimeIndex,
    *,
    min_observations: int = 60,
    ewma_lambda: float = 0.94,
) -> dict[str, pd.DataFrame]:
    if benchmark_return is None or len(benchmark_return.dropna()) == 0:
        return {name: _empty(name) for name in ("volatility_forecasts", "volatility_model_comparison", "model_warnings")}
    returns = benchmark_return.dropna().astype(float).sort_index()
    returns.index = pd.to_datetime(returns.index)
    rows: list[dict[str, Any]] = []
    warning_rows: list[dict[str, Any]] = []
    for as_of in pd.DatetimeIndex(pd.to_datetime(rebalance_dates)).sort_values().unique():
        history = returns[returns.index < as_of]
        future = returns[returns.index >= as_of]
        target = pd.Timestamp(future.index.min()) if len(future) else pd.Timestamp(as_of) + pd.offsets.BDay(1)
        actual = float(future.iloc[0] ** 2) if len(future) else np.nan
        extreme_threshold = float(history.abs().quantile(0.95)) if len(history) else np.nan
        for model in VOLATILITY_MODELS:
            base = {
                "as_of_date": as_of, "training_end": history.index.max() if len(history) else pd.NaT,
                "forecast_target": target, "model": model, "observation_count": len(history),
                "actual_squared_return": actual, "detail": "", "model_version": MODEL_VERSION,
            }
            required = 20 if model == "historical_20" else min_observations
            if len(history) < required:
                rows.append({**base, "status": "insufficient_history"})
                continue
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                if model == "historical_20":
                    variance = float(history.tail(20).var(ddof=1))
                    conditional = np.full(len(history), variance)
                    status, detail = "ok", ""
                elif model == "historical_60":
                    variance = float(history.tail(60).var(ddof=1))
                    conditional = np.full(len(history), variance)
                    status, detail = "ok", ""
                elif model == "ewma":
                    squared = (history - history.mean()) ** 2
                    conditional_series = squared.ewm(alpha=1.0 - ewma_lambda, adjust=False).mean()
                    variance = float(ewma_lambda * conditional_series.iloc[-1] + (1.0 - ewma_lambda) * squared.iloc[-1])
                    conditional = conditional_series.to_numpy(dtype=float)
                    status, detail = "ok", ""
                else:
                    fitted = fit_volatility_qml(history, model)
                    variance = float(fitted.get("forecast_variance", np.nan))
                    conditional = np.asarray(fitted.get("conditional_variance", []), dtype=float)
                    status, detail = str(fitted["status"]), str(fitted.get("detail", ""))
                for item in caught:
                    warning_rows.append({
                        "module": "volatility", "as_of_date": as_of, "model": model,
                        "warning_category": item.category.__name__, "message": str(item.message)[:500],
                        "model_version": MODEL_VERSION,
                    })
            variance = max(variance, 1e-12) if np.isfinite(variance) else np.nan
            residuals = history.to_numpy(dtype=float) / np.sqrt(np.maximum(conditional, 1e-12)) if len(conditional) == len(history) else np.array([])
            qlike = np.log(variance) + actual / variance if np.isfinite(actual) and np.isfinite(variance) else np.nan
            rows.append({
                **base, "status": status, "forecast_variance": variance,
                "annualized_volatility_forecast": sqrt(variance * 252.0) if np.isfinite(variance) else np.nan,
                "error": actual - variance if np.isfinite(actual) and np.isfinite(variance) else np.nan,
                "absolute_error": abs(actual - variance) if np.isfinite(actual) and np.isfinite(variance) else np.nan,
                "qlike": qlike, "arch_lm_p_value": _arch_lm_p_value(residuals) if len(residuals) else np.nan,
                "extreme_observation": bool(len(future) and np.isfinite(extreme_threshold) and abs(float(future.iloc[0])) >= extreme_threshold),
                "detail": detail,
            })
    forecasts = pd.DataFrame(rows).reindex(columns=SCHEMAS["volatility_forecasts"])
    metrics = []
    for model, part in forecasts[forecasts["status"].eq("ok")].dropna(subset=["actual_squared_return", "forecast_variance"]).groupby("model"):
        error = part["actual_squared_return"] - part["forecast_variance"]
        extreme_mask = part["extreme_observation"].map(lambda value: bool(value) if pd.notna(value) else False)
        extreme = part[extreme_mask]
        metrics.append({
            "model": model, "prediction_count": len(part), "rmse": sqrt(float(np.mean(error ** 2))),
            "mae": float(np.mean(abs(error))), "mean_qlike": float(part["qlike"].mean()),
            "residual_arch_rejection_rate": float((part["arch_lm_p_value"].dropna() < 0.05).mean()) if part["arch_lm_p_value"].notna().any() else np.nan,
            "extreme_period_mae": float(extreme["absolute_error"].mean()) if len(extreme) else np.nan,
            "volatility_target_bias": float((np.sqrt(part["forecast_variance"] * 252.0) - np.sqrt(part["actual_squared_return"] * 252.0)).mean()),
            "status": "ok", "model_version": MODEL_VERSION,
        })
    return {
        "volatility_forecasts": forecasts,
        "volatility_model_comparison": pd.DataFrame(metrics, columns=SCHEMAS["volatility_model_comparison"]),
        "model_warnings": pd.DataFrame(warning_rows, columns=SCHEMAS["model_warnings"]),
    }


def _nearest_psd(matrix: np.ndarray) -> tuple[np.ndarray, float]:
    symmetric = 0.5 * (matrix + matrix.T)
    eigenvalues, eigenvectors = np.linalg.eigh(symmetric)
    minimum = float(eigenvalues.min())
    clipped = np.maximum(eigenvalues, 1e-12)
    repaired = eigenvectors @ np.diag(clipped) @ eigenvectors.T
    return 0.5 * (repaired + repaired.T), minimum


def run_dcc_stage(
    monthly_factor_returns: pd.DataFrame,
    rebalance_dates: pd.DatetimeIndex,
    selected_factors: list[str],
    *,
    alpha: float = 0.02,
    beta: float = 0.97,
) -> dict[str, pd.DataFrame]:
    if alpha < 0 or beta < 0 or alpha + beta >= 1:
        raise ValueError("DCC parameters must be non-negative and sum to less than one")
    if len(selected_factors) < 6:
        return {"dynamic_covariance": _empty("dynamic_covariance"), "dcc_risk_contributions": _empty("dcc_risk_contributions")}
    selected = list(dict.fromkeys(selected_factors))[:10]
    if not 6 <= len(selected) <= 10:
        return {"dynamic_covariance": _empty("dynamic_covariance"), "dcc_risk_contributions": _empty("dcc_risk_contributions")}
    data = monthly_factor_returns.copy()
    if data.empty:
        return {"dynamic_covariance": _empty("dynamic_covariance"), "dcc_risk_contributions": _empty("dcc_risk_contributions")}
    if "availability_date" not in data or "factor" not in data:
        raise ValueError("monthly factor returns require availability_date and factor")
    return_column = next((name for name in ("q5_minus_q1", "Q5_minus_Q1_raw", "net_return") if name in data), None)
    if return_column is None:
        raise ValueError("monthly factor returns missing a supported factor return column")
    data["availability_date"] = pd.to_datetime(data["availability_date"])
    pivot = data[data["factor"].isin(selected)].pivot_table(
        index="availability_date", columns="factor", values=return_column, aggfunc="last"
    ).sort_index()
    covariance_rows: list[dict[str, Any]] = []
    risk_rows: list[dict[str, Any]] = []
    for as_of in pd.DatetimeIndex(pd.to_datetime(rebalance_dates)).sort_values().unique():
        history = pivot[pivot.index < as_of].dropna(how="any")
        if history.shape[0] < 20 or history.shape[1] < 6:
            continue
        scale = history.std(ddof=1).replace(0.0, np.nan)
        standardized = ((history - history.mean()) / scale).dropna(how="any")
        if len(standardized) < 20:
            continue
        values = standardized.to_numpy(dtype=float)
        q_bar, _ = _nearest_psd(np.cov(values, rowvar=False))
        q = q_bar.copy()
        for row in values:
            q = (1.0 - alpha - beta) * q_bar + alpha * np.outer(row, row) + beta * q
            q, _ = _nearest_psd(q)
        diagonal = np.sqrt(np.maximum(np.diag(q), 1e-12))
        correlation = q / np.outer(diagonal, diagonal)
        covariance = np.diag(scale.to_numpy(dtype=float)) @ correlation @ np.diag(scale.to_numpy(dtype=float))
        covariance, raw_minimum = _nearest_psd(covariance)
        names = list(standardized.columns)
        for left_index, left in enumerate(names):
            for right_index, right in enumerate(names):
                covariance_rows.append({
                    "as_of_date": as_of, "factor_left": left, "factor_right": right,
                    "conditional_covariance": float(covariance[left_index, right_index]),
                    "model": f"dcc_{alpha:.2f}_{beta:.2f}", "min_eigenvalue": raw_minimum,
                    "parameter_stable": alpha + beta < 1.0, "model_version": MODEL_VERSION,
                })
        portfolio_weights = np.full(len(names), 1.0 / len(names))
        marginal = covariance @ portfolio_weights
        total_variance = float(portfolio_weights @ marginal)
        contributions = portfolio_weights * marginal
        for factor, contribution in zip(names, contributions):
            risk_rows.append({
                "as_of_date": as_of, "factor": factor, "risk_contribution": float(contribution),
                "risk_contribution_fraction": float(contribution / total_variance) if total_variance > 0 else np.nan,
                "model": f"dcc_{alpha:.2f}_{beta:.2f}", "model_version": MODEL_VERSION,
            })
    return {
        "dynamic_covariance": pd.DataFrame(covariance_rows, columns=SCHEMAS["dynamic_covariance"]),
        "dcc_risk_contributions": pd.DataFrame(risk_rows, columns=SCHEMAS["dcc_risk_contributions"]),
    }


def run_stage46_models(
    monthly_ic: pd.DataFrame,
    monthly_factor_returns: pd.DataFrame,
    state_variables: pd.DataFrame,
    benchmark_return: pd.Series | None,
    *,
    config: dict[str, Any] | None = None,
    rebalance_dates: pd.DatetimeIndex | None = None,
    final_holdout_start: str | pd.Timestamp = "2024-01-01",
    mode: str = "sample",
) -> dict[str, pd.DataFrame]:
    if mode not in {"sample", "real"}:
        raise ValueError("mode must be sample or real")
    cfg = config or {}
    holdout = pd.Timestamp(final_holdout_start)
    if rebalance_dates is None:
        if "signal_date" in monthly_ic:
            rebalance_dates = pd.DatetimeIndex(pd.to_datetime(monthly_ic["signal_date"].dropna().unique()))
        else:
            rebalance_dates = pd.DatetimeIndex([])
    dates = pd.DatetimeIndex(pd.to_datetime(rebalance_dates)).sort_values().unique()
    dates = dates[dates < holdout]
    ic_input = monthly_ic.copy()
    if "availability_date" in ic_input:
        ic_input = ic_input[pd.to_datetime(ic_input["availability_date"]) < holdout]
    return_input = monthly_factor_returns.copy()
    if "availability_date" in return_input:
        return_input = return_input[pd.to_datetime(return_input["availability_date"]) < holdout]
    state_input = state_variables.copy()
    state_date_column = "availability_date" if "availability_date" in state_input else "signal_date"
    if state_date_column in state_input:
        state_input = state_input[pd.to_datetime(state_input[state_date_column]) < holdout]
    benchmark_input = benchmark_return
    if benchmark_input is not None:
        benchmark_input = benchmark_input.copy()
        benchmark_input.index = pd.to_datetime(benchmark_input.index)
        benchmark_input = benchmark_input[benchmark_input.index < holdout]
    min_oos = int(cfg.get("min_oos_months", 36))
    if min_oos < 36:
        raise ValueError("stage 4-6 minimum OOS months must be at least 36")
    kalman = run_kalman_stage(
        ic_input, dates, config=cfg.get("dynamic_weights", {}), min_oos_months=min_oos
    )
    hmm = run_hmm_stage(
        state_input, dates, return_input, config=cfg.get("regime", {})
    )
    volatility = run_volatility_stage(
        benchmark_input, dates,
        min_observations=int(cfg.get("volatility", {}).get("min_observations", 60)),
        ewma_lambda=float(cfg.get("volatility", {}).get("ewma_lambda", 0.94)),
    )
    dynamic_cfg = cfg.get("dynamic_weights", {})
    primary_trial = _trial_id(
        float(dynamic_cfg.get("process_variance", 0.001)),
        float(dynamic_cfg.get("observation_variance", 0.01)),
        float(dynamic_cfg.get("turnover_penalty", 0.20)),
    )
    primary_weights = kalman["dynamic_factor_weights"]
    primary_weights = primary_weights[primary_weights["trial_id"].eq(primary_trial)] if not primary_weights.empty else primary_weights
    selected_factors = (
        primary_weights.groupby("factor")["weight"].count().sort_values(ascending=False).head(10).index.astype(str).tolist()
        if not primary_weights.empty else []
    )
    dcc = run_dcc_stage(return_input, dates, selected_factors)
    comparisons = kalman["factor_timing_comparison"]
    primary_comparison = comparisons[comparisons["trial_id"].eq(primary_trial)] if not comparisons.empty else comparisons
    oos_months = int(primary_comparison["oos_months"].max()) if not primary_comparison.empty else 0
    eligible = oos_months >= min_oos
    pit_gate_passed = bool(cfg.get("pit_gate_passed", False))
    promotion_ready = mode == "real" and eligible and pit_gate_passed
    statuses = [
        {
            "module": "kalman", "status": "candidate_complete" if not kalman["factor_ic_forecasts"].empty else "insufficient_history",
            "sample_eligibility": eligible, "oos_months": oos_months,
            "data_mode": mode, "synthetic_engineering_only": mode == "sample",
            "detail": "eligible for dynamic use" if eligible else f"requires at least {min_oos} non-overlapping OOS months",
            "model_version": MODEL_VERSION,
        },
        {
            "module": "hmm", "status": "candidate_complete" if (hmm["regime_probabilities"]["status"] == "ok").any() else "insufficient_history",
            "sample_eligibility": eligible, "oos_months": oos_months, "data_mode": mode,
            "synthetic_engineering_only": mode == "sample", "detail": "filtered probabilities only",
            "model_version": MODEL_VERSION,
        },
        {
            "module": "volatility", "status": "candidate_complete" if (volatility["volatility_forecasts"]["status"] == "ok").any() else "insufficient_history",
            "sample_eligibility": eligible, "oos_months": oos_months, "data_mode": mode,
            "synthetic_engineering_only": mode == "sample", "detail": "candidate comparison; no automatic promotion",
            "model_version": MODEL_VERSION,
        },
        {
            "module": "dcc", "status": "candidate_complete" if not dcc["dynamic_covariance"].empty else "insufficient_factors_or_history",
            "sample_eligibility": eligible, "oos_months": oos_months, "data_mode": mode,
            "synthetic_engineering_only": mode == "sample", "detail": f"selected_factor_count={len(selected_factors)}",
            "model_version": MODEL_VERSION,
        },
        {
            "module": "overall", "status": "dynamic_ready" if promotion_ready else "insufficient_history",
            "sample_eligibility": eligible, "oos_months": oos_months, "data_mode": mode,
            "synthetic_engineering_only": mode == "sample", "detail": (
                "real conclusions remain frozen" if mode == "sample"
                else ("PIT, holdout and OOS gates passed" if promotion_ready else f"pit_gate_passed={pit_gate_passed}; eligible_oos={eligible}")
            ),
            "model_version": MODEL_VERSION,
        },
    ]
    frames = {**kalman, **hmm, **volatility, **dcc, "stage46_status": pd.DataFrame(statuses, columns=SCHEMAS["stage46_status"])}
    for name, schema in SCHEMAS.items():
        if name not in frames:
            frames[name] = pd.DataFrame(columns=schema)
        else:
            frames[name] = frames[name].reindex(columns=schema)
    return frames
