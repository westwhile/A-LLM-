import unittest

import numpy as np
import pandas as pd

from ashare_factor_research.time_series.interface import PointInTimeForecaster
from ashare_factor_research.time_series.models import (
    GaussianHMM,
    dcc_covariance,
    deflated_sharpe_probability,
    diebold_mariano_test,
    gjr_garch_forecast,
    expanding_forecast_comparison,
    kalman_local_level,
    probability_of_backtest_overfitting,
    superior_predictive_ability_test,
)
from ashare_factor_research.time_series.research import (
    build_dynamic_factor_weights,
    build_dynamic_scores,
    build_regime_probabilities,
    build_volatility_forecasts,
)


class TimeSeriesModelTest(unittest.TestCase):
    def test_uniform_forecaster_enforces_point_in_time_boundary_and_update_order(self):
        dates = pd.date_range("2020-01-31", periods=12, freq="ME")
        model = PointInTimeForecaster("kalman_local_level", min_observations=12)
        model.fit(pd.Series(np.linspace(0.01, 0.03, 12), index=dates), as_of_date=dates[-1])
        forecast = model.forecast(target_date=dates[-1] + pd.offsets.MonthEnd(1))
        self.assertEqual(forecast.status, "ok")
        self.assertTrue(forecast.passed_validity_gate)
        self.assertLess(forecast.training_end, forecast.forecast_target)
        with self.assertRaises(ValueError):
            model.update(0.02, as_of_date=dates[-1])
        with self.assertRaises(ValueError):
            model.forecast(target_date=dates[-1])

    def test_kalman_local_level_recovers_positive_latent_mean(self):
        rng = np.random.default_rng(7)
        observations = pd.Series(0.12 + rng.normal(0.0, 0.02, 80))
        forecast = kalman_local_level(observations, process_variance=1e-5, observation_variance=0.0004)
        self.assertEqual(forecast.observation_count, 80)
        self.assertGreater(forecast.forecast_mean, 0.08)
        self.assertLess(forecast.forecast_mean, 0.16)
        self.assertGreater(forecast.forecast_variance, 0.0)

    def test_hmm_filtered_probabilities_are_normalized_and_forward_only(self):
        rng = np.random.default_rng(9)
        values = np.r_[rng.normal(-1.0, 0.15, 40), rng.normal(1.0, 0.15, 40)]
        model = GaussianHMM(n_states=2, max_iter=30).fit(values)
        prefix = values[:50]
        filtered_prefix = model.filtered_probabilities(prefix)
        filtered_full = model.filtered_probabilities(values)
        self.assertTrue(np.allclose(filtered_prefix.sum(axis=1), 1.0))
        self.assertTrue(np.allclose(filtered_prefix[-1], filtered_full[49]))
        self.assertLess(model.state_means_original_scale()[0, 0], model.state_means_original_scale()[1, 0])

    def test_dynamic_weights_use_only_available_labels(self):
        dates = pd.date_range("2018-01-31", periods=24, freq="ME")
        rows = []
        for idx, date in enumerate(dates):
            for factor, value in (("quality", 0.08 + idx * 0.001), ("value", -0.05)):
                rows.append({
                    "signal_date": date,
                    "availability_date": date + pd.Timedelta(days=20),
                    "factor": factor,
                    "rank_ic": value,
                    "asset_count": 100,
                })
        test_date = pd.Timestamp("2020-03-31")
        weights = build_dynamic_factor_weights(
            pd.DataFrame(rows), pd.DatetimeIndex([test_date]), min_observations=12, max_factors=2,
            max_factor_weight=0.7,
        )
        self.assertFalse(weights.empty)
        self.assertTrue((pd.to_datetime(weights["train_label_end_max"]) < test_date).all())
        self.assertAlmostEqual(float(weights["weight"].sum()), 1.0)
        self.assertEqual(set(weights["direction"]), {1.0, -1.0})

        panel = pd.DataFrame({
            "trade_date": [test_date, test_date], "ts_code": ["A", "B"],
            "quality": [1.0, -1.0], "value": [-1.0, 1.0],
        })
        scores = build_dynamic_scores(panel, weights)
        self.assertEqual(set(scores["score_source"]), {"time_series_dynamic"})
        self.assertGreater(float(scores.loc[scores["ts_code"].eq("A"), "score"].iloc[0]), 0.0)

    def test_gjr_and_dcc_return_finite_risk_forecasts(self):
        rng = np.random.default_rng(11)
        returns = pd.Series(rng.normal(0.0, 0.01, 250))
        forecast = gjr_garch_forecast(returns)
        self.assertEqual(forecast["status"], "ok")
        self.assertGreater(float(forecast["forecast_variance"]), 0.0)

        block = pd.DataFrame({
            "factor_a": returns,
            "factor_b": 0.4 * returns + rng.normal(0.0, 0.008, len(returns)),
        })
        covariance = dcc_covariance(block)
        self.assertEqual(covariance.shape, (2, 2))
        self.assertTrue(np.allclose(covariance, covariance.T))

    def test_research_forecast_metadata_is_strictly_forward(self):
        dates = pd.date_range("2018-01-01", periods=90, freq="B")
        rng = np.random.default_rng(12)
        standard = pd.DataFrame(
            {
                "benchmark_log_return": rng.normal(0.0, 0.01, len(dates)),
                "realized_volatility_20": rng.uniform(0.1, 0.3, len(dates)),
                "breadth": rng.uniform(0.2, 0.8, len(dates)),
                "log_median_amount": rng.normal(15.0, 0.2, len(dates)),
            },
            index=dates,
        )
        as_of = dates[70]
        regime = build_regime_probabilities(
            standard,
            pd.DatetimeIndex([as_of]),
            n_states=2,
            min_observations=2,
            max_iterations=2,
        )
        volatility = build_volatility_forecasts(
            pd.Series(rng.normal(0.0, 0.01, len(dates)), index=dates),
            pd.DatetimeIndex([as_of]),
            min_observations=20,
        )
        self.assertTrue((pd.to_datetime(regime["training_end"]) < pd.to_datetime(regime["forecast_target"])).all())
        self.assertTrue((pd.to_datetime(volatility["training_end"]) < pd.to_datetime(volatility["forecast_target"])).all())

    def test_diebold_mariano_reports_insufficient_short_samples(self):
        result = diebold_mariano_test([0.1, 0.2], [0.1, 0.1])
        self.assertEqual(result["status"], "insufficient_history")

    def test_forecast_comparison_includes_arimax_when_exogenous_data_are_available(self):
        rng = np.random.default_rng(13)
        dates = pd.date_range("2018-01-31", periods=36, freq="ME")
        exogenous = pd.DataFrame({
            "breadth": rng.normal(0.0, 1.0, len(dates)),
            "liquidity": rng.normal(0.0, 1.0, len(dates)),
        }, index=dates)
        target = pd.Series(
            0.01 + 0.003 * exogenous["breadth"].shift(1).fillna(0.0)
            + rng.normal(0.0, 0.01, len(dates)),
            index=dates,
        )
        forecasts = expanding_forecast_comparison(
            target, exogenous=exogenous, min_train=12,
        )
        self.assertIn("arimax_1_0_0", set(forecasts["model"]))
        self.assertTrue((forecasts["training_end"] < forecasts["forecast_target"]).all())

    def test_multiple_trial_audits_return_bounded_probabilities(self):
        rng = np.random.default_rng(17)
        returns = pd.DataFrame({
            "a": rng.normal(0.001, 0.01, 160),
            "b": rng.normal(0.0002, 0.01, 160),
            "c": rng.normal(-0.0001, 0.01, 160),
        })
        dsr = deflated_sharpe_probability(returns["a"], trial_count=3)
        self.assertEqual(dsr["status"], "ok")
        self.assertGreaterEqual(float(dsr["probability"]), 0.0)
        self.assertLessEqual(float(dsr["probability"]), 1.0)
        pbo = probability_of_backtest_overfitting(returns, block_count=8)
        self.assertEqual(pbo["status"], "ok")
        self.assertGreaterEqual(float(pbo["pbo"]), 0.0)
        self.assertLessEqual(float(pbo["pbo"]), 1.0)

        losses = pd.DataFrame({
            "candidate_a": rng.normal(-0.0001, 0.001, 80),
            "candidate_b": rng.normal(0.0001, 0.001, 80),
        })
        spa = superior_predictive_ability_test(losses, bootstrap_samples=100, seed=17)
        self.assertEqual(spa["status"], "ok")
        self.assertGreaterEqual(float(spa["p_value"]), 0.0)
        self.assertLessEqual(float(spa["p_value"]), 1.0)


if __name__ == "__main__":
    unittest.main()
