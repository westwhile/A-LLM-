import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from ashare_factor_research.backtest.cost_model import CostConfig
from ashare_factor_research.data.pit_audit import (
    audit_benchmark_alignment,
    audit_financial_revisions,
    audit_pit_timing,
    audit_survivorship,
    audit_universe_coverage,
)
from ashare_factor_research.monthly_research import (
    attach_monthly_label_returns,
    build_monthly_labels,
    build_real_mode_audits,
    check_real_mode_gates,
    compute_historical_member_coverage,
)
from ashare_factor_research.time_series.models import expanding_forecast_comparison
from ashare_factor_research.time_series.research import (
    build_model_selection_audit,
    build_monthly_factor_ic,
    build_monthly_factor_returns,
    build_standard_series,
    build_time_series_diagnostics_by_origin,
    compare_preregistered_weight_schemes,
    run_time_series_baselines,
)


class Phase23HardGatesTest(unittest.TestCase):
    def _make_tables(self, coverage: float = 1.0) -> dict[str, pd.DataFrame]:
        dates = pd.date_range("2015-01-05", periods=200, freq="B")
        codes = [f"{i:06d}.SZ" for i in range(50)]
        daily_bar = pd.DataFrame({
            "trade_date": np.tile(dates, len(codes)),
            "ts_code": np.repeat(codes, len(dates)),
            "open": 10.0, "close": 10.0, "high": 11.0, "low": 9.0,
            "volume": 1e6, "amount": 1e7, "adj_factor": 1.0,
        })
        if coverage < 1.0:
            mask = np.random.default_rng(3).random(len(daily_bar)) > coverage
            daily_bar.loc[mask, "amount"] = np.nan
            daily_bar.loc[mask, "adj_factor"] = np.nan
        calendar = pd.DataFrame({
            "trade_date": dates, "is_open": True,
        })
        members = pd.DataFrame({
            "index_code": ["000905.SH"] * len(codes),
            "ts_code": codes,
            "weight": 1.0 / len(codes),
            "in_date": pd.Timestamp("2014-01-01"),
            "out_date": pd.NaT,
        })
        basic = pd.DataFrame({
            "ts_code": codes,
            "list_date": pd.Timestamp("2010-01-01"),
            "delist_date": pd.NaT,
        })
        benchmark = pd.DataFrame({
            "trade_date": dates, "index_code": "000905.SH", "close": 1000.0,
        })
        financial = pd.DataFrame({
            "ts_code": [codes[0]], "report_period": pd.Timestamp("2014-12-31"),
            "ann_date": pd.Timestamp("2015-03-01"), "revision_date": pd.Timestamp("2015-03-01"),
            "usable_date": pd.Timestamp("2015-03-02"), "source_id": "s1", "revision_id": 1,
        })
        return {
            "trade_calendar": calendar,
            "daily_bar": daily_bar,
            "index_member": members,
            "stock_basic": basic,
            "benchmark_index": benchmark,
            "financial_indicator": financial,
            "daily_basic": pd.DataFrame(columns=["trade_date", "ts_code"]),
            "industry": pd.DataFrame(columns=["trade_date", "ts_code", "industry_code"]),
            "limit_price": pd.DataFrame(columns=["trade_date", "ts_code", "up_limit", "down_limit"]),
        }

    def _signed_manifest(self) -> dict:
        return {
            "mode": "real",
            "import_gate_status": "ready_for_quality_audit",
            "review_status": "approved",
            "reviewed_by": "user",
            "reviewed_at": "2026-07-19T00:00:00",
            "source_registry_sha256": "a" * 64,
            "source_registry_validation": {"valid": True, "errors": []},
        }

    def test_unsigned_registry_blocks_real_mode(self):
        tables = self._make_tables()
        manifest = self._signed_manifest()
        manifest["review_status"] = "pending_user_review"
        audits = build_real_mode_audits(tables)
        blocking = check_real_mode_gates(
            tables, manifest, audits=audits, labels=build_monthly_labels(tables["daily_bar"]["trade_date"])
        )
        self.assertTrue(any("review_status" in reason for reason in blocking))

    def test_missing_required_table_blocks(self):
        tables = self._make_tables()
        del tables["daily_bar"]
        blocking = check_real_mode_gates(
            tables, self._signed_manifest(), audits={}, labels=pd.DataFrame()
        )
        self.assertTrue(any("daily_bar" in reason for reason in blocking))

    def test_empty_audit_blocks(self):
        tables = self._make_tables()
        audits = build_real_mode_audits(tables)
        audits["survivorship_audit.csv"] = pd.DataFrame()
        blocking = check_real_mode_gates(
            tables, self._signed_manifest(), audits=audits, labels=build_monthly_labels(tables["daily_bar"]["trade_date"])
        )
        self.assertTrue(any("survivorship" in reason for reason in blocking))

    def test_missing_named_audit_blocks(self):
        tables = self._make_tables()
        audits = build_real_mode_audits(tables)
        del audits["benchmark_alignment.csv"]
        blocking = check_real_mode_gates(
            tables, self._signed_manifest(), audits=audits,
            labels=build_monthly_labels(tables["daily_bar"]["trade_date"]),
        )
        self.assertTrue(any("missing specialized audit" in reason for reason in blocking))

    def test_coverage_below_threshold_blocks(self):
        tables = self._make_tables(coverage=0.90)
        blocking = check_real_mode_gates(
            tables, self._signed_manifest(), audits=build_real_mode_audits(tables),
            labels=build_monthly_labels(tables["daily_bar"]["trade_date"]), min_coverage=0.95,
        )
        self.assertTrue(any("coverage below" in reason for reason in blocking))

    def test_universe_coverage_excludes_suspended_members(self):
        """口径修正（2026-08-11 批准）：停牌成员不计入 daily_bar 覆盖率分母。"""
        dates = pd.date_range("2015-01-05", periods=3, freq="B")
        codes = [f"{i:06d}.SZ" for i in range(5)]
        tables = {
            "trade_calendar": pd.DataFrame({"trade_date": dates, "is_open": True}),
            "index_member": pd.DataFrame({
                "index_code": ["000905.SH"] * 5, "ts_code": codes, "weight": 0.2,
                "in_date": pd.Timestamp("2014-01-01"), "out_date": pd.NaT,
            }),
            "suspension": pd.DataFrame({
                "ts_code": codes[:2],
                "suspend_date": [dates[0], dates[0]],
                "resume_date": [dates[-1] + pd.Timedelta(days=1), dates[-1] + pd.Timedelta(days=1)],
            }),
            # 停牌 2 只无 K 线行（正确数据行为），仅 3 只有行情
            "daily_bar": pd.DataFrame({
                "trade_date": np.tile(dates, 3), "ts_code": np.repeat(codes[2:], 3),
            }),
            # 其余三表停牌日仍有行
            "daily_basic": pd.DataFrame({"trade_date": np.tile(dates, 5), "ts_code": np.repeat(codes, 3)}),
            "industry": pd.DataFrame({"trade_date": np.tile(dates, 5), "ts_code": np.repeat(codes, 3)}),
            "limit_price": pd.DataFrame({"trade_date": np.tile(dates, 5), "ts_code": np.repeat(codes, 3)}),
        }
        cov = audit_universe_coverage(tables, required_start="2015-01-01")
        self.assertIn("suspended_member_count", cov.columns)
        self.assertTrue((cov["suspended_member_count"] == 2).all())
        self.assertTrue((cov["daily_bar_coverage"] == 1.0).all())  # 3/3 而非 3/5
        self.assertTrue(cov["passed"].all())
        # 对照：无停牌表时维持旧口径 3/5=0.6 并触发不达标
        tables_no_suspension = {name: frame for name, frame in tables.items() if name != "suspension"}
        cov_old = audit_universe_coverage(tables_no_suspension, required_start="2015-01-01")
        self.assertTrue((cov_old["suspended_member_count"] == 0).all())
        self.assertTrue((cov_old["daily_bar_coverage"] == 0.6).all())
        self.assertFalse(cov_old["passed"].any())

    def test_overlapping_labels_rejected(self):
        dates = pd.date_range("2022-01-03", periods=40, freq="B")
        with self.assertRaisesRegex(ValueError, "overlap"):
            build_monthly_labels(dates, horizon=2)

    def test_holdout_crossing_rejected(self):
        dates = pd.date_range("2023-11-01", periods=60, freq="B")
        with self.assertRaisesRegex(ValueError, "holdout"):
            build_monthly_labels(dates, final_holdout_start="2024-01-01")

    def test_historical_member_coverage_schema(self):
        tables = self._make_tables()
        coverage = compute_historical_member_coverage(
            tables, required_fields={"daily_bar": ["amount", "adj_factor"]}, required_start="2015-01-01"
        )
        self.assertIn("coverage", coverage.columns)
        self.assertTrue((coverage["coverage"] == 1.0).all())

    def test_historical_member_coverage_financial_pit_and_suspension(self):
        """回归：financial_indicator（无 trade_date）按 usable_date 口径统计，不再 KeyError；
        日频表分母剔除当日停牌成员（与已批准的门禁口径同原则）。"""
        dates = pd.date_range("2015-01-05", periods=3, freq="B")
        codes = [f"{i:06d}.SZ" for i in range(5)]
        tables = {
            "trade_calendar": pd.DataFrame({"trade_date": dates, "is_open": True}),
            "index_member": pd.DataFrame({
                "index_code": ["000905.SH"] * 5, "ts_code": codes, "weight": 0.2,
                "in_date": pd.Timestamp("2014-01-01"), "out_date": pd.NaT,
            }),
            "suspension": pd.DataFrame({
                "ts_code": codes[:2],
                "suspend_date": [dates[0], dates[0]],
                "resume_date": [dates[-1] + pd.Timedelta(days=1), dates[-1] + pd.Timedelta(days=1)],
            }),
            # 停牌 2 只无 K 线行（正确数据行为），3 只有行情
            "daily_bar": pd.DataFrame({
                "trade_date": np.tile(dates, 3), "ts_code": np.repeat(codes[2:], 3),
                "amount": 1e7, "adj_factor": 1.0,
            }),
            # 季度财务表：无 trade_date；codes[3] 第三日才可用；codes[4] roe 缺失
            "financial_indicator": pd.DataFrame({
                "ts_code": codes,
                "report_period": pd.Timestamp("2014-09-30"),
                "ann_date": pd.Timestamp("2014-10-30"),
                "usable_date": [pd.Timestamp("2014-10-31")] * 3 + [pd.Timestamp("2015-01-07"), pd.Timestamp("2014-10-31")],
                "revision_date": pd.Timestamp("2014-10-30"),
                "revision_id": 0,
                "source_id": "s1",
                "roe": [0.1, 0.1, 0.1, 0.1, np.nan],
                "gross_margin": 0.2, "debt_ratio": 0.4, "revenue_yoy": 0.1, "profit_yoy": 0.1,
            }),
        }
        coverage = compute_historical_member_coverage(
            tables,
            required_fields={"daily_bar": ["amount"], "financial_indicator": ["roe"]},
            required_start="2015-01-01",
        )
        bar = coverage[coverage["table"] == "daily_bar"]
        self.assertTrue((bar["coverage"] == 1.0).all())  # 3/(5-2停牌)=1.0 而非 3/5
        fin_rows = coverage[coverage["table"] == "financial_indicator"].sort_values("trade_date")
        self.assertFalse(fin_rows.empty)
        self.assertAlmostEqual(fin_rows["coverage"].iloc[0], 0.6)  # 3/5：code3 未可用、code4 缺 roe
        self.assertAlmostEqual(fin_rows["coverage"].iloc[-1], 0.8)  # 4/5：code3 到可用日

    def test_required_fields_map_derived_and_unsourced(self):
        """审计字段映射：roa→net_profit/total_assets；ps 等无来源字段不进审计并显式列出。"""
        from ashare_factor_research.factors.registry import DEFAULT_FACTOR_REGISTRY
        from ashare_factor_research.main import _required_fields_from_specs, unsourced_factor_inputs

        specs = [DEFAULT_FACTOR_REGISTRY[name] for name in ["roa", "sp", "mf_20", "large_order_mf_20", "cfp"]]
        fields = _required_fields_from_specs(specs)
        self.assertIn("net_profit", fields["financial_indicator"])
        self.assertIn("total_assets", fields["financial_indicator"])
        self.assertNotIn("roa", fields.get("financial_indicator", []))
        self.assertIn("net_mf_amount", fields["daily_basic"])
        self.assertNotIn("ps", fields.get("daily_basic", []))
        self.assertEqual(
            unsourced_factor_inputs(specs),
            ["large_order_net_mf_amount", "operating_cash_flow", "ps"],
        )

    def _exemption_fixture(self):
        dates = pd.date_range("2015-01-05", periods=2, freq="B")
        codes = [f"{i:06d}.SZ" for i in range(5)]
        members = pd.DataFrame({
            "index_code": ["000905.SH"] * 5, "ts_code": codes, "weight": 0.2,
            "in_date": pd.Timestamp("2014-01-01"), "out_date": pd.NaT,
        })
        calendar = pd.DataFrame({"trade_date": dates, "is_open": True})
        return dates, codes, members, calendar

    def test_amount_exemption_only_no_amount_stocks(self):
        """登记豁免：daily_bar.amount 分母仅剔除"全部行 amount 缺失"的股票；其他字段不受影响。"""
        dates, codes, members, calendar = self._exemption_fixture()
        amount = [np.nan, np.nan, 1e7, 1e7, 1e7]  # codes0/1 全程无成交额（腾讯源口径）
        daily_bar = pd.DataFrame({
            "trade_date": np.tile(dates, 5), "ts_code": np.repeat(codes, 2),
            "amount": np.repeat(amount, 2),
            "adj_factor": np.repeat([1.0, 1.0, np.nan, 1.0, 1.0], 2),  # code2 adj_factor 缺失
        })
        tables = {"trade_calendar": calendar, "index_member": members, "daily_bar": daily_bar}
        cov = compute_historical_member_coverage(
            tables, required_fields={"daily_bar": ["amount", "adj_factor"]}, required_start="2015-01-01"
        )
        amt = cov[cov["field"] == "amount"]
        self.assertTrue((amt["exempted_count"] == 2).all())       # 每日豁免 2 只无成交额股票
        self.assertTrue((amt["coverage"] == 1.0).all())           # 3/(5-2)=1.0
        adj = cov[cov["field"] == "adj_factor"]
        self.assertTrue((adj["exempted_count"] == 0).all())       # adj_factor 不适用豁免
        self.assertTrue((adj["coverage"] == 0.8).all())           # 分母仍为 5：4/5

    def test_gross_margin_exemption_only_financial_members(self):
        """登记豁免：gross_margin 分母仅剔除金融类成员；industry 缺失成员保持计入；其他财务字段不受影响。"""
        dates, codes, members, calendar = self._exemption_fixture()
        industry = pd.DataFrame({
            "trade_date": np.tile(dates, 3),
            "ts_code": np.repeat(codes[:3], 2),  # codes3/4 无行业记录
            "industry_code": "x", "industry_name": np.repeat(["银行", "非银金融", "电子"], 2),
        })
        financial = pd.DataFrame({
            "ts_code": codes,
            "report_period": pd.Timestamp("2014-09-30"),
            "ann_date": pd.Timestamp("2014-10-30"),
            "usable_date": pd.Timestamp("2014-10-31"),
            "revision_date": pd.Timestamp("2014-10-30"),
            "revision_id": 0, "source_id": "s1",
            "gross_margin": [np.nan, np.nan, 0.3, np.nan, 0.25],  # 金融 2 只 NaN + code3 非金融 NaN
            "roe": [0.1, np.nan, 0.1, 0.1, 0.1],                  # code1 roe NaN（非豁免字段）
            "debt_ratio": 0.4, "revenue_yoy": 0.1, "profit_yoy": 0.1,
        })
        tables = {"trade_calendar": calendar, "index_member": members,
                  "industry": industry, "financial_indicator": financial}
        cov = compute_historical_member_coverage(
            tables, required_fields={"financial_indicator": ["gross_margin", "roe"]}, required_start="2015-01-01"
        )
        gm = cov[cov["field"] == "gross_margin"]
        self.assertTrue((gm["exempted_count"] == 2).all())        # 每日豁免 2 只金融类
        self.assertTrue((gm["coverage"] == 2 / 3).all())          # code3 保持计入分母：2/3
        roe = cov[cov["field"] == "roe"]
        self.assertTrue((roe["exempted_count"] == 0).all())       # roe 不适用豁免
        self.assertTrue((roe["coverage"] == 0.8).all())           # 分母仍为 5：4/5

    def test_adjacent_month_labels_have_strict_timing(self):
        dates = pd.date_range("2022-01-03", "2022-05-31", freq="B")
        labels = build_monthly_labels(dates)
        self.assertTrue((labels["signal_date"] < labels["execution_date"]).all())
        self.assertTrue((labels["execution_date"] <= labels["label_end_date"]).all())
        self.assertTrue((labels["label_end_date"] < labels["availability_date"]).all())
        self.assertTrue((labels["label_end_date"].iloc[:-1].to_numpy() == labels["signal_date"].iloc[1:].to_numpy()).all())


class Phase23ArtifactTest(unittest.TestCase):
    def _make_panel(self) -> tuple[pd.DataFrame, list[str], pd.Series]:
        dates = pd.date_range("2020-01-31", periods=24, freq="ME")
        codes = [f"{i:06d}.SZ" for i in range(20)]
        rows = []
        rng = np.random.default_rng(5)
        for date in dates:
            for code in codes:
                rows.append({
                    "trade_date": date, "ts_code": code,
                    "future_return_20": rng.normal(0.0, 0.05),
                    "factor_a": rng.normal(0.0, 1.0),
                    "factor_b": rng.normal(0.0, 1.0),
                    "size": rng.lognormal(10.0, 0.5),
                    "industry_code": f"I{int(rng.integers(0, 4))}",
                    "return_1d": rng.normal(0.0, 0.01),
                    "target_return_end_date": date + pd.offsets.MonthEnd(1),
                })
        panel = pd.DataFrame(rows)
        benchmark = pd.Series(rng.normal(0.0, 0.01, len(dates) * 2), index=pd.date_range("2020-01-01", periods=len(dates) * 2, freq="B"))
        return panel, ["factor_a", "factor_b"], benchmark

    def test_monthly_factor_ic_schema(self):
        panel, factor_cols, _ = self._make_panel()
        rebal_dates = pd.to_datetime(panel["trade_date"].unique())
        ic = build_monthly_factor_ic(panel, factor_cols, "future_return_20", rebal_dates)
        required = {"signal_date", "availability_date", "factor", "rank_ic", "valid_stock_count", "universe_denominator", "coverage", "interval"}
        self.assertTrue(required.issubset(set(ic.columns)))
        self.assertTrue((ic["valid_stock_count"] <= ic["universe_denominator"]).all())
        self.assertTrue((ic["coverage"].dropna() <= 1.0).all())

    def test_monthly_return_uses_next_open_and_month_end_close(self):
        labels = pd.DataFrame({
            "signal_date": pd.to_datetime(["2022-01-31"]),
            "execution_date": pd.to_datetime(["2022-02-01"]),
            "label_end_date": pd.to_datetime(["2022-02-28"]),
            "availability_date": pd.to_datetime(["2022-03-01"]),
        })
        panel = pd.DataFrame({
            "trade_date": pd.to_datetime(["2022-01-31"]),
            "ts_code": ["000001.SZ"], "factor_a": [1.0],
        })
        bars = pd.DataFrame({
            "trade_date": pd.to_datetime(["2022-02-01", "2022-02-28"]),
            "ts_code": ["000001.SZ", "000001.SZ"],
            "open": [10.0, 12.0], "close": [10.5, 12.0],
            "adj_factor": [0.5, 0.5],
        })
        result = attach_monthly_label_returns(panel, bars, labels)
        self.assertAlmostEqual(float(result.loc[0, "monthly_forward_return"]), 0.2)
        self.assertEqual(result.loc[0, "execution_date"], pd.Timestamp("2022-02-01"))
        self.assertEqual(result.loc[0, "availability_date"], pd.Timestamp("2022-03-01"))

    def test_monthly_factor_returns_schema_and_identity(self):
        panel, factor_cols, benchmark = self._make_panel()
        rebal_dates = pd.to_datetime(panel["trade_date"].unique())
        returns = build_monthly_factor_returns(panel, factor_cols, "future_return_20", rebal_dates, benchmark, CostConfig())
        required = {
            "signal_date", "availability_date", "factor", "interval",
            "Q1_raw", "Q5_raw", "Q5_minus_Q1_raw",
            "Q1_neutral", "Q5_neutral", "Q5_minus_Q1_neutral",
            "Q5_long_only_return", "relative_csi500_return",
            "gross_return", "cost", "net_return", "turnover", "tradable_count",
        }
        self.assertTrue(required.issubset(set(returns.columns)))
        finite = returns.dropna(subset=["gross_return", "cost", "net_return"])
        self.assertTrue(np.allclose(finite["gross_return"] - finite["cost"], finite["net_return"], rtol=1e-10))

    def test_monthly_state_variables_schema(self):
        panel, _, benchmark = self._make_panel()
        daily_bar = pd.DataFrame({
            "trade_date": panel["trade_date"].unique(),
            "ts_code": "000001.SZ", "amount": 1e7, "turnover_rate": 0.02,
        })
        state = build_standard_series(panel, daily_bar, benchmark)
        required = {"benchmark_log_return", "realized_volatility_20", "breadth", "log_median_amount", "median_turnover_rate", "cross_sectional_dispersion"}
        self.assertTrue(required.issubset(set(state.columns)))

    def test_forecast_comparison_enriched_schema(self):
        rng = np.random.default_rng(7)
        dates = pd.date_range("2018-01-31", periods=36, freq="ME")
        exog = pd.DataFrame({
            "breadth": rng.normal(0.0, 1.0, len(dates)),
            "liquidity": rng.normal(0.0, 1.0, len(dates)),
        }, index=dates)
        target = pd.Series(rng.normal(0.0, 0.01, len(dates)), index=dates)
        trade_dates = pd.date_range("2018-01-31", periods=40, freq="ME")
        forecasts = expanding_forecast_comparison(target, exogenous=exog, min_train=12, target_series="test", trade_dates=trade_dates)
        required = {"target_series", "train_start", "train_end", "forecast_origin", "forecast_target", "availability_date", "direction_hit"}
        self.assertTrue(required.issubset(set(forecasts.columns)))
        self.assertTrue((forecasts["forecast_origin"] < forecasts["forecast_target"]).all())
        self.assertTrue((forecasts["train_end"] == forecasts["forecast_origin"]).all())
        self.assertIn("direction_hit", forecasts.columns)
        self.assertTrue(forecasts["point_in_time_valid"].all())

    def test_model_selection_audit_schema(self):
        rng = np.random.default_rng(8)
        dates = pd.date_range("2018-01-31", periods=48, freq="ME")
        target = pd.Series(rng.normal(0.0, 0.01, len(dates)), index=dates)
        forecasts = expanding_forecast_comparison(target, min_train=12, target_series="test")
        audit = build_model_selection_audit(forecasts, min_oos_months=6)
        required = {"model", "observations", "rmse", "mae", "direction_accuracy", "rank_correlation", "dm_stat", "dm_p_value", "spa_stat", "spa_p_value", "sample_eligibility", "status"}
        self.assertTrue(required.issubset(set(audit.columns)))
        self.assertTrue((audit["sample_eligibility"] == (audit["observations"] >= 6)).all())

    def test_time_series_baselines_reject_holdout(self):
        rng = np.random.default_rng(9)
        dates = pd.date_range("2018-01-31", periods=80, freq="ME")
        standard = pd.DataFrame({
            "benchmark_log_return": rng.normal(0.0, 0.01, len(dates)),
            "realized_volatility_20": rng.uniform(0.1, 0.3, len(dates)),
            "breadth": rng.uniform(0.2, 0.8, len(dates)),
            "log_median_amount": rng.normal(15.0, 0.2, len(dates)),
            "median_turnover_rate": rng.uniform(0.01, 0.05, len(dates)),
            "cross_sectional_dispersion": rng.uniform(0.01, 0.03, len(dates)),
        }, index=dates)
        monthly_ic = pd.DataFrame({
            "signal_date": dates,
            "availability_date": dates + pd.Timedelta(days=5),
            "factor": "test",
            "rank_ic": rng.normal(0.0, 0.05, len(dates)),
        })
        result = run_time_series_baselines(
            standard, monthly_ic, rebalance_dates=dates,
            config={"evaluation_start": "2018-01-31", "evaluation_end": "2023-12-31"},
            final_holdout_start="2024-01-01",
        )
        self.assertIn("forecast_comparison", result)
        self.assertIn("model_selection_audit", result)
        if not result["forecast_comparison"].empty:
            self.assertTrue(
                (pd.to_datetime(result["forecast_comparison"]["forecast_target"]) < pd.Timestamp("2024-01-01")).all()
            )

    def test_diagnostics_by_origin_run_all_tests(self):
        rng = np.random.default_rng(10)
        dates = pd.date_range("2018-01-31", periods=60, freq="ME")
        standard = pd.DataFrame({
            "benchmark_log_return": rng.normal(0.0, 0.01, len(dates)),
        }, index=dates)
        diagnostics = build_time_series_diagnostics_by_origin(standard, dates, max_lag=6)
        tests = set(diagnostics["test"])
        self.assertTrue({"adf", "kpss", "ljung_box", "arch_lm", "zivot_andrews"}.issubset(tests))

    def test_preregistered_weight_schemas(self):
        panel, factor_cols, benchmark = self._make_panel()
        rebal_dates = pd.to_datetime(panel["trade_date"].unique())
        ic = build_monthly_factor_ic(panel, factor_cols, "future_return_20", rebal_dates)
        returns = build_monthly_factor_returns(panel, factor_cols, "future_return_20", rebal_dates, benchmark, CostConfig())
        comparison = compare_preregistered_weight_schemes(ic, returns, rebal_dates, CostConfig())
        self.assertIn("scheme", comparison.columns)
        self.assertTrue(set(comparison["scheme"]).issuperset({"static_equal", "rolling_ic_12m", "ewma_ic"}))

    def test_weight_schemes_gross_normalization_blocks_leverage_explosion(self):
        # 回归（2026-08-11 口径修复）：符号权重按 Σ|w| 归一（gross=1）。
        # 旧口径按 Σw 归一，Σw 近零正数时杠杆爆炸（真实批次 rolling_ic_12m 单月
        # net -611%/+150%、换手为负）。构造两因子滚动 IC +0.001/-0.0009（Σw≈0.053），
        # 断言修复后收益有界、换手与成本非负。
        dates = pd.date_range("2015-01-31", periods=24, freq="ME")
        ic = pd.DataFrame([
            {"signal_date": d, "availability_date": d + pd.Timedelta(days=1),
             "factor": factor, "rank_ic": rank_ic}
            for d in dates
            for factor, rank_ic in (("fa", 0.001), ("fb", -0.0009))
        ])
        returns = pd.DataFrame([
            {"signal_date": d, "availability_date": d + pd.Timedelta(days=2),
             "factor": factor, "Q5_minus_Q1_raw": q5q1, "turnover": 0.2}
            for d in dates
            for factor, q5q1 in (("fa", 0.10), ("fb", -0.10))
        ])
        comparison = compare_preregistered_weight_schemes(ic, returns, pd.DatetimeIndex(dates), CostConfig())
        signed = comparison[comparison["scheme"].isin(["rolling_ic_12m", "rolling_ic_24m", "ewma_ic"])]
        self.assertFalse(signed.empty)
        # gross=1 下 |net| 不超过组合内最大单腿收益量级 + 成本；旧口径此处约 +1.9
        self.assertTrue((signed["net_return"].abs() <= 0.20).all())
        self.assertTrue((signed["turnover"] >= 0).all())
        self.assertTrue((signed["cost"] >= 0).all())

    def test_leakage_availability_after_training_cutoff_rejected(self):
        # forecast origin must be strictly before availability date
        rng = np.random.default_rng(11)
        dates = pd.date_range("2018-01-31", periods=24, freq="ME")
        target = pd.Series(rng.normal(0.0, 0.01, len(dates)), index=dates)
        forecasts = expanding_forecast_comparison(target, min_train=12, target_series="test")
        self.assertTrue((forecasts["forecast_origin"] < forecasts["availability_date"]).all())


if __name__ == "__main__":
    unittest.main()
