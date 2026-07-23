import unittest

import numpy as np
import pandas as pd

from ashare_factor_research.time_series.stage46 import (
    SCHEMAS,
    fit_volatility_qml,
    kalman_trial_registry,
    run_dcc_stage,
    run_hmm_stage,
    run_kalman_stage,
    run_stage46_models,
    run_volatility_stage,
    validate_kalman_registry,
)


class Stage46ResearchTest(unittest.TestCase):
    @staticmethod
    def _monthly_ic(periods=54, factors=6):
        rng = np.random.default_rng(101)
        dates = pd.date_range("2018-01-31", periods=periods, freq="ME")
        rows = []
        for index, date in enumerate(dates):
            latent = 0.025 + 0.0008 * index
            for factor_index in range(factors):
                sign = 1.0 if factor_index % 2 == 0 else -1.0
                rows.append({
                    "signal_date": date,
                    "availability_date": date + pd.Timedelta(days=15),
                    "factor": f"factor_{factor_index}",
                    "rank_ic": sign * latent + rng.normal(0.0, 0.003),
                    "valid_stock_count": 120,
                    "universe_denominator": 150,
                    "coverage": 0.8,
                })
        return pd.DataFrame(rows)

    def test_kalman_registry_is_exactly_27_and_matches_csv(self):
        trials = kalman_trial_registry()
        self.assertEqual(len(trials), 27)
        self.assertEqual(trials[["process_variance", "observation_variance", "turnover_penalty"]].drop_duplicates().shape[0], 27)
        validate_kalman_registry(pd.read_csv("config/experiment_registry.csv"))

    def test_kalman_grid_blocks_future_labels_and_enforces_weight_contract(self):
        monthly_ic = self._monthly_ic()
        dates = pd.DatetimeIndex(pd.date_range("2021-07-31", periods=6, freq="ME"))
        result = run_kalman_stage(
            monthly_ic,
            dates,
            config={
                "min_observations": 12, "min_asset_count": 30, "min_coverage": 0.3,
                "max_factors": 6, "max_factor_weight": 0.25, "max_fdr_q_value": 0.05,
            },
        )
        self.assertEqual(len(result["kalman_trial_registry"]), 27)
        forecasts = result["factor_ic_forecasts"]
        self.assertTrue((pd.to_datetime(forecasts["train_label_end_max"]) < pd.to_datetime(forecasts["test_date"])).all())
        self.assertEqual(forecasts["trial_id"].nunique(), 27)
        weights = result["dynamic_factor_weights"]
        self.assertFalse(weights.empty)
        grouped = weights.groupby(["test_date", "trial_id"])["weight"]
        self.assertTrue(np.allclose(grouped.sum().to_numpy(), 1.0))
        self.assertLessEqual(float(weights["weight"].max()), 0.25 + 1e-12)
        turnover = result["factor_weight_turnover"]
        self.assertTrue(np.allclose(turnover["turnover"], turnover["identity_l1"]))

        cutoff = dates[0]
        perturbed = monthly_ic.copy()
        perturbed.loc[perturbed["availability_date"] >= cutoff, "rank_ic"] = 99.0
        original = run_kalman_stage(monthly_ic, pd.DatetimeIndex([cutoff]), config={"max_factor_weight": 0.25, "max_factors": 6})
        changed = run_kalman_stage(perturbed, pd.DatetimeIndex([cutoff]), config={"max_factor_weight": 0.25, "max_factors": 6})
        forecast_columns = [column for column in original["factor_ic_forecasts"].columns if column != "actual_ic"]
        pd.testing.assert_frame_equal(
            original["factor_ic_forecasts"][forecast_columns],
            changed["factor_ic_forecasts"][forecast_columns],
        )

    @staticmethod
    def _state_variables(periods=90):
        rng = np.random.default_rng(202)
        dates = pd.date_range("2015-01-31", periods=periods, freq="ME")
        state = np.tile(np.r_[np.zeros(15), np.ones(15)], 3)[:periods]
        return pd.DataFrame({
            "signal_date": dates,
            "availability_date": dates,
            "benchmark_log_return": np.where(state == 0, -0.05, 0.05) + rng.normal(0, 0.008, periods),
            "realized_volatility_20": np.where(state == 0, 0.32, 0.12) + rng.normal(0, 0.01, periods),
            "breadth": np.where(state == 0, 0.25, 0.75) + rng.normal(0, 0.02, periods),
            "log_median_amount": 15.0 + rng.normal(0, 0.05, periods),
        })

    def test_hmm_probabilities_transitions_durations_and_prefix_are_stable(self):
        states = self._state_variables()
        origin = pd.Timestamp("2021-01-31")
        config = {"state_counts": [2], "initialization_seeds": [17, 29], "min_observations": 24, "max_iterations": 25}
        original = run_hmm_stage(states, pd.DatetimeIndex([origin]), config=config)
        probabilities = original["regime_probabilities"]
        self.assertEqual(probabilities.iloc[0]["status"], "ok")
        self.assertAlmostEqual(float(probabilities[["bear_probability", "neutral_probability", "bull_probability"]].sum(axis=1).iloc[0]), 1.0, places=8)
        self.assertGreater(float(probabilities.iloc[0]["bear_probability"]), float(probabilities.iloc[0]["bull_probability"]))
        transition = original["regime_transition_matrix"]
        self.assertTrue(np.allclose(transition.groupby("from_state")["probability"].sum(), 1.0))
        self.assertTrue((original["regime_durations"]["expected_duration"] > 0).all())

        perturbed = states.copy()
        mask = perturbed["availability_date"] >= origin
        perturbed.loc[mask, ["benchmark_log_return", "realized_volatility_20", "breadth"]] *= -10
        changed = run_hmm_stage(perturbed, pd.DatetimeIndex([origin]), config=config)
        pd.testing.assert_frame_equal(original["regime_probabilities"], changed["regime_probabilities"])
        rolling = run_hmm_stage(states, pd.DatetimeIndex([origin, origin + pd.offsets.MonthEnd(1)]), config=config)
        self.assertFalse(rolling["regime_stability"].empty)

    def test_garch_family_has_positive_variance_and_constraints(self):
        rng = np.random.default_rng(303)
        values = np.zeros(260)
        variance = np.full(260, 0.0001)
        for index in range(1, len(values)):
            variance[index] = 0.000005 + 0.08 * values[index - 1] ** 2 + 0.86 * variance[index - 1]
            values[index] = rng.normal(0.0, np.sqrt(variance[index]))
        for model in ("garch", "gjr_garch", "egarch"):
            result = fit_volatility_qml(values, model)
            self.assertEqual(result["status"], "ok", msg=f"{model}: {result.get('detail')}")
            self.assertGreater(float(result["forecast_variance"]), 0.0)
            self.assertLess(float(result["persistence"]), 0.999)

        dates = pd.date_range("2020-01-01", periods=len(values), freq="B")
        forecasts = run_volatility_stage(pd.Series(values, index=dates), pd.DatetimeIndex([dates[-5]]))
        frame = forecasts["volatility_forecasts"]
        self.assertEqual(set(frame["model"]), {"historical_20", "historical_60", "ewma", "garch", "gjr_garch", "egarch"})
        ok = frame[frame["status"].eq("ok")]
        self.assertTrue((ok["forecast_variance"] > 0).all())
        self.assertTrue(np.isfinite(ok["qlike"]).all())

    def test_dcc_is_symmetric_psd_and_requires_six_factors(self):
        rng = np.random.default_rng(404)
        dates = pd.date_range("2018-01-31", periods=40, freq="ME")
        rows = []
        common = rng.normal(0, 0.02, len(dates))
        for factor_index in range(6):
            series = (0.2 + 0.1 * factor_index) * common + rng.normal(0, 0.01, len(dates))
            for date, value in zip(dates, series):
                rows.append({"signal_date": date, "availability_date": date + pd.Timedelta(days=10), "factor": f"f{factor_index}", "q5_minus_q1": value})
        returns = pd.DataFrame(rows)
        result = run_dcc_stage(returns, pd.DatetimeIndex([pd.Timestamp("2021-06-30")]), [f"f{i}" for i in range(6)])
        covariance = result["dynamic_covariance"]
        self.assertFalse(covariance.empty)
        matrix = covariance.pivot(index="factor_left", columns="factor_right", values="conditional_covariance").to_numpy()
        self.assertTrue(np.allclose(matrix, matrix.T))
        self.assertGreaterEqual(float(np.linalg.eigvalsh(matrix).min()), -1e-10)
        fractions = result["dcc_risk_contributions"]["risk_contribution_fraction"]
        self.assertAlmostEqual(float(fractions.sum()), 1.0, places=8)
        blocked = run_dcc_stage(returns, pd.DatetimeIndex([pd.Timestamp("2021-06-30")]), [f"f{i}" for i in range(5)])
        self.assertTrue(blocked["dynamic_covariance"].empty)

    def test_orchestrator_keeps_sample_engineering_only_and_fixed_schemas(self):
        monthly_ic = self._monthly_ic(periods=18)
        dates = pd.DatetimeIndex(pd.to_datetime(monthly_ic["signal_date"].unique()))
        returns = monthly_ic.rename(columns={"rank_ic": "q5_minus_q1"})[["signal_date", "availability_date", "factor", "q5_minus_q1"]]
        result = run_stage46_models(
            monthly_ic, returns, self._state_variables(periods=18), None,
            rebalance_dates=dates, final_holdout_start="2024-01-01", mode="sample",
        )
        for name, columns in SCHEMAS.items():
            self.assertEqual(list(result[name].columns), columns)
        overall = result["stage46_status"].query("module == 'overall'").iloc[0]
        self.assertEqual(overall["status"], "insufficient_history")
        self.assertTrue(bool(overall["synthetic_engineering_only"]))

    def test_final_holdout_rows_cannot_change_pre_holdout_outputs(self):
        monthly_ic = self._monthly_ic(periods=54)
        returns = monthly_ic.rename(columns={"rank_ic": "q5_minus_q1"})[
            ["signal_date", "availability_date", "factor", "q5_minus_q1"]
        ]
        states = self._state_variables(periods=54)
        holdout = pd.Timestamp("2022-01-01")
        dates = pd.DatetimeIndex(pd.to_datetime(monthly_ic["signal_date"].unique()))
        first = run_stage46_models(
            monthly_ic, returns, states, None, rebalance_dates=dates,
            final_holdout_start=holdout, mode="sample",
        )
        changed_ic = monthly_ic.copy()
        changed_returns = returns.copy()
        changed_states = states.copy()
        changed_ic.loc[changed_ic["availability_date"] >= holdout, "rank_ic"] = 999.0
        changed_returns.loc[changed_returns["availability_date"] >= holdout, "q5_minus_q1"] = 999.0
        changed_states.loc[changed_states["availability_date"] >= holdout, "benchmark_log_return"] = 999.0
        second = run_stage46_models(
            changed_ic, changed_returns, changed_states, None, rebalance_dates=dates,
            final_holdout_start=holdout, mode="sample",
        )
        for name in ("factor_ic_forecasts", "dynamic_factor_weights", "regime_probabilities"):
            pd.testing.assert_frame_equal(first[name], second[name])


if __name__ == "__main__":
    unittest.main()
