from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys

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
from ashare_factor_research.quality import run_quality_checks
from ashare_factor_research.time_series.research import (
    build_monthly_factor_ic,
    build_monthly_factor_returns,
    build_monthly_state_variables,
    build_standard_series,
    compare_preregistered_weight_schemes,
    run_time_series_baselines,
)
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
    print(json.dumps({"labels": len(labels), "output": str(output), "review": str(review_path)}, ensure_ascii=False))
    return 0


def _required_fields_from_specs(factor_specs: list) -> dict[str, list[str]]:
    """Map factor input columns to their likely source tables for coverage checks."""

    field_map: dict[str, set[str]] = {
        "daily_bar": {"amount", "adj_factor", "close"},
        "daily_basic": {"turnover_rate", "total_mv", "pb", "pe_ttm", "ps", "net_mf_amount", "large_order_net_mf_amount"},
        "financial_indicator": {"roe", "roa", "gross_margin", "debt_ratio", "operating_revenue", "total_assets", "revenue_yoy", "profit_yoy", "operating_cash_flow"},
    }
    required: dict[str, set[str]] = {name: set() for name in field_map}
    for spec in factor_specs:
        for column in spec.input_columns:
            for table, fields in field_map.items():
                if column in fields:
                    required[table].add(column)
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
    required_fields.setdefault("daily_bar", []).extend(["amount", "adj_factor"])

    trade_dates = data.get("trade_calendar", data["daily_bar"])["trade_date"]
    labels = build_monthly_labels(
        trade_dates,
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
    paths = write_monthly_artifacts(out, monthly_ic, monthly_returns, state_variables)
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
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
