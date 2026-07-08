import tempfile
import unittest
from pathlib import Path

from ashare_factor_research.data.sample_data import write_sample_data
from ashare_factor_research.pipeline import run_research_pipeline, run_sample_pipeline


class SmokePipelineTest(unittest.TestCase):
    def test_sample_pipeline_runs_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "sample"
            out_dir = root / "out"
            write_sample_data(data_dir)
            result = run_sample_pipeline(data_dir=data_dir, output_dir=out_dir, top_n=10, max_weight=0.2)
            self.assertGreaterEqual(len(result["factor_cols"]), 15)
            self.assertFalse(result["raw_coverage"]["by_date"].empty)
            self.assertFalse(result["processing_audit"].empty)
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
            self.assertTrue((out_dir / "factor_coverage_by_date.csv").exists())
            self.assertTrue((out_dir / "factor_processing_audit.csv").exists())
            self.assertTrue((out_dir / "annual_ic_summary.csv").exists())
            self.assertTrue((out_dir / "factor_decay.csv").exists())
            self.assertTrue((out_dir / "factor_spec_table.csv").exists())
            self.assertIn("execution_date", result["factor_panel"].columns)
            self.assertIn("target_return_end_date", result["factor_panel"].columns)

    def test_standard_run_pipeline_writes_stage_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "sample"
            output_dir = root / "runs"
            write_sample_data(data_dir)
            result = run_research_pipeline(
                data_dir=data_dir,
                output_root=output_dir,
                mode="sample",
                run_id="unit",
                top_n=10,
                max_weight=0.2,
            )
            run_dir = result["run_dir"]
            self.assertTrue((run_dir / "config_snapshot.yaml").exists())
            self.assertTrue((run_dir / "data_manifest.json").exists())
            self.assertTrue((run_dir / "data_quality_report.md").exists())
            self.assertTrue((run_dir / "metrics.csv").exists())
            self.assertTrue((run_dir / "orders.csv").exists())
            self.assertTrue((run_dir / "fills.csv").exists())
            self.assertTrue((run_dir / "positions.csv").exists())
            self.assertTrue((run_dir / "figures" / "industry_return_attribution.csv").exists())
            self.assertIn("information_ratio", result["metrics"])


if __name__ == "__main__":
    unittest.main()
