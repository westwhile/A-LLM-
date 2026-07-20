import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ashare_factor_research.backtest.backtest_engine import run_event_backtest
from ashare_factor_research.backtest.constraints import exchange_limit_rate
from ashare_factor_research.backtest.cost_model import CostConfig
from ashare_factor_research.backtest.portfolio_builder import build_portfolio
from ashare_factor_research.config import load_config_bundle
from ashare_factor_research.data.data_quality import audit_tables
from ashare_factor_research.data.data_cleaner import filter_universe
from ashare_factor_research.data.import_standard import import_standard_tables
from ashare_factor_research.data.sample_data import write_sample_data
from ashare_factor_research.factor_testing.walk_forward import build_walk_forward_scores
from ashare_factor_research.factors.llm_event_factors import compute_event_sentiment_factor
from ashare_factor_research.factors.fundamental_factors import align_financial_to_dates
from ashare_factor_research.llm.audit import label_quality_passes, sample_labels_for_review
from ashare_factor_research.llm.client import batch_label_events
from ashare_factor_research.pipeline import run_research_pipeline


class ImprovementPlanTest(unittest.TestCase):
    def test_config_bundle_uses_backtest_defaults_and_costs(self):
        bundle = load_config_bundle()
        self.assertEqual(bundle.top_n, 50)
        self.assertAlmostEqual(bundle.max_weight, 0.05)
        self.assertAlmostEqual(bundle.cost.stamp_tax_sell, 0.0005)

    def test_import_standard_writes_manifest_and_normalizes_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            output = root / "standard"
            write_sample_data(source)
            manifest = import_standard_tables(source, output, output_format="csv")
            self.assertTrue((output / "data_manifest.json").exists())
            self.assertIn("daily_bar", manifest["tables"])
            loaded = json.loads((output / "data_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(loaded["manifest_version"], 2)
            self.assertEqual(loaded["mode"], "sample")
            self.assertIsNone(loaded["source_registry_sha256"])

    def test_cross_table_audit_blocks_overlapping_membership(self):
        members = pd.DataFrame({
            "index_code": ["000905.SH", "000905.SH"], "ts_code": ["000001.SZ"] * 2,
            "weight": [1.0, 1.0], "in_date": pd.to_datetime(["2022-01-01", "2022-02-01"]),
            "out_date": pd.to_datetime(["2022-03-01", "2022-04-01"]),
        })
        issues = audit_tables({"index_member": members})
        overlap = issues[issues["check"].eq("overlapping_intervals")].iloc[0]
        self.assertEqual(overlap["severity"], "blocking")

    def test_event_factor_is_same_day_point_in_time_and_deduplicated(self):
        events = pd.DataFrame({
            "event_id": ["e1", "e1"], "stock_code": ["000001.SZ"] * 2,
            "publish_date": pd.to_datetime(["2022-01-03", "2022-01-03"]),
            "event_type": ["other"] * 2, "sentiment": ["positive"] * 2,
            "impact_horizon": ["short"] * 2, "confidence": [0.5, 0.8], "reason": ["a", "b"],
        })
        factor = compute_event_sentiment_factor(events, pd.DatetimeIndex([pd.Timestamp("2022-01-03")]))
        self.assertAlmostEqual(float(factor.iloc[0]["event_sentiment_20"]), 0.8)

    def test_financial_alignment_retains_latest_known_source_dates(self):
        dates = pd.DatetimeIndex(pd.to_datetime(["2022-01-03", "2022-01-04", "2022-01-05"]))
        financial = pd.DataFrame({
            "ts_code": ["000001.SZ", "000001.SZ"],
            "report_period": pd.to_datetime(["2021-09-30", "2021-12-31"]),
            "ann_date": pd.to_datetime(["2022-01-03", "2022-01-04"]),
            "usable_date": pd.to_datetime(["2022-01-04", "2022-01-05"]),
            "roe": [0.1, 0.2], "gross_margin": [0.3, 0.4], "debt_ratio": [0.5, 0.6],
            "revenue_yoy": [0.1, 0.2], "profit_yoy": [0.1, 0.2],
        })
        aligned = align_financial_to_dates(dates, financial)
        self.assertTrue(pd.isna(aligned.iloc[0]["roe"]))
        self.assertEqual(aligned.iloc[1]["financial_usable_date"], pd.Timestamp("2022-01-04"))
        self.assertAlmostEqual(float(aligned.iloc[2]["roe"]), 0.2)

    def test_universe_filters_st_suspension_and_delisting_by_date(self):
        bars = pd.DataFrame({
            "trade_date": pd.to_datetime(["2022-01-03", "2022-01-04", "2022-01-05", "2022-01-06"]),
            "ts_code": ["000001.SZ"] * 4, "amount": [1_000_000.0] * 4,
        })
        basic = pd.DataFrame({
            "ts_code": ["000001.SZ"], "list_date": pd.to_datetime(["2020-01-01"]),
            "delist_date": pd.to_datetime(["2022-01-06"]),
        })
        st = pd.DataFrame({
            "ts_code": ["000001.SZ"], "start_date": pd.to_datetime(["2022-01-04"]),
            "end_date": pd.to_datetime(["2022-01-05"]),
        })
        suspension = pd.DataFrame({
            "ts_code": ["000001.SZ"], "suspend_date": pd.to_datetime(["2022-01-05"]),
            "resume_date": pd.to_datetime(["2022-01-06"]),
        })
        filtered = filter_universe(bars, stock_basic=basic, st_status=st, suspension=suspension, min_list_days=0)
        self.assertEqual(filtered["trade_date"].tolist(), [pd.Timestamp("2022-01-03")])

    def test_real_pipeline_requires_import_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp) / "runs"
            with self.assertRaisesRegex(ValueError, "Real PIT data gate failed"):
                run_research_pipeline(data_dir=tmp, output_root=output_root, mode="real", run_id="blocked")
            summary_path = output_root / "blocked" / "data_gate_summary.json"
            self.assertTrue(summary_path.exists())
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "blocked_by_missing_pit_tables")

    def test_walk_forward_uses_only_lagged_windows(self):
        dates = pd.date_range("2021-01-31", periods=10, freq="ME")
        rows = []
        for date_i, date in enumerate(dates):
            for asset_i in range(8):
                rows.append({
                    "trade_date": date, "ts_code": f"{asset_i:06d}.SZ",
                    "factor": float(asset_i), "future_return_1": float(asset_i) / 100 + date_i / 1000,
                    "target_return_end_date": date + pd.offsets.MonthEnd(1),
                })
        result = build_walk_forward_scores(
            pd.DataFrame(rows), ["factor"], pd.DatetimeIndex(dates), "future_return_1",
            train_months=4, validation_months=1, min_train_dates=2, min_abs_ic=0.0,
            require_validation_sign=False,
        )
        self.assertFalse(result["weights"].empty)
        self.assertTrue((result["window_ic"]["train_end"] < result["window_ic"]["test_date"]).all())
        selected = result["window_ic"][result["window_ic"]["selected"]]
        self.assertFalse(selected.empty)

    def test_execution_delay_and_exchange_limits(self):
        portfolio = pd.DataFrame({"trade_date": pd.to_datetime(["2022-01-03"]), "ts_code": ["000001.SZ"], "target_weight": [1.0]})
        market = pd.DataFrame({
            "trade_date": pd.to_datetime(["2022-01-03", "2022-01-04", "2022-01-05"]),
            "ts_code": ["000001.SZ"] * 3, "open": [10.0] * 3, "close": [10.0] * 3,
            "up_limit": [11.0] * 3, "down_limit": [9.0] * 3, "is_suspended": [False] * 3,
        })
        result = run_event_backtest(portfolio, market, CostConfig(), execution_delay_days=2)
        self.assertEqual(result.orders.iloc[0]["execution_date"], pd.Timestamp("2022-01-05"))
        self.assertAlmostEqual(exchange_limit_rate("688001.SH", "2022-01-01"), 0.20)
        self.assertAlmostEqual(exchange_limit_rate("000001.SZ", "2022-01-01", is_st=True), 0.05)

    def test_portfolio_industry_cap(self):
        scores = pd.DataFrame({
            "trade_date": ["2022-01-31"] * 6, "ts_code": [f"{i:06d}.SZ" for i in range(6)],
            "score": [6, 5, 4, 3, 2, 1], "industry_code": ["A", "A", "A", "B", "B", "C"],
        })
        portfolio = build_portfolio(scores, top_n=6, max_weight=0.5, industry_col="industry_code", max_industry_weight=0.5)
        self.assertLessEqual(float(portfolio.groupby("industry_code")["target_weight"].sum().max()), 0.5 + 1e-10)

    def test_llm_labeling_is_offline_cached_and_review_gated(self):
        raw = pd.DataFrame({
            "event_id": ["e1"], "stock_code": ["000001.SZ"], "title": ["利润增长"],
            "content": ["年度利润增长"], "source": ["exchange"], "publish_time": ["2022-01-03 18:00:00"],
        })
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "labels.jsonl"
            first = batch_label_events(raw, cache_path=cache)
            second = batch_label_events(raw, cache_path=cache)
            self.assertEqual(first.iloc[0]["cache_key"], second.iloc[0]["cache_key"])
            review = sample_labels_for_review(first, sample_size=1)
            self.assertFalse(label_quality_passes(review))
            review["review_status"] = "pass"
            self.assertTrue(label_quality_passes(review))


if __name__ == "__main__":
    unittest.main()
