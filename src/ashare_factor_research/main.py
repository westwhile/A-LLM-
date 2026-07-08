from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

from ashare_factor_research.data.data_loader import AkShareProvider, LocalDataLoader
from ashare_factor_research.data.data_quality import (
    REAL_DATA_EXPECTED_TABLES,
    has_blocking_issues,
    write_data_quality_report,
)
from ashare_factor_research.data.sample_data import write_sample_data
from ashare_factor_research.pipeline import run_research_pipeline, run_sample_pipeline
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


def main() -> None:
    parser = argparse.ArgumentParser(description="A-share multi-factor research helper CLI.")
    sub = parser.add_subparsers(dest="command", required=True)

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

    pipeline = sub.add_parser("run-pipeline", help="Run staged research pipeline into outputs/runs/<run_id>.")
    pipeline.add_argument("--data-dir", default="data/sample")
    pipeline.add_argument("--output-dir", default="outputs/runs")
    pipeline.add_argument("--mode", choices=["sample", "real"], default="sample")
    pipeline.add_argument("--run-id")
    pipeline.add_argument("--horizon", type=int, default=20)
    pipeline.add_argument("--top-n", type=int, default=10)
    pipeline.add_argument("--max-weight", type=float, default=0.2)
    pipeline.add_argument("--fail-on-quality", action="store_true")

    args = parser.parse_args()
    try:
        if args.command == "generate-sample":
            paths = write_sample_data(args.output_dir)
            print(json.dumps({k: str(v) for k, v in paths.items()}, ensure_ascii=False, indent=2))
        elif args.command == "run-sample":
            result = run_sample_pipeline(args.data_dir, args.output_dir)
            print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))
        elif args.command == "fetch-data":
            raise SystemExit(_cmd_fetch_data(args))
        elif args.command == "quality-check":
            raise SystemExit(_cmd_quality_check(args))
        elif args.command == "run-pipeline":
            result = run_research_pipeline(
                data_dir=args.data_dir,
                output_root=args.output_dir,
                mode=args.mode,
                horizon=args.horizon,
                top_n=args.top_n,
                max_weight=args.max_weight,
                run_id=args.run_id,
                fail_on_quality=args.fail_on_quality or None,
            )
            print(json.dumps({"run_dir": str(result["run_dir"]), "metrics": result["metrics"]}, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
