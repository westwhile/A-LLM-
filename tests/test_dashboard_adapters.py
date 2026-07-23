"""dashboard.adapters 只读适配层测试。

只测适配层，不启动 Streamlit。覆盖：正常读取、缺文件降级、schema 不符降级、
run_id 混杂拒绝、读取前后源文件 sha256 不变、synthetic 标记透传。
测试只写入临时目录，不写入 reports/ 等仓库目录。
"""

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from dashboard.adapters import (
    STATUS_EMPTY,
    STATUS_MISSING,
    STATUS_OK,
    STATUS_RUN_ID_MISMATCH,
    STATUS_SCHEMA_MISMATCH,
    file_sha256,
    read_csv_artifact,
    validate_run_directory,
)
from dashboard.adapters.audit_reader import (
    load_overfit_audit,
    load_prediction_test_results,
)
from dashboard.adapters.data_quality_reader import (
    AUDIT_SCHEMAS as GATE_AUDIT_SCHEMAS,
    list_gate_dirs,
    load_audit_csv,
    load_data_gate_summary,
    load_gate_artifacts,
)
from dashboard.adapters.manifest_reader import (
    load_evidence_manifest,
    load_stage46_summary,
    manifest_synthetic_flag,
)
from dashboard.adapters.performance_reader import (
    find_ablation_dirs,
    load_ablation_nav,
)
from dashboard.adapters.run_catalog import discover_runs
from dashboard.adapters.time_series_reader import (
    TIME_SERIES_SCHEMAS,
    find_time_series_dirs,
    load_dynamic_factor_weights,
    load_regime_probabilities,
    load_stage46_status,
)


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8")


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


class DashboardAdapterFixtureMixin:
    """构建临时项目夹具：outputs/runs、stage46、gate 目录。"""

    def _make_project(self, root: Path) -> dict[str, Path]:
        run_dir = root / "outputs" / "runs" / "run-a"
        run_dir.mkdir(parents=True)
        _write_json(run_dir / "run_metadata.json", {
            "run_id": "run-a", "created_at": "2026-07-20T10:00:00", "mode": "sample",
        })
        _write_json(run_dir / "evidence_manifest.json", {
            "run_id": "run-a", "claims": [], "data_gate_status": None,
        })
        _write_json(run_dir / "data_manifest.json", {"run_id": "run-a", "files": {}})

        stage_dir = root / "outputs" / "stage46"
        stage_dir.mkdir(parents=True)
        _write_json(stage_dir / "stage46_summary.json", {
            "command": "run-time-series-models", "mode": "sample",
            "status": "insufficient_history", "synthetic_engineering_only": True,
        })
        weights = pd.DataFrame(
            [[pd.Timestamp("2022-01-31"), "factor_0", "FT-KALMAN-001", 1, 0.2, 0.01,
              0.012, 0.001, 0.03, 0.04, 0.8, 24, pd.Timestamp("2021-12-31"), "time-series-v2"]],
            columns=TIME_SERIES_SCHEMAS["dynamic_factor_weights"],
        )
        _write_csv(stage_dir / "dynamic_factor_weights.csv", weights)
        status = pd.DataFrame(
            [["overall", "insufficient_history", False, 0, "sample", True, "detail", "time-series-v2"]],
            columns=TIME_SERIES_SCHEMAS["stage46_status"],
        )
        _write_csv(stage_dir / "stage46_status.csv", status)

        gate_dir = root / "reports" / "gate" / "gate-fixture"
        gate_dir.mkdir(parents=True)
        _write_json(gate_dir / "data_gate_summary.json", {"status": "passed"})
        pit = pd.DataFrame(
            [["daily_bar", "000001.SZ", "2024Q4", "2025-03-01", "", "2025-03-03", "src", True, ""]],
            columns=GATE_AUDIT_SCHEMAS["pit_timing_audit"],
        )
        _write_csv(gate_dir / "pit_timing_audit.csv", pit)
        return {"run_dir": run_dir, "stage_dir": stage_dir, "gate_dir": gate_dir}


class CsvArtifactReadTest(unittest.TestCase):
    def test_read_existing_csv_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.csv"
            _write_csv(path, pd.DataFrame({"a": [1, 2], "b": [3, 4]}))
            result = read_csv_artifact(Path(tmp), "artifact.csv", expected_columns=["a"])
            self.assertEqual(result.status, STATUS_OK)
            self.assertTrue(result.ok)
            self.assertEqual(result.frame.shape, (2, 2))
            self.assertEqual(len(result.sha256), 64)

    def test_missing_file_degrades_without_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = read_csv_artifact(Path(tmp), "nope.csv", expected_columns=["a"])
            self.assertEqual(result.status, STATUS_MISSING)
            self.assertFalse(result.ok)
            self.assertIn("缺失", result.message)
            self.assertIsNone(result.frame)

    def test_empty_file_degrades(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "empty.csv").write_text("", encoding="utf-8")
            result = read_csv_artifact(Path(tmp), "empty.csv")
            self.assertEqual(result.status, STATUS_EMPTY)

    def test_schema_mismatch_reports_expected_and_actual_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_csv(Path(tmp) / "bad.csv", pd.DataFrame({"a": [1]}))
            result = read_csv_artifact(Path(tmp), "bad.csv", expected_columns=["a", "b", "c"])
            self.assertEqual(result.status, STATUS_SCHEMA_MISMATCH)
            self.assertEqual(result.expected_columns, ["a", "b", "c"])
            self.assertEqual(result.actual_columns, ["a"])
            self.assertIn("b", result.message)

    def test_run_id_mixing_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_csv(Path(tmp) / "mixed.csv", pd.DataFrame({
                "run_id": ["run-a", "run-b"], "value": [1, 2],
            }))
            result = read_csv_artifact(
                Path(tmp), "mixed.csv", expected_columns=["run_id"], expected_run_id="run-a",
            )
            self.assertEqual(result.status, STATUS_RUN_ID_MISMATCH)

    def test_run_id_consistent_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_csv(Path(tmp) / "ok.csv", pd.DataFrame({
                "run_id": ["run-a", "run-a"], "value": [1, 2],
            }))
            result = read_csv_artifact(
                Path(tmp), "ok.csv", expected_columns=["run_id"], expected_run_id="run-a",
            )
            self.assertEqual(result.status, STATUS_OK)


class RunCatalogTest(DashboardAdapterFixtureMixin, unittest.TestCase):
    def test_discover_runs_finds_pipeline_and_stage_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_project(root)
            entries = discover_runs(root)
            kinds = {entry.run_id: entry.kind for entry in entries}
            self.assertEqual(kinds["run-a"], "pipeline_run")
            self.assertEqual(kinds["stage46"], "stage46")
            stage = next(entry for entry in entries if entry.run_id == "stage46")
            self.assertEqual(stage.status, "insufficient_history")
            self.assertTrue(stage.synthetic_engineering_only)

    def test_run_id_directory_mismatch_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "outputs" / "runs" / "run-x"
            run_dir.mkdir(parents=True)
            _write_json(run_dir / "run_metadata.json", {"run_id": "run-y"})
            issues = validate_run_directory(run_dir)
            self.assertTrue(any("不一致" in issue for issue in issues))
            entries = discover_runs(root)
            self.assertTrue(entries[0].issues)

    def test_discover_runs_without_outputs_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(discover_runs(Path(tmp)), [])


class TimeSeriesReaderTest(DashboardAdapterFixtureMixin, unittest.TestCase):
    def test_load_dynamic_factor_weights_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            dirs = self._make_project(Path(tmp))
            result = load_dynamic_factor_weights(dirs["stage_dir"])
            self.assertEqual(result.status, STATUS_OK)
            self.assertEqual(result.frame.iloc[0]["factor"], "factor_0")

    def test_missing_artifact_degrades(self):
        with tempfile.TemporaryDirectory() as tmp:
            dirs = self._make_project(Path(tmp))
            result = load_regime_probabilities(dirs["stage_dir"])
            self.assertEqual(result.status, STATUS_MISSING)

    def test_old_schema_degrades_with_column_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            dirs = self._make_project(Path(tmp))
            _write_csv(dirs["stage_dir"] / "regime_probabilities.csv", pd.DataFrame({
                "as_of_date": ["2022-01-31"], "status": ["ok"],
            }))
            result = load_regime_probabilities(dirs["stage_dir"])
            self.assertEqual(result.status, STATUS_SCHEMA_MISMATCH)
            self.assertEqual(result.expected_columns, TIME_SERIES_SCHEMAS["regime_probabilities"])

    def test_stage46_status_synthetic_flag_passthrough(self):
        with tempfile.TemporaryDirectory() as tmp:
            dirs = self._make_project(Path(tmp))
            result = load_stage46_status(dirs["stage_dir"])
            self.assertEqual(result.status, STATUS_OK)
            self.assertTrue(result.synthetic_engineering_only)
            summary = load_stage46_summary(dirs["stage_dir"])
            self.assertTrue(manifest_synthetic_flag(summary))

    def test_find_time_series_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_project(root)
            found = find_time_series_dirs(root)
            self.assertIn(root / "outputs" / "stage46", found)


class DataQualityReaderTest(DashboardAdapterFixtureMixin, unittest.TestCase):
    def test_gate_artifacts_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dirs = self._make_project(root)
            self.assertEqual(list_gate_dirs(root), [dirs["gate_dir"]])
            summary = load_data_gate_summary(dirs["gate_dir"])
            self.assertEqual(summary.status, STATUS_OK)
            self.assertEqual(summary.data["status"], "passed")
            audit = load_audit_csv(dirs["gate_dir"], "pit_timing_audit")
            self.assertEqual(audit.status, STATUS_OK)
            results = load_gate_artifacts(dirs["gate_dir"])
            self.assertEqual(results["survivorship_audit"].status, STATUS_MISSING)


class PerformanceAndAuditReaderTest(unittest.TestCase):
    def test_ablation_missing_dir_and_file_degrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(find_ablation_dirs(root), [])
            result = load_ablation_nav(root / "outputs" / "stage7")
            self.assertEqual(result.status, STATUS_MISSING)

    def test_ablation_and_audit_fixtures_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stage7 = root / "outputs" / "stage7-ablation"
            _write_csv(stage7 / "ablation_nav.csv", pd.DataFrame({
                "date": ["2022-01-31"], "portfolio_id": ["A"], "nav": [1.0],
                "status": ["ok"], "model_version": ["time-series-v2"],
            }))
            self.assertEqual(find_ablation_dirs(root), [stage7])
            self.assertEqual(load_ablation_nav(stage7).status, STATUS_OK)

            stage8 = root / "outputs" / "stage8-audit"
            _write_csv(stage8 / "prediction_test_results.csv", pd.DataFrame({
                "test": ["DM"], "comparison": ["C-A"], "statistic": [2.1],
                "p_value": [0.03], "passed": [True], "fdr_q_value": [0.05],
                "fdr_5pct": [True], "effective_samples": [36],
                "status": ["ok"], "model_version": ["time-series-v2"],
            }))
            _write_csv(stage8 / "overfit_audit.csv", pd.DataFrame({
                "metric": ["dsr_probability"], "scope": ["best_dynamic"],
                "statistic": ["dsr"], "value": [0.97], "threshold": [0.95],
                "passed": [True], "p_value": [0.01], "fdr_q_value": [0.05],
                "fdr_5pct": [False], "trial_count": [12], "effective_samples": [36],
                "status": ["ok"], "detail": ["deflated sharpe probability"],
                "model_version": ["time-series-v2"],
            }))
            self.assertEqual(load_prediction_test_results(stage8).status, STATUS_OK)
            self.assertEqual(load_overfit_audit(stage8).status, STATUS_OK)


class ReadOnlyGuaranteeTest(DashboardAdapterFixtureMixin, unittest.TestCase):
    def test_source_files_unchanged_after_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dirs = self._make_project(root)
            files = [
                dirs["run_dir"] / "run_metadata.json",
                dirs["run_dir"] / "evidence_manifest.json",
                dirs["stage_dir"] / "stage46_summary.json",
                dirs["stage_dir"] / "dynamic_factor_weights.csv",
                dirs["stage_dir"] / "stage46_status.csv",
                dirs["gate_dir"] / "data_gate_summary.json",
                dirs["gate_dir"] / "pit_timing_audit.csv",
            ]
            before = {path: file_sha256(path) for path in files}

            discover_runs(root)
            load_evidence_manifest(dirs["run_dir"])
            load_stage46_summary(dirs["stage_dir"])
            load_dynamic_factor_weights(dirs["stage_dir"])
            load_stage46_status(dirs["stage_dir"])
            load_gate_artifacts(dirs["gate_dir"])
            load_regime_probabilities(dirs["stage_dir"])  # missing → 降级读取
            validate_run_directory(dirs["run_dir"])

            after = {path: file_sha256(path) for path in files}
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
