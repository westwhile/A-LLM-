import argparse
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ashare_factor_research.main import _cmd_run_promotion_audit
from ashare_factor_research.time_series.stage8 import STAGE8_SCHEMAS, synthesize_stage7_frames


class Stage8CliTest(unittest.TestCase):
    def _args(self, root: Path, mode: str, stage7_dir: Path | None) -> argparse.Namespace:
        gate_path = root / "pit_gate.json"
        gate_path.write_text('{"status":"passed"}', encoding="utf-8")
        return argparse.Namespace(
            output_dir=str(root / f"out_{mode}"), mode=mode,
            stage7_dir=str(stage7_dir) if stage7_dir is not None else None,
            protocol=f"config/research_protocol{'.real' if mode == 'real' else ''}.yaml",
            experiment_registry="config/experiment_registry.csv",
            project_config="config/project_config.yaml",
            factor_config="config/factor_config.yaml",
            backtest_config="config/backtest_config.yaml",
            pit_gate_summary=str(gate_path) if mode == "real" else None,
        )

    def test_sample_cli_synthesizes_stage7_and_marks_synthetic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(_cmd_run_promotion_audit(self._args(root, "sample", None)), 0)
            output = root / "out_sample"
            for name, columns in STAGE8_SCHEMAS.items():
                self.assertEqual(list(pd.read_csv(output / f"{name}.csv").columns), columns)
            summary = json.loads((output / "stage8_summary.json").read_text(encoding="utf-8"))
            self.assertTrue(summary["synthetic_engineering_only"])
            self.assertEqual(summary["command"], "run-promotion-audit")
            self.assertEqual(summary["status"], "research_candidate")
            self.assertFalse(summary["dynamic_ready"])
            self.assertIn("synthetic_ablation_status", summary["input_hashes"])
            conclusion = pd.read_csv(output / "promotion_conclusion.csv").iloc[0]
            self.assertEqual(conclusion["conclusion"], "research_candidate")
            self.assertFalse(bool(conclusion["dynamic_ready"]))
            manifest = json.loads((output / "evidence_manifest.json").read_text(encoding="utf-8"))
            claim_ids = {claim["claim_id"] for claim in manifest["claims"]}
            self.assertEqual(claim_ids, {"stage8_promotion_audit", "stage7_portfolio_ablation"})

    def test_real_cli_returns_nonzero_when_history_is_short(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames = synthesize_stage7_frames()
            status = frames["ablation_status"]
            status.loc[status["portfolio_id"].eq("overall"), "status"] = "insufficient_history"
            status.loc[status["portfolio_id"].eq("overall"), "oos_months"] = 24
            stage7_dir = root / "stage7"
            stage7_dir.mkdir()
            for name, frame in frames.items():
                frame.to_csv(stage7_dir / f"{name}.csv", index=False)
            self.assertEqual(_cmd_run_promotion_audit(self._args(root, "real", stage7_dir)), 2)
            output = root / "out_real"
            summary = json.loads((output / "stage8_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "insufficient_evidence")
            self.assertFalse(summary["synthetic_engineering_only"])
            self.assertFalse(summary["dynamic_ready"])
            conclusion = pd.read_csv(output / "promotion_conclusion.csv").iloc[0]
            self.assertEqual(conclusion["conclusion"], "insufficient_evidence")
            for name, columns in STAGE8_SCHEMAS.items():
                self.assertEqual(list(pd.read_csv(output / f"{name}.csv").columns), columns)

    def test_real_cli_requires_stage7_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                _cmd_run_promotion_audit(self._args(root, "real", None))


if __name__ == "__main__":
    unittest.main()
