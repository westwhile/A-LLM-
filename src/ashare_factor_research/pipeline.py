from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pandas as pd
from ashare_factor_research import __version__
from ashare_factor_research.analysis.attribution import (
    active_industry_exposure,
    cost_attribution,
    industry_exposure,
    industry_return_attribution,
    market_cap_bucket_attribution,
    security_return_contribution,
    top_bottom_contributors,
)
from ashare_factor_research.analysis.drawdown import drawdown_contribution, max_drawdown_period
from ashare_factor_research.analysis.performance import calc_performance
from ashare_factor_research.analysis.report_charts import save_report_artifacts, save_research_extension_charts
from ashare_factor_research.backtest.backtest_engine import run_event_backtest
from ashare_factor_research.backtest.cost_model import CostConfig
from ashare_factor_research.backtest.portfolio_builder import build_portfolio
from ashare_factor_research.backtest.robustness import run_execution_scenarios, summarize_unfilled_orders
from ashare_factor_research.config import ConfigBundle, load_config_bundle
from ashare_factor_research.data.data_cleaner import add_adjusted_prices, add_forward_returns, filter_universe
from ashare_factor_research.data.data_loader import LocalDataLoader
from ashare_factor_research.data.data_quality import (
    REAL_DATA_EXPECTED_TABLES,
    has_blocking_issues,
    write_data_quality_report,
)
from ashare_factor_research.data.trading_calendar import get_trade_dates, month_end_rebalance_dates, next_trade_date
from ashare_factor_research.factor_testing.factor_decay import calc_factor_decay_table
from ashare_factor_research.factor_testing.factor_selection import select_factors, write_selected_factors_report
from ashare_factor_research.factor_testing.group_test import calc_group_returns
from ashare_factor_research.factor_testing.ic_analysis import (
    calc_annual_ic_summary,
    calc_factor_rolling_ic,
    calc_regime_ic_summary,
)
from ashare_factor_research.factor_testing.ic_test import calc_factor_ic_table, calc_ic
from ashare_factor_research.factor_testing.walk_forward import build_walk_forward_scores
from ashare_factor_research.factors.coverage import audit_factor_coverage
from ashare_factor_research.factors.factor_processor import factor_correlation, process_factors
from ashare_factor_research.factors.fundamental_factors import compute_fundamental_factors
from ashare_factor_research.factors.llm_event_factors import compute_event_sentiment_factor
from ashare_factor_research.factors.money_flow_factors import compute_money_flow_factors
from ashare_factor_research.factors.price_volume_factors import compute_price_volume_factors
from ashare_factor_research.factors.registry import (
    FactorSpec,
    apply_factor_directions,
    enabled_factor_names,
    get_factor_specs,
    load_factor_config,
)
from ashare_factor_research.llm.audit import (
    label_quality_passes,
    sample_labels_for_review,
    write_llm_event_audit_report,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FACTOR_CONFIG = PROJECT_ROOT / "config" / "factor_config.yaml"
DEFAULT_PROJECT_CONFIG = PROJECT_ROOT / "config" / "project_config.yaml"
DEFAULT_BACKTEST_CONFIG = PROJECT_ROOT / "config" / "backtest_config.yaml"


def _load_enabled_factor_specs(config_path: str | Path | None = None) -> tuple[dict[str, object], list[FactorSpec]]:
    config = load_factor_config(config_path or DEFAULT_FACTOR_CONFIG)
    return config, get_factor_specs(enabled_factor_names(config))


def _mask_low_coverage_factors(
    factor_df: pd.DataFrame,
    factor_cols: list[str],
    coverage_by_date: pd.DataFrame,
    min_coverage: float,
) -> pd.DataFrame:
    out = factor_df.copy()
    for factor in factor_cols:
        low_dates = coverage_by_date.loc[
            coverage_by_date["factor"].eq(factor) & coverage_by_date["coverage"].lt(min_coverage),
            "trade_date",
        ]
        if not low_dates.empty:
            out.loc[out["trade_date"].isin(low_dates), factor] = pd.NA
    return out


def _trade_dates_from_data(data: dict[str, pd.DataFrame], daily_bar: pd.DataFrame) -> pd.DatetimeIndex:
    if "trade_calendar" in data and not data["trade_calendar"].empty:
        cal = data["trade_calendar"].copy()
        if "is_open" in cal:
            cal = cal[cal["is_open"].astype(bool)]
        return pd.DatetimeIndex(pd.to_datetime(cal["trade_date"]).sort_values().unique())
    return get_trade_dates(daily_bar)


def _attach_timing_columns(df: pd.DataFrame, trade_dates: pd.DatetimeIndex, horizon: int) -> pd.DataFrame:
    out = df.copy()
    out["signal_date"] = pd.to_datetime(out["trade_date"])
    next_map = {date: next_trade_date(trade_dates, pd.Timestamp(date)) for date in trade_dates}
    end_map = {
        date: trade_dates[pos + horizon] if pos + horizon < len(trade_dates) else pd.NaT
        for pos, date in enumerate(trade_dates)
    }
    out["execution_date"] = out["signal_date"].map(next_map)
    out["target_return_end_date"] = out["signal_date"].map(end_map)
    return out


def _prepare_market_data(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    daily_bar = data["daily_bar"].copy()
    if "limit_price" in data and not data["limit_price"].empty:
        cols = ["trade_date", "ts_code", "up_limit", "down_limit"]
        limit_price = data["limit_price"][cols].copy()
        daily_bar = daily_bar.drop(columns=[c for c in ["up_limit", "down_limit"] if c in daily_bar], errors="ignore")
        daily_bar = daily_bar.merge(limit_price, on=["trade_date", "ts_code"], how="left")
    return daily_bar


def build_factor_panel(
    data: dict[str, pd.DataFrame],
    horizon: int = 20,
    config_path: str | Path | None = None,
    index_code: str = "000905.SH",
) -> tuple[pd.DataFrame, list[str]]:
    _, factor_specs = _load_enabled_factor_specs(config_path)
    daily_bar = add_adjusted_prices(_prepare_market_data(data))
    for extra_horizon in sorted({5, 10, horizon, 60}):
        daily_bar = add_forward_returns(daily_bar, horizon=extra_horizon)
    daily_bar = filter_universe(
        daily_bar,
        stock_basic=data.get("stock_basic"),
        index_member=data.get("index_member"),
        st_status=data.get("st_status"),
        suspension=data.get("suspension"),
        index_code=index_code,
        trade_dates=_trade_dates_from_data(data, daily_bar),
    )
    trade_dates = _trade_dates_from_data(data, daily_bar)

    forward_cols = [col for col in daily_bar.columns if col.startswith("future_return_")]
    base_cols = ["trade_date", "ts_code", "adj_close", "return_1d", *forward_cols]
    base = _attach_timing_columns(daily_bar[base_cols], trade_dates, horizon)
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
    event_factor = compute_event_sentiment_factor(data.get("news_event", pd.DataFrame()), trade_dates)
    factors = factors.merge(event_factor, on=["trade_date", "ts_code"], how="left")
    factors["event_sentiment_20"] = factors["event_sentiment_20"].fillna(0.0)
    factors = apply_factor_directions(factors, factor_specs)
    factor_cols = [spec.name for spec in factor_specs if spec.name in factors.columns]
    return factors, factor_cols


def _benchmark_return_series(data: dict[str, pd.DataFrame]) -> pd.Series | None:
    benchmark = data.get("benchmark_index")
    if benchmark is None or benchmark.empty:
        return None
    df = benchmark.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.sort_values(["index_code", "trade_date"])
    if df["index_code"].nunique() > 1:
        df = df[df["index_code"].eq(df["index_code"].iloc[0])]
    returns = df.set_index("trade_date")["close"].astype(float).pct_change().fillna(0.0)
    returns.name = "benchmark_return"
    return returns


def _write_factor_spec_table(factor_specs: list[FactorSpec], output_path: Path) -> pd.DataFrame:
    rows = [
        {
            "factor": spec.name,
            "category": spec.category,
            "direction": spec.direction,
            "window": spec.window,
            "input_columns": ",".join(spec.input_columns),
            "requires_pit": spec.requires_pit,
            "neutralize": spec.neutralize,
            "description": spec.description,
        }
        for spec in factor_specs
    ]
    out = pd.DataFrame(rows)
    out.to_csv(output_path, index=False, encoding="utf-8")
    return out


def _write_manifest(data: dict[str, pd.DataFrame], output_path: Path, mode: str) -> dict[str, object]:
    manifest = {
        "mode": mode,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "tables": {
            name: {
                "rows": int(len(df)),
                "columns": list(df.columns),
            }
            for name, df in sorted(data.items())
        },
    }
    output_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _copy_config_snapshots(run_dir: Path, bundle: ConfigBundle) -> None:
    names = {
        "project": "project_config_snapshot.yaml",
        "factor": "factor_config_snapshot.yaml",
        "backtest": "backtest_config_snapshot.yaml",
    }
    for key, name in names.items():
        shutil.copyfile(bundle.paths[key], run_dir / name)
    shutil.copyfile(bundle.paths["project"], run_dir / "config_snapshot.yaml")


def _save_diagnostics(
    out: Path,
    processed: pd.DataFrame,
    factor_cols: list[str],
    factor_specs: list[FactorSpec],
    return_col: str,
    ic_table: pd.DataFrame,
    corr: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    annual_ic = calc_annual_ic_summary(processed, factor_cols, return_col=return_col)
    rolling_ic = calc_factor_rolling_ic(processed, factor_cols, return_col=return_col)
    decay = calc_factor_decay_table(processed, factor_cols, horizons=[5, 10, 20, 60])
    regime_ic = calc_regime_ic_summary(
        processed,
        factor_cols,
        return_col=return_col,
        benchmark_return_col="benchmark_return" if "benchmark_return" in processed else None,
    )
    selection = select_factors(ic_table, corr)
    annual_ic.to_csv(out / "annual_ic_summary.csv", index=False)
    rolling_ic.to_csv(out / "rolling_ic_summary.csv", index=False)
    decay.to_csv(out / "factor_decay.csv", index=False)
    regime_ic.to_csv(out / "regime_ic_summary.csv", index=False)
    selection.to_csv(out / "factor_selection.csv", index=False)
    write_selected_factors_report(selection, out / "selected_factors.md")
    _write_factor_spec_table(factor_specs, out / "factor_spec_table.csv")
    return {
        "annual_ic": annual_ic,
        "rolling_ic": rolling_ic,
        "factor_decay": decay,
        "regime_ic": regime_ic,
        "factor_selection": selection,
    }


def _save_attribution(
    out: Path,
    portfolio: pd.DataFrame,
    processed: pd.DataFrame,
    market_df: pd.DataFrame,
    trades: pd.DataFrame,
    nav: pd.DataFrame,
    cost_config: CostConfig,
) -> dict[str, pd.DataFrame]:
    returns = add_adjusted_prices(market_df)[["trade_date", "ts_code", "return_1d"]]
    industry = processed[["trade_date", "ts_code", "industry_code"]].drop_duplicates()
    market_cap = processed[["trade_date", "ts_code", "size"]].copy()
    market_cap["total_mv"] = market_cap["size"].where(market_cap["size"].notna()).map(lambda x: float("nan"))
    if "total_mv" in market_df:
        market_cap = market_df[["trade_date", "ts_code", "total_mv"]]
    security_contrib = security_return_contribution(portfolio, returns)
    top_contrib, bottom_contrib = top_bottom_contributors(security_contrib)
    industry_attr = industry_return_attribution(portfolio, returns, industry)
    size_attr = market_cap_bucket_attribution(portfolio, returns, processed[["trade_date", "ts_code", "size"]].rename(columns={"size": "total_mv"}))
    cost_summary = cost_attribution(trades, nav, cost_config=cost_config)
    nav_series = nav.assign(trade_date=pd.to_datetime(nav["trade_date"])).set_index("trade_date")["nav"]
    worst = max_drawdown_period(nav_series)
    if pd.notna(worst.get("start")) and pd.notna(worst.get("trough")):
        drawdown_attr = drawdown_contribution(security_contrib, worst["start"], worst["trough"])
    else:
        drawdown_attr = pd.DataFrame(columns=["ts_code", "return_contribution"])
    security_contrib.to_csv(out / "security_return_contribution.csv", index=False)
    top_contrib.to_csv(out / "top_contributors.csv", index=False)
    bottom_contrib.to_csv(out / "bottom_contributors.csv", index=False)
    industry_attr.to_csv(out / "industry_return_attribution.csv", index=False)
    size_attr.to_csv(out / "market_cap_bucket_attribution.csv", index=False)
    cost_summary.to_csv(out / "cost_attribution.csv", index=False)
    drawdown_attr.to_csv(out / "drawdown_contribution.csv", index=False)
    return {
        "security_contribution": security_contrib,
        "top_contributors": top_contrib,
        "bottom_contributors": bottom_contrib,
        "industry_attribution": industry_attr,
        "market_cap_attribution": size_attr,
        "cost_summary": cost_summary,
        "drawdown_contribution": drawdown_attr,
    }


def _benchmark_industry_exposure(
    portfolio_dates: pd.Series,
    index_member: pd.DataFrame | None,
    industry: pd.DataFrame,
    index_code: str,
) -> pd.DataFrame:
    if index_member is None or index_member.empty:
        return pd.DataFrame(columns=["trade_date", "industry_code", "benchmark_weight"])
    members = index_member.copy()
    members["in_date"] = pd.to_datetime(members["in_date"])
    members["out_date"] = pd.to_datetime(members["out_date"])
    members = members[members["index_code"].eq(index_code)]
    ind = industry.copy()
    ind["trade_date"] = pd.to_datetime(ind["trade_date"])
    rows = []
    for date in pd.DatetimeIndex(pd.to_datetime(portfolio_dates).unique()):
        active = members[(members["in_date"] <= date) & (members["out_date"].isna() | (date < members["out_date"]))].copy()
        if active.empty:
            continue
        raw_weight = active["weight"] if "weight" in active else pd.Series(1.0, index=active.index)
        active["benchmark_weight"] = pd.to_numeric(raw_weight, errors="coerce").fillna(0.0)
        if active["benchmark_weight"].sum() <= 0:
            active["benchmark_weight"] = 1.0
        active["benchmark_weight"] /= active["benchmark_weight"].sum()
        day_industry = ind[ind["trade_date"].eq(date)][["ts_code", "industry_code"]]
        merged = active.merge(day_industry, on="ts_code", how="left")
        grouped = merged.groupby("industry_code", dropna=False, as_index=False)["benchmark_weight"].sum()
        grouped["trade_date"] = date
        rows.append(grouped)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["trade_date", "industry_code", "benchmark_weight"])


def run_sample_pipeline(
    data_dir: str | Path = "data/sample",
    output_dir: str | Path = "reports/figures",
    horizon: int | None = None,
    top_n: int | None = None,
    max_weight: float | None = None,
    config_path: str | Path | None = None,
    project_config_path: str | Path | None = None,
    backtest_config_path: str | Path | None = None,
) -> dict[str, object]:
    bundle = load_config_bundle(project_config_path, config_path, backtest_config_path)
    data = LocalDataLoader(data_dir).load_all()
    return _run_pipeline_core(
        data=data,
        output_dir=output_dir,
        horizon=horizon or bundle.horizon,
        top_n=top_n or bundle.top_n,
        max_weight=max_weight or bundle.max_weight,
        config_path=config_path,
        config_bundle=bundle,
        mode="sample",
        fail_on_quality=False,
    )


def run_research_pipeline(
    data_dir: str | Path = "data/sample",
    output_root: str | Path = "outputs/runs",
    mode: str = "sample",
    horizon: int | None = None,
    top_n: int | None = None,
    max_weight: float | None = None,
    config_path: str | Path | None = None,
    project_config_path: str | Path | None = None,
    backtest_config_path: str | Path | None = None,
    run_id: str | None = None,
    fail_on_quality: bool | None = None,
    robustness: bool = False,
) -> dict[str, object]:
    if mode not in {"sample", "real"}:
        raise ValueError("mode must be 'sample' or 'real'")
    run_name = run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = Path(output_root) / run_name
    figures_dir = run_dir / "figures"
    run_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)
    bundle = load_config_bundle(project_config_path, config_path, backtest_config_path)
    if mode == "real" and not (Path(data_dir) / "data_manifest.json").exists():
        raise ValueError("Real mode requires data_manifest.json produced by import-data.")
    data = LocalDataLoader(data_dir, create_if_missing=mode == "sample").load_all()
    result = _run_pipeline_core(
        data=data,
        output_dir=figures_dir,
        horizon=horizon or bundle.horizon,
        top_n=top_n or bundle.top_n,
        max_weight=max_weight or bundle.max_weight,
        config_path=config_path,
        config_bundle=bundle,
        mode=mode,
        fail_on_quality=fail_on_quality if fail_on_quality is not None else mode == "real",
        robustness=robustness,
    )
    _copy_config_snapshots(run_dir, bundle)
    manifest = _write_manifest(data, run_dir / "data_manifest.json", mode)
    for name in ["metrics", "orders", "fills", "positions"]:
        frame_or_dict = result[name if name != "metrics" else "metrics"]
        if isinstance(frame_or_dict, dict):
            pd.Series(frame_or_dict).to_csv(run_dir / "metrics.csv", header=["value"])
        else:
            frame_or_dict.to_csv(run_dir / f"{name}.csv", index=False)
    for quality_name in ["data_quality_report.md", "data_quality_issues.csv"]:
        src = figures_dir / quality_name
        if src.exists():
            shutil.copyfile(src, run_dir / quality_name)
    result["run_dir"] = run_dir
    _write_run_summary(run_dir, result, bundle, mode, run_name)
    _write_run_metadata(run_dir, result, bundle, mode, run_name, manifest)
    return result


def _run_pipeline_core(
    data: dict[str, pd.DataFrame],
    output_dir: str | Path,
    horizon: int,
    top_n: int,
    max_weight: float,
    config_path: str | Path | None,
    config_bundle: ConfigBundle,
    mode: str,
    fail_on_quality: bool,
    robustness: bool = False,
) -> dict[str, object]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    expected = REAL_DATA_EXPECTED_TABLES if mode == "real" else None
    _, _, quality_issues = write_data_quality_report(data, out, expected_tables=expected)
    if fail_on_quality and has_blocking_issues(quality_issues):
        raise ValueError(f"Blocking data-quality issues found. See {out / 'data_quality_report.md'}")

    factor_config, factor_specs = _load_enabled_factor_specs(config_path)
    project_meta = config_bundle.project.get("project", {})
    universe_config = config_bundle.project.get("universe", {})
    index_code = str(universe_config.get("index_code", project_meta.get("benchmark", "000905.SH")))
    factor_panel, factor_cols = build_factor_panel(data, horizon=horizon, config_path=config_path, index_code=index_code)
    llm_config = config_bundle.project.get("llm", {})
    labels = data.get("news_event", pd.DataFrame()).copy()
    if not labels.empty:
        if "event_id" not in labels:
            labels["event_id"] = labels.reset_index().index.map(lambda value: f"event-{value:06d}")
        review = sample_labels_for_review(labels, sample_size=int(llm_config.get("review_sample_size", 50)))
        review.to_csv(out / "llm_label_audit.csv", index=False)
        write_llm_event_audit_report(review, out / "llm_event_audit.md")
        if bool(llm_config.get("use_as_signal_only_after_review", True)) and not label_quality_passes(
            review, float(llm_config.get("minimum_review_pass_ratio", 0.8))
        ):
            factor_cols = [name for name in factor_cols if not name.startswith("event_")]
    raw_coverage = audit_factor_coverage(factor_panel, factor_cols)
    processing_config = factor_config.get("processing", {}) if isinstance(factor_config.get("processing", {}), dict) else {}
    min_coverage = 1.0 - float(processing_config.get("max_missing_ratio_by_date", 0.7))
    factor_panel = _mask_low_coverage_factors(factor_panel, factor_cols, raw_coverage["by_date"], min_coverage)
    neutralize_modes = {spec.name: spec.neutralize for spec in factor_specs}
    processed, processing_audit = process_factors(
        factor_panel,
        factor_cols,
        size_col="size",
        industry_col="industry_code",
        winsor_n=float(processing_config.get("winsorize_mad_n", 3.0)),
        neutralize=bool(processing_config.get("neutralize_industry_size", True)),
        neutralize_modes=neutralize_modes,
        return_audit=True,
    )
    benchmark_return = _benchmark_return_series(data)
    if benchmark_return is not None:
        processed["benchmark_return"] = pd.to_datetime(processed["trade_date"]).map(benchmark_return)
    processed_coverage = audit_factor_coverage(processed, factor_cols)
    return_col = f"future_return_{horizon}"
    processed["score"] = processed[factor_cols].mean(axis=1, skipna=True)
    ic_table = calc_factor_ic_table(processed, factor_cols, return_col=return_col)
    score_ic_series = calc_ic(processed, "score", return_col=return_col)
    group_returns = calc_group_returns(processed, "score", return_col=return_col)
    corr = factor_correlation(processed, factor_cols)

    rebal_dates = month_end_rebalance_dates(get_trade_dates(data["daily_bar"]))
    wf_config = config_bundle.project.get("research", {}).get("walk_forward", {})
    walk_forward = build_walk_forward_scores(
        processed,
        factor_cols,
        rebal_dates,
        return_col,
        train_months=int(wf_config.get("train_months", 24)),
        validation_months=int(wf_config.get("validation_months", 6)),
        min_train_dates=int(wf_config.get("min_train_dates", 6)),
        min_abs_ic=float(wf_config.get("min_abs_ic", 0.01)),
        min_coverage=float(wf_config.get("min_coverage", min_coverage)),
        require_validation_sign=bool(wf_config.get("require_validation_sign", True)),
        max_factors=wf_config.get("max_factors"),
    )
    for name, frame in walk_forward.items():
        frame.to_csv(out / f"walk_forward_{name}.csv", index=False)
    score_df = walk_forward["scores"][["trade_date", "ts_code", "score"]].dropna()
    if score_df.empty:
        if mode == "real":
            raise ValueError("Walk-forward configuration produced no out-of-sample scores.")
        score_df = processed[processed["trade_date"].isin(rebal_dates)][["trade_date", "ts_code", "score"]].dropna()
    score_df = score_df.merge(
        processed[["trade_date", "ts_code", "industry_code"]].drop_duplicates(),
        on=["trade_date", "ts_code"],
        how="left",
    )
    portfolio_config = config_bundle.backtest.get("portfolio", {})
    portfolio = build_portfolio(
        score_df,
        top_n=top_n,
        max_weight=max_weight,
        min_holding_count=min(top_n, int(portfolio_config.get("min_holding_count", top_n))),
        industry_col="industry_code",
        max_industry_weight=float(portfolio_config.get("max_industry_weight", 1.0)),
    )
    market_df = add_adjusted_prices(_prepare_market_data(data))
    execution = config_bundle.backtest.get("execution", {})
    backtest = run_event_backtest(
        portfolio,
        market_df,
        cost_config=config_bundle.cost,
        lot_size=int(execution.get("lot_size", 100)),
        max_turnover=execution.get("max_turnover", 0.5),
        max_participation_rate=execution.get("max_participation_rate"),
        min_trade_amount=execution.get("min_trade_amount"),
    )
    nav = backtest.nav
    trades = backtest.trades
    strategy_returns = nav.assign(trade_date=pd.to_datetime(nav["trade_date"])).set_index("trade_date")["net_return"]
    benchmark_for_perf = benchmark_return.reindex(strategy_returns.index) if benchmark_return is not None else None
    if benchmark_for_perf is not None and benchmark_for_perf.isna().any():
        if mode == "real":
            missing_dates = benchmark_for_perf[benchmark_for_perf.isna()].index[:5].date.tolist()
            raise ValueError(f"Benchmark returns do not strictly cover strategy dates. Missing sample: {missing_dates}")
        benchmark_for_perf = None
    metrics = calc_performance(nav, benchmark_return=benchmark_for_perf)
    exposure = industry_exposure(portfolio, processed[["trade_date", "ts_code", "industry_code"]])
    benchmark_exposure = _benchmark_industry_exposure(
        portfolio["trade_date"], data.get("index_member"), data["industry"], index_code
    )
    if not benchmark_exposure.empty:
        active_exposure = active_industry_exposure(exposure, benchmark_exposure)
    else:
        active_exposure = pd.DataFrame(columns=["trade_date", "industry_code", "target_weight", "benchmark_weight", "active_weight"])
    active_exposure.to_csv(out / "active_industry_exposure.csv", index=False)
    attribution = _save_attribution(out, portfolio, processed, market_df, trades, nav, config_bundle.cost)
    cost_summary = attribution["cost_summary"]
    unfilled_summary = summarize_unfilled_orders(backtest.orders)
    unfilled_summary.to_csv(out / "unfilled_order_analysis.csv", index=False)
    scenario_summary = pd.DataFrame()
    if robustness:
        robust = config_bundle.backtest.get("robustness", {})
        cost_multipliers = tuple((str(key), float(value)) for key, value in robust.get("cost_multipliers", {}).items())
        scenario_summary, _ = run_execution_scenarios(
            portfolio,
            market_df,
            config_bundle.cost,
            delays=tuple(int(value) for value in robust.get("execution_delay_days", [1, 2, 3])),
            participation_rates=tuple(float(value) for value in robust.get("participation_rates", [0.01, 0.05, 0.10])),
            cost_multipliers=cost_multipliers,
            min_trade_amount=execution.get("min_trade_amount"),
            max_turnover=execution.get("max_turnover", 0.5),
        )
        scenario_summary.to_csv(out / "robustness_scenarios.csv", index=False)

    save_report_artifacts(
        out,
        metrics,
        ic_table,
        group_returns,
        corr,
        nav,
        trades,
        exposure,
        score_ic_series,
        cost_summary,
        benchmark_return=benchmark_for_perf,
    )
    diagnostics = _save_diagnostics(out, processed, factor_cols, factor_specs, return_col, ic_table, corr)
    save_research_extension_charts(out, diagnostics["factor_decay"], scenario_summary)
    group_returns.to_csv(out / "group_returns.csv")
    corr.to_csv(out / "factor_corr.csv")
    raw_coverage["by_date"].to_csv(out / "factor_coverage_by_date.csv", index=False)
    raw_coverage["by_industry"].to_csv(out / "factor_coverage_by_industry.csv", index=False)
    raw_coverage["by_size_bucket"].to_csv(out / "factor_coverage_by_size_bucket.csv", index=False)
    raw_coverage["missing_streaks"].to_csv(out / "factor_missing_streaks.csv", index=False)
    processing_audit.to_csv(out / "factor_processing_audit.csv", index=False)
    timing_cols = [
        col for col in ["trade_date", "signal_date", "execution_date", "target_return_end_date", "ts_code",
                        "financial_report_period", "financial_ann_date", "financial_usable_date"] if col in processed
    ]
    processed[timing_cols].to_csv(out / "factor_panel_timing.csv", index=False)
    nav.to_csv(out / "sample_nav.csv", index=False)
    trades.to_csv(out / "sample_trades.csv", index=False)
    backtest.orders.to_csv(out / "sample_orders.csv", index=False)
    backtest.fills.to_csv(out / "sample_fills.csv", index=False)
    backtest.positions.to_csv(out / "sample_positions.csv", index=False)
    return {
        "factor_panel": processed,
        "factor_cols": factor_cols,
        "factor_specs": factor_specs,
        "raw_coverage": raw_coverage,
        "coverage": processed_coverage,
        "processing_audit": processing_audit,
        "ic_table": ic_table,
        "score_ic_series": score_ic_series,
        "group_returns": group_returns,
        "portfolio": portfolio,
        "industry_exposure": exposure,
        "active_industry_exposure": active_exposure,
        "nav": nav,
        "trades": trades,
        "orders": backtest.orders,
        "fills": backtest.fills,
        "positions": backtest.positions,
        "metrics": metrics,
        "quality_issues": quality_issues,
        "diagnostics": diagnostics,
        "attribution": attribution,
        "walk_forward": walk_forward,
        "unfilled_summary": unfilled_summary,
        "robustness_summary": scenario_summary,
    }


def _write_run_summary(
    run_dir: Path,
    result: dict[str, object],
    bundle: ConfigBundle,
    mode: str,
    run_id: str,
) -> None:
    project = bundle.project.get("project", {})
    research = bundle.project.get("research", {})
    portfolio = bundle.backtest.get("portfolio", {})
    cost = bundle.backtest.get("cost", {})
    factor_panel = result.get("factor_panel")
    if isinstance(factor_panel, pd.DataFrame) and not factor_panel.empty:
        actual_start = pd.to_datetime(factor_panel["trade_date"]).min().date()
        actual_end = pd.to_datetime(factor_panel["trade_date"]).max().date()
    else:
        actual_start = actual_end = "unknown"
    lines = [
        "# Run Summary", "", f"- run_id: {run_id}", f"- package_version: {__version__}", f"- mode: {mode}",
        f"- data interpretation: {'synthetic engineering validation' if mode == 'sample' else 'standardized real-data research'}",
        f"- benchmark: {project.get('benchmark')}", f"- configured range: {research.get('start_date')} to {research.get('end_date')}",
        f"- actual factor-panel range: {actual_start} to {actual_end}",
        f"- universe: {bundle.project.get('universe', {}).get('index_code')}",
        f"- rebalance: {portfolio.get('rebalance_frequency')}", f"- top_n: {portfolio.get('top_n')}",
        f"- max_weight: {portfolio.get('max_weight')}", f"- cost assumptions: {cost}",
        "- execution: next-open with suspension, price-limit, lot-size, turnover and participation constraints.",
        "- unresolved biases: provider coverage, historical PIT correctness, delisting completeness, and market-impact calibration require source-specific verification.",
        "- LLM role: auxiliary explanation and weak-signal research only; not investment advice.", "",
    ]
    (run_dir / "run_summary.md").write_text("\n".join(lines), encoding="utf-8")


def _write_run_metadata(
    run_dir: Path,
    result: dict[str, object],
    bundle: ConfigBundle,
    mode: str,
    run_id: str,
    manifest: dict[str, object],
) -> None:
    manifest_text = json.dumps(manifest, ensure_ascii=False, sort_keys=True)
    metadata = {
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "package_version": __version__,
        "git_commit": _git_commit(),
        "mode": mode,
        "data_version": hashlib.sha256(manifest_text.encode("utf-8")).hexdigest(),
        "config_paths": {key: str(path) for key, path in bundle.paths.items()},
        "universe": bundle.project.get("universe", {}),
        "research": bundle.project.get("research", {}),
        "portfolio": bundle.backtest.get("portfolio", {}),
        "cost": bundle.backtest.get("cost", {}),
        "execution": bundle.backtest.get("execution", {}),
        "factors": list(result.get("factor_cols", [])),
    }
    (run_dir / "run_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


def _git_commit() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return completed.stdout.strip() if completed.returncode == 0 else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"
