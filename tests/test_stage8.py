import unittest

import numpy as np
import pandas as pd

from ashare_factor_research.time_series.stage8 import (
    GATE_ORDER,
    STAGE8_SCHEMAS,
    run_stage8_promotion_audit,
    synthesize_stage7_frames,
)


def _registry() -> pd.DataFrame:
    return pd.DataFrame([
        {"experiment_id": "FT-KALMAN-001", "module": "factor_timing", "model": "kalman_local_level",
         "parameters": "{}", "status": "preregistered"},
        {"experiment_id": "FT-KGRID-001", "module": "factor_timing", "model": "kalman_local_level_grid",
         "parameters": '{"process_variance":0.001,"observation_variance":0.01,"turnover_penalty":0.2}',
         "status": "preregistered"},
        {"experiment_id": "FT-KGRID-002", "module": "factor_timing", "model": "kalman_local_level_grid",
         "parameters": '{"process_variance":0.0001,"observation_variance":0.005,"turnover_penalty":0.0}',
         "status": "preregistered"},
    ])


class Stage8PromotionAuditTest(unittest.TestCase):
    def setUp(self):
        self.frames = synthesize_stage7_frames()
        self.registry = _registry()

    def _run(self, **kwargs):
        return run_stage8_promotion_audit(self.frames, self.registry, **kwargs)

    def _patch_ga(self, column, value):
        mask = self.frames["ablation_incremental"]["comparison"].eq("G-A")
        self.frames["ablation_incremental"].loc[mask, column] = value

    def _gate(self, result, name):
        row = result["promotion_gate_results"].set_index("gate").loc[name]
        return bool(row["passed"]), float(row["value"])

    def test_fixed_schemas_and_ten_gates(self):
        result = self._run(mode="sample")
        for name, columns in STAGE8_SCHEMAS.items():
            self.assertEqual(list(result[name].columns), columns)
        gates = result["promotion_gate_results"]
        self.assertEqual(list(gates["gate"]), list(GATE_ORDER))
        self.assertEqual(len(gates), 10)

    def test_all_gates_pass_sample_caps_at_research_candidate(self):
        result = self._run(mode="sample")
        self.assertTrue(bool(result["promotion_gate_results"]["passed"].all()))
        conclusion = result["promotion_conclusion"].iloc[0]
        self.assertEqual(conclusion["conclusion"], "research_candidate")
        self.assertEqual(int(conclusion["conclusion_level"]), 2)
        self.assertFalse(bool(conclusion["dynamic_ready"]))
        self.assertTrue(bool(conclusion["synthetic_engineering_only"]))

    def test_all_gates_pass_real_with_pit_gate_promotes(self):
        result = self._run(mode="real", pit_gate_passed=True)
        conclusion = result["promotion_conclusion"].iloc[0]
        self.assertEqual(conclusion["conclusion"], "production_candidate")
        self.assertEqual(int(conclusion["conclusion_level"]), 3)
        self.assertTrue(bool(conclusion["dynamic_ready"]))
        self.assertFalse(bool(conclusion["synthetic_engineering_only"]))

    def test_real_without_pit_gate_cannot_promote(self):
        result = self._run(mode="real", pit_gate_passed=False)
        conclusion = result["promotion_conclusion"].iloc[0]
        self.assertEqual(conclusion["conclusion"], "research_candidate")
        self.assertFalse(bool(conclusion["dynamic_ready"]))

    def test_incremental_annual_return_boundary(self):
        self._patch_ga("incremental_annual_return", 0.0)
        passed, value = self._gate(self._run(), "incremental_annual_return")
        self.assertFalse(passed)
        self.assertEqual(value, 0.0)
        self._patch_ga("incremental_annual_return", 1e-9)
        passed, _ = self._gate(self._run(), "incremental_annual_return")
        self.assertTrue(passed)

    def test_positive_year_ratio_boundary(self):
        self._patch_ga("positive_year_ratio", 0.5)
        passed, _ = self._gate(self._run(), "positive_year_ratio")
        self.assertFalse(passed)
        self._patch_ga("positive_year_ratio", 0.500001)
        passed, _ = self._gate(self._run(), "positive_year_ratio")
        self.assertTrue(passed)

    def test_ir_improvement_boundary(self):
        self._patch_ga("ir_improvement", 0.149)
        passed, _ = self._gate(self._run(), "ir_improvement")
        self.assertFalse(passed)
        self._patch_ga("ir_improvement", 0.15)
        passed, value = self._gate(self._run(), "ir_improvement")
        self.assertTrue(passed)
        self.assertAlmostEqual(value, 0.15, places=12)

    def test_max_drawdown_worsening_boundary(self):
        self._patch_ga("max_drawdown_change", -0.10)
        passed, _ = self._gate(self._run(), "max_drawdown_worsening")
        self.assertTrue(passed)
        self._patch_ga("max_drawdown_change", -0.100001)
        passed, _ = self._gate(self._run(), "max_drawdown_worsening")
        self.assertFalse(passed)

    def test_failed_gate_rejects_with_reason(self):
        self._patch_ga("ir_improvement", 0.0)
        result = self._run(mode="real", pit_gate_passed=True)
        conclusion = result["promotion_conclusion"].iloc[0]
        self.assertEqual(conclusion["conclusion"], "rejected")
        self.assertEqual(int(conclusion["conclusion_level"]), 0)
        self.assertIn("ir_improvement", conclusion["reasons"])
        self.assertFalse(bool(conclusion["dynamic_ready"]))

    def test_identical_portfolios_fail_dm_or_spa(self):
        returns = self.frames["ablation_portfolio_returns"]
        base = returns[returns["portfolio_id"].eq("A")]
        identical = []
        for portfolio_id in "BCDEFG":
            part = base.copy()
            part["portfolio_id"] = portfolio_id
            identical.append(part)
        self.frames["ablation_portfolio_returns"] = pd.concat([base, *identical], ignore_index=True)
        result = self._run()
        passed, value = self._gate(result, "dm_or_spa")
        self.assertFalse(passed)
        self.assertTrue(np.isnan(value))
        self.assertEqual(result["promotion_conclusion"].iloc[0]["conclusion"], "rejected")
        statuses = result["prediction_test_results"].set_index("test")["status"]
        self.assertNotEqual(statuses["spa"], "ok")

    def test_short_history_is_insufficient_evidence_not_rejected(self):
        status = self.frames["ablation_status"]
        status.loc[status["portfolio_id"].eq("overall"), "status"] = "insufficient_history"
        status.loc[status["portfolio_id"].eq("overall"), "oos_months"] = 24
        result = self._run(mode="real", pit_gate_passed=True)
        conclusion = result["promotion_conclusion"].iloc[0]
        self.assertEqual(conclusion["conclusion"], "insufficient_evidence")
        self.assertEqual(int(conclusion["conclusion_level"]), 1)
        self.assertFalse(bool(conclusion["dynamic_ready"]))
        for name in ("promotion_gate_results", "prediction_test_results", "overfit_audit"):
            self.assertEqual(len(result[name]), 1)
            self.assertEqual(result[name]["status"].iloc[0], "insufficient_history")
        for name, columns in STAGE8_SCHEMAS.items():
            self.assertEqual(list(result[name].columns), columns)

    def test_missing_stage7_artifact_is_insufficient_evidence(self):
        del self.frames["ablation_incremental"]
        result = self._run()
        conclusion = result["promotion_conclusion"].iloc[0]
        self.assertEqual(conclusion["conclusion"], "insufficient_evidence")
        self.assertEqual(result["promotion_gate_results"]["status"].iloc[0], "missing_input")

    def test_trial_registry_coverage_counts_and_unregistered_rejection(self):
        result = self._run()
        coverage = result["trial_registry_coverage"].iloc[0]
        self.assertEqual(int(coverage["registered_trials"]), 2)  # two grid triples + primary via local_level row
        self.assertGreaterEqual(int(coverage["registered_trials"]), 2)
        self.assertEqual(int(coverage["executed_trials"]), 1)
        self.assertEqual(float(coverage["coverage"]), 1.0)
        self.assertTrue(bool(coverage["passed"]))
        executed = pd.DataFrame([{
            "trial_id": "FT-KALMAN-999", "process_variance": 9.9, "observation_variance": 9.9,
            "turnover_penalty": 0.9, "prediction_count": 12,
        }])
        result = self._run(executed_trials=executed)
        coverage = result["trial_registry_coverage"].iloc[0]
        self.assertEqual(int(coverage["executed_trials"]), 2)
        self.assertAlmostEqual(float(coverage["coverage"]), 0.5, places=12)
        self.assertFalse(bool(coverage["passed"]))
        self.assertEqual(coverage["status"], "unregistered_trial")
        self.assertEqual(result["promotion_conclusion"].iloc[0]["conclusion"], "rejected")

    def test_dsr_trial_count_uses_preregistered_registry_count(self):
        result = self._run()
        dsr = result["overfit_audit"].set_index("metric").loc["dsr"]
        self.assertEqual(int(dsr["trial_count"]), 3)

    def test_execution_violations_gate(self):
        passed, value = self._gate(self._run(execution_violations=0), "execution_violations")
        self.assertTrue(passed)
        self.assertEqual(value, 0.0)
        result = self._run(execution_violations=1)
        passed, value = self._gate(result, "execution_violations")
        self.assertFalse(passed)
        self.assertEqual(value, 1.0)
        self.assertEqual(result["promotion_conclusion"].iloc[0]["conclusion"], "rejected")

    def test_min_oos_months_floor_and_mode_validation(self):
        with self.assertRaises(ValueError):
            self._run(promotion_config={"min_oos_months": 12})
        with self.assertRaises(ValueError):
            self._run(mode="production")


if __name__ == "__main__":
    unittest.main()
