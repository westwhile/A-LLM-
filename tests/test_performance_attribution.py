import unittest

import pandas as pd

from ashare_factor_research.analysis.attribution import cost_attribution, security_return_contribution
from ashare_factor_research.analysis.drawdown import drawdown_periods
from ashare_factor_research.analysis.performance import (
    calc_performance,
    information_ratio,
    monthly_return_matrix,
    tracking_error,
    yearly_returns,
)
from ashare_factor_research.backtest.cost_model import CostConfig


class PerformanceAttributionTest(unittest.TestCase):
    def test_benchmark_dates_must_match(self):
        strategy = pd.Series(
            [0.01, 0.02],
            index=pd.to_datetime(["2022-01-03", "2022-01-04"]),
        )
        benchmark = pd.Series(
            [0.01, 0.02],
            index=pd.to_datetime(["2022-01-03", "2022-01-05"]),
        )
        with self.assertRaises(ValueError):
            tracking_error(strategy, benchmark)

    def test_tracking_error_and_information_ratio(self):
        strategy = pd.Series(
            [0.02, 0.00, 0.03],
            index=pd.to_datetime(["2022-01-03", "2022-01-04", "2022-01-05"]),
        )
        benchmark = pd.Series(
            [0.01, 0.01, 0.01],
            index=strategy.index,
        )
        excess = strategy - benchmark
        expected_te = float(excess.std(ddof=1) * (252**0.5))
        self.assertAlmostEqual(tracking_error(strategy, benchmark), expected_te)
        self.assertAlmostEqual(information_ratio(strategy, benchmark), float(excess.mean() * 252 / expected_te))

    def test_yearly_returns_are_compounded(self):
        returns = pd.Series(
            [0.10, -0.10, 0.05],
            index=pd.to_datetime(["2022-01-03", "2022-01-04", "2023-01-03"]),
        )
        yearly = yearly_returns(returns)
        self.assertAlmostEqual(float(yearly.loc[2022]), -0.01)
        self.assertAlmostEqual(float(yearly.loc[2023]), 0.05)

    def test_monthly_return_matrix(self):
        returns = pd.Series(
            [0.10, -0.10, 0.05],
            index=pd.to_datetime(["2022-01-03", "2022-01-04", "2022-02-03"]),
        )
        matrix = monthly_return_matrix(returns)
        self.assertAlmostEqual(float(matrix.loc[2022, 1]), -0.01)
        self.assertAlmostEqual(float(matrix.loc[2022, 2]), 0.05)

    def test_drawdown_period_identifies_recovery(self):
        nav = pd.Series(
            [1.0, 1.2, 1.0, 0.9, 1.25],
            index=pd.to_datetime(["2022-01-03", "2022-01-04", "2022-01-05", "2022-01-06", "2022-01-07"]),
        )
        periods = drawdown_periods(nav)
        self.assertAlmostEqual(float(periods.loc[0, "max_drawdown"]), -0.25)
        self.assertEqual(periods.loc[0, "start"], pd.Timestamp("2022-01-04"))
        self.assertEqual(periods.loc[0, "trough"], pd.Timestamp("2022-01-06"))
        self.assertEqual(periods.loc[0, "recovery"], pd.Timestamp("2022-01-07"))

    def test_calc_performance_includes_cost_drag(self):
        nav = pd.DataFrame(
            {
                "trade_date": pd.to_datetime(["2022-01-03", "2022-01-04"]),
                "gross_return": [0.0, 0.02],
                "cost": [0.0, 0.001],
                "net_return": [0.0, 0.019],
                "nav": [1.0, 1.019],
                "turnover": [0.0, 0.5],
                "holding_count": [0.0, 3.0],
            }
        )
        metrics = calc_performance(nav)
        self.assertIn("sortino", metrics)
        self.assertAlmostEqual(metrics["cost_drag"], 0.001)

    def test_security_contribution_and_cost_attribution(self):
        weights = pd.DataFrame(
            {
                "trade_date": pd.to_datetime(["2022-01-03", "2022-01-03"]),
                "ts_code": ["000001.SZ", "000002.SZ"],
                "target_weight": [0.6, 0.4],
            }
        )
        returns = pd.DataFrame(
            {
                "trade_date": pd.to_datetime(["2022-01-03", "2022-01-03"]),
                "ts_code": ["000001.SZ", "000002.SZ"],
                "return_1d": [0.01, -0.02],
            }
        )
        contrib = security_return_contribution(weights, returns)
        self.assertAlmostEqual(float(contrib["return_contribution"].sum()), -0.002)

        trades = pd.DataFrame({"buy_turnover": [1.0], "sell_turnover": [0.5], "gross_turnover": [1.5], "cost": [0.002]})
        cost = cost_attribution(trades, cost_config=CostConfig())
        self.assertAlmostEqual(float(cost["total_cost"].iloc[0]), 0.002)


if __name__ == "__main__":
    unittest.main()
