from __future__ import annotations

import argparse
import json

from ashare_factor_research.data.sample_data import write_sample_data
from ashare_factor_research.pipeline import run_sample_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="A-share multi-factor research helper CLI.")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate-sample", help="Generate deterministic sample CSV files.")
    gen.add_argument("--output-dir", default="data/sample")

    run = sub.add_parser("run-sample", help="Run sample factor research pipeline.")
    run.add_argument("--data-dir", default="data/sample")
    run.add_argument("--output-dir", default="reports/figures")

    args = parser.parse_args()
    if args.command == "generate-sample":
        paths = write_sample_data(args.output_dir)
        print(json.dumps({k: str(v) for k, v in paths.items()}, ensure_ascii=False, indent=2))
    elif args.command == "run-sample":
        result = run_sample_pipeline(args.data_dir, args.output_dir)
        print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
