"""Stage 7: seven fixed portfolio schemes and ablation experiments.

All seven portfolios (A--G) share the same rebalance dates, factor return
panel, execution cost model and comparison interval.  They differ only in the
three module switches: factor weight scheme (static / rule_based_ic / kalman),
regime adjustment (none / hmm) and volatility control (none / gjr_garch_dcc).

The simulation is strictly point-in-time: weights formed at rebalance date
``t`` only use monthly IC observations with ``availability_date < t`` and earn
the factor return labelled ``signal_date == t``; regime and volatility exposure
scalars come from stage 4-6 artifacts whose ``as_of_date == t`` rows were
themselves produced without look-ahead.
"""

from __future__ import annotations

from math import sqrt
from typing import Any

import numpy as np
import pandas as pd

from ashare_factor_research.analysis.performance import (
    annualized_return_from_returns,
    information_ratio,
    max_drawdown,
    yearly_returns,
)
from ashare_factor_research.backtest.cost_model import CostConfig, estimate_rebalance_cost
from ashare_factor_research.time_series.models import MODEL_VERSION
from ashare_factor_research.time_series.research import (
    build_dynamic_factor_weights,
    build_exposure_scalars,
)
from ashare_factor_research.time_series.stage46 import (
    _cap_weights,
    _trial_id,
    run_dcc_stage,
    run_hmm_stage,
    run_volatility_stage,
)


PORTFOLIO_SPECS: dict[str, dict[str, str]] = {
    "A": {"weight_scheme": "static", "regime_adjustment": "none", "volatility_control": "none"},
    "B": {"weight_scheme": "rule_based_ic", "regime_adjustment": "none", "volatility_control": "none"},
    "C": {"weight_scheme": "kalman", "regime_adjustment": "none", "volatility_control": "none"},
    "D": {"weight_scheme": "static", "regime_adjustment": "hmm", "volatility_control": "none"},
    "E": {"weight_scheme": "static", "regime_adjustment": "none", "volatility_control": "gjr_garch_dcc"},
    "F": {"weight_scheme": "kalman", "regime_adjustment": "hmm", "volatility_control": "none"},
    "G": {"weight_scheme": "kalman", "regime_adjustment": "hmm", "volatility_control": "gjr_garch_dcc"},
}
PORTFOLIO_IDS: tuple[str, ...] = tuple(PORTFOLIO_SPECS)
INCREMENTAL_COMPARISONS: tuple[tuple[str, str], ...] = (
    ("C", "A"), ("D", "A"), ("E", "A"), ("F", "C"), ("G", "F"), ("G", "A"),
)
ARTIFACT_KEYS: tuple[str, ...] = (
    "dynamic_factor_weights", "regime_probabilities", "volatility_forecasts", "dynamic_covariance",
)
DEFAULT_COST_MULTIPLIERS: dict[str, float] = {"zero": 0.0, "standard": 1.0, "high": 2.0}

STAGE7_SCHEMAS: dict[str, list[str]] = {
    "ablation_portfolio_returns": ["date", "portfolio_id", "gross_return", "net_return", "turnover", "status", "model_version"],
    "ablation_nav": ["date", "portfolio_id", "nav", "status", "model_version"],
    "ablation_performance": [
        "portfolio_id", "status", "annual_return", "annual_volatility", "sharpe", "information_ratio",
        "max_drawdown", "monthly_win_rate", "annual_turnover", "oos_months", "model_version",
    ],
    "ablation_incremental": [
        "comparison", "treatment", "baseline", "status", "incremental_annual_return",
        "ir_improvement", "max_drawdown_change", "positive_year_ratio", "model_version",
    ],
    "ablation_cost_sensitivity": [
        "portfolio_id", "cost_scenario", "cost_multiplier", "status",
        "net_annual_return", "net_total_return", "model_version",
    ],
    "ablation_status": [
        "portfolio_id", "weight_scheme", "regime_adjustment", "volatility_control",
        "status", "oos_months", "data_mode", "synthetic_engineering_only", "detail", "model_version",
    ],
}


def _empty(name: str) -> pd.DataFrame:
    return pd.DataFrame(columns=STAGE7_SCHEMAS[name])


def _status_frame(name: str, status: str, key_column: str) -> pd.DataFrame:
    """Single status row used when history or inputs are insufficient."""
    row = {column: np.nan for column in STAGE7_SCHEMAS[name]}
    row[key_column] = "all"
    row["status"] = status
    row["model_version"] = MODEL_VERSION
    return pd.DataFrame([row], columns=STAGE7_SCHEMAS[name])


def _normalize_ic(monthly_ic: pd.DataFrame) -> pd.DataFrame:
    required = {"signal_date", "availability_date", "factor", "rank_ic"}
    missing = required - set(monthly_ic.columns)
    if missing:
        raise ValueError(f"monthly IC missing columns: {sorted(missing)}")
    data = monthly_ic.copy()
    data["signal_date"] = pd.to_datetime(data["signal_date"])
    data["availability_date"] = pd.to_datetime(data["availability_date"])
    return data.sort_values(["availability_date", "factor"])


def _factor_return_pivot(monthly_factor_returns: pd.DataFrame) -> pd.DataFrame:
    required = {"signal_date", "factor"}
    missing = required - set(monthly_factor_returns.columns)
    if missing:
        raise ValueError(f"monthly factor returns missing columns: {sorted(missing)}")
    return_column = next(
        (name for name in ("q5_minus_q1", "Q5_minus_Q1_raw", "net_return") if name in monthly_factor_returns),
        None,
    )
    if return_column is None:
        raise ValueError("monthly factor returns missing a supported factor return column")
    data = monthly_factor_returns.copy()
    data["signal_date"] = pd.to_datetime(data["signal_date"])
    return data.pivot_table(index="signal_date", columns="factor", values=return_column, aggfunc="last").sort_index()


def _static_weights(ic: pd.DataFrame, test_date: pd.Timestamp, factors: list[str]) -> pd.Series:
    history = ic[ic["availability_date"].lt(test_date)]
    mean_ic = history.groupby("factor")["rank_ic"].mean()
    direction = {factor: (1.0 if mean_ic.get(factor, 0.0) >= 0 else -1.0) for factor in factors}
    return pd.Series(direction, dtype=float) / max(len(factors), 1)


def _rule_based_ic_weights(
    ic: pd.DataFrame,
    test_date: pd.Timestamp,
    factors: list[str],
    *,
    window: int,
    min_observations: int,
    cap: float,
) -> pd.Series:
    history = ic[ic["availability_date"].lt(test_date)]
    raw: dict[str, float] = {}
    direction: dict[str, float] = {}
    for factor in factors:
        series = history[history["factor"].eq(factor)].sort_values("availability_date")["rank_ic"].dropna()
        if len(series) < min_observations:
            continue
        mean = float(series.tail(window).mean())
        raw[factor] = abs(mean)
        direction[factor] = 1.0 if mean >= 0 else -1.0
    weights = _cap_weights(pd.Series(raw, dtype=float), cap)
    if weights.empty:
        return _static_weights(ic, test_date, factors)
    return weights * pd.Series(direction, dtype=float).reindex(weights.index)


def _kalman_weights(dynamic_weights: pd.DataFrame, test_date: pd.Timestamp, primary_trial: str) -> pd.Series:
    frame = dynamic_weights[pd.to_datetime(dynamic_weights["test_date"]).eq(test_date)]
    if "trial_id" in frame:
        frame = frame[frame["trial_id"].eq(primary_trial)]
    if frame.empty:
        return pd.Series(dtype=float)
    signed = frame.set_index("factor")["weight"].astype(float) * frame.set_index("factor")["direction"].astype(float)
    return signed


def _apply_dcc_adjustment(signed: pd.Series, covariance: pd.DataFrame | None, test_date: pd.Timestamp) -> pd.Series:
    if signed.empty or covariance is None or covariance.empty:
        return signed
    frame = covariance[pd.to_datetime(covariance["as_of_date"]).eq(test_date)]
    if frame.empty:
        return signed
    variance = frame[frame["factor_left"].eq(frame["factor_right"])]
    variance = variance.set_index("factor_left")["conditional_covariance"].reindex(signed.index).dropna()
    variance = variance[variance.gt(0)]
    if len(variance) < 2:
        return signed
    adjusted = signed.reindex(variance.index) / np.sqrt(variance)
    gross = adjusted.abs().sum()
    return adjusted / gross if gross > 0 else signed


def _exposure_scalars(
    regime: pd.DataFrame | None,
    volatility: pd.DataFrame | None,
    *,
    target_annual_volatility: float,
    min_exposure: float,
    max_exposure: float,
) -> pd.DataFrame:
    return build_exposure_scalars(
        regime if regime is not None else pd.DataFrame(),
        volatility if volatility is not None else pd.DataFrame(),
        target_annual_volatility=target_annual_volatility,
        min_exposure=min_exposure,
        max_exposure=max_exposure,
    )


def _derive_sample_artifacts(
    ic: pd.DataFrame,
    returns: pd.DataFrame,
    state_variables: pd.DataFrame | None,
    benchmark_return: pd.Series | None,
    dates: pd.DatetimeIndex,
    cfg: dict[str, Any],
) -> dict[str, pd.DataFrame]:
    dynamic_cfg = dict(cfg.get("dynamic_weights", {}))
    dynamic_weights = build_dynamic_factor_weights(
        ic,
        dates,
        min_observations=int(dynamic_cfg.get("min_observations", 12)),
        min_asset_count=int(dynamic_cfg.get("min_asset_count", 30)),
        max_factors=int(dynamic_cfg.get("max_factors", 10)),
        max_factor_weight=float(dynamic_cfg.get("max_factor_weight", 0.20)),
        max_fdr_q_value=float(dynamic_cfg.get("max_fdr_q_value", 0.05)),
        process_variance=float(dynamic_cfg.get("process_variance", 0.001)),
        observation_variance=float(dynamic_cfg.get("observation_variance", 0.01)),
        turnover_penalty=float(dynamic_cfg.get("turnover_penalty", 0.20)),
    )
    regime = run_hmm_stage(
        state_variables if state_variables is not None else pd.DataFrame(),
        dates,
        returns,
        config=cfg.get("regime", {}),
    )["regime_probabilities"]
    volatility = run_volatility_stage(
        benchmark_return,
        dates,
        min_observations=int(cfg.get("volatility", {}).get("min_observations", 60)),
        ewma_lambda=float(cfg.get("volatility", {}).get("ewma_lambda", 0.94)),
    )["volatility_forecasts"]
    factors = sorted(returns["factor"].astype(str).unique()) if not returns.empty else []
    dcc = run_dcc_stage(returns, dates, factors)["dynamic_covariance"]
    return {
        "dynamic_factor_weights": dynamic_weights,
        "regime_probabilities": regime,
        "volatility_forecasts": volatility,
        "dynamic_covariance": dcc,
    }


def _required_artifacts(spec: dict[str, str]) -> list[str]:
    required: list[str] = []
    if spec["weight_scheme"] == "kalman":
        required.append("dynamic_factor_weights")
    if spec["regime_adjustment"] == "hmm":
        required.append("regime_probabilities")
    if spec["volatility_control"] == "gjr_garch_dcc":
        required.extend(["volatility_forecasts", "dynamic_covariance"])
    return required


def run_stage7_ablation(
    monthly_ic: pd.DataFrame,
    monthly_factor_returns: pd.DataFrame,
    state_variables: pd.DataFrame | None = None,
    benchmark_return: pd.Series | None = None,
    *,
    artifacts: dict[str, pd.DataFrame | None] | None = None,
    config: dict[str, Any] | None = None,
    cost_config: CostConfig | None = None,
    cost_multipliers: dict[str, float] | None = None,
    rebalance_dates: pd.DatetimeIndex | None = None,
    final_holdout_start: str | pd.Timestamp = "2024-01-01",
    mode: str = "sample",
) -> dict[str, pd.DataFrame]:
    if mode not in {"sample", "real"}:
        raise ValueError("mode must be sample or real")
    cfg = dict(config or {})
    holdout = pd.Timestamp(final_holdout_start)
    min_oos = int(cfg.get("min_oos_months", 36))
    if min_oos < 36:
        raise ValueError("stage 7 minimum OOS months must be at least 36")
    cost = cost_config or CostConfig()
    multipliers = dict(cost_multipliers or DEFAULT_COST_MULTIPLIERS)

    ic = _normalize_ic(monthly_ic)
    ic = ic[ic["availability_date"] < holdout]
    returns_input = monthly_factor_returns.copy()
    if "availability_date" in returns_input:
        returns_input = returns_input[pd.to_datetime(returns_input["availability_date"]) < holdout]
    pivot = _factor_return_pivot(returns_input) if not returns_input.empty else pd.DataFrame()
    if rebalance_dates is None:
        rebalance_dates = pd.DatetimeIndex(ic["signal_date"].dropna().unique()) if not ic.empty else pd.DatetimeIndex([])
    dates = pd.DatetimeIndex(pd.to_datetime(rebalance_dates)).sort_values().unique()
    dates = dates[dates < holdout]
    if not pivot.empty:
        dates = dates[dates.isin(pivot.index)]
    factors = list(pivot.columns) if not pivot.empty else []

    if artifacts is None:
        derived = _derive_sample_artifacts(ic, returns_input, state_variables, benchmark_return, dates, cfg)
        artifact_map: dict[str, pd.DataFrame | None] = derived
    else:
        artifact_map = {key: artifacts.get(key) for key in ARTIFACT_KEYS}
    dynamic_cfg = dict(cfg.get("dynamic_weights", {}))
    primary_trial = _trial_id(
        float(dynamic_cfg.get("process_variance", 0.001)),
        float(dynamic_cfg.get("observation_variance", 0.01)),
        float(dynamic_cfg.get("turnover_penalty", 0.20)),
    )
    rule_window = int(dynamic_cfg.get("min_observations", 12))
    rule_cap = float(dynamic_cfg.get("max_factor_weight", 0.20))
    vol_cfg = dict(cfg.get("volatility", {}))

    # Determine per-portfolio status; missing stage 4-6 inputs only block the
    # portfolios that actually consume them.
    portfolio_status: dict[str, tuple[str, str]] = {}
    for portfolio_id, spec in PORTFOLIO_SPECS.items():
        missing = [key for key in _required_artifacts(spec) if artifact_map.get(key) is None]
        if dates.empty or not factors:
            portfolio_status[portfolio_id] = ("missing_input", "no monthly IC or factor return observations")
        elif missing:
            portfolio_status[portfolio_id] = ("missing_input", f"missing stage 4-6 artifacts: {','.join(missing)}")
        else:
            portfolio_status[portfolio_id] = ("ok", "")

    regime = artifact_map.get("regime_probabilities")
    volatility = artifact_map.get("volatility_forecasts")
    covariance = artifact_map.get("dynamic_covariance")
    dynamic_weights = artifact_map.get("dynamic_factor_weights")
    empty_exposure = pd.DataFrame(columns=["trade_date", "exposure_scalar", "model_version"])
    exposure_by_id: dict[str, pd.DataFrame] = {}
    for portfolio_id, spec in PORTFOLIO_SPECS.items():
        if portfolio_status[portfolio_id][0] != "ok":
            exposure_by_id[portfolio_id] = empty_exposure
            continue
        use_regime = regime if spec["regime_adjustment"] == "hmm" else None
        use_vol = volatility if spec["volatility_control"] == "gjr_garch_dcc" else None
        exposure_by_id[portfolio_id] = _exposure_scalars(
            use_regime,
            use_vol,
            target_annual_volatility=float(vol_cfg.get("target_annual_volatility", 0.15)),
            min_exposure=float(vol_cfg.get("min_exposure", 0.90)),
            max_exposure=float(vol_cfg.get("max_exposure", 1.00)),
        )

    # Simulate every eligible portfolio over the shared rebalance dates.
    simulated: dict[str, pd.DataFrame] = {}
    for portfolio_id, spec in PORTFOLIO_SPECS.items():
        if portfolio_status[portfolio_id][0] != "ok":
            continue
        exposure = exposure_by_id[portfolio_id]
        exposure_map = (
            exposure.set_index(pd.to_datetime(exposure["trade_date"]))["exposure_scalar"].astype(float)
            if not exposure.empty else pd.Series(dtype=float)
        )
        previous_effective = pd.Series(dtype=float)
        rows: list[dict[str, Any]] = []
        for test_date in dates:
            if spec["weight_scheme"] == "static":
                signed = _static_weights(ic, test_date, factors)
            elif spec["weight_scheme"] == "rule_based_ic":
                signed = _rule_based_ic_weights(
                    ic, test_date, factors,
                    window=rule_window, min_observations=rule_window, cap=rule_cap,
                )
            else:
                signed = _kalman_weights(dynamic_weights, test_date, primary_trial)  # type: ignore[arg-type]
                if spec["volatility_control"] == "gjr_garch_dcc":
                    signed = _apply_dcc_adjustment(signed, covariance, test_date)
            if signed.empty:
                continue
            factor_return = pivot.loc[test_date].reindex(signed.index).fillna(0.0).astype(float)
            scalar = float(exposure_map.get(test_date, 1.0)) if not exposure_map.empty else 1.0
            scalar = float(np.clip(scalar, 0.0, 1.0))
            effective = signed * scalar
            gross = float((signed * factor_return).sum()) * scalar
            cost_result = estimate_rebalance_cost(previous_effective, effective, cost)
            turnover = float(cost_result["portfolio_turnover"])
            net = gross - float(cost_result["cost"])
            previous_effective = effective
            rows.append({
                "date": test_date, "portfolio_id": portfolio_id,
                "gross_return": gross, "net_return": net, "turnover": turnover,
                "status": "ok", "model_version": MODEL_VERSION,
            })
        simulated[portfolio_id] = pd.DataFrame(rows, columns=STAGE7_SCHEMAS["ablation_portfolio_returns"])
        if simulated[portfolio_id].empty:
            portfolio_status[portfolio_id] = ("missing_input", "no simulated rebalance dates")

    # Common comparison interval across all eligible portfolios.
    active_ids = [pid for pid in PORTFOLIO_IDS if pid in simulated and not simulated[pid].empty]
    if active_ids:
        common_start = max(pd.Timestamp(simulated[pid]["date"].min()) for pid in active_ids)
        common_end = min(pd.Timestamp(simulated[pid]["date"].max()) for pid in active_ids)
        for pid in active_ids:
            frame = simulated[pid]
            simulated[pid] = frame[
                frame["date"].ge(common_start) & frame["date"].le(common_end)
            ].reset_index(drop=True)
        active_ids = [pid for pid in active_ids if not simulated[pid].empty]
    oos_months = int(simulated[active_ids[0]]["date"].nunique()) if active_ids else 0

    synthetic = mode == "sample"
    if not active_ids:
        blocked = "missing_input" if any(status == "missing_input" for status, _ in portfolio_status.values()) else "insufficient_history"
        frames = {
            "ablation_portfolio_returns": _status_frame("ablation_portfolio_returns", blocked, "portfolio_id"),
            "ablation_nav": _status_frame("ablation_nav", blocked, "portfolio_id"),
            "ablation_performance": _status_frame("ablation_performance", blocked, "portfolio_id"),
            "ablation_incremental": _status_frame("ablation_incremental", blocked, "comparison"),
            "ablation_cost_sensitivity": _status_frame("ablation_cost_sensitivity", blocked, "portfolio_id"),
        }
    elif oos_months < min_oos:
        for pid in active_ids:
            portfolio_status[pid] = ("insufficient_history", f"requires at least {min_oos} OOS months")
        frames = {
            "ablation_portfolio_returns": _status_frame("ablation_portfolio_returns", "insufficient_history", "portfolio_id"),
            "ablation_nav": _status_frame("ablation_nav", "insufficient_history", "portfolio_id"),
            "ablation_performance": _status_frame("ablation_performance", "insufficient_history", "portfolio_id"),
            "ablation_incremental": _status_frame("ablation_incremental", "insufficient_history", "comparison"),
            "ablation_cost_sensitivity": _status_frame("ablation_cost_sensitivity", "insufficient_history", "portfolio_id"),
        }
    else:
        frames = _build_result_frames(simulated, active_ids, portfolio_status, cost, multipliers, oos_months)

    status_rows: list[dict[str, Any]] = []
    for portfolio_id, spec in PORTFOLIO_SPECS.items():
        status, detail = portfolio_status[portfolio_id]
        status_rows.append({
            "portfolio_id": portfolio_id, **spec, "status": status,
            "oos_months": oos_months, "data_mode": mode, "synthetic_engineering_only": synthetic,
            "detail": detail, "model_version": MODEL_VERSION,
        })
    all_ok = all(status == "ok" for status, _ in portfolio_status.values()) and oos_months >= min_oos
    any_missing = any(status == "missing_input" for status, _ in portfolio_status.values())
    if all_ok:
        overall_status = "ablation_complete"
    elif oos_months < min_oos:
        overall_status = "insufficient_history"
    elif any_missing:
        overall_status = "missing_input"
    else:
        overall_status = "insufficient_history"
    status_rows.append({
        "portfolio_id": "overall", "weight_scheme": "all", "regime_adjustment": "all", "volatility_control": "all",
        "status": overall_status, "oos_months": oos_months, "data_mode": mode,
        "synthetic_engineering_only": synthetic,
        "detail": "seven fixed schemes compared on a common interval" if all_ok else "promotion gates not met",
        "model_version": MODEL_VERSION,
    })
    frames["ablation_status"] = pd.DataFrame(status_rows, columns=STAGE7_SCHEMAS["ablation_status"])
    for name, schema in STAGE7_SCHEMAS.items():
        frames[name] = frames[name].reindex(columns=schema)
    return frames


def _performance_row(portfolio_id: str, net: pd.Series, turnover: pd.Series, baseline: pd.Series, oos_months: int) -> dict[str, Any]:
    annual_return = annualized_return_from_returns(net, 12)
    annual_volatility = float(net.std(ddof=1) * sqrt(12.0)) if len(net) > 1 else np.nan
    sharpe = annual_return / annual_volatility if np.isfinite(annual_volatility) and annual_volatility > 0 else np.nan
    nav = (1.0 + net).cumprod()
    years = max(len(net) / 12.0, 1.0 / 12.0)
    return {
        "portfolio_id": portfolio_id, "status": "ok",
        "annual_return": annual_return,
        "annual_volatility": annual_volatility,
        "sharpe": float(sharpe) if np.isfinite(sharpe) else np.nan,
        "information_ratio": information_ratio(net, baseline, 12),
        "max_drawdown": max_drawdown(nav),
        "monthly_win_rate": float((net > 0.0).mean()),
        "annual_turnover": float(turnover.sum() / years),
        "oos_months": oos_months, "model_version": MODEL_VERSION,
    }


def _build_result_frames(
    simulated: dict[str, pd.DataFrame],
    active_ids: list[str],
    portfolio_status: dict[str, tuple[str, str]],
    cost: CostConfig,
    multipliers: dict[str, float],
    oos_months: int,
) -> dict[str, pd.DataFrame]:
    returns_frame = pd.concat([simulated[pid] for pid in active_ids], ignore_index=True)
    nav_rows = []
    for pid in active_ids:
        frame = simulated[pid]
        nav_rows.append(pd.DataFrame({
            "date": frame["date"], "portfolio_id": pid,
            "nav": (1.0 + frame["net_return"].astype(float)).cumprod(),
            "status": "ok", "model_version": MODEL_VERSION,
        }))
    nav_frame = pd.concat(nav_rows, ignore_index=True) if nav_rows else _empty("ablation_nav")

    net_series = {
        pid: pd.Series(simulated[pid]["net_return"].astype(float).to_numpy(), index=pd.to_datetime(simulated[pid]["date"]))
        for pid in active_ids
    }
    turnover_series = {
        pid: pd.Series(simulated[pid]["turnover"].astype(float).to_numpy(), index=pd.to_datetime(simulated[pid]["date"]))
        for pid in active_ids
    }
    baseline = net_series["A"] if "A" in net_series else pd.Series(0.0, index=next(iter(net_series.values())).index)

    performance_rows = [
        _performance_row(pid, net_series[pid], turnover_series[pid], baseline, oos_months) for pid in active_ids
    ]
    for pid, (status, detail) in portfolio_status.items():
        if status != "ok":
            performance_rows.append({
                "portfolio_id": pid, "status": status, "annual_return": np.nan, "annual_volatility": np.nan,
                "sharpe": np.nan, "information_ratio": np.nan, "max_drawdown": np.nan,
                "monthly_win_rate": np.nan, "annual_turnover": np.nan, "oos_months": oos_months,
                "model_version": MODEL_VERSION,
            })
    performance = pd.DataFrame(performance_rows, columns=STAGE7_SCHEMAS["ablation_performance"])

    ir_map = performance.set_index("portfolio_id")["information_ratio"].to_dict()
    ann_map = performance.set_index("portfolio_id")["annual_return"].to_dict()
    mdd_map = performance.set_index("portfolio_id")["max_drawdown"].to_dict()
    incremental_rows: list[dict[str, Any]] = []
    for treatment, base in INCREMENTAL_COMPARISONS:
        label = f"{treatment}-{base}"
        if treatment not in net_series or base not in net_series:
            incremental_rows.append({
                "comparison": label, "treatment": treatment, "baseline": base, "status": "missing_input",
                "incremental_annual_return": np.nan, "ir_improvement": np.nan,
                "max_drawdown_change": np.nan, "positive_year_ratio": np.nan, "model_version": MODEL_VERSION,
            })
            continue
        diff = net_series[treatment] - net_series[base]
        yearly_treatment = yearly_returns(net_series[treatment])
        yearly_base = yearly_returns(net_series[base]).reindex(yearly_treatment.index)
        positive_ratio = float((yearly_treatment - yearly_base > 0.0).mean()) if len(yearly_treatment) else np.nan
        incremental_rows.append({
            "comparison": label, "treatment": treatment, "baseline": base, "status": "ok",
            "incremental_annual_return": float(ann_map[treatment] - ann_map[base]),
            "ir_improvement": float((ir_map[treatment] if np.isfinite(ir_map[treatment]) else 0.0) - (ir_map[base] if np.isfinite(ir_map[base]) else 0.0)),
            "max_drawdown_change": float(mdd_map[treatment] - mdd_map[base]),
            "positive_year_ratio": positive_ratio,
            "model_version": MODEL_VERSION,
        })
    incremental = pd.DataFrame(incremental_rows, columns=STAGE7_SCHEMAS["ablation_incremental"])

    sensitivity_rows: list[dict[str, Any]] = []
    for pid, (status, _detail) in portfolio_status.items():
        if status != "ok" or pid not in simulated:
            for scenario in multipliers:
                sensitivity_rows.append({
                    "portfolio_id": pid, "cost_scenario": scenario, "cost_multiplier": float(multipliers[scenario]),
                    "status": status if status != "ok" else "missing_input",
                    "net_annual_return": np.nan, "net_total_return": np.nan, "model_version": MODEL_VERSION,
                })
            continue
        frame = simulated[pid]
        for scenario, multiplier in multipliers.items():
            # estimate_rebalance_cost is linear in every CostConfig rate, so the
            # scenario cost equals the standard cost times the multiplier and no
            # re-simulation is needed.
            standard_cost = frame["gross_return"].astype(float) - frame["net_return"].astype(float)
            net = frame["gross_return"].astype(float) - standard_cost * float(multiplier)
            series = pd.Series(net.to_numpy(), index=pd.to_datetime(frame["date"]))
            total = float((1.0 + series).prod() - 1.0)
            sensitivity_rows.append({
                "portfolio_id": pid, "cost_scenario": scenario, "cost_multiplier": float(multiplier),
                "status": "ok",
                "net_annual_return": annualized_return_from_returns(series, 12),
                "net_total_return": total,
                "model_version": MODEL_VERSION,
            })
    sensitivity = pd.DataFrame(sensitivity_rows, columns=STAGE7_SCHEMAS["ablation_cost_sensitivity"])

    return {
        "ablation_portfolio_returns": returns_frame,
        "ablation_nav": nav_frame,
        "ablation_performance": performance,
        "ablation_incremental": incremental,
        "ablation_cost_sensitivity": sensitivity,
    }
