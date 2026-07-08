import tempfile
import unittest
from pathlib import Path

from ashare_factor_research.data.sample_data import write_sample_data
from ashare_factor_research.pipeline import run_sample_pipeline


class SmokePipelineTest(unittest.TestCase):
    def test_sample_pipeline_runs_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "sample"
            out_dir = root / "out"
            write_sample_data(data_dir)
            result = run_sample_pipeline(data_dir=data_dir, output_dir=out_dir, top_n=10, max_weight=0.2)
            self.assertGreater(len(result["factor_cols"]), 8)
            self.assertFalse(result["ic_table"].empty)
            self.assertFalse(result["portfolio"].empty)
            self.assertFalse(result["nav"].empty)
            self.assertFalse(result["orders"].empty)
            self.assertFalse(result["fills"].empty)
            self.assertFalse(result["positions"].empty)
            self.assertTrue((out_dir / "performance_metrics.csv").exists())
            self.assertTrue((out_dir / "sample_orders.csv").exists())
            self.assertTrue((out_dir / "sample_fills.csv").exists())
            self.assertTrue((out_dir / "sample_positions.csv").exists())


if __name__ == "__main__":
    unittest.main()
