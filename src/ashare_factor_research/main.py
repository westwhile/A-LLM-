from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import warnings

import pandas as pd

from ashare_factor_research import __version__
from ashare_factor_research.config import load_config_bundle
from ashare_factor_research.data.provenance import dataframe_sha256, file_sha256, verify_data_directory
from ashare_factor_research.governance.config_contract import config_path_summary, validate_config_bundle
from ashare_factor_research.governance.protocol import load_research_protocol
from ashare_factor_research.data.data_loader import AKSHARE_TABLE_ENDPOINTS, AkShareProvider, LocalDataLoader
from ashare_factor_research.data.import_standard import import_standard_tables
from ashare_factor_research.data.data_quality import (
    REAL_DATA_EXPECTED_TABLES,
    has_blocking_issues,
    write_data_quality_report,
)
from ashare_factor_research.data.sample_data import write_sample_data
from ashare_factor_research.data.pit_audit import write_real_data_gate
from ashare_factor_research.monthly_research import (
    attach_monthly_label_returns,
    benchmark_returns_frame,
    build_monthly_labels,
    build_real_mode_audits,
    check_real_mode_gates,
    compute_historical_member_coverage,
    load_or_build_manifest,
    write_monthly_artifacts,
)
from ashare_factor_research.pipeline import (
    _benchmark_return_series,
    build_factor_panel,
    run_research_pipeline,
    run_sample_pipeline,
)
from ashare_factor_research.llm.audit import sample_labels_for_review, write_llm_event_audit_report
from ashare_factor_research.llm.client import batch_label_events
from ashare_factor_research.llm.evaluator import (
    evaluate_representation_increment,
    write_r1_evaluation_artifacts,
)
from ashare_factor_research.llm.r1_protocol import (
    frozen_linear_spec_from_protocol,
    load_r1_protocol,
    write_r1_protocol_receipt,
)
from ashare_factor_research.llm.representation import (
    build_label_representation,
    write_text_representation_artifact,
)
from ashare_factor_research.llm.rule_baseline import write_rule_baseline_artifact
from ashare_factor_research.llm.text_dataset import prepare_text_events, write_text_preparation_artifacts
from ashare_factor_research.quality import run_quality_checks
from ashare_factor_research.time_series.research import (
    build_monthly_factor_ic,
    build_monthly_factor_returns,
    build_monthly_state_variables,
    build_standard_series,
    compare_preregistered_weight_schemes,
    run_time_series_baselines,
)
from ashare_factor_research.time_series.stage46 import run_stage46_models, validate_kalman_registry
from ashare_factor_research.time_series.stage7 import ARTIFACT_KEYS, run_stage7_ablation
from ashare_factor_research.time_series.stage8 import (
    STAGE7_INPUT_KEYS,
    run_stage8_promotion_audit,
    synthesize_stage7_frames,
)
from ashare_factor_research.reporting.evidence import write_evidence_manifest
from ashare_factor_research.utils.io import ensure_dir


LOADERS = {
    "trade_calendar": "load_trade_calendar",
    "stock_basic": "load_stock_basic",
    "daily_bar": "load_daily_bar",
    "daily_basic": "load_daily_basic",
    "benchmark_index": "load_benchmark_index",
    "index_member": "load_index_member",
    "industry": "load_industry",
    "limit_price": "load_limit_price",
}


def _json_default(obj: object) -> str:
    return str(obj)


def _write_frame(df, path: Path, fmt: str) -> None:
    if fmt == "parquet":
        try:
            df.to_parquet(path, index=False)
        except ImportError as exc:
            raise RuntimeError("Parquet output requires pyarrow. Install with `python -m pip install pyarrow`.") from exc
    else:
        df.to_csv(path, index=False, encoding="utf-8")


def _read_symbols_file(path: str | Path | None) -> list[str]:
    if not path:
        return []
    source = Path(path)
    if source.suffix.lower() == ".csv":
        frame = pd.read_csv(source)
        column = next((name for name in ("ts_code", "symbol", "code") if name in frame), None)
        if column is None:
            if len(frame.columns) != 1:
                raise ValueError("Symbols CSV must contain ts_code, symbol, code, or exactly one column")
            column = str(frame.columns[0])
        values = frame[column]
    else:
        values = pd.Series(source.read_text(encoding="utf-8").splitlines())
    return [str(value).strip() for value in values if str(value).strip()]


def _cmd_fetch_data(args: argparse.Namespace) -> int:
    tables = [item.strip() for item in args.tables.split(",") if item.strip()]
    symbols = list(dict.fromkeys([
        *[item.strip() for item in args.symbols.split(",") if item.strip()],
        *_read_symbols_file(args.symbols_file),
    ]))
    provider = AkShareProvider(args.start_date, args.end_date, symbols=symbols, index_code=args.index_code)
    output_root = ensure_dir(args.output_dir)
    out_dir = Path(output_root) / args.batch_id
    if out_dir.exists() and any(out_dir.iterdir()) and not args.resume:
        raise FileExistsError(f"Raw batch already exists; use a new --batch-id or --resume: {out_dir}")
    out_dir = ensure_dir(out_dir)
    manifest_path = out_dir / "fetch_manifest.json"
    if args.resume and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("start_date") != args.start_date or manifest.get("end_date") != args.end_date:
            raise ValueError("Resume parameters do not match the existing batch manifest")
    else:
        manifest = {
        "manifest_version": 2,
        "provider": "akshare",
        "provider_version": provider.provider_version(),
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "batch_id": args.batch_id,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "symbols": symbols,
        "symbols_file": str(Path(args.symbols_file).resolve()) if args.symbols_file else None,
        "index_code": args.index_code,
        "formal_pit_universe": bool(args.symbols_file),
        "tables": {},
    }
    for table in tables:
        if table not in LOADERS:
            raise ValueError(f"Unknown table: {table}. Available: {sorted(LOADERS)}")
        path = out_dir / f"{table}.{args.format}"
        if args.resume and path.exists() and table in manifest.get("tables", {}):
            continue
        loader = getattr(provider, LOADERS[table])
        df = loader()
        _write_frame(df, path, args.format)
        manifest["tables"][table] = {
            "endpoint": AKSHARE_TABLE_ENDPOINTS.get(table, "unsupported_for_formal_pit"),
            "path": str(path.resolve()),
            "file_sha256": file_sha256(path),
            "content_sha256": dataframe_sha256(df),
            "rows": int(len(df)),
            "columns": list(df.columns),
            "dtypes": {name: str(dtype) for name, dtype in df.dtypes.items()},
            "requested_start": args.start_date,
            "requested_end": args.end_date,
            "pit_ready": table in {"trade_calendar", "benchmark_index"},
            "research_limit": (
                "current-list reconnaissance only" if table == "stock_basic"
                else "unadjusted prices with placeholder adj_factor; requires local corporate-action evidence"
                if table == "daily_bar" else None
            ),
        }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2, default=_json_default))
    return 0


def _cmd_quality_check(args: argparse.Namespace) -> int:
    tables = LocalDataLoader(args.data_dir, create_if_missing=False).load_all()
    _, _, issues = write_data_quality_report(
        tables,
        args.output_dir,
        expected_tables=REAL_DATA_EXPECTED_TABLES if args.mode == "real" else None,
    )
    blocking = has_blocking_issues(issues)
    gate_summary = None
    if args.mode == "real":
        manifest_path = Path(args.data_dir) / "data_manifest.json"
        source_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
        gate_summary = write_real_data_gate(
            tables,
            args.output_dir,
            source_manifest=source_manifest,
            index_code=args.index_code,
            required_start=args.required_start,
            min_coverage=args.min_coverage,
            quality_issues=issues,
        )
        blocking = blocking or gate_summary["status"] != "passed"
    print(
        json.dumps(
            {
                "tables": len(tables),
                "issues": int(len(issues)),
                "blocking": bool(blocking),
                "data_gate_status": gate_summary["status"] if gate_summary else "not_applicable",
                "output_dir": str(args.output_dir),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if args.fail_on_blocking and blocking else 0


def _cmd_import_data(args: argparse.Namespace) -> int:
    manifest = import_standard_tables(
        args.source_dir,
        args.output_dir,
        mapping_path=args.mapping,
        output_format=args.format,
        mode=args.mode,
        source_registry_path=args.source_registry,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, default=_json_default))
    return 0 if manifest.get("import_gate_status") == "ready_for_quality_audit" else 1


def _cmd_label_events(args: argparse.Namespace) -> int:
    raw = pd.read_csv(args.input)
    labels = batch_label_events(raw, cache_path=args.cache)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    labels.to_csv(output, index=False, encoding="utf-8")
    review = sample_labels_for_review(labels, sample_size=args.review_sample_size)
    review_path = output.with_name(f"{output.stem}_review.csv")
    review.to_csv(review_path, index=False, encoding="utf-8")
    write_llm_event_audit_report(review, output.with_name(f"{output.stem}_audit.md"))
    summary = {"labels": len(labels), "output": str(output), "review": str(review_path)}
    if args.artifact_dir:
        write_rule_baseline_artifact(labels, args.artifact_dir)
        summary["artifact_dir"] = str(args.artifact_dir)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def _cmd_prepare_text_events(args: argparse.Namespace) -> int:
    raw = pd.read_csv(args.input)
    registry: list[str] | None = None
    if args.stock_registry:
        registry_frame = pd.read_csv(args.stock_registry)
        candidates = [column for column in ("stock_code", "ts_code") if column in registry_frame]
        if not candidates:
            raise ValueError("stock registry requires a stock_code or ts_code column")
        registry = registry_frame[candidates[0]].dropna().astype(str).tolist()
    result = prepare_text_events(
        raw,
        stock_registry=registry,
        near_duplicate_threshold=args.near_duplicate_threshold,
        near_duplicate_window_days=args.near_duplicate_window_days,
    )
    paths = write_text_preparation_artifacts(result, args.output_dir)
    print(json.dumps({"paths": paths, "quality": result.quality_report}, ensure_ascii=False, indent=2))
    return 0


def _cmd_build_r1_label_representation(args: argparse.Namespace) -> int:
    prepared = pd.read_csv(args.prepared_events)
    labels = pd.read_csv(args.labels)
    text_manifest = (
        json.loads(Path(args.text_manifest).read_text(encoding="utf-8"))
        if args.text_manifest
        else None
    )
    rows = build_label_representation(
        prepared,
        labels,
        representation_type=args.representation_type,
        representation_version=args.representation_version,
    )
    models = sorted(labels["model"].dropna().astype(str).unique())
    if len(models) != 1:
        raise ValueError(f"label representation requires one model, got: {models}")
    artifact = write_text_representation_artifact(
        rows,
        args.output_dir,
        representation_id=args.representation_id,
        model_card={
            "model_id": models[0],
            "model_revision": args.model_revision,
            "preprocessing_version": args.preprocessing_version,
            "intended_use": "R1 label representation comparison",
            "license_status": args.model_license_status,
        },
        preprocessing={
            "version": args.preprocessing_version,
            "prepared_events": str(args.prepared_events),
        },
        aggregation={
            "level": "event",
            "deduplication": "consume prepared dedup_group_id; signal selection keeps first available exact duplicate",
        },
        text_manifest=text_manifest,
        trial_id=args.trial_id,
        status="draft",
    )
    print(json.dumps(artifact, ensure_ascii=False, indent=2))
    return 0


def _cmd_validate_r1_protocol(args: argparse.Namespace) -> int:
    protocol = load_r1_protocol(args.protocol)
    receipt_path = Path(args.receipt) if args.receipt else Path(args.protocol).with_suffix(".receipt.json")
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt = write_r1_protocol_receipt(protocol, receipt_path)
    print(json.dumps({**receipt, "receipt": str(receipt_path)}, ensure_ascii=False, indent=2))
    return 0


def _cmd_run_r1_evaluator(args: argparse.Namespace) -> int:
    protocol = load_r1_protocol(args.protocol)
    spec = frozen_linear_spec_from_protocol(protocol)
    panel = pd.read_csv(args.panel)
    base_features = [value.strip() for value in args.base_features.split(",") if value.strip()]
    text_features = [value.strip() for value in args.text_features.split(",") if value.strip()]
    if not text_features:
        raise ValueError("--text-features must contain at least one feature")
    result = evaluate_representation_increment(
        panel,
        base_features=base_features,
        text_features=text_features,
        spec=spec,
        target_col=args.target_col,
        signal_date_col=args.signal_date_col,
        label_end_date_col=args.label_end_date_col,
        asset_col=args.asset_col,
        allow_final_holdout=args.allow_final_holdout,
        final_holdout_access_ref=args.final_holdout_access_ref,
    )
    paths = write_r1_evaluation_artifacts(result, args.output_dir)
    print(json.dumps({"paths": paths, "summary": result["summary"]}, ensure_ascii=False, indent=2))
    return 0


# 因子输入列的审计口径修正（2026-08-11）：
# - roa：因子侧由 net_profit/total_assets 推导（factors/fundamental_factors.py），审计映射到真实来源列。
# - ps / large_order_net_mf_amount / operating_cash_flow：真实签署表无此列且无已签署推导路径
#   （样本表有这三列；RESSET 批次 daily_basic 无 ps/large_order 单列、financial_indicator 无经营现金流），
#   对应因子 sp / large_order_mf_20 / cfp 在本批 real 数据下不可得——已知缺口，不进覆盖审计，构建日志明示。
FACTOR_INPUT_DERIVED_SOURCES: dict[str, list[str]] = {
    "roa": ["net_profit", "total_assets"],
}
UNSOURCED_FACTOR_INPUTS = frozenset({"ps", "large_order_net_mf_amount", "operating_cash_flow"})


def unsourced_factor_inputs(factor_specs: list) -> list[str]:
    """因子配置启用但真实表无来源列的输入字段（已知缺口，供报告/日志）。"""
    return sorted({col for spec in factor_specs for col in spec.input_columns if col in UNSOURCED_FACTOR_INPUTS})


def _required_fields_from_specs(factor_specs: list) -> dict[str, list[str]]:
    """Map factor input columns to their likely source tables for coverage checks."""

    field_map: dict[str, set[str]] = {
        "daily_bar": {"amount", "adj_factor", "close"},
        "daily_basic": {"turnover_rate", "total_mv", "pb", "pe_ttm", "net_mf_amount"},
        "financial_indicator": {"roe", "gross_margin", "debt_ratio", "operating_revenue", "total_assets",
                                "net_profit", "revenue_yoy", "profit_yoy"},
    }
    required: dict[str, set[str]] = {name: set() for name in field_map}
    for spec in factor_specs:
        for column in spec.input_columns:
            if column in UNSOURCED_FACTOR_INPUTS:
                continue
            for source_column in FACTOR_INPUT_DERIVED_SOURCES.get(column, [column]):
                for table, fields in field_map.items():
                    if source_column in fields:
                        required[table].add(source_column)
    return {table: sorted(fields) for table, fields in required.items() if fields}


def _monthly_state_market(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    market = data["daily_bar"].copy()
    daily_basic = data.get("daily_basic")
    if daily_basic is not None and not daily_basic.empty and "turnover_rate" in daily_basic:
        turnover = daily_basic[["trade_date", "ts_code", "turnover_rate"]].copy()
        market = market.drop(columns=["turnover_rate"], errors="ignore").merge(
            turnover, on=["trade_date", "ts_code"], how="left", validate="one_to_one"
        )
    return market


def _cmd_build_monthly_sample(args: argparse.Namespace) -> int:
    bundle = load_config_bundle(args.project_config, args.factor_config, args.backtest_config)
    validate_config_bundle(bundle)
    if args.mode == "real":
        verify_data_directory(args.data_dir, require_manifest=True, expected_mode="real")
    data = LocalDataLoader(args.data_dir, create_if_missing=args.mode == "sample").load_all()
    source_manifest = load_or_build_manifest(args.data_dir) if args.mode == "real" else None

    universe_config = bundle.project.get("universe", {})
    index_code = str(universe_config.get("index_code", "000905.SH"))

    from ashare_factor_research.factors.registry import enabled_factor_names, load_factor_config, get_factor_specs
    factor_config_dict = load_factor_config(args.factor_config)
    specs = get_factor_specs(enabled_factor_names(factor_config_dict))
    required_fields = _required_fields_from_specs(specs)
    bar_required = required_fields.setdefault("daily_bar", [])
    for field in ["amount", "adj_factor"]:
        if field not in bar_required:
            bar_required.append(field)
    unsourced = unsourced_factor_inputs(specs)
    if unsourced:
        print(f"WARNING: factor inputs with no source column in the signed real tables "
              f"(factors will be empty; documented gap): {unsourced}")

    trade_dates = data.get("trade_calendar", data["daily_bar"])["trade_date"]
    # The holdout tripwire in build_monthly_labels raises when a label's
    # availability lands inside the holdout; real calendars extend past the
    # holdout start, so feed only pre-holdout dates — the last label then ends
    # one month earlier with availability strictly before the holdout.
    pre_holdout_dates = pd.to_datetime(trade_dates)
    pre_holdout_dates = pre_holdout_dates[pre_holdout_dates < pd.Timestamp(args.final_holdout_start)]
    labels = build_monthly_labels(
        pre_holdout_dates,
        final_holdout_start=args.final_holdout_start,
    )

    audits: dict[str, pd.DataFrame] = {}
    blocking: list[str] = []
    if args.mode == "real":
        audits = build_real_mode_audits(
            data,
            index_code=index_code,
            required_start=args.required_start,
            min_coverage=args.min_coverage,
        )
        blocking = check_real_mode_gates(
            data,
            source_manifest,
            required_tables=REAL_DATA_EXPECTED_TABLES - {"news_event"},
            audits=audits,
            min_coverage=args.min_coverage,
            required_fields=required_fields,
            required_start=args.required_start,
            final_holdout_start=args.final_holdout_start,
            labels=labels,
            data_dir=Path(args.data_dir),
        )
        if blocking:
            raise ValueError(f"Real-mode monthly sample gates blocked: {blocking}")

    research_config = bundle.project.get("research", {})
    factor_panel, factor_cols = build_factor_panel(
        data,
        horizon=1,
        config_path=args.factor_config,
        index_code=index_code,
        min_listed_days=int(universe_config.get("min_listed_days", 120)),
        exclude_st=bool(universe_config.get("exclude_st", True)),
        exclude_suspended=bool(universe_config.get("exclude_suspended", True)),
        start_date=research_config.get("start_date"),
        end_date=research_config.get("end_date"),
    )
    daily_factor_panel = factor_panel
    factor_panel = attach_monthly_label_returns(daily_factor_panel, data["daily_bar"], labels)
    benchmark_return = _benchmark_return_series(data, index_code)
    rebal_dates = pd.to_datetime(labels["signal_date"].unique())
    monthly_ic = build_monthly_factor_ic(factor_panel, factor_cols, "monthly_forward_return", rebal_dates)
    monthly_returns = build_monthly_factor_returns(
        factor_panel, factor_cols, "monthly_forward_return", rebal_dates, benchmark_return, bundle.cost
    )
    state_variables = build_monthly_state_variables(
        daily_factor_panel, _monthly_state_market(data), benchmark_return, labels
    )

    out = ensure_dir(args.output_dir)
    benchmark_frame = benchmark_returns_frame(benchmark_return)
    paths = write_monthly_artifacts(out, monthly_ic, monthly_returns, state_variables, benchmark_frame)
    economic = compare_preregistered_weight_schemes(monthly_ic, monthly_returns, rebal_dates, cost_config=bundle.cost)
    economic.to_csv(out / "economic_comparison.csv", index=False, encoding="utf-8")

    if audits:
        for filename, frame in audits.items():
            frame.to_csv(out / filename, index=False, encoding="utf-8")
    summary = {
        "mode": args.mode,
        "output_dir": str(out),
        "artifact_paths": {k: str(v) for k, v in paths.items()},
        "economic_comparison": str(out / "economic_comparison.csv"),
        "benchmark_returns_sha256": dataframe_sha256(benchmark_frame),
        "labels": int(len(labels)),
        "factors": len(factor_cols),
        "gate_status": "passed" if args.mode != "real" or not blocking else "blocked",
    }
    (out / "monthly_sample_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


def _cmd_run_time_series_baselines(args: argparse.Namespace) -> int:
    out = ensure_dir(args.output_dir)
    if args.monthly_ic and args.monthly_returns and args.state_variables:
        monthly_ic = pd.read_csv(args.monthly_ic)
        monthly_returns = pd.read_csv(args.monthly_returns)
        state_variables = pd.read_csv(args.state_variables, index_col=0, parse_dates=True)
    else:
        data = LocalDataLoader(args.data_dir, create_if_missing=True).load_all()
        universe_config = {"index_code": "000905.SH"}
        factor_panel, factor_cols = build_factor_panel(data, horizon=1, index_code="000905.SH")
        benchmark_return = _benchmark_return_series(data, "000905.SH")
        labels = build_monthly_labels(data["daily_bar"]["trade_date"], final_holdout_start=args.final_holdout_start)
        rebal_dates = pd.to_datetime(labels["signal_date"].unique())
        daily_factor_panel = factor_panel
        factor_panel = attach_monthly_label_returns(daily_factor_panel, data["daily_bar"], labels)
        monthly_ic = build_monthly_factor_ic(factor_panel, factor_cols, "monthly_forward_return", rebal_dates)
        state_variables = build_monthly_state_variables(
            daily_factor_panel, _monthly_state_market(data), benchmark_return, labels
        ).set_index("signal_date")
    state_variables.index = pd.to_datetime(state_variables.index)
    result = run_time_series_baselines(
        state_variables,
        monthly_ic,
        config={
            "evaluation_start": args.evaluation_start,
            "evaluation_end": args.evaluation_end,
        },
        final_holdout_start=args.final_holdout_start,
    )
    for name, frame in result.items():
        frame.to_csv(out / f"{name}.csv", index=False, encoding="utf-8")
    summary = {
        "output_dir": str(out),
        "files": [str(out / f"{name}.csv") for name in result],
        "evaluation_start": args.evaluation_start,
        "evaluation_end": args.evaluation_end,
        "forecast_rows": int(len(result["forecast_comparison"])),
    }
    (out / "baseline_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


def _cmd_run_time_series_models(args: argparse.Namespace) -> int:
    out = ensure_dir(args.output_dir)
    protocol = load_research_protocol(args.protocol)
    if protocol["mode"] != args.mode:
        raise ValueError(f"protocol mode {protocol['mode']} does not match --mode {args.mode}")
    pit_gate_passed = False
    if args.mode == "real":
        if not args.pit_gate_summary:
            raise ValueError("real mode requires --pit-gate-summary from the completed real data gate")
        gate_path = Path(args.pit_gate_summary)
        if not gate_path.exists():
            raise FileNotFoundError(gate_path)
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        pit_gate_passed = gate.get("status") == "passed"
        if not pit_gate_passed:
            raise ValueError("real PIT data gate is not passed")
    registry = pd.read_csv(args.experiment_registry)
    validate_kalman_registry(registry)
    bundle = load_config_bundle(args.project_config, args.factor_config, args.backtest_config)
    validate_config_bundle(bundle)
    explicit = [args.monthly_ic, args.monthly_returns, args.state_variables, args.benchmark_returns]
    if any(explicit) and not all(explicit):
        raise ValueError("monthly IC, monthly returns, state variables and benchmark returns must be supplied together")
    input_paths: dict[str, Path] = {}
    captured_input_warnings: list[warnings.WarningMessage] = []
    if all(explicit):
        input_paths = {
            "monthly_ic": Path(args.monthly_ic),
            "monthly_returns": Path(args.monthly_returns),
            "state_variables": Path(args.state_variables),
            "benchmark_returns": Path(args.benchmark_returns),
        }
        for name, path in input_paths.items():
            if not path.exists():
                raise FileNotFoundError(f"{name}: {path}")
        monthly_ic = pd.read_csv(input_paths["monthly_ic"])
        monthly_returns = pd.read_csv(input_paths["monthly_returns"])
        state_variables = pd.read_csv(input_paths["state_variables"])
        benchmark_frame = pd.read_csv(input_paths["benchmark_returns"])
        required_benchmark = {"trade_date", "benchmark_return"}
        if not required_benchmark.issubset(benchmark_frame.columns):
            raise ValueError("benchmark returns require trade_date,benchmark_return")
        benchmark_return = pd.Series(
            pd.to_numeric(benchmark_frame["benchmark_return"], errors="coerce").to_numpy(),
            index=pd.to_datetime(benchmark_frame["trade_date"]),
            name="benchmark_return",
        ).dropna()
    else:
        if args.mode == "real":
            raise ValueError("real mode requires all four explicit stage-2 input artifacts")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            data = LocalDataLoader(args.data_dir, create_if_missing=True).load_all()
            factor_panel, factor_cols = build_factor_panel(data, horizon=1, index_code="000905.SH")
            benchmark_return = _benchmark_return_series(data, "000905.SH")
            labels = build_monthly_labels(data["daily_bar"]["trade_date"], final_holdout_start=protocol["final_holdout_start"])
            dates = pd.DatetimeIndex(pd.to_datetime(labels["signal_date"].unique()))
            labeled_panel = attach_monthly_label_returns(factor_panel, data["daily_bar"], labels)
            monthly_ic = build_monthly_factor_ic(labeled_panel, factor_cols, "monthly_forward_return", dates)
            monthly_returns = build_monthly_factor_returns(
                labeled_panel, factor_cols, "monthly_forward_return", dates, benchmark_return
            )
            state_variables = build_monthly_state_variables(
                factor_panel, _monthly_state_market(data), benchmark_return, labels
            )
        for item in caught:
            if item.category.__name__ not in {"FutureWarning", "RuntimeWarning"}:
                raise RuntimeError(f"unexpected input warning {item.category.__name__}: {item.message}")
        captured_input_warnings = list(caught)
    for frame_name, frame in (("monthly_ic", monthly_ic), ("monthly_returns", monthly_returns)):
        if not frame.empty:
            frame["signal_date"] = pd.to_datetime(frame["signal_date"])
            frame["availability_date"] = pd.to_datetime(frame["availability_date"])
            if bool((frame["availability_date"] <= frame["signal_date"]).any()):
                raise ValueError(f"{frame_name} violates label availability timing")
    time_series_config = dict(bundle.project.get("time_series", {}))
    time_series_config["mode"] = args.mode
    time_series_config["pit_gate_passed"] = pit_gate_passed
    dates = pd.DatetimeIndex(pd.to_datetime(monthly_ic.get("signal_date", pd.Series(dtype="datetime64[ns]")).dropna().unique()))
    result = run_stage46_models(
        monthly_ic,
        monthly_returns,
        state_variables,
        benchmark_return,
        config=time_series_config,
        rebalance_dates=dates,
        final_holdout_start=protocol["final_holdout_start"],
        mode=args.mode,
    )
    if captured_input_warnings:
        captured = pd.DataFrame([{
            "module": "input_build", "as_of_date": pd.NaT, "model": "sample_builder",
            "warning_category": item.category.__name__, "message": str(item.message)[:500],
            "model_version": "time-series-v2",
        } for item in captured_input_warnings])
        result["model_warnings"] = pd.concat([result["model_warnings"], captured], ignore_index=True)
    for name, frame in result.items():
        frame.to_csv(out / f"{name}.csv", index=False, encoding="utf-8")
    input_hashes = (
        {name: file_sha256(path) for name, path in input_paths.items()}
        if input_paths else {
            "monthly_ic": dataframe_sha256(monthly_ic),
            "monthly_returns": dataframe_sha256(monthly_returns),
            "state_variables": dataframe_sha256(state_variables),
            "benchmark_returns": dataframe_sha256(benchmark_return.rename_axis("trade_date").reset_index()),
        }
    )
    overall = result["stage46_status"]
    overall_status = str(overall.loc[overall["module"].eq("overall"), "status"].iloc[0])
    summary = {
        "command": "run-time-series-models",
        "mode": args.mode,
        "status": overall_status,
        "synthetic_engineering_only": args.mode == "sample",
        "final_holdout_start": protocol["final_holdout_start"],
        "protocol_sha256": protocol["protocol_sha256"],
        "project_config_sha256": file_sha256(args.project_config),
        "experiment_registry_sha256": file_sha256(args.experiment_registry),
        "input_hashes": input_hashes,
        "output_files": sorted(str(path) for path in out.glob("*.csv")),
    }
    (out / "stage46_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    if args.mode == "real" and overall_status != "dynamic_ready":
        return 2
    return 0


def _cmd_run_portfolio_ablation(args: argparse.Namespace) -> int:
    out = ensure_dir(args.output_dir)
    protocol = load_research_protocol(args.protocol)
    if protocol["mode"] != args.mode:
        raise ValueError(f"protocol mode {protocol['mode']} does not match --mode {args.mode}")
    pit_gate_passed = False
    if args.mode == "real":
        if not args.pit_gate_summary:
            raise ValueError("real mode requires --pit-gate-summary from the completed real data gate")
        gate_path = Path(args.pit_gate_summary)
        if not gate_path.exists():
            raise FileNotFoundError(gate_path)
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        pit_gate_passed = gate.get("status") == "passed"
        if not pit_gate_passed:
            raise ValueError("real PIT data gate is not passed")
        if not args.stage46_dir:
            raise ValueError("real mode requires --stage46-dir with completed stage 4-6 artifacts")
    registry = pd.read_csv(args.experiment_registry)
    validate_kalman_registry(registry)
    bundle = load_config_bundle(args.project_config, args.factor_config, args.backtest_config)
    validate_config_bundle(bundle)
    explicit = [args.monthly_ic, args.monthly_returns, args.state_variables, args.benchmark_returns]
    if any(explicit) and not all(explicit):
        raise ValueError("monthly IC, monthly returns, state variables and benchmark returns must be supplied together")
    input_paths: dict[str, Path] = {}
    if all(explicit):
        input_paths = {
            "monthly_ic": Path(args.monthly_ic),
            "monthly_returns": Path(args.monthly_returns),
            "state_variables": Path(args.state_variables),
            "benchmark_returns": Path(args.benchmark_returns),
        }
        for name, path in input_paths.items():
            if not path.exists():
                raise FileNotFoundError(f"{name}: {path}")
        monthly_ic = pd.read_csv(input_paths["monthly_ic"])
        monthly_returns = pd.read_csv(input_paths["monthly_returns"])
        state_variables = pd.read_csv(input_paths["state_variables"])
        benchmark_frame = pd.read_csv(input_paths["benchmark_returns"])
        required_benchmark = {"trade_date", "benchmark_return"}
        if not required_benchmark.issubset(benchmark_frame.columns):
            raise ValueError("benchmark returns require trade_date,benchmark_return")
        benchmark_return = pd.Series(
            pd.to_numeric(benchmark_frame["benchmark_return"], errors="coerce").to_numpy(),
            index=pd.to_datetime(benchmark_frame["trade_date"]),
            name="benchmark_return",
        ).dropna()
    else:
        if args.mode == "real":
            raise ValueError("real mode requires all four explicit stage-2 input artifacts")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            data = LocalDataLoader(args.data_dir, create_if_missing=True).load_all()
            factor_panel, factor_cols = build_factor_panel(data, horizon=1, index_code="000905.SH")
            benchmark_return = _benchmark_return_series(data, "000905.SH")
            labels = build_monthly_labels(data["daily_bar"]["trade_date"], final_holdout_start=protocol["final_holdout_start"])
            dates = pd.DatetimeIndex(pd.to_datetime(labels["signal_date"].unique()))
            labeled_panel = attach_monthly_label_returns(factor_panel, data["daily_bar"], labels)
            monthly_ic = build_monthly_factor_ic(labeled_panel, factor_cols, "monthly_forward_return", dates)
            monthly_returns = build_monthly_factor_returns(
                labeled_panel, factor_cols, "monthly_forward_return", dates, benchmark_return
            )
            state_variables = build_monthly_state_variables(
                factor_panel, _monthly_state_market(data), benchmark_return, labels
            )
        for item in caught:
            if item.category.__name__ not in {"FutureWarning", "RuntimeWarning"}:
                raise RuntimeError(f"unexpected input warning {item.category.__name__}: {item.message}")
    for frame_name, frame in (("monthly_ic", monthly_ic), ("monthly_returns", monthly_returns)):
        if not frame.empty:
            frame["signal_date"] = pd.to_datetime(frame["signal_date"])
            frame["availability_date"] = pd.to_datetime(frame["availability_date"])
            if bool((frame["availability_date"] <= frame["signal_date"]).any()):
                raise ValueError(f"{frame_name} violates label availability timing")
    artifact_paths: dict[str, Path] = {}
    artifacts: dict[str, pd.DataFrame] | None = None
    if args.mode == "real":
        stage46_dir = Path(args.stage46_dir)
        if not stage46_dir.exists():
            raise FileNotFoundError(stage46_dir)
        artifacts = {}
        for key in ARTIFACT_KEYS:
            path = stage46_dir / f"{key}.csv"
            if path.exists():
                artifacts[key] = pd.read_csv(path)
                artifact_paths[f"stage46_{key}"] = path
    time_series_config = dict(bundle.project.get("time_series", {}))
    time_series_config["mode"] = args.mode
    time_series_config["pit_gate_passed"] = pit_gate_passed
    dates = pd.DatetimeIndex(pd.to_datetime(monthly_ic.get("signal_date", pd.Series(dtype="datetime64[ns]")).dropna().unique()))
    cost_multipliers = {
        str(name): float(value)
        for name, value in bundle.backtest.get("robustness", {}).get("cost_multipliers", {}).items()
    } or None
    result = run_stage7_ablation(
        monthly_ic,
        monthly_returns,
        state_variables,
        benchmark_return,
        artifacts=artifacts,
        config=time_series_config,
        cost_config=bundle.cost,
        cost_multipliers=cost_multipliers,
        rebalance_dates=dates,
        final_holdout_start=protocol["final_holdout_start"],
        mode=args.mode,
    )
    for name, frame in result.items():
        frame.to_csv(out / f"{name}.csv", index=False, encoding="utf-8")
    input_hashes = (
        {name: file_sha256(path) for name, path in input_paths.items()}
        if input_paths else {
            "monthly_ic": dataframe_sha256(monthly_ic),
            "monthly_returns": dataframe_sha256(monthly_returns),
            "state_variables": dataframe_sha256(state_variables),
            "benchmark_returns": dataframe_sha256(benchmark_return.rename_axis("trade_date").reset_index()),
        }
    )
    input_hashes.update({name: file_sha256(path) for name, path in artifact_paths.items()})
    overall = result["ablation_status"]
    overall_status = str(overall.loc[overall["portfolio_id"].eq("overall"), "status"].iloc[0])
    summary = {
        "command": "run-portfolio-ablation",
        "mode": args.mode,
        "status": overall_status,
        "synthetic_engineering_only": args.mode == "sample",
        "final_holdout_start": protocol["final_holdout_start"],
        "protocol_sha256": protocol["protocol_sha256"],
        "project_config_sha256": file_sha256(args.project_config),
        "experiment_registry_sha256": file_sha256(args.experiment_registry),
        "input_hashes": input_hashes,
        "output_files": sorted(str(path) for path in out.glob("*.csv")),
    }
    (out / "stage7_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    if args.mode == "real" and overall_status != "ablation_complete":
        return 2
    return 0


def _cmd_run_promotion_audit(args: argparse.Namespace) -> int:
    out = ensure_dir(args.output_dir)
    protocol = load_research_protocol(args.protocol)
    if protocol["mode"] != args.mode:
        raise ValueError(f"protocol mode {protocol['mode']} does not match --mode {args.mode}")
    pit_gate_passed = False
    data_gate_status = None
    if args.mode == "real":
        if not args.pit_gate_summary:
            raise ValueError("real mode requires --pit-gate-summary from the completed real data gate")
        gate_path = Path(args.pit_gate_summary)
        if not gate_path.exists():
            raise FileNotFoundError(gate_path)
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        data_gate_status = gate.get("status")
        pit_gate_passed = gate.get("status") == "passed"
        if not pit_gate_passed:
            raise ValueError("real PIT data gate is not passed")
        if not args.stage7_dir:
            raise ValueError("real mode requires --stage7-dir with completed stage 7 artifacts")
    registry = pd.read_csv(args.experiment_registry)
    validate_kalman_registry(registry)
    bundle = load_config_bundle(args.project_config, args.factor_config, args.backtest_config)
    validate_config_bundle(bundle)

    input_hashes: dict[str, str] = {}
    auxiliary: dict[str, pd.DataFrame] = {}
    if args.stage7_dir:
        stage7_dir = Path(args.stage7_dir)
        if not stage7_dir.exists():
            raise FileNotFoundError(stage7_dir)
        frames: dict[str, pd.DataFrame] = {}
        for name in (*STAGE7_INPUT_KEYS, "kalman_trial_registry", "execution_compliance_summary"):
            path = stage7_dir / f"{name}.csv"
            if path.exists():
                frame = pd.read_csv(path)
                input_hashes[f"stage7_{name}"] = file_sha256(path)
            elif name in STAGE7_INPUT_KEYS:
                raise FileNotFoundError(f"stage 7 artifact missing: {path}")
            else:
                continue
            if name in STAGE7_INPUT_KEYS:
                frames[name] = frame
            else:
                auxiliary[name] = frame
    else:
        if args.mode == "real":
            raise ValueError("real mode requires --stage7-dir with completed stage 7 artifacts")
        frames = synthesize_stage7_frames()
        for name, frame in frames.items():
            frame.to_csv(out / f"{name}.csv", index=False, encoding="utf-8")
            input_hashes[f"synthetic_{name}"] = dataframe_sha256(frame)

    executed_trials = auxiliary.get("kalman_trial_registry")
    execution_violations = None
    compliance = auxiliary.get("execution_compliance_summary")
    if compliance is not None and "violations" in compliance.columns:
        execution_violations = int(pd.to_numeric(compliance["violations"], errors="coerce").fillna(0).sum())
    dynamic_cfg = bundle.project.get("time_series", {}).get("dynamic_weights", {})
    primary_trial = (
        float(dynamic_cfg.get("process_variance", 0.001)),
        float(dynamic_cfg.get("observation_variance", 0.01)),
        float(dynamic_cfg.get("turnover_penalty", 0.20)),
    )
    result = run_stage8_promotion_audit(
        frames,
        registry,
        promotion_config=bundle.project.get("promotion", {}),
        executed_trials=executed_trials,
        primary_trial=primary_trial,
        execution_violations=execution_violations,
        mode=args.mode,
        pit_gate_passed=pit_gate_passed,
    )
    for name, frame in result.items():
        frame.to_csv(out / f"{name}.csv", index=False, encoding="utf-8")
    conclusion_row = result["promotion_conclusion"].iloc[0]
    conclusion = str(conclusion_row["conclusion"])
    summary = {
        "command": "run-promotion-audit",
        "mode": args.mode,
        "status": conclusion,
        "dynamic_ready": bool(conclusion_row["dynamic_ready"]),
        "synthetic_engineering_only": args.mode == "sample",
        "final_holdout_start": protocol["final_holdout_start"],
        "protocol_sha256": protocol["protocol_sha256"],
        "project_config_sha256": file_sha256(args.project_config),
        "experiment_registry_sha256": file_sha256(args.experiment_registry),
        "input_hashes": input_hashes,
        "output_files": sorted(str(path) for path in out.glob("*.csv")),
    }
    (out / "stage8_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    write_evidence_manifest(
        out,
        run_metadata={
            "run_id": f"stage8-promotion-audit-{args.mode}",
            "mode": args.mode,
            "protocol_sha256": protocol["protocol_sha256"],
            "data_gate_status": data_gate_status,
        },
        claims=[
            {
                "claim_id": "stage8_promotion_audit",
                "status": "supported" if conclusion == "production_candidate" else "evaluated_not_promoted",
                "evidence": [f"{name}.csv" for name in result] + ["stage8_summary.json"],
            },
            {
                "claim_id": "stage7_portfolio_ablation",
                "status": "supported_upstream",
                "evidence": [f"{name}.csv" for name in STAGE7_INPUT_KEYS] + ["stage7_summary.json"],
            },
        ],
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    if args.mode == "real" and conclusion != "production_candidate":
        return 2
    return 0


def _add_pipeline_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--data-dir", default="data/sample")
    parser.add_argument("--output-dir", default="outputs/runs")
    parser.add_argument("--mode", choices=["sample", "real"], default="sample")
    parser.add_argument("--run-id")
    parser.add_argument("--horizon", type=int)
    parser.add_argument("--top-n", type=int)
    parser.add_argument("--max-weight", type=float)
    parser.add_argument("--project-config", default="config/project_config.yaml")
    parser.add_argument("--factor-config", default="config/factor_config.yaml")
    parser.add_argument("--backtest-config", default="config/backtest_config.yaml")
    parser.add_argument("--fail-on-quality", action="store_true")


def _run_pipeline_command(args: argparse.Namespace, robustness: bool) -> dict[str, object]:
    return run_research_pipeline(
        data_dir=args.data_dir,
        output_root=args.output_dir,
        mode=args.mode,
        horizon=args.horizon,
        top_n=args.top_n,
        max_weight=args.max_weight,
        project_config_path=args.project_config,
        config_path=args.factor_config,
        backtest_config_path=args.backtest_config,
        run_id=args.run_id,
        fail_on_quality=args.fail_on_quality or None,
        robustness=robustness,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="A-share multi-factor research helper CLI.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("version", help="Show package, Python, pandas and configuration information.")

    gen = sub.add_parser("generate-sample", help="Generate deterministic sample CSV files.")
    gen.add_argument("--output-dir", default="data/sample")

    run = sub.add_parser("run-sample", help="Run sample factor research pipeline.")
    run.add_argument("--data-dir", default="data/sample")
    run.add_argument("--output-dir", default="reports/figures")

    fetch = sub.add_parser("fetch-data", help="Fetch standardized real data through AkShare.")
    fetch.add_argument("--start-date", required=True)
    fetch.add_argument("--end-date")
    fetch.add_argument("--symbols", default="", help="Comma-separated ts_code list for per-stock endpoints.")
    fetch.add_argument("--symbols-file", help="Reviewed CSV/text universe; current stock lists are not a PIT substitute.")
    fetch.add_argument("--tables", default="trade_calendar,stock_basic,daily_bar,benchmark_index")
    fetch.add_argument("--index-code", default="000905.SH")
    fetch.add_argument("--output-dir", default="data/raw")
    fetch.add_argument("--batch-id", required=True)
    fetch.add_argument("--resume", action="store_true")
    fetch.add_argument("--format", choices=["csv", "parquet"], default="csv")

    quality = sub.add_parser("quality-check", help="Audit standardized local data tables.")
    quality.add_argument("--data-dir", default="data/sample")
    quality.add_argument("--output-dir", default="reports")
    quality.add_argument("--mode", choices=["sample", "real"], default="sample")
    quality.add_argument("--fail-on-blocking", action="store_true")
    quality.add_argument("--required-start", default="2015-01-01")
    quality.add_argument("--index-code", default="000905.SH")
    quality.add_argument("--min-coverage", type=float, default=0.95)

    import_data = sub.add_parser("import-data", help="Normalize standard local tables and create data_manifest.json.")
    import_data.add_argument("--source-dir", required=True)
    import_data.add_argument("--output-dir", required=True)
    import_data.add_argument("--mapping", help="Optional YAML mapping of source column names to standard names.")
    import_data.add_argument("--format", choices=["csv", "parquet"], default="parquet")
    import_data.add_argument("--mode", choices=["sample", "real"], default="sample")
    import_data.add_argument("--source-registry", help="Required in real mode; contains source, license, PIT and unit evidence.")

    pipeline = sub.add_parser("run-pipeline", help="Run staged research pipeline into outputs/runs/<run_id>.")
    _add_pipeline_arguments(pipeline)

    robust = sub.add_parser("run-robustness", help="Run pipeline plus cost, delay and capacity scenarios.")
    _add_pipeline_arguments(robust)

    describe = sub.add_parser("describe-run", help="Print a completed run summary.")
    describe.add_argument("run_dir")

    labels = sub.add_parser("label-events", help="Dry-run auditable event labeling; no external API is called.")
    labels.add_argument("--input", required=True)
    labels.add_argument("--output", required=True)
    labels.add_argument("--cache", default="outputs/llm/label_cache.jsonl")
    labels.add_argument("--review-sample-size", type=int, default=50)
    labels.add_argument("--artifact-dir", default=None,
                        help="Optional directory to write the R1-E1 rule-baseline artifact (labels.csv + manifest).")

    prepare_text = sub.add_parser(
        "prepare-text-events",
        help="Build R1 PIT/dedup/entity-review artifacts from an already authorised local text table.",
    )
    prepare_text.add_argument("--input", required=True)
    prepare_text.add_argument("--output-dir", required=True)
    prepare_text.add_argument("--stock-registry", help="Optional CSV with stock_code or ts_code for mapping checks.")
    prepare_text.add_argument("--near-duplicate-threshold", type=float, default=0.85)
    prepare_text.add_argument("--near-duplicate-window-days", type=int, default=7)

    label_representation = sub.add_parser(
        "build-r1-label-representation",
        help="Package prepared PIT metadata and rule/LLM labels into a draft TextRepresentationArtifact.",
    )
    label_representation.add_argument("--prepared-events", required=True)
    label_representation.add_argument("--labels", required=True)
    label_representation.add_argument("--output-dir", required=True)
    label_representation.add_argument("--representation-id", required=True)
    label_representation.add_argument("--representation-type", choices=["rule_labels", "llm_labels"], required=True)
    label_representation.add_argument("--representation-version")
    label_representation.add_argument("--model-revision", required=True)
    label_representation.add_argument("--model-license-status", required=True)
    label_representation.add_argument("--preprocessing-version", default="r1_text_preparation_v1")
    label_representation.add_argument("--text-manifest")
    label_representation.add_argument("--trial-id")

    r1_protocol = sub.add_parser(
        "validate-r1-protocol",
        help="Validate the frozen-evaluator R1 contract and write a non-promotional receipt.",
    )
    r1_protocol.add_argument("--protocol", default="config/r1_protocol.template.yaml")
    r1_protocol.add_argument("--receipt")

    r1_evaluator = sub.add_parser(
        "run-r1-fixed-evaluator",
        help="Run the fixed linear R1 evaluator; refuses draft/unapproved protocols.",
    )
    r1_evaluator.add_argument("--protocol", required=True)
    r1_evaluator.add_argument("--panel", required=True)
    r1_evaluator.add_argument("--base-features", default="")
    r1_evaluator.add_argument("--text-features", required=True)
    r1_evaluator.add_argument("--target-col", default="target_return")
    r1_evaluator.add_argument("--signal-date-col", default="signal_date")
    r1_evaluator.add_argument("--label-end-date-col", default="label_end_date")
    r1_evaluator.add_argument("--asset-col", default="ts_code")
    r1_evaluator.add_argument("--output-dir", required=True)
    r1_evaluator.add_argument("--allow-final-holdout", action="store_true")
    r1_evaluator.add_argument("--final-holdout-access-ref")

    quality_all = sub.add_parser("quality", help="Run compile, tests, CLI and notebook smoke gates.")
    quality_all.add_argument("--skip-notebooks", action="store_true")
    quality_all.add_argument("--require-ruff", action="store_true")
    quality_all.add_argument("--update-artifacts", action="store_true")

    validate_config = sub.add_parser("validate-config", help="Validate configuration values and reject unconsumed keys.")
    validate_config.add_argument("--project-config", default="config/project_config.yaml")
    validate_config.add_argument("--factor-config", default="config/factor_config.yaml")
    validate_config.add_argument("--backtest-config", default="config/backtest_config.yaml")

    verify_data = sub.add_parser("verify-data", help="Verify standardized data schema and content hashes.")
    verify_data.add_argument("--data-dir", required=True)
    verify_data.add_argument("--mode", choices=["sample", "real"], default="real")

    research = sub.add_parser("run-research", help="Run a frozen research protocol.")
    research.add_argument("--protocol", required=True)
    research.add_argument("--run-id")
    research.add_argument("--robustness", action="store_true")

    advisor = sub.add_parser("build-advisor-report", help="Build the advisor DOCX from one completed run directory.")
    advisor.add_argument("--run-dir", required=True)
    advisor.add_argument("--output")

    sub.add_parser("build-report", help="Build the checked-in Markdown research report as PDF.")

    monthly = sub.add_parser("build-monthly-sample", help="Build monthly factor IC/returns/state-variable artifacts.")
    monthly.add_argument("--data-dir", default="data/sample")
    monthly.add_argument("--output-dir", default="outputs/monthly")
    monthly.add_argument("--mode", choices=["sample", "real"], default="sample")
    monthly.add_argument("--project-config", default="config/project_config.yaml")
    monthly.add_argument("--factor-config", default="config/factor_config.yaml")
    monthly.add_argument("--backtest-config", default="config/backtest_config.yaml")
    monthly.add_argument("--required-start", default="2015-01-01")
    monthly.add_argument("--final-holdout-start", default="2024-01-01")
    monthly.add_argument("--min-coverage", type=float, default=0.95)

    baselines = sub.add_parser("run-time-series-baselines", help="Run point-in-time time-series baseline forecasts and diagnostics.")
    baselines.add_argument("--data-dir", default="data/sample")
    baselines.add_argument("--output-dir", default="outputs/baselines")
    baselines.add_argument("--monthly-ic", help="Optional path to monthly_factor_ic.csv")
    baselines.add_argument("--monthly-returns", help="Optional path to monthly_factor_returns.csv")
    baselines.add_argument("--state-variables", help="Optional path to monthly_state_variables.csv")
    baselines.add_argument("--evaluation-start", default="2018-01-01")
    baselines.add_argument("--evaluation-end", default="2023-12-31")
    baselines.add_argument("--final-holdout-start", default="2024-01-01")

    stage46 = sub.add_parser("run-time-series-models", help="Run strict stage 4-6 Kalman, HMM, volatility and DCC research.")
    stage46.add_argument("--data-dir", default="data/sample")
    stage46.add_argument("--output-dir", default="outputs/stage46")
    stage46.add_argument("--mode", choices=["sample", "real"], default="sample")
    stage46.add_argument("--monthly-ic")
    stage46.add_argument("--monthly-returns")
    stage46.add_argument("--state-variables")
    stage46.add_argument("--benchmark-returns")
    stage46.add_argument("--protocol", default="config/research_protocol.yaml")
    stage46.add_argument("--experiment-registry", default="config/experiment_registry.csv")
    stage46.add_argument("--project-config", default="config/project_config.yaml")
    stage46.add_argument("--factor-config", default="config/factor_config.yaml")
    stage46.add_argument("--backtest-config", default="config/backtest_config.yaml")
    stage46.add_argument("--pit-gate-summary", help="Required in real mode; JSON summary with status=passed.")

    stage7 = sub.add_parser("run-portfolio-ablation", help="Run stage 7 fixed portfolio schemes and ablation experiments.")
    stage7.add_argument("--data-dir", default="data/sample")
    stage7.add_argument("--output-dir", default="outputs/stage7")
    stage7.add_argument("--mode", choices=["sample", "real"], default="sample")
    stage7.add_argument("--monthly-ic")
    stage7.add_argument("--monthly-returns")
    stage7.add_argument("--state-variables")
    stage7.add_argument("--benchmark-returns")
    stage7.add_argument("--stage46-dir", help="Required in real mode; directory with stage 4-6 output CSVs.")
    stage7.add_argument("--protocol", default="config/research_protocol.yaml")
    stage7.add_argument("--experiment-registry", default="config/experiment_registry.csv")
    stage7.add_argument("--project-config", default="config/project_config.yaml")
    stage7.add_argument("--factor-config", default="config/factor_config.yaml")
    stage7.add_argument("--backtest-config", default="config/backtest_config.yaml")
    stage7.add_argument("--pit-gate-summary", help="Required in real mode; JSON summary with status=passed.")

    stage8 = sub.add_parser("run-promotion-audit", help="Run stage 8 statistical, overfitting and promotion audit.")
    stage8.add_argument("--output-dir", default="outputs/stage8")
    stage8.add_argument("--mode", choices=["sample", "real"], default="sample")
    stage8.add_argument("--stage7-dir", help="Required in real mode; directory with stage 7 output CSVs.")
    stage8.add_argument("--protocol", default="config/research_protocol.yaml")
    stage8.add_argument("--experiment-registry", default="config/experiment_registry.csv")
    stage8.add_argument("--project-config", default="config/project_config.yaml")
    stage8.add_argument("--factor-config", default="config/factor_config.yaml")
    stage8.add_argument("--backtest-config", default="config/backtest_config.yaml")
    stage8.add_argument("--pit-gate-summary", help="Required in real mode; JSON summary with status=passed.")

    args = parser.parse_args()
    try:
        if args.command == "version":
            bundle = load_config_bundle()
            print(json.dumps({
                "package_version": __version__, "python_version": sys.version.split()[0],
                "pandas_version": pd.__version__, "cwd": str(Path.cwd()),
                "config_paths": {key: str(path) for key, path in bundle.paths.items()},
            }, ensure_ascii=False, indent=2))
        elif args.command == "generate-sample":
            paths = write_sample_data(args.output_dir)
            print(json.dumps({k: str(v) for k, v in paths.items()}, ensure_ascii=False, indent=2))
        elif args.command == "run-sample":
            result = run_sample_pipeline(args.data_dir, args.output_dir)
            print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))
        elif args.command == "fetch-data":
            raise SystemExit(_cmd_fetch_data(args))
        elif args.command == "quality-check":
            raise SystemExit(_cmd_quality_check(args))
        elif args.command == "import-data":
            raise SystemExit(_cmd_import_data(args))
        elif args.command == "run-pipeline":
            result = _run_pipeline_command(args, robustness=False)
            print(json.dumps({"run_dir": str(result["run_dir"]), "metrics": result["metrics"]}, ensure_ascii=False, indent=2))
        elif args.command == "run-robustness":
            result = _run_pipeline_command(args, robustness=True)
            print(json.dumps({"run_dir": str(result["run_dir"]), "scenario_count": len(result["robustness_summary"])}, ensure_ascii=False, indent=2))
        elif args.command == "describe-run":
            summary = Path(args.run_dir) / "run_summary.md"
            if not summary.exists():
                raise FileNotFoundError(summary)
            print(summary.read_text(encoding="utf-8"))
        elif args.command == "label-events":
            raise SystemExit(_cmd_label_events(args))
        elif args.command == "prepare-text-events":
            raise SystemExit(_cmd_prepare_text_events(args))
        elif args.command == "build-r1-label-representation":
            raise SystemExit(_cmd_build_r1_label_representation(args))
        elif args.command == "validate-r1-protocol":
            raise SystemExit(_cmd_validate_r1_protocol(args))
        elif args.command == "run-r1-fixed-evaluator":
            raise SystemExit(_cmd_run_r1_evaluator(args))
        elif args.command == "quality":
            print(json.dumps(run_quality_checks(args.skip_notebooks, args.require_ruff, args.update_artifacts), ensure_ascii=False, indent=2, default=_json_default))
        elif args.command == "validate-config":
            bundle = load_config_bundle(args.project_config, args.factor_config, args.backtest_config)
            result = validate_config_bundle(bundle)
            print(json.dumps({
                "valid": result.is_valid,
                "warnings": result.warnings,
                "unconsumed_paths": result.unconsumed_paths,
                "config_paths": config_path_summary(bundle),
            }, ensure_ascii=False, indent=2))
        elif args.command == "verify-data":
            result = verify_data_directory(
                args.data_dir,
                require_manifest=args.mode == "real",
                expected_mode=args.mode,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))
        elif args.command == "run-research":
            protocol = load_research_protocol(args.protocol)
            result = run_research_pipeline(
                data_dir=protocol["data_dir"],
                output_root=protocol["output_root"],
                mode=protocol["mode"],
                project_config_path=protocol["project_config"],
                config_path=protocol["factor_config"],
                backtest_config_path=protocol["backtest_config"],
                run_id=args.run_id or protocol.get("run_id"),
                robustness=args.robustness,
                protocol=protocol,
            )
            print(json.dumps({"run_dir": str(result["run_dir"]), "metrics": result["metrics"]}, ensure_ascii=False, indent=2))
        elif args.command == "build-advisor-report":
            command = [sys.executable, "scripts/build_advisor_report_docx.py", "--run-dir", args.run_dir]
            if args.output:
                command.extend(["--output", args.output])
            completed = subprocess.run(
                command,
                check=False,
            )
            if completed.returncode:
                raise RuntimeError("Advisor report build failed")
        elif args.command == "build-report":
            completed = subprocess.run([sys.executable, "scripts/build_report_pdf.py"], check=False)
            if completed.returncode:
                raise RuntimeError("Report build failed")
        elif args.command == "build-monthly-sample":
            raise SystemExit(_cmd_build_monthly_sample(args))
        elif args.command == "run-time-series-baselines":
            raise SystemExit(_cmd_run_time_series_baselines(args))
        elif args.command == "run-time-series-models":
            raise SystemExit(_cmd_run_time_series_models(args))
        elif args.command == "run-portfolio-ablation":
            raise SystemExit(_cmd_run_portfolio_ablation(args))
        elif args.command == "run-promotion-audit":
            raise SystemExit(_cmd_run_promotion_audit(args))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
