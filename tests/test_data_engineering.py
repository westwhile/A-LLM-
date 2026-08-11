import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ashare_factor_research.data.data_cleaner import (
    active_index_members,
    add_limit_tradability,
    compute_usable_dates,
    validate_point_in_time,
)
from ashare_factor_research.data.data_quality import audit_table, write_data_quality_report
from ashare_factor_research.data.schema import validate_primary_key


class DataEngineeringTest(unittest.TestCase):
    def test_primary_key_duplicate_raises(self):
        df = pd.DataFrame(
            {
                "trade_date": pd.to_datetime(["2022-01-03", "2022-01-03"]),
                "ts_code": ["000001.SZ", "000001.SZ"],
                "open": [10.0, 10.0],
                "high": [10.2, 10.2],
                "low": [9.8, 9.8],
                "close": [10.1, 10.1],
                "volume": [1000, 1000],
                "amount": [10000.0, 10000.0],
                "adj_factor": [1.0, 1.0],
            }
        )
        with self.assertRaises(ValueError):
            validate_primary_key(df, "daily_bar")

    def test_compute_usable_dates_uses_next_trade_date(self):
        trade_dates = pd.DatetimeIndex(pd.to_datetime(["2022-04-20", "2022-04-22"]))
        financial = pd.DataFrame({"ann_date": pd.to_datetime(["2022-04-20"])})
        out = compute_usable_dates(financial, trade_dates)
        self.assertEqual(out["usable_date"].iloc[0], pd.Timestamp("2022-04-22"))

    def test_validate_point_in_time_rejects_future_usable_date(self):
        df = pd.DataFrame(
            {
                "trade_date": pd.to_datetime(["2022-04-20"]),
                "usable_date": pd.to_datetime(["2022-04-22"]),
            }
        )
        with self.assertRaises(ValueError):
            validate_point_in_time(df)

    def test_active_index_members_respects_membership_interval(self):
        members = pd.DataFrame(
            {
                "index_code": ["000905.SH", "000905.SH"],
                "ts_code": ["000001.SZ", "000002.SZ"],
                "weight": [0.5, 0.5],
                "in_date": pd.to_datetime(["2022-01-01", "2022-02-01"]),
                "out_date": pd.to_datetime(["2022-03-01", None]),
            }
        )
        active = active_index_members(members, pd.Timestamp("2022-01-31"), index_code="000905.SH")
        self.assertEqual(active, {"000001.SZ"})

    def test_add_limit_tradability_flags_open_limit(self):
        bar = pd.DataFrame(
            {
                "open": [11.0, 9.0, 10.0],
                "up_limit": [11.0, 11.0, 11.0],
                "down_limit": [9.0, 9.0, 9.0],
                "is_suspended": [False, False, True],
            }
        )
        out = add_limit_tradability(bar)
        self.assertFalse(bool(out["can_buy_open"].iloc[0]))
        self.assertFalse(bool(out["can_sell_open"].iloc[1]))
        self.assertFalse(bool(out["can_buy_open"].iloc[2]))

    def test_data_quality_report_detects_duplicates(self):
        df = pd.DataFrame(
            {
                "trade_date": pd.to_datetime(["2022-01-03", "2022-01-03"]),
                "ts_code": ["000001.SZ", "000001.SZ"],
                "open": [10.0, 10.0],
                "high": [10.2, 10.2],
                "low": [9.8, 9.8],
                "close": [10.1, 10.1],
                "volume": [1000, 1000],
                "amount": [10000.0, 10000.0],
                "adj_factor": [1.0, 1.0],
            }
        )
        report = audit_table(df, "daily_bar")
        duplicate = report[report["check"].eq("primary_key_duplicates")].iloc[0]
        self.assertEqual(duplicate["severity"], "blocking")
        with tempfile.TemporaryDirectory() as tmp:
            md_path, csv_path, issues = write_data_quality_report({"daily_bar": df}, Path(tmp))
            self.assertTrue(md_path.exists())
            self.assertTrue(csv_path.exists())
            self.assertTrue(issues["severity"].eq("blocking").any())

    def test_usable_date_beyond_batch_window_tolerated(self):
        """批次窗口豁免（决策3）：usable_date 晚于日历终点保留不阻断；日历内非开市日仍阻断。"""
        from ashare_factor_research.data.data_quality import audit_tables

        calendar = pd.DataFrame({
            "trade_date": pd.to_datetime(["2026-06-26", "2026-06-29", "2026-06-30"]),
            "is_open": [True, True, True],
        })
        financial = pd.DataFrame({
            "ts_code": ["000001.SZ", "000002.SZ", "000004.SZ", "000005.SZ"],
            "report_period": ["2026-03-31"] * 4,
            "ann_date": pd.to_datetime(["2026-06-25", "2026-06-30", "2026-06-26", "2026-06-27"]),
            "usable_date": pd.to_datetime(["2026-06-29", "2026-07-01", "2026-06-28", "2026-06-27"]),
            "revision_date": pd.to_datetime(["2026-06-25", "2026-06-30", "2026-06-26", "2026-06-27"]),
            "revision_id": [0, 0, 0, 0],
            "source_id": ["s1", "s2", "s3", "s4"],
        })
        issues = audit_tables({"trade_calendar": calendar, "financial_indicator": financial})
        outside = issues[issues["check"].eq("usable_date_outside_trade_calendar")].iloc[0]
        beyond = issues[issues["check"].eq("usable_date_beyond_batch_window")].iloc[0]
        # 2026-06-28/06-27 为日历范围内非开市日（阻断 2 行）；2026-07-01 超批次终点（豁免 1 行）
        self.assertEqual(outside["severity"], "blocking")
        self.assertEqual(outside["value"], 2)
        self.assertEqual(beyond["value"], 1)
        # 仅豁免行时无阻断
        financial_ok = financial.iloc[[0, 1]]
        issues_ok = audit_tables({"trade_calendar": calendar, "financial_indicator": financial_ok})
        outside_ok = issues_ok[issues_ok["check"].eq("usable_date_outside_trade_calendar")].iloc[0]
        self.assertEqual(outside_ok["severity"], "ok")
        self.assertEqual(outside_ok["value"], 0)


if __name__ == "__main__":
    unittest.main()
