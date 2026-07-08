import unittest

import pandas as pd

from ashare_factor_research.factor_testing.group_test import calc_group_returns
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
                "factor": list(range(10)),
                "future_return": [x / 100 for x in range(10)],
            }
        )
        groups = calc_group_returns(df, "factor", "future_return", n_groups=5)
        self.assertIn("Q5-Q1", groups.columns)
        self.assertGreater(float(groups["Q5-Q1"].iloc[0]), 0)


if __name__ == "__main__":
    unittest.main()
