import unittest

import pandas as pd

from ashare_factor_research.factor_testing.factor_decay import calc_factor_decay_table
from ashare_factor_research.factor_testing.group_test import calc_group_test_report
from ashare_factor_research.factor_testing.group_test import calc_group_returns
from ashare_factor_research.factor_testing.ic_analysis import calc_annual_ic_summary
from ashare_factor_research.factor_testing.ic_test import calc_ic, summarize_ic


class FactorTestingTest(unittest.TestCase):
    def test_calc_rank_ic_positive(self):
        df = pd.DataFrame(
            {
                "trade_date": ["2022-01-31"] * 5,
                "factor": [1, 2, 3, 4, 5],
                "future_return": [0.01, 0.02, 0.03, 0.04, 0.05],
            }
        )
        ic = calc_ic(df, "factor", "future_return")
        summary = summarize_ic(ic)
        self.assertAlmostEqual(float(ic.iloc[0]), 1.0)
        self.assertEqual(summary["hit_rate"], 1.0)

    def test_group_returns_has_long_short(self):
        df = pd.DataFrame(
            {
                "trade_date": ["2022-01-31"] * 10,
                "ts_code": [f"{i:06d}.SZ" for i in range(10)],
                "factor": list(range(10)),
                "future_return": [x / 100 for x in range(10)],
            }
        )
        groups = calc_group_returns(df, "factor", "future_return", n_groups=5)
        self.assertIn("Q5-Q1", groups.columns)
        self.assertGreater(float(groups["Q5-Q1"].iloc[0]), 0)

    def test_annual_ic_summary_keeps_years_separate(self):
        df = pd.DataFrame(
            {
                "trade_date": ["2021-12-31"] * 5 + ["2022-01-31"] * 5,
                "factor": [1, 2, 3, 4, 5] + [1, 2, 3, 4, 5],
                "future_return": [1, 2, 3, 4, 5] + [5, 4, 3, 2, 1],
            }
        )
        annual = calc_annual_ic_summary(df, ["factor"], "future_return")
        by_year = annual.set_index("year")["mean"]
        self.assertAlmostEqual(float(by_year.loc[2021]), 1.0)
        self.assertAlmostEqual(float(by_year.loc[2022]), -1.0)

    def test_group_report_outputs_turnover_and_cumulative_returns(self):
        df = pd.DataFrame(
            {
                "trade_date": ["2022-01-31"] * 10 + ["2022-02-28"] * 10,
                "ts_code": [f"{i:06d}.SZ" for i in range(10)] * 2,
                "factor": list(range(10)) + list(range(9, -1, -1)),
                "future_return": [x / 100 for x in range(10)] * 2,
            }
        )
        report = calc_group_test_report(df, "factor", "future_return", n_groups=5)
        self.assertFalse(report["cumulative_returns"].empty)
        self.assertFalse(report["counts"].empty)
        self.assertFalse(report["turnover"].empty)
        self.assertIn("monotonic_score", report["monotonicity"])

    def test_factor_decay_table_uses_available_horizons(self):
        df = pd.DataFrame(
            {
                "trade_date": ["2022-01-31"] * 5,
                "factor": [1, 2, 3, 4, 5],
                "future_return_5": [1, 2, 3, 4, 5],
                "future_return_20": [5, 4, 3, 2, 1],
            }
        )
        decay = calc_factor_decay_table(df, ["factor"], horizons=[5, 10, 20])
        self.assertEqual(set(decay["horizon"]), {5, 20})
        self.assertEqual(len(decay), 2)


if __name__ == "__main__":
    unittest.main()
