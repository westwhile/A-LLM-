import unittest

import numpy as np
import pandas as pd

from ashare_factor_research.time_series.stage46 import _trial_id
from ashare_factor_research.time_series.stage7 import (
    INCREMENTAL_COMPARISONS,
    PORTFOLIO_IDS,
    PORTFOLIO_SPECS,
    STAGE7_SCHEMAS,
    run_stage7_ablation,
)


class Stage7AblationTest(unittest.TestCase):
    FACTORS = [f"f{i}" for i in range(6)]

    def _monthly_frames(self, periods=54):
        rng = np.random.default_rng(101)
        dates = pd.date_range("2018-01-31", periods=periods, freq="ME")
        ic_rows, return_rows = [], []
        for date in dates:
            for index, factor in enumerate(self.FACTORS):
                sign = 1.0 if index % 2 == 0 else -1.0
                ic_rows.append({
                    "signal_date": date, "availability_date": date + pd.Timedelta(days=15),
                    "factor": factor, "rank_ic": sign * 0.03 + rng.normal(0.0, 0.005),
                    "asset_count": 100,
                })
                return_rows.append({
                    "signal_date": date, "availability_date": date + pd.Timedelta(days=15),
                    "factor": factor, "q5_minus_q1": sign * 0.01 + rng.normal(0.0, 0.01),
                })
        return pd.DataFrame(ic_rows), pd.DataFrame(return_rows)

    def _artifacts(self, dates):
        trial = _trial_id(0.001, 0.01, 0.20)
        weight_rows, regime_rows, volatility_rows, covariance_rows = [], [], [], []
        for date in dates:
            for index, factor in enumerate(self.FACTORS):
                sign = 1.0 if index % 2 == 0 else -1.0
                weight_rows.append({
                    "test_date": date, "factor": factor, "trial_id": trial,
                    "direction": sign, "weight": 1.0 / len(self.FACTORS),
                })
                covariance_rows.append({
                    "as_of_date": date, "factor_left": factor, "factor_right": factor,
                    "conditional_covariance": 0.001 * (1 + index), "model": "dcc_0.02_0.97",
                })
            regime_rows.append({
                "as_of_date": date, "model": "hmm_3_state", "status": "ok",
                "bear_probability": 0.2, "neutral_probability": 0.2, "bull_probability": 0.6,
            })
            volatility_rows.append({
                "as_of_date": date, "model": "gjr_garch", "status": "ok",
                "annualized_volatility_forecast": 0.30,
            })
        return {
            "dynamic_factor_weights": pd.DataFrame(weight_rows),
            "regime_probabilities": pd.DataFrame(regime_rows),
            "volatility_forecasts": pd.DataFrame(volatility_rows),
            "dynamic_covariance": pd.DataFrame(covariance_rows),
        }

    def _run(self, periods=54, artifacts="default", mode="sample"):
        monthly_ic, monthly_returns = self._monthly_frames(periods)
        dates = pd.DatetimeIndex(pd.to_datetime(monthly_ic["signal_date"].unique()))
        if artifacts == "default":
            artifacts = self._artifacts(dates)
        return run_stage7_ablation(
            monthly_ic, monthly_returns,
            artifacts=artifacts, mode=mode, rebalance_dates=dates,
            final_holdout_start="2024-06-01",
        )

    def test_seven_portfolios_and_switch_mapping(self):
        result = self._run()
        for name, columns in STAGE7_SCHEMAS.items():
            self.assertEqual(list(result[name].columns), columns)
        returns = result["ablation_portfolio_returns"]
        self.assertEqual(sorted(returns["portfolio_id"].unique()), list(PORTFOLIO_IDS))
        self.assertEqual(PORTFOLIO_IDS, tuple("ABCDEFG"))
        status = result["ablation_status"].set_index("portfolio_id")
        for portfolio_id, spec in PORTFOLIO_SPECS.items():
            self.assertEqual(status.loc[portfolio_id, "weight_scheme"], spec["weight_scheme"])
            self.assertEqual(status.loc[portfolio_id, "regime_adjustment"], spec["regime_adjustment"])
            self.assertEqual(status.loc[portfolio_id, "volatility_control"], spec["volatility_control"])
            self.assertEqual(status.loc[portfolio_id, "status"], "ok")
        self.assertEqual(status.loc["overall", "status"], "ablation_complete")
        self.assertTrue(bool(status.loc["overall", "synthetic_engineering_only"]))

    def test_shared_rebalance_dates_and_comparison_interval(self):
        result = self._run()
        returns = result["ablation_portfolio_returns"]
        date_sets = returns.groupby("portfolio_id")["date"].apply(lambda series: tuple(series))
        self.assertEqual(date_sets.nunique(), 1)
        nav = result["ablation_nav"]
        nav_date_sets = nav.groupby("portfolio_id")["date"].apply(lambda series: tuple(series))
        self.assertEqual(nav_date_sets.nunique(), 1)
        self.assertEqual(set(nav["date"].unique()), set(returns["date"].unique()))
        performance = result["ablation_performance"]
        self.assertEqual(sorted(performance["portfolio_id"]), list(PORTFOLIO_IDS))
        self.assertTrue((performance["oos_months"] == returns["date"].nunique()).all())

    def test_incremental_table_has_exactly_six_directed_rows(self):
        result = self._run()
        incremental = result["ablation_incremental"]
        self.assertEqual(len(incremental), 6)
        expected = [f"{treatment}-{baseline}" for treatment, baseline in INCREMENTAL_COMPARISONS]
        self.assertEqual(list(incremental["comparison"]), expected)
        self.assertEqual(list(incremental["treatment"]), [item[0] for item in INCREMENTAL_COMPARISONS])
        self.assertEqual(list(incremental["baseline"]), [item[1] for item in INCREMENTAL_COMPARISONS])
        annual = result["ablation_performance"].set_index("portfolio_id")["annual_return"]
        for _, row in incremental.iterrows():
            self.assertAlmostEqual(
                row["incremental_annual_return"],
                float(annual[row["treatment"]] - annual[row["baseline"]]),
                places=12,
            )
        self.assertTrue((incremental["status"] == "ok").all())

    def test_cost_sensitivity_covers_seven_portfolios_and_three_scenarios(self):
        result = self._run()
        sensitivity = result["ablation_cost_sensitivity"]
        self.assertEqual(len(sensitivity), 21)
        self.assertEqual(sorted(sensitivity["cost_scenario"].unique()), ["high", "standard", "zero"])
        pivot = sensitivity.pivot(index="portfolio_id", columns="cost_scenario", values="net_annual_return")
        self.assertTrue((pivot["zero"] >= pivot["standard"] - 1e-12).all())
        self.assertTrue((pivot["standard"] >= pivot["high"] - 1e-12).all())

    def test_prefix_stability_against_future_pollution(self):
        monthly_ic, monthly_returns = self._monthly_frames()
        dates = pd.DatetimeIndex(pd.to_datetime(monthly_ic["signal_date"].unique()))
        artifacts = self._artifacts(dates)
        origin = dates[30]
        kwargs = dict(
            artifacts=artifacts, mode="sample", rebalance_dates=dates, final_holdout_start="2024-06-01",
        )
        original = run_stage7_ablation(monthly_ic, monthly_returns, **kwargs)
        polluted_ic = monthly_ic.copy()
        polluted_returns = monthly_returns.copy()
        polluted_ic.loc[polluted_ic["signal_date"] >= origin, "rank_ic"] = 999.0
        polluted_returns.loc[polluted_returns["signal_date"] >= origin, "q5_minus_q1"] = -0.9
        changed = run_stage7_ablation(polluted_ic, polluted_returns, **kwargs)
        for name in ("ablation_portfolio_returns", "ablation_nav"):
            before_original = original[name][original[name]["date"] < origin].reset_index(drop=True)
            before_changed = changed[name][changed[name]["date"] < origin].reset_index(drop=True)
            pd.testing.assert_frame_equal(before_original, before_changed)

    def test_missing_artifacts_block_only_dependent_portfolios(self):
        result = self._run(artifacts={
            "dynamic_factor_weights": None, "regime_probabilities": None,
            "volatility_forecasts": None, "dynamic_covariance": None,
        }, mode="real")
        status = result["ablation_status"].set_index("portfolio_id")["status"]
        self.assertEqual(status["A"], "ok")
        self.assertEqual(status["B"], "ok")
        for portfolio_id in ("C", "D", "E", "F", "G"):
            self.assertEqual(status[portfolio_id], "missing_input")
        self.assertEqual(status["overall"], "missing_input")
        incremental = result["ablation_incremental"].set_index("comparison")["status"]
        self.assertEqual(incremental["C-A"], "missing_input")
        self.assertEqual(incremental["G-A"], "missing_input")
        self.assertFalse(bool(result["ablation_status"].iloc[0]["synthetic_engineering_only"]))

    def test_short_history_marks_insufficient_with_fixed_schemas(self):
        monthly_ic, monthly_returns = self._monthly_frames(18)
        dates = pd.DatetimeIndex(pd.to_datetime(monthly_ic["signal_date"].unique()))
        result = run_stage7_ablation(
            monthly_ic, monthly_returns,
            artifacts=self._artifacts(dates), mode="sample", rebalance_dates=dates,
            final_holdout_start="2024-06-01",
        )
        for name, columns in STAGE7_SCHEMAS.items():
            self.assertEqual(list(result[name].columns), columns)
        for name in (
            "ablation_portfolio_returns", "ablation_nav", "ablation_performance",
            "ablation_incremental", "ablation_cost_sensitivity",
        ):
            frame = result[name]
            self.assertEqual(len(frame), 1)
            self.assertEqual(frame["status"].iloc[0], "insufficient_history")
        status = result["ablation_status"].set_index("portfolio_id")["status"]
        self.assertTrue((status.drop("overall") == "insufficient_history").all())
        self.assertEqual(status["overall"], "insufficient_history")


if __name__ == "__main__":
    unittest.main()
