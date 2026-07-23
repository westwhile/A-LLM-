import argparse
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from ashare_factor_research.main import _cmd_run_time_series_models
from ashare_factor_research.time_series.stage46 import SCHEMAS


class Stage46CliTest(unittest.TestCase):
    def _write_inputs(self, root: Path) -> dict[str, Path]:
        dates = pd.date_range("2019-01-31", periods=18, freq="ME")
        ic_rows = []
        return_rows = []
        for date in dates:
            for factor_index in range(6):
                factor = f"f{factor_index}"
                availability = date + pd.Timedelta(days=10)
                ic_rows.append({
                    "signal_date": date, "availability_date": availability, "factor": factor,
                    "rank_ic": 0.03 * (-1 if factor_index % 2 else 1), "asset_count": 100,
                })
                return_rows.append({
                    "signal_date": date, "availability_date": availability, "factor": factor,
                    "q5_minus_q1": 0.01 * (-1 if factor_index % 2 else 1),
                })
        states = pd.DataFrame({
            "signal_date": dates, "availability_date": dates,
            "benchmark_log_return": np.linspace(-0.02, 0.02, len(dates)),
            "realized_volatility_20": np.linspace(0.2, 0.1, len(dates)),
            "breadth": np.linspace(0.3, 0.7, len(dates)),
            "log_median_amount": 15.0,
        })
        daily_dates = pd.date_range("2019-01-01", "2020-07-31", freq="B")
        benchmark = pd.DataFrame({"trade_date": daily_dates, "benchmark_return": 0.001})
        frames = {
            "monthly_ic": pd.DataFrame(ic_rows),
            "monthly_returns": pd.DataFrame(return_rows),
            "state_variables": states,
            "benchmark_returns": benchmark,
        }
        paths = {}
        for name, frame in frames.items():
            path = root / f"{name}.csv"
            frame.to_csv(path, index=False)
            paths[name] = path
        return paths

    def _args(self, root: Path, paths: dict[str, Path], mode: str) -> argparse.Namespace:
        gate_path = root / "pit_gate.json"
        gate_path.write_text('{"status":"passed"}', encoding="utf-8")
        return argparse.Namespace(
            output_dir=str(root / f"out_{mode}"), mode=mode,
            monthly_ic=str(paths["monthly_ic"]), monthly_returns=str(paths["monthly_returns"]),
            state_variables=str(paths["state_variables"]), benchmark_returns=str(paths["benchmark_returns"]),
            protocol=f"config/research_protocol{'.real' if mode == 'real' else ''}.yaml",
            experiment_registry="config/experiment_registry.csv", project_config="config/project_config.yaml",
            factor_config="config/factor_config.yaml", backtest_config="config/backtest_config.yaml",
            data_dir="data/sample",
            pit_gate_summary=str(gate_path) if mode == "real" else None,
        )

    def test_sample_cli_writes_fixed_schemas_and_engineering_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._write_inputs(root)
            self.assertEqual(_cmd_run_time_series_models(self._args(root, paths, "sample")), 0)
            output = root / "out_sample"
            for name, columns in SCHEMAS.items():
                self.assertEqual(list(pd.read_csv(output / f"{name}.csv").columns), columns)
            summary = json.loads((output / "stage46_summary.json").read_text(encoding="utf-8"))
            self.assertTrue(summary["synthetic_engineering_only"])
            self.assertEqual(summary["status"], "insufficient_history")

    def test_real_cli_returns_nonzero_when_history_is_short(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._write_inputs(root)
            self.assertEqual(_cmd_run_time_series_models(self._args(root, paths, "real")), 2)


if __name__ == "__main__":
    unittest.main()
