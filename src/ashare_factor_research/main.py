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
from ashare_factor_research.data.data_loader import AkShareProvider, LocalDataLoader
from ashare_factor_research.data.import_standard import import_standard_tables
from ashare_factor_research.data.data_quality import (
    REAL_DATA_EXPECTED_TABLES,
    has_blocking_issues,
    write_data_quality_report,
)
from ashare_factor_research.data.sample_data import write_sample_data
from ashare_factor_research.pipeline import run_research_pipeline, run_sample_pipeline
from ashare_factor_research.llm.audit import sample_labels_for_review, write_llm_event_audit_report
from ashare_factor_research.llm.client import batch_label_events
from ashare_factor_research.quality import run_quality_checks
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


def _cmd_fetch_data(args: argparse.Namespace) -> int:
    tables = [item.strip() for item in args.tables.split(",") if item.strip()]
    symbols = [item.strip() for item in args.symbols.split(",") if item.strip()]
    provider = AkShareProvider(args.start_date, args.end_date, symbols=symbols, index_code=args.index_code)
    out_dir = ensure_dir(args.output_dir)
    manifest: dict[str, object] = {
        "provider": "akshare",
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "start_date": args.start_date,
        "end_date": args.end_date,
        "symbols": symbols,
        "index_code": args.index_code,
        "tables": {},
    }
    loaded = {}
    for table in tables:
        if table not in LOADERS:
            raise ValueError(f"Unknown table: {table}. Available: {sorted(LOADERS)}")
        loader = getattr(provider, LOADERS[table])
        df = loader()
        path = out_dir / f"{table}.{args.format}"
        _write_frame(df, path, args.format)
        loaded[table] = df
        manifest["tables"][table] = {
            "path": str(path),
            "rows": int(len(df)),
            "columns": list(df.columns),
        }
    manifest_path = out_dir / "fetch_manifest.json"
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
    print(
        json.dumps(
            {
                "tables": len(tables),
                "issues": int(len(issues)),
                "blocking": bool(blocking),
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
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, default=_json_default))
    return 0


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
    fetch.add_argument("--tables", default="trade_calendar,stock_basic,daily_bar,benchmark_index")
    fetch.add_argument("--index-code", default="000905.SH")
    fetch.add_argument("--output-dir", default="data/raw")
    fetch.add_argument("--format", choices=["csv", "parquet"], default="csv")

    quality = sub.add_parser("quality-check", help="Audit standardized local data tables.")
    quality.add_argument("--data-dir", default="data/sample")
    quality.add_argument("--output-dir", default="reports")
    quality.add_argument("--mode", choices=["sample", "real"], default="sample")
    quality.add_argument("--fail-on-blocking", action="store_true")

    import_data = sub.add_parser("import-data", help="Normalize standard local tables and create data_manifest.json.")
    import_data.add_argument("--source-dir", required=True)
    import_data.add_argument("--output-dir", required=True)
    import_data.add_argument("--mapping", help="Optional YAML mapping of source column names to standard names.")
    import_data.add_argument("--format", choices=["csv", "parquet"], default="parquet")

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

    sub.add_parser("build-report", help="Build the checked-in Markdown research report as PDF.")

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
            print(json.dumps(run_quality_checks(args.skip_notebooks, args.require_ruff), ensure_ascii=False, indent=2, default=_json_default))
        elif args.command == "build-report":
            completed = subprocess.run([sys.executable, "scripts/build_report_pdf.py"], check=False)
            if completed.returncode:
                raise RuntimeError("Report build failed")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
