import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import pandas as pd

from ashare_factor_research.analysis.attribution import cost_attribution
from ashare_factor_research.backtest.backtest_engine import run_event_backtest
from ashare_factor_research.backtest.compliance import audit_execution_compliance
from ashare_factor_research.config import load_config_bundle
from ashare_factor_research.data.import_standard import import_standard_tables, resolve_financial_revisions
from ashare_factor_research.data.provenance import build_data_manifest, dataframe_sha256, verify_data_directory
from ashare_factor_research.data.sample_data import write_sample_data
from ashare_factor_research.factor_testing.group_test import calc_non_overlapping_group_returns
from ashare_factor_research.factor_testing.inference import benjamini_hochberg, newey_west_mean_test
from ashare_factor_research.factors.llm_event_factors import compute_event_sentiment_factor
from ashare_factor_research.governance.config_contract import validate_config_bundle
from ashare_factor_research.pipeline import _benchmark_return_series, _validate_real_history


class ResearchGovernanceTest(unittest.TestCase):
    def test_config_contract_rejects_unconsumed_parameter(self):
        bundle = load_config_bundle()
        project = copy.deepcopy(bundle.project)
        project["research"]["unknown_switch"] = True
        changed = replace(bundle, project=project)
        with self.assertRaisesRegex(ValueError, "unconsumed"):
            validate_config_bundle(changed)

    def test_content_hash_and_data_version_are_stable(self):
        frame = pd.DataFrame({"trade_date": pd.to_datetime(["2022-01-04", "2022-01-03"]), "value": [2.0, 1.0]})
        reversed_frame = frame.iloc[::-1].reset_index(drop=True)
        self.assertEqual(dataframe_sha256(frame), dataframe_sha256(reversed_frame))
        first = build_data_manifest({"daily": frame}, mode="sample")
        second = build_data_manifest({"daily": reversed_frame}, mode="real")
        self.assertEqual(first["data_version"], second["data_version"])

    def test_import_manifest_verifies_and_matches_data_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, output = root / "source", root / "standard"
            write_sample_data(source)
            imported = import_standard_tables(source, output, output_format="csv")
            verified = verify_data_directory(output, require_manifest=True)
            self.assertTrue(verified["verified"])
            self.assertEqual(imported["data_version"], verified["data_version"])

    def test_benchmark_selection_requires_configured_index(self):
        benchmark = pd.DataFrame({
            "trade_date": pd.to_datetime(["2022-01-03", "2022-01-04"] * 2),
            "index_code": ["000300.SH", "000300.SH", "000905.SH", "000905.SH"],
            "close": [100.0, 101.0, 200.0, 204.0],
        })
        selected = _benchmark_return_series({"benchmark_index": benchmark}, "000905.SH")
        self.assertAlmostEqual(float(selected.iloc[-1]), 0.02)
        with self.assertRaisesRegex(ValueError, "000852.SH"):
            _benchmark_return_series({"benchmark_index": benchmark}, "000852.SH")

    def test_real_history_gate_preserves_pre_evaluation_training_data(self):
        research = {"start_date": "2018-01-01", "walk_forward": {"train_months": 24, "validation_months": 6}}
        time_series = {"min_history_start": "2015-01-01"}
        too_short = {"daily_bar": pd.DataFrame({"trade_date": pd.to_datetime(["2016-01-04"])})}
        with self.assertRaisesRegex(ValueError, "history is too short"):
            _validate_real_history(too_short, research, time_series)
        sufficient = {"daily_bar": pd.DataFrame({"trade_date": pd.to_datetime(["2014-12-31"])})}
        _validate_real_history(sufficient, research, time_series)

    def test_overlapping_group_periods_are_rejected(self):
        dates = pd.to_datetime(["2022-01-03", "2022-01-10"])
        rows = []
        for date in dates:
            for asset in range(10):
                rows.append({
                    "trade_date": date, "ts_code": str(asset), "score": float(asset),
                    "future_return_20": asset / 100.0,
                    "target_return_end_date": date + pd.Timedelta(days=20),
                })
        with self.assertRaisesRegex(ValueError, "overlap"):
            calc_non_overlapping_group_returns(
                pd.DataFrame(rows), "score", "future_return_20", pd.DatetimeIndex(dates)
            )

    def test_hac_and_fdr_statistics(self):
        result = newey_west_mean_test(pd.Series([0.1, 0.2, 0.15, 0.12, 0.18]), max_lag=2)
        self.assertEqual(result["count"], 5.0)
        self.assertGreater(result["hac_t"], 0)
        adjusted = benjamini_hochberg(pd.Series([0.01, 0.04, 0.03]))
        self.assertTrue((adjusted >= pd.Series([0.01, 0.04, 0.03])).all())

    def test_cost_attribution_uses_currency_and_ratio_fields(self):
        fills = pd.DataFrame({
            "commission": [10.0], "stamp_tax": [5.0], "slippage": [3.0],
            "impact_cost": [2.0], "total_cost": [20.0],
        })
        result = cost_attribution(fills, initial_cash=1_000.0)
        self.assertAlmostEqual(float(result.iloc[0]["total_cost"]), 20.0)
        self.assertAlmostEqual(float(result.iloc[0]["total_cost_ratio"]), 0.02)

    def test_after_close_event_is_available_next_trade_date(self):
        events = pd.DataFrame({
            "event_id": ["e1"], "stock_code": ["000001.SZ"],
            "publish_date": pd.to_datetime(["2022-01-03"]),
            "publish_time": pd.to_datetime(["2022-01-03 18:00"]),
            "event_type": ["other"], "sentiment": ["positive"], "impact_horizon": ["short"],
            "confidence": [1.0], "reason": ["test"],
        })
        factor = compute_event_sentiment_factor(events, pd.DatetimeIndex(pd.to_datetime(["2022-01-03", "2022-01-04"])))
        self.assertEqual(factor["trade_date"].min(), pd.Timestamp("2022-01-04"))

    def test_same_day_financial_revision_uses_latest_explicit_version(self):
        frame = pd.DataFrame({
            "ts_code": ["A", "A"], "report_period": pd.to_datetime(["2021-12-31"] * 2),
            "ann_date": pd.to_datetime(["2022-03-01"] * 2), "revision_id": [1, 2], "roe": [0.1, 0.2],
        })
        resolved = resolve_financial_revisions(frame)
        self.assertEqual(len(resolved), 1)
        self.assertAlmostEqual(float(resolved.iloc[0]["roe"]), 0.2)

    def test_suspended_position_uses_last_close_for_valuation(self):
        portfolio = pd.DataFrame({"trade_date": pd.to_datetime(["2022-01-03"]), "ts_code": ["A"], "target_weight": [1.0]})
        market = pd.DataFrame({
            "trade_date": pd.to_datetime(["2022-01-03", "2022-01-04", "2022-01-05"]),
            "ts_code": ["A", "A", "B"], "open": [10.0, 10.0, 1.0], "close": [10.0, 10.0, 1.0],
            "amount": [1e9, 1e9, 1e9], "is_suspended": [False, False, False],
        })
        result = run_event_backtest(portfolio, market, initial_cash=100_000.0, max_turnover=1.0)
        self.assertAlmostEqual(float(result.nav.iloc[-1]["nav"]), float(result.nav.iloc[-2]["nav"]))
        self.assertIn("A", set(result.positions[result.positions["mark_date"].eq(pd.Timestamp("2022-01-05"))]["ts_code"]))

    def test_execution_compliance_checks_realized_participation(self):
        portfolio = pd.DataFrame({
            "trade_date": pd.to_datetime(["2022-01-03"]), "ts_code": ["A"],
            "target_weight": [1.0], "industry_code": ["I"],
        })
        nav = pd.DataFrame({
            "trade_date": pd.to_datetime(["2022-01-04"]), "holding_count": [1.0],
            "cash_weight": [0.0], "turnover": [1.0],
        })
        positions = pd.DataFrame({
            "mark_date": pd.to_datetime(["2022-01-04"]), "ts_code": ["A"], "weight": [1.0],
        })
        orders = pd.DataFrame({
            "execution_date": pd.to_datetime(["2022-01-04"]), "ts_code": ["A"], "filled_value": [50.0],
        })
        market = pd.DataFrame({
            "trade_date": pd.to_datetime(["2022-01-04"]), "ts_code": ["A"], "amount": [100.0],
        })
        audit = audit_execution_compliance(
            portfolio, nav, positions, orders=orders, market=market, min_holding_count=1,
            max_weight=1.0, max_industry_weight=1.0, max_cash_weight=0.1, max_turnover=1.0,
            max_participation_rate=0.1,
        )
        participation = audit[audit["check"].eq("participation_rate")].iloc[0]
        self.assertFalse(bool(participation["passed"]))


if __name__ == "__main__":
    unittest.main()
