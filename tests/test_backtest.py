import unittest

import pandas as pd

from ashare_factor_research.analysis.performance import max_drawdown
from ashare_factor_research.backtest.backtest_engine import run_backtest
from ashare_factor_research.backtest.cost_model import CostConfig, estimate_rebalance_cost
from ashare_factor_research.backtest.portfolio_builder import build_portfolio


class BacktestTest(unittest.TestCase):
    def test_build_portfolio_weights_sum_to_one(self):
        df = pd.DataFrame(
            {
                "trade_date": ["2022-01-31"] * 5,
                "ts_code": [f"{i:06d}.SZ" for i in range(5)],
                "score": [5, 4, 3, 2, 1],
            }
        )
        portfolio = build_portfolio(df, top_n=5, max_weight=0.25)
        self.assertAlmostEqual(float(portfolio["target_weight"].sum()), 1.0)
        self.assertEqual(len(portfolio), 5)

    def test_rebalance_cost_is_positive(self):
        previous = pd.Series({"000001.SZ": 0.5, "000002.SZ": 0.5})
        target = pd.Series({"000001.SZ": 0.0, "000003.SZ": 1.0})
        cost = estimate_rebalance_cost(previous, target, CostConfig())
        self.assertGreater(cost["cost"], 0)
        self.assertGreater(cost["gross_turnover"], 0)

    def test_backtest_cost_reduces_nav(self):
        portfolio = pd.DataFrame(
            {
                "trade_date": pd.to_datetime(["2022-01-03"]),
                "ts_code": ["000001.SZ"],
                "target_weight": [1.0],
            }
        )
        returns = pd.DataFrame(
            {
                "trade_date": pd.to_datetime(["2022-01-03", "2022-01-04", "2022-01-05"]),
                "ts_code": ["000001.SZ"] * 3,
                "return_1d": [0.0, 0.01, 0.0],
            }
        )
        nav, trades = run_backtest(portfolio, returns, CostConfig())
        self.assertFalse(trades.empty)
        self.assertLess(float(nav.loc[nav["trade_date"].eq(pd.Timestamp("2022-01-04")), "nav"].iloc[0]), 1.01)

    def test_max_drawdown(self):
        dd = max_drawdown(pd.Series([1.0, 1.1, 0.99, 1.2]))
        self.assertAlmostEqual(dd, -0.1)


if __name__ == "__main__":
    unittest.main()
