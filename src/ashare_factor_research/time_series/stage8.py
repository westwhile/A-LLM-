"""Stage 8: statistical, overfitting and model promotion audit.

This stage consumes the frozen stage 7 ablation artifacts and evaluates the
ten preregistered promotion gates (see ``docs/plans/时间序列研究执行计划.md``
chapter 11): non-overlapping OOS history, net-of-cost incremental value of the
full dynamic scheme (G) over the static scheme (A), prediction tests
(Diebold-Mariano and SPA), overfitting audits (DSR and PBO), execution
violations and trial registry coverage.

Conclusion levels are ``rejected``, ``insufficient_evidence``,
``research_candidate`` and ``production_candidate``.  Sample-mode runs are
engineering chains and can never promote themselves: their ceiling is
``research_candidate`` with ``dynamic_ready=False``.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

from ashare_factor_research.backtest.cost_model import CostConfig
from ashare_factor_research.factor_testing.inference import benjamini_hochberg
from ashare_factor_research.time_series.models import (
    MODEL_VERSION,
    deflated_sharpe_probability,
    diebold_mariano_test,
    probability_of_backtest_overfitting,
    superior_predictive_ability_test,
)
from ashare_factor_research.time_series.stage46 import _trial_id
from ashare_factor_research.time_series.stage7 import (
    DEFAULT_COST_MULTIPLIERS,
    PORTFOLIO_IDS,
    STAGE7_SCHEMAS,
    _build_result_frames,
)

DYNAMIC_PORTFOLIO_IDS: tuple[str, ...] = tuple(pid for pid in PORTFOLIO_IDS if pid != "A")
STATIC_PORTFOLIO_ID = "A"
FULL_DYNAMIC_COMPARISON = "G-A"
SIGNIFICANCE_LEVEL = 0.05

STAGE7_INPUT_KEYS: tuple[str, ...] = (
    "ablation_portfolio_returns", "ablation_nav", "ablation_performance",
    "ablation_incremental", "ablation_cost_sensitivity", "ablation_status",
)

PROMOTION_DEFAULTS: dict[str, Any] = {
    "min_oos_months": 36,
    "min_incremental_annual_return": 0.0,
    "min_positive_year_ratio": 0.5,
    "min_ir_improvement": 0.15,
    "max_drawdown_worsening": 0.10,
    "dsr_min_probability": 0.95,
    "pbo_max": 0.20,
    "max_execution_violations": 0,
    "min_trial_registry_coverage": 1.0,
    "require_dm_or_spa": True,
}

STAGE8_SCHEMAS: dict[str, list[str]] = {
    "promotion_gate_results": ["gate", "threshold", "value", "passed", "status", "detail", "model_version"],
    "prediction_test_results": [
        "test", "comparison", "statistic", "p_value", "passed", "fdr_q_value", "fdr_5pct",
        "effective_samples", "status", "model_version",
    ],
    "overfit_audit": [
        "metric", "scope", "statistic", "value", "threshold", "passed", "p_value",
        "fdr_q_value", "fdr_5pct", "trial_count", "effective_samples", "status", "detail", "model_version",
    ],
    "trial_registry_coverage": [
        "module", "registered_trials", "executed_trials", "coverage", "passed",
        "status", "detail", "model_version",
    ],
    "promotion_conclusion": [
        "conclusion", "conclusion_level", "reasons", "dynamic_ready", "data_mode",
        "synthetic_engineering_only", "status", "model_version",
    ],
}

#: Ordinal rank of each conclusion grade (higher is closer to production).
CONCLUSION_LEVELS: dict[str, int] = {
    "rejected": 0,
    "insufficient_evidence": 1,
    "research_candidate": 2,
    "production_candidate": 3,
}

GATE_ORDER: tuple[str, ...] = (
    "non_overlapping_oos_months",
    "incremental_annual_return",
    "positive_year_ratio",
    "ir_improvement",
    "max_drawdown_worsening",
    "dm_or_spa",
    "dsr_probability",
    "pbo",
    "execution_violations",
    "trial_registry_coverage",
)


def _empty(name: str) -> pd.DataFrame:
    return pd.DataFrame(columns=STAGE8_SCHEMAS[name])


def _status_frames(status: str, conclusion: str, reason: str, mode: str) -> dict[str, pd.DataFrame]:
    """Single status row per artifact used when promotion cannot be evaluated."""
    gate_row = {column: np.nan for column in STAGE8_SCHEMAS["promotion_gate_results"]}
    gate_row.update({"gate": "all", "passed": False, "status": status, "detail": reason, "model_version": MODEL_VERSION})
    prediction_row = {column: np.nan for column in STAGE8_SCHEMAS["prediction_test_results"]}
    prediction_row.update({"test": "all", "comparison": "all", "passed": False, "status": status, "model_version": MODEL_VERSION})
    overfit_row = {column: np.nan for column in STAGE8_SCHEMAS["overfit_audit"]}
    overfit_row.update({"metric": "all", "scope": "all", "passed": False, "status": status, "detail": reason, "model_version": MODEL_VERSION})
    coverage_row = {column: np.nan for column in STAGE8_SCHEMAS["trial_registry_coverage"]}
    coverage_row.update({
        "module": "all", "registered_trials": 0, "executed_trials": 0, "passed": False,
        "status": status, "detail": reason, "model_version": MODEL_VERSION,
    })
    frames = {
        "promotion_gate_results": pd.DataFrame([gate_row], columns=STAGE8_SCHEMAS["promotion_gate_results"]),
        "prediction_test_results": pd.DataFrame([prediction_row], columns=STAGE8_SCHEMAS["prediction_test_results"]),
        "overfit_audit": pd.DataFrame([overfit_row], columns=STAGE8_SCHEMAS["overfit_audit"]),
        "trial_registry_coverage": pd.DataFrame([coverage_row], columns=STAGE8_SCHEMAS["trial_registry_coverage"]),
        "promotion_conclusion": _conclusion_frame(conclusion, False, reason, mode, status),
    }
    return frames


def _conclusion_frame(conclusion: str, dynamic_ready: bool, reason: str, mode: str, status: str = "ok") -> pd.DataFrame:
    row = {
        "conclusion": conclusion, "conclusion_level": CONCLUSION_LEVELS[conclusion],
        "reasons": reason, "dynamic_ready": bool(dynamic_ready),
        "data_mode": mode, "synthetic_engineering_only": mode == "sample",
        "status": status, "model_version": MODEL_VERSION,
    }
    return pd.DataFrame([row], columns=STAGE8_SCHEMAS["promotion_conclusion"])


def _registered_triples(registry: pd.DataFrame, primary_trial: tuple[float, float, float]) -> set[tuple[float, float, float]]:
    """Preregistered factor-timing trials, keyed by (q, r, turnover_penalty)."""
    triples: set[tuple[float, float, float]] = set()
    grid = registry[
        registry["module"].eq("factor_timing")
        & registry["model"].eq("kalman_local_level_grid")
        & registry["status"].eq("preregistered")
    ]
    for _, row in grid.iterrows():
        try:
            params = json.loads(str(row["parameters"]))
            triples.add((
                float(params["process_variance"]),
                float(params["observation_variance"]),
                float(params["turnover_penalty"]),
            ))
        except (ValueError, TypeError, KeyError):
            continue
    primary_registered = registry[
        registry["module"].eq("factor_timing")
        & registry["model"].eq("kalman_local_level")
        & registry["status"].eq("preregistered")
    ]
    if not primary_registered.empty:
        triples.add(tuple(float(value) for value in primary_trial))
    return triples


def _executed_triples(
    primary_trial: tuple[float, float, float],
    executed_trials: pd.DataFrame | None,
) -> set[tuple[float, float, float]]:
    triples = {tuple(float(value) for value in primary_trial)}
    if executed_trials is None or executed_trials.empty:
        return triples
    required = {"process_variance", "observation_variance", "turnover_penalty"}
    if not required.issubset(executed_trials.columns):
        return triples
    frame = executed_trials
    if "prediction_count" in frame:
        frame = frame[pd.to_numeric(frame["prediction_count"], errors="coerce").fillna(0) > 0]
    for _, row in frame.iterrows():
        try:
            triples.add((
                float(row["process_variance"]),
                float(row["observation_variance"]),
                float(row["turnover_penalty"]),
            ))
        except (ValueError, TypeError):
            continue
    return triples


def _trial_label(triple: tuple[float, float, float]) -> str:
    try:
        return _trial_id(*triple)
    except ValueError:
        return f"FT-KALMAN-CUSTOM-{triple[0]:g}-{triple[1]:g}-{triple[2]:g}"


def _select_best_dynamic(performance: pd.DataFrame) -> str | None:
    candidates = performance[
        performance["portfolio_id"].isin(DYNAMIC_PORTFOLIO_IDS) & performance["status"].eq("ok")
    ]
    if candidates.empty:
        return None
    best: str | None = None
    best_ir = -np.inf
    for portfolio_id in DYNAMIC_PORTFOLIO_IDS:
        rows = candidates[candidates["portfolio_id"].eq(portfolio_id)]
        if rows.empty:
            continue
        ir = pd.to_numeric(rows["information_ratio"], errors="coerce").iloc[0]
        ir = float(ir) if np.isfinite(ir) else -np.inf
        if best is None or ir > best_ir:
            best_ir = ir
            best = portfolio_id
    return best


def _gate(gate: str, threshold: float, value: Any, passed: bool, status: str, detail: str) -> dict[str, Any]:
    numeric = float(value) if value is not None and np.isfinite(value) else np.nan
    if not np.isfinite(numeric) and status == "ok":
        status = "insufficient_history"
        passed = False
    return {
        "gate": gate, "threshold": float(threshold), "value": numeric, "passed": bool(passed),
        "status": status, "detail": detail, "model_version": MODEL_VERSION,
    }


def run_stage8_promotion_audit(
    stage7_frames: dict[str, pd.DataFrame],
    experiment_registry: pd.DataFrame,
    *,
    promotion_config: dict[str, Any] | None = None,
    executed_trials: pd.DataFrame | None = None,
    primary_trial: tuple[float, float, float] = (0.001, 0.01, 0.20),
    execution_violations: int | None = None,
    mode: str = "sample",
    pit_gate_passed: bool = False,
) -> dict[str, pd.DataFrame]:
    if mode not in {"sample", "real"}:
        raise ValueError("mode must be sample or real")
    cfg = {**PROMOTION_DEFAULTS, **dict(promotion_config or {})}
    min_oos = int(cfg["min_oos_months"])
    if min_oos < 36:
        raise ValueError("promotion minimum OOS months must be at least 36")

    returns = stage7_frames.get("ablation_portfolio_returns")
    performance = stage7_frames.get("ablation_performance")
    incremental = stage7_frames.get("ablation_incremental")
    status_frame = stage7_frames.get("ablation_status")
    missing = [
        name for name, frame in (
            ("ablation_portfolio_returns", returns), ("ablation_performance", performance),
            ("ablation_incremental", incremental), ("ablation_status", status_frame),
        )
        if frame is None or frame.empty
    ]
    if missing:
        return _status_frames("missing_input", "insufficient_evidence", f"missing stage 7 artifacts: {','.join(missing)}", mode)
    overall = status_frame[status_frame["portfolio_id"].eq("overall")]
    if overall.empty:
        return _status_frames("missing_input", "insufficient_evidence", "stage 7 status artifact has no overall row", mode)
    overall_status = str(overall["status"].iloc[0])
    oos_months = int(pd.to_numeric(overall["oos_months"], errors="coerce").fillna(0).iloc[0])
    if overall_status != "ablation_complete":
        reason = f"stage 7 overall status is {overall_status}"
        blocked = "insufficient_history" if overall_status == "insufficient_history" else "missing_input"
        return _status_frames(blocked, "insufficient_evidence", reason, mode)

    pivot = returns.pivot_table(index="date", columns="portfolio_id", values="net_return", aggfunc="last").sort_index()
    pivot = pivot.reindex(columns=[pid for pid in PORTFOLIO_IDS if pid in pivot.columns]).dropna(how="any")
    best_dynamic = _select_best_dynamic(performance)
    ga = incremental[incremental["comparison"].eq(FULL_DYNAMIC_COMPARISON) & incremental["status"].eq("ok")]
    if best_dynamic is None or ga.empty or pivot.shape[1] < 2:
        return _status_frames("missing_input", "insufficient_evidence", "no eligible dynamic portfolio or G-A comparison", mode)

    # ---- prediction tests -------------------------------------------------
    losses = -pivot.astype(float)
    dm = diebold_mariano_test(losses[STATIC_PORTFOLIO_ID], losses[best_dynamic], max_lag=1)
    differentials = pd.DataFrame({
        pid: pivot[STATIC_PORTFOLIO_ID].astype(float) - pivot[pid].astype(float)
        for pid in pivot.columns if pid != STATIC_PORTFOLIO_ID
    })
    spa = superior_predictive_ability_test(differentials, seed=0)
    raw_p = pd.Series(
        [dm.get("p_value", np.nan), spa.get("p_value", np.nan)],
        index=["diebold_mariano", "spa"], dtype=float,
    )
    fdr = benjamini_hochberg(raw_p)
    prediction_rows = [
        {
            "test": "diebold_mariano", "comparison": f"{best_dynamic}-{STATIC_PORTFOLIO_ID}",
            "statistic": dm.get("dm_stat", np.nan), "p_value": dm.get("p_value", np.nan),
            "passed": bool(np.isfinite(dm.get("p_value", np.nan)) and dm["p_value"] <= SIGNIFICANCE_LEVEL),
            "fdr_q_value": float(fdr["diebold_mariano"]), "fdr_5pct": bool(fdr["diebold_mariano"] <= SIGNIFICANCE_LEVEL) if np.isfinite(fdr["diebold_mariano"]) else False,
            "effective_samples": int(dm.get("count", 0)), "status": str(dm.get("status", "ok")),
            "model_version": MODEL_VERSION,
        },
        {
            "test": "spa", "comparison": f"all_vs_{STATIC_PORTFOLIO_ID}",
            "statistic": spa.get("spa_stat", np.nan), "p_value": spa.get("p_value", np.nan),
            "passed": bool(np.isfinite(spa.get("p_value", np.nan)) and spa["p_value"] <= SIGNIFICANCE_LEVEL),
            "fdr_q_value": float(fdr["spa"]), "fdr_5pct": bool(fdr["spa"] <= SIGNIFICANCE_LEVEL) if np.isfinite(fdr["spa"]) else False,
            "effective_samples": int(spa.get("observations", 0)), "status": str(spa.get("status", "ok")),
            "model_version": MODEL_VERSION,
        },
    ]
    prediction = pd.DataFrame(prediction_rows, columns=STAGE8_SCHEMAS["prediction_test_results"])

    # ---- overfitting audits ------------------------------------------------
    trial_count = int(experiment_registry["status"].eq("preregistered").sum()) if "status" in experiment_registry else len(experiment_registry)
    dsr = deflated_sharpe_probability(pivot[best_dynamic], trial_count=max(trial_count, 1), periods_per_year=12)
    pbo = probability_of_backtest_overfitting(pivot[[pid for pid in PORTFOLIO_IDS if pid in pivot.columns]])
    dsr_probability = dsr.get("probability", np.nan)
    dsr_passed = bool(np.isfinite(dsr_probability) and dsr_probability >= float(cfg["dsr_min_probability"]))
    pbo_value = pbo.get("pbo", np.nan)
    pbo_passed = bool(np.isfinite(pbo_value) and pbo_value <= float(cfg["pbo_max"]))
    overfit_rows = [
        {
            "metric": "dsr", "scope": best_dynamic,
            "statistic": dsr.get("sharpe", np.nan), "value": dsr_probability,
            "threshold": float(cfg["dsr_min_probability"]), "passed": dsr_passed,
            "p_value": np.nan, "fdr_q_value": np.nan, "fdr_5pct": False,
            "trial_count": int(dsr.get("trial_count", trial_count)),
            "effective_samples": int(dsr.get("count", 0)), "status": str(dsr.get("status", "ok")),
            "detail": f"benchmark_sharpe={dsr.get('benchmark_sharpe', np.nan)}", "model_version": MODEL_VERSION,
        },
        {
            "metric": "pbo", "scope": "A-G",
            "statistic": np.nan, "value": pbo_value,
            "threshold": float(cfg["pbo_max"]), "passed": pbo_passed,
            "p_value": np.nan, "fdr_q_value": np.nan, "fdr_5pct": False,
            "trial_count": np.nan,
            "effective_samples": int(pbo.get("observations", 0)), "status": str(pbo.get("status", "ok")),
            "detail": f"CSCV over seven portfolio return series; combinations={pbo.get('combinations', 0)}",
            "model_version": MODEL_VERSION,
        },
    ]
    for test_name in ("diebold_mariano", "spa"):
        fdr_passed = bool(fdr[test_name] <= SIGNIFICANCE_LEVEL) if np.isfinite(fdr[test_name]) else False
        overfit_rows.append({
            "metric": "bh_fdr", "scope": test_name,
            "statistic": np.nan, "value": float(fdr[test_name]),
            "threshold": SIGNIFICANCE_LEVEL, "passed": fdr_passed,
            "p_value": float(raw_p[test_name]) if np.isfinite(raw_p[test_name]) else np.nan,
            "fdr_q_value": float(fdr[test_name]),
            "fdr_5pct": fdr_passed,
            "trial_count": 2, "effective_samples": int(raw_p.notna().sum()),
            "status": "ok", "detail": "benjamini_hochberg_fdr_5pct over prediction test p-values",
            "model_version": MODEL_VERSION,
        })
    overfit = pd.DataFrame(overfit_rows, columns=STAGE8_SCHEMAS["overfit_audit"])

    # ---- trial registry coverage ------------------------------------------
    registered = _registered_triples(experiment_registry, primary_trial)
    executed = _executed_triples(primary_trial, executed_trials)
    covered = executed & registered
    unregistered = sorted(executed - registered)
    coverage = len(covered) / max(len(executed), 1)
    coverage_passed = coverage >= float(cfg["min_trial_registry_coverage"])
    coverage_detail = (
        "all executed trials are preregistered" if not unregistered
        else f"executed without preregistration: {','.join(_trial_label(triple) for triple in unregistered)}"
    )
    coverage_frame = pd.DataFrame([{
        "module": "factor_timing", "registered_trials": len(registered), "executed_trials": len(executed),
        "coverage": coverage, "passed": coverage_passed,
        "status": "ok" if not unregistered else "unregistered_trial",
        "detail": coverage_detail, "model_version": MODEL_VERSION,
    }], columns=STAGE8_SCHEMAS["trial_registry_coverage"])

    # ---- promotion gates ----------------------------------------------------
    ga_row = ga.iloc[0]
    ga_incremental = float(pd.to_numeric(pd.Series([ga_row["incremental_annual_return"]]), errors="coerce").iloc[0])
    ga_year_ratio = float(pd.to_numeric(pd.Series([ga_row["positive_year_ratio"]]), errors="coerce").iloc[0])
    ga_ir = float(pd.to_numeric(pd.Series([ga_row["ir_improvement"]]), errors="coerce").iloc[0])
    ga_mdd_change = float(pd.to_numeric(pd.Series([ga_row["max_drawdown_change"]]), errors="coerce").iloc[0])
    dm_p = float(raw_p["diebold_mariano"])
    spa_p = float(raw_p["spa"])
    test_passed = any(p <= SIGNIFICANCE_LEVEL for p in (dm_p, spa_p) if np.isfinite(p))
    violations = int(execution_violations) if execution_violations is not None else 0
    violation_detail = (
        "execution compliance summary supplied" if execution_violations is not None
        else "no execution compliance artifact supplied; factor-level simulation has no order-level checks"
    )
    gates = [
        _gate("non_overlapping_oos_months", min_oos, oos_months, oos_months >= min_oos, "ok",
              f"oos_months={oos_months}"),
        _gate("incremental_annual_return", float(cfg["min_incremental_annual_return"]), ga_incremental,
              ga_incremental > float(cfg["min_incremental_annual_return"]), "ok",
              "net-of-cost G-A incremental annual return must be strictly positive"),
        _gate("positive_year_ratio", float(cfg["min_positive_year_ratio"]), ga_year_ratio,
              ga_year_ratio > float(cfg["min_positive_year_ratio"]), "ok",
              "share of years with positive G-A incremental return"),
        _gate("ir_improvement", float(cfg["min_ir_improvement"]), ga_ir,
              ga_ir >= float(cfg["min_ir_improvement"]), "ok", "information ratio improvement G-A"),
        _gate("max_drawdown_worsening", float(cfg["max_drawdown_worsening"]), ga_mdd_change,
              ga_mdd_change >= -float(cfg["max_drawdown_worsening"]), "ok",
              "max drawdown change G-A; negative values mean a deeper drawdown"),
    ]
    if bool(cfg["require_dm_or_spa"]):
        best_p = min((p for p in (dm_p, spa_p) if np.isfinite(p)), default=np.nan)
        gates.append(_gate("dm_or_spa", SIGNIFICANCE_LEVEL, best_p, test_passed, "ok",
                           "at least one of Diebold-Mariano or SPA must pass at 5%"))
    else:
        gates.append(_gate("dm_or_spa", SIGNIFICANCE_LEVEL, np.nan, True, "skipped",
                           "dm_or_spa requirement disabled by configuration"))
    gates.extend([
        _gate("dsr_probability", float(cfg["dsr_min_probability"]), dsr_probability, dsr_passed,
              str(dsr.get("status", "ok")), f"trial_count={trial_count}"),
        _gate("pbo", float(cfg["pbo_max"]), pbo_value, pbo_passed,
              str(pbo.get("status", "ok")), "PBO over seven portfolio return series"),
        _gate("execution_violations", float(cfg["max_execution_violations"]), violations,
              violations <= int(cfg["max_execution_violations"]), "ok", violation_detail),
        _gate("trial_registry_coverage", float(cfg["min_trial_registry_coverage"]), coverage, coverage_passed,
              "ok" if not unregistered else "unregistered_trial",
              f"executed={len(executed)} registered={len(registered)} covered={len(covered)}"),
    ])
    gate_order = {name: index for index, name in enumerate(GATE_ORDER)}
    gates.sort(key=lambda row: gate_order[row["gate"]])
    gate_frame = pd.DataFrame(gates, columns=STAGE8_SCHEMAS["promotion_gate_results"])

    # ---- conclusion ----------------------------------------------------------
    failed = [row["gate"] for row in gates if not row["passed"]]
    if oos_months < min_oos:
        conclusion = "insufficient_evidence"
        dynamic_ready = False
        reason = f"requires at least {min_oos} non-overlapping OOS months, found {oos_months}"
    elif failed:
        conclusion = "rejected"
        dynamic_ready = False
        reason = f"failed gates: {','.join(failed)}"
    elif mode == "real" and pit_gate_passed:
        conclusion = "production_candidate"
        dynamic_ready = True
        reason = "all promotion gates passed with a passed real PIT data gate"
    else:
        conclusion = "research_candidate"
        dynamic_ready = False
        reason = (
            "all promotion gates passed; sample engineering chains cannot self-promote"
            if mode == "sample"
            else "all promotion gates passed but the real PIT data gate is not passed"
        )
    conclusion_frame = _conclusion_frame(conclusion, dynamic_ready, reason, mode)

    frames = {
        "promotion_gate_results": gate_frame,
        "prediction_test_results": prediction,
        "overfit_audit": overfit,
        "trial_registry_coverage": coverage_frame,
        "promotion_conclusion": conclusion_frame,
    }
    for name, schema in STAGE8_SCHEMAS.items():
        frames[name] = frames[name].reindex(columns=schema)
    return frames


def synthesize_stage7_frames(*, months: int = 48, seed: int = 807) -> dict[str, pd.DataFrame]:
    """Deterministic synthetic stage 7 artifacts for sample-mode engineering runs.

    The seven portfolios share a common market component; dynamic schemes earn
    a small persistent alpha so the full promotion chain can be exercised
    end to end.  All outputs are engineering-only and must be flagged with
    ``synthetic_engineering_only=True`` downstream.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2018-01-31", periods=months, freq="ME")
    market = rng.normal(0.004, 0.040, months)
    common = rng.normal(0.0, 0.035, months)
    alpha = {"A": 0.0, "B": 0.0012, "C": 0.0024, "D": 0.0006, "E": 0.0008, "F": 0.0030, "G": 0.0080}
    beta = {"A": 1.00, "B": 0.99, "C": 0.98, "D": 0.99, "E": 0.96, "F": 0.94, "G": 0.90}
    common_share = {"A": 1.00, "B": 0.85, "C": 0.70, "D": 0.90, "E": 0.60, "F": 0.40, "G": 0.20}
    noise = {"A": 0.0, "B": 0.006, "C": 0.005, "D": 0.006, "E": 0.004, "F": 0.003, "G": 0.002}
    simulated: dict[str, pd.DataFrame] = {}
    for portfolio_id in PORTFOLIO_IDS:
        idiosyncratic = rng.normal(0.0, noise[portfolio_id], months)
        gross = beta[portfolio_id] * market + alpha[portfolio_id] + common_share[portfolio_id] * common + idiosyncratic
        turnover = np.abs(rng.normal(0.15, 0.05, months))
        cost = turnover * 0.002
        simulated[portfolio_id] = pd.DataFrame({
            "date": dates, "portfolio_id": portfolio_id,
            "gross_return": gross, "net_return": gross - cost, "turnover": turnover,
            "status": "ok", "model_version": MODEL_VERSION,
        }, columns=STAGE7_SCHEMAS["ablation_portfolio_returns"])
    portfolio_status = {pid: ("ok", "") for pid in PORTFOLIO_IDS}
    frames = _build_result_frames(
        simulated, list(PORTFOLIO_IDS), portfolio_status, CostConfig(), dict(DEFAULT_COST_MULTIPLIERS), months,
    )
    status_rows = []
    for portfolio_id in PORTFOLIO_IDS:
        status_rows.append({
            "portfolio_id": portfolio_id, "weight_scheme": "synthetic", "regime_adjustment": "synthetic",
            "volatility_control": "synthetic", "status": "ok", "oos_months": months,
            "data_mode": "sample", "synthetic_engineering_only": True,
            "detail": "synthetic engineering fixture", "model_version": MODEL_VERSION,
        })
    status_rows.append({
        "portfolio_id": "overall", "weight_scheme": "all", "regime_adjustment": "all", "volatility_control": "all",
        "status": "ablation_complete", "oos_months": months, "data_mode": "sample",
        "synthetic_engineering_only": True,
        "detail": "synthetic stage 7 artifacts for the promotion audit engineering chain",
        "model_version": MODEL_VERSION,
    })
    frames["ablation_status"] = pd.DataFrame(status_rows, columns=STAGE7_SCHEMAS["ablation_status"])
    for name, schema in STAGE7_SCHEMAS.items():
        frames[name] = frames[name].reindex(columns=schema)
    return frames
