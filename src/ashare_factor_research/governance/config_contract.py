from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ashare_factor_research.config import ConfigBundle


@dataclass(frozen=True)
class ConfigValidationResult:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    consumed_paths: tuple[str, ...]
    unconsumed_paths: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return not self.errors and not self.unconsumed_paths


CONSUMED_PATHS = {
    "project.project.name",
    "project.project.market",
    "project.project.benchmark",
    "project.project.data_source",
    "project.project.sample_data_dir",
    "project.research.start_date",
    "project.research.end_date",
    "project.research.rebalance_frequency",
    "project.research.default_horizon",
    "project.research.signal_timing",
    "project.research.execution_timing",
    "project.research.walk_forward.enabled",
    "project.research.walk_forward.train_months",
    "project.research.walk_forward.validation_months",
    "project.research.walk_forward.min_train_dates",
    "project.research.walk_forward.min_abs_ic",
    "project.research.walk_forward.min_coverage",
    "project.research.walk_forward.require_validation_sign",
    "project.research.walk_forward.max_factors",
    "project.time_series.enabled",
    "project.time_series.min_history_start",
    "project.time_series.min_oos_months",
    "project.time_series.diagnostics.max_lag",
    "project.time_series.regime.states",
    "project.time_series.regime.min_observations",
    "project.time_series.regime.max_iterations",
    "project.time_series.dynamic_weights.min_observations",
    "project.time_series.dynamic_weights.min_asset_count",
    "project.time_series.dynamic_weights.max_factors",
    "project.time_series.dynamic_weights.max_factor_weight",
    "project.time_series.dynamic_weights.max_fdr_q_value",
    "project.time_series.dynamic_weights.process_variance",
    "project.time_series.dynamic_weights.observation_variance",
    "project.time_series.dynamic_weights.turnover_penalty",
    "project.time_series.volatility.model",
    "project.time_series.volatility.min_observations",
    "project.time_series.volatility.target_annual_volatility",
    "project.time_series.volatility.min_exposure",
    "project.time_series.volatility.max_exposure",
    "project.time_series.forecast.horizon",
    "project.time_series.forecast.min_train_observations",
    "project.time_series.forecast.ewma_alpha",
    "project.universe.index_code",
    "project.universe.min_listed_days",
    "project.universe.exclude_st",
    "project.universe.exclude_suspended",
    "project.universe.exclude_limit_up_for_buy",
    "project.universe.exclude_limit_down_for_sell",
    "project.llm.dry_run",
    "project.llm.review_sample_size",
    "project.llm.minimum_review_pass_ratio",
    "project.llm.use_as_signal_only_after_review",
    "factor.price_volume_factors",
    "factor.risk_factors",
    "factor.fundamental_factors",
    "factor.quality_factors",
    "factor.growth_factors",
    "factor.money_flow_factors",
    "factor.llm_event_factors",
    "factor.processing.winsorize_mad_n",
    "factor.processing.neutralize_industry_size",
    "factor.processing.max_missing_ratio_by_date",
    "backtest.portfolio.top_n",
    "backtest.portfolio.max_weight",
    "backtest.portfolio.min_holding_count",
    "backtest.portfolio.rebalance_frequency",
    "backtest.portfolio.max_industry_weight",
    "backtest.portfolio.max_cash_weight",
    "backtest.cost.commission_buy",
    "backtest.cost.commission_sell",
    "backtest.cost.stamp_tax_sell",
    "backtest.cost.slippage",
    "backtest.cost.impact_coef",
    "backtest.cost.min_commission",
    "backtest.execution.signal_price",
    "backtest.execution.execution_price",
    "backtest.execution.fallback_execution_price",
    "backtest.execution.lot_size",
    "backtest.execution.max_turnover",
    "backtest.execution.min_trade_amount",
    "backtest.execution.max_participation_rate",
    "backtest.execution.initial_cash",
    "backtest.robustness.execution_delay_days",
    "backtest.robustness.participation_rates",
    "backtest.robustness.cost_multipliers.zero",
    "backtest.robustness.cost_multipliers.standard",
    "backtest.robustness.cost_multipliers.high",
    "backtest.robustness.initial_cash_values",
}


def _leaf_paths(value: Any, prefix: str) -> list[str]:
    if isinstance(value, dict):
        rows: list[str] = []
        for key, child in value.items():
            rows.extend(_leaf_paths(child, f"{prefix}.{key}"))
        return rows
    return [prefix]


def validate_config_bundle(bundle: ConfigBundle, *, raise_on_error: bool = True) -> ConfigValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    all_paths = set(_leaf_paths(bundle.project, "project"))
    all_paths.update(_leaf_paths(bundle.factor, "factor"))
    all_paths.update(_leaf_paths(bundle.backtest, "backtest"))
    unconsumed = sorted(all_paths - CONSUMED_PATHS)

    research = bundle.project.get("research", {})
    portfolio = bundle.backtest.get("portfolio", {})
    execution = bundle.backtest.get("execution", {})
    universe = bundle.project.get("universe", {})
    walk_forward = research.get("walk_forward", {})
    time_series = bundle.project.get("time_series", {})

    if research.get("rebalance_frequency") != "month_end":
        errors.append("research.rebalance_frequency currently supports only 'month_end'")
    if portfolio.get("rebalance_frequency") != research.get("rebalance_frequency"):
        errors.append("project and backtest rebalance_frequency must match")
    if bundle.project.get("project", {}).get("benchmark") != universe.get("index_code"):
        errors.append("project.benchmark and universe.index_code must match")
    if research.get("signal_timing") != "close_after_signal_date":
        errors.append("research.signal_timing currently supports only 'close_after_signal_date'")
    if research.get("execution_timing") != "next_trade_date":
        errors.append("research.execution_timing currently supports only 'next_trade_date'")
    if execution.get("signal_price") != "close":
        errors.append("execution.signal_price currently supports only 'close'")
    if execution.get("execution_price") != "next_open":
        errors.append("execution.execution_price currently supports only 'next_open'")
    if execution.get("fallback_execution_price") not in {None, "none"}:
        errors.append("fallback execution prices are not supported; set fallback_execution_price to 'none'")

    horizon = int(research.get("default_horizon", 0))
    if horizon <= 0:
        errors.append("research.default_horizon must be positive")
    start = research.get("start_date")
    end = research.get("end_date")
    if start and end and str(start) > str(end):
        errors.append("research.start_date must not be after research.end_date")
    if int(universe.get("min_listed_days", 0)) < 0:
        errors.append("universe.min_listed_days must be non-negative")
    if not 0 < float(portfolio.get("max_weight", 0)) <= 1:
        errors.append("portfolio.max_weight must be in (0, 1]")
    if int(portfolio.get("top_n", 0)) <= 0:
        errors.append("portfolio.top_n must be positive")
    if int(portfolio.get("min_holding_count", 0)) > int(portfolio.get("top_n", 0)):
        errors.append("portfolio.min_holding_count must not exceed portfolio.top_n")
    for key in ("max_industry_weight", "max_cash_weight"):
        if not 0 <= float(portfolio.get(key, 0)) <= 1:
            errors.append(f"portfolio.{key} must be in [0, 1]")
    if not 0 <= float(execution.get("max_turnover", 0)) <= 1:
        errors.append("execution.max_turnover must be in [0, 1]")
    participation = execution.get("max_participation_rate")
    if participation is not None and not 0 < float(participation) <= 1:
        errors.append("execution.max_participation_rate must be in (0, 1]")
    if float(execution.get("initial_cash", 1_000_000)) <= 0:
        errors.append("execution.initial_cash must be positive")
    if bool(walk_forward.get("enabled", True)) is False:
        errors.append("walk-forward disabling is not supported; set research.walk_forward.enabled to true")
    if bool(time_series.get("enabled", True)):
        regime = time_series.get("regime", {})
        dynamic = time_series.get("dynamic_weights", {})
        volatility = time_series.get("volatility", {})
        forecast = time_series.get("forecast", {})
        if int(regime.get("states", 0)) not in {2, 3, 4}:
            errors.append("time_series.regime.states must be 2, 3, or 4")
        if int(regime.get("min_observations", 0)) < int(regime.get("states", 3)) * 3:
            errors.append("time_series.regime.min_observations must provide at least three observations per state")
        if int(dynamic.get("min_observations", 0)) < 6:
            errors.append("time_series.dynamic_weights.min_observations must be at least 6")
        if int(dynamic.get("min_asset_count", 0)) < 3:
            errors.append("time_series.dynamic_weights.min_asset_count must be at least 3")
        if not 0 < float(dynamic.get("max_factor_weight", 0)) <= 1:
            errors.append("time_series.dynamic_weights.max_factor_weight must be in (0, 1]")
        if not 0 < float(dynamic.get("max_fdr_q_value", 0)) <= 1:
            errors.append("time_series.dynamic_weights.max_fdr_q_value must be in (0, 1]")
        if not 0 <= float(dynamic.get("turnover_penalty", 0)) < 1:
            errors.append("time_series.dynamic_weights.turnover_penalty must be in [0, 1)")
        if volatility.get("model") != "gjr_garch":
            errors.append("time_series.volatility.model currently supports only 'gjr_garch'")
        min_exposure = float(volatility.get("min_exposure", 0))
        max_exposure = float(volatility.get("max_exposure", 0))
        if not 0 <= min_exposure <= max_exposure <= 1:
            errors.append("time_series volatility exposure bounds must satisfy 0 <= min <= max <= 1")
        if int(forecast.get("horizon", 0)) != 1:
            errors.append("time_series.forecast.horizon currently supports only one-step forecasts")
        if not 0 < float(forecast.get("ewma_alpha", 0)) <= 1:
            errors.append("time_series.forecast.ewma_alpha must be in (0, 1]")
    if bool(bundle.project.get("llm", {}).get("dry_run", True)) is False:
        errors.append("online LLM labeling is not supported; set llm.dry_run to true")
    if unconsumed:
        errors.append(f"unconsumed configuration keys: {unconsumed}")

    result = ConfigValidationResult(
        errors=tuple(errors),
        warnings=tuple(warnings),
        consumed_paths=tuple(sorted(all_paths & CONSUMED_PATHS)),
        unconsumed_paths=tuple(unconsumed),
    )
    if raise_on_error and not result.is_valid:
        raise ValueError("; ".join(result.errors))
    return result


def config_path_summary(bundle: ConfigBundle) -> dict[str, str]:
    return {key: str(Path(path)) for key, path in bundle.paths.items()}
