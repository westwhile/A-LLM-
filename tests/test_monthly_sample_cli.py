import argparse
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ashare_factor_research.main import _cmd_build_monthly_sample
from ashare_factor_research.monthly_research import benchmark_returns_frame


class BenchmarkReturnsFrameTest(unittest.TestCase):
    def test_none_series_raises(self):
        with self.assertRaises(ValueError):
            benchmark_returns_frame(None)

    def test_nan_values_raise(self):
        series = pd.Series(
            [0.01, float("nan")],
            index=pd.to_datetime(["2020-01-31", "2020-02-28"]),
            name="benchmark_return",
        )
        with self.assertRaises(ValueError):
            benchmark_returns_frame(series)

    def test_duplicated_dates_raise(self):
        series = pd.Series([0.01, 0.02], index=pd.to_datetime(["2020-01-31", "2020-01-31"]))
        with self.assertRaises(ValueError):
            benchmark_returns_frame(series)

    def test_valid_series_schema_and_sorting(self):
        series = pd.Series([0.02, 0.01], index=pd.to_datetime(["2020-02-28", "2020-01-31"]))
        frame = benchmark_returns_frame(series)
        self.assertEqual(list(frame.columns), ["trade_date", "benchmark_return"])
        self.assertTrue(frame["trade_date"].is_monotonic_increasing)


class BuildMonthlySampleCliTest(unittest.TestCase):
    def test_sample_mode_writes_benchmark_returns_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "monthly"
            args = argparse.Namespace(
                data_dir="data/sample",
                output_dir=str(out),
                mode="sample",
                project_config="config/project_config.yaml",
                factor_config="config/factor_config.yaml",
                backtest_config="config/backtest_config.yaml",
                required_start="2015-01-01",
                final_holdout_start="2024-01-01",
                min_coverage=0.95,
            )
            self.assertEqual(_cmd_build_monthly_sample(args), 0)
            handoff = out / "benchmark_returns.csv"
            self.assertTrue(handoff.exists())
            frame = pd.read_csv(handoff)
            self.assertEqual(list(frame.columns), ["trade_date", "benchmark_return"])
            self.assertFalse(frame.empty)
            self.assertFalse(frame["benchmark_return"].isna().any())
            summary = json.loads((out / "monthly_sample_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["artifact_paths"]["benchmark_returns"], str(handoff))
            self.assertIn("benchmark_returns_sha256", summary)


if __name__ == "__main__":
    unittest.main()
