from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import erf, exp, log, pi, sqrt
from statistics import NormalDist

import numpy as np
import pandas as pd


MODEL_VERSION = "time-series-v1"


@dataclass(frozen=True)
class KalmanForecast:
    filtered_mean: float
    filtered_variance: float
    forecast_mean: float
    forecast_variance: float
    observation_count: int


def kalman_local_level(
    values: pd.Series | np.ndarray,
    *,
    process_variance: float = 0.001,
    observation_variance: float = 0.01,
) -> KalmanForecast:
    """Filter a local-level model and return a one-step-ahead forecast."""

    clean = np.asarray(pd.Series(values).dropna(), dtype=float)
    if clean.size == 0:
        return KalmanForecast(np.nan, np.nan, np.nan, np.nan, 0)
    q = max(float(process_variance), 1e-12)
    r = max(float(observation_variance), 1e-12)
    mean = float(clean[0])
    variance = r * 10.0
    for observation in clean:
        predicted_variance = variance + q
        gain = predicted_variance / (predicted_variance + r)
        mean = mean + gain * (float(observation) - mean)
        variance = (1.0 - gain) * predicted_variance
    return KalmanForecast(
        filtered_mean=mean,
        filtered_variance=variance,
        forecast_mean=mean,
        forecast_variance=variance + q + r,
        observation_count=int(clean.size),
    )


class GaussianHMM:
    """Small diagonal-Gaussian HMM with forward-only probability output.

    Baum-Welch is used only for parameter estimation. ``filtered_probabilities``
    deliberately returns forward probabilities and never smoothed probabilities.
    """

    def __init__(self, n_states: int = 3, max_iter: int = 50, tolerance: float = 1e-5) -> None:
        if n_states < 2:
            raise ValueError("n_states must be at least 2")
        self.n_states = int(n_states)
        self.max_iter = int(max_iter)
        self.tolerance = float(tolerance)
        self.initial_: np.ndarray | None = None
        self.transition_: np.ndarray | None = None
        self.means_: np.ndarray | None = None
        self.variances_: np.ndarray | None = None
        self.location_: np.ndarray | None = None
        self.scale_: np.ndarray | None = None
        self.log_likelihood_: float = np.nan

    def _standardize(self, values: np.ndarray, *, fit: bool) -> np.ndarray:
        if fit:
            self.location_ = np.nanmean(values, axis=0)
            scale = np.nanstd(values, axis=0)
            self.scale_ = np.where(scale > 1e-12, scale, 1.0)
        if self.location_ is None or self.scale_ is None:
            raise ValueError("model is not fitted")
        return (values - self.location_) / self.scale_

    def _log_emission(self, values: np.ndarray) -> np.ndarray:
        if self.means_ is None or self.variances_ is None:
            raise ValueError("model is not fitted")
        result = np.empty((len(values), self.n_states), dtype=float)
        for state in range(self.n_states):
            var = np.maximum(self.variances_[state], 1e-6)
            diff = values - self.means_[state]
            result[:, state] = -0.5 * np.sum(np.log(2.0 * pi * var) + diff * diff / var, axis=1)
        return result

    @staticmethod
    def _emission_from_log(log_emission: np.ndarray) -> np.ndarray:
        shifted = log_emission - log_emission.max(axis=1, keepdims=True)
        return np.maximum(np.exp(shifted), 1e-300)

    def _forward(self, emission: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
        if self.initial_ is None or self.transition_ is None:
            raise ValueError("model is not fitted")
        alpha = np.zeros_like(emission)
        scales = np.zeros(len(emission), dtype=float)
        alpha[0] = self.initial_ * emission[0]
        scales[0] = max(float(alpha[0].sum()), 1e-300)
        alpha[0] /= scales[0]
        for step in range(1, len(emission)):
            alpha[step] = (alpha[step - 1] @ self.transition_) * emission[step]
            scales[step] = max(float(alpha[step].sum()), 1e-300)
            alpha[step] /= scales[step]
        return alpha, scales, float(np.log(scales).sum())

    def fit(self, values: pd.DataFrame | np.ndarray) -> GaussianHMM:
        raw = np.asarray(values, dtype=float)
        if raw.ndim == 1:
            raw = raw[:, None]
        if len(raw) < self.n_states * 3 or not np.isfinite(raw).all():
            raise ValueError("HMM requires finite observations and at least three observations per state")
        data = self._standardize(raw, fit=True)
        order = np.argsort(data[:, 0])
        partitions = np.array_split(order, self.n_states)
        self.means_ = np.vstack([data[idx].mean(axis=0) for idx in partitions])
        self.variances_ = np.vstack([np.maximum(data[idx].var(axis=0), 0.1) for idx in partitions])
        self.initial_ = np.full(self.n_states, 1.0 / self.n_states)
        self.transition_ = np.full((self.n_states, self.n_states), 0.1 / max(self.n_states - 1, 1))
        np.fill_diagonal(self.transition_, 0.9)
        self.transition_ /= self.transition_.sum(axis=1, keepdims=True)
        previous = -np.inf
        for _ in range(self.max_iter):
            emission = self._emission_from_log(self._log_emission(data))
            alpha, scales, likelihood = self._forward(emission)
            beta = np.ones_like(alpha)
            for step in range(len(data) - 2, -1, -1):
                beta[step] = self.transition_ @ (emission[step + 1] * beta[step + 1])
                beta[step] /= max(scales[step + 1], 1e-300)
            gamma = alpha * beta
            gamma /= np.maximum(gamma.sum(axis=1, keepdims=True), 1e-300)
            xi_sum = np.zeros_like(self.transition_)
            for step in range(len(data) - 1):
                xi = alpha[step][:, None] * self.transition_ * (emission[step + 1] * beta[step + 1])[None, :]
                xi_sum += xi / max(float(xi.sum()), 1e-300)
            self.initial_ = np.maximum(gamma[0], 1e-8)
            self.initial_ /= self.initial_.sum()
            self.transition_ = np.maximum(xi_sum, 1e-8)
            self.transition_ /= self.transition_.sum(axis=1, keepdims=True)
            weights = np.maximum(gamma.sum(axis=0), 1e-8)
            self.means_ = (gamma.T @ data) / weights[:, None]
            for state in range(self.n_states):
                diff = data - self.means_[state]
                self.variances_[state] = np.maximum(
                    (gamma[:, state][:, None] * diff * diff).sum(axis=0) / weights[state], 1e-4
                )
            if abs(likelihood - previous) < self.tolerance:
                break
            previous = likelihood
        self.log_likelihood_ = likelihood
        state_order = np.argsort(self.means_[:, 0])
        self.initial_ = self.initial_[state_order]
        self.means_ = self.means_[state_order]
        self.variances_ = self.variances_[state_order]
        self.transition_ = self.transition_[state_order][:, state_order]
        return self

    def filtered_probabilities(self, values: pd.DataFrame | np.ndarray) -> np.ndarray:
        raw = np.asarray(values, dtype=float)
        if raw.ndim == 1:
            raw = raw[:, None]
        data = self._standardize(raw, fit=False)
        emission = self._emission_from_log(self._log_emission(data))
        alpha, _, _ = self._forward(emission)
        return alpha

    def state_means_original_scale(self) -> np.ndarray:
        if self.means_ is None or self.location_ is None or self.scale_ is None:
            raise ValueError("model is not fitted")
        return self.means_ * self.scale_ + self.location_


def gjr_garch_forecast(values: pd.Series | np.ndarray) -> dict[str, float | int | str]:
    """Estimate a parsimonious GJR-GARCH(1,1) by deterministic QML grid search."""

    returns = np.asarray(pd.Series(values).dropna(), dtype=float)
    if returns.size < 30:
        return {"model": "gjr_garch_1_1", "status": "insufficient_history", "count": int(returns.size)}
    centered = returns - returns.mean()
    unconditional = max(float(centered.var(ddof=1)), 1e-12)
    best: tuple[float, float, float, float, float] | None = None
    for alpha in (0.03, 0.06, 0.10):
        for gamma in (0.0, 0.05, 0.10):
            for beta in (0.80, 0.87, 0.93, 0.96):
                persistence = alpha + 0.5 * gamma + beta
                if persistence >= 0.995:
                    continue
                omega = unconditional * (1.0 - persistence)
                variance = unconditional
                likelihood = 0.0
                for step, lagged in enumerate(centered[:-1], start=1):
                    variance = omega + alpha * lagged * lagged + gamma * (lagged < 0) * lagged * lagged + beta * variance
                    variance = max(float(variance), 1e-12)
                    likelihood += -0.5 * (log(2.0 * pi) + log(variance) + centered[step] ** 2 / variance)
                if best is None or likelihood > best[0]:
                    best = (likelihood, omega, alpha, gamma, beta)
    if best is None:
        return {"model": "gjr_garch_1_1", "status": "fit_failed", "count": int(returns.size)}
    _, omega, alpha, gamma, beta = best
    variance = unconditional
    for lagged in centered[:-1]:
        variance = omega + alpha * lagged * lagged + gamma * (lagged < 0) * lagged * lagged + beta * variance
    last = centered[-1]
    forecast_variance = omega + alpha * last * last + gamma * (last < 0) * last * last + beta * variance
    return {
        "model": "gjr_garch_1_1",
        "status": "ok",
        "count": int(returns.size),
        "omega": float(omega),
        "alpha": float(alpha),
        "gamma": float(gamma),
        "beta": float(beta),
        "forecast_variance": float(max(forecast_variance, 0.0)),
    }


def rolling_mean_forecast(train: pd.Series, window: int) -> float:
    """Mean of the most recent ``window`` observations."""

    clean = train.dropna().astype(float)
    if clean.empty:
        return np.nan
    return float(clean.tail(window).mean())


def expanding_forecast_comparison(
    series: pd.Series,
    *,
    min_train: int = 12,
    ewma_alpha: float = 0.2,
    exogenous: pd.DataFrame | None = None,
    target_series: str = "target",
    trade_dates: pd.DatetimeIndex | None = None,
) -> pd.DataFrame:
    """Compare one-step naive, mean, rolling means, EWMA and ARIMA(1,0,0)-equivalent forecasts."""

    clean = series.dropna().astype(float).sort_index()
    if exogenous is not None and exogenous.shape[1] > 4:
        raise ValueError("ARIMAX accepts at most four preregistered economic variables")
    exog = exogenous.reindex(clean.index).astype(float).ffill() if exogenous is not None else None
    rows: list[dict[str, object]] = []
    for idx in range(max(int(min_train), 3), len(clean)):
        train = clean.iloc[:idx]
        actual = float(clean.iloc[idx])
        target_date = clean.index[idx]
        forecast_origin = train.index[-1]
        # A monthly realized target is observable at its target timestamp.  It
        # must never enter the training set at the preceding forecast origin.
        availability_date = pd.Timestamp(target_date)
        x = train.to_numpy()[:-1]
        y = train.to_numpy()[1:]
        if len(x) >= 2 and float(np.var(x)) > 1e-12:
            slope = float(np.cov(x, y, ddof=0)[0, 1] / np.var(x))
            intercept = float(y.mean() - slope * x.mean())
            ar1 = intercept + slope * float(train.iloc[-1])
        else:
            ar1 = float(train.mean())
        forecasts = {
            "lag_1": float(train.iloc[-1]),
            "historical_mean": float(train.mean()),
            "rolling_12m_mean": rolling_mean_forecast(train, 12),
            "rolling_24m_mean": rolling_mean_forecast(train, 24),
            "ewma": float(train.ewm(alpha=ewma_alpha, adjust=False).mean().iloc[-1]),
            "ar_1": ar1,
        }
        if exog is not None and idx >= 4:
            train_exog = exog.iloc[:idx]
            design = pd.concat(
                [
                    pd.Series(1.0, index=train.index[1:], name="intercept"),
                    train.shift(1).rename("lagged_target"),
                    train_exog.shift(1).add_prefix("lagged_"),
                ],
                axis=1,
                sort=False,
            ).loc[train.index[1:]]
            response = train.loc[design.index].rename("target")
            fitted = pd.concat([response, design], axis=1).dropna()
            if len(fitted) >= design.shape[1] + 2:
                beta = np.linalg.lstsq(
                    fitted[design.columns].to_numpy(dtype=float),
                    fitted["target"].to_numpy(dtype=float),
                    rcond=None,
                )[0]
                forecast_row = np.r_[1.0, float(train.iloc[-1]), train_exog.iloc[-1].to_numpy(dtype=float)]
                forecasts["arimax_1_0_0"] = float(forecast_row @ beta)
        for model, forecast in forecasts.items():
            direction_hit = np.nan
            if np.isfinite(forecast) and np.isfinite(actual):
                direction_hit = int(np.sign(forecast) == np.sign(actual))
            rows.append({
                "target_series": target_series,
                "train_start": train.index[0],
                "train_end": train.index[-1],
                "training_end": train.index[-1],
                "forecast_origin": forecast_origin,
                "forecast_target": target_date,
                "availability_date": availability_date,
                "model": model,
                "forecast": forecast,
                "actual": actual,
                "error": actual - forecast,
                "squared_error": (actual - forecast) ** 2,
                "absolute_error": abs(actual - forecast),
                "direction_hit": direction_hit,
                "point_in_time_valid": bool(
                    pd.Timestamp(train.index[-1]) < pd.Timestamp(target_date)
                    and pd.Timestamp(forecast_origin) < pd.Timestamp(availability_date)
                ),
                "model_version": MODEL_VERSION,
            })
    return pd.DataFrame(rows)


def _next_trade_date(trade_dates: pd.DatetimeIndex, date: pd.Timestamp) -> pd.Timestamp:
    """Return the first trade date strictly after ``date``."""

    sorted_dates = pd.DatetimeIndex(pd.to_datetime(trade_dates)).sort_values().unique()
    idx = sorted_dates.searchsorted(pd.Timestamp(date), side="right")
    if idx >= len(sorted_dates):
        return pd.Timestamp(date) + pd.Timedelta(days=1)
    return pd.Timestamp(sorted_dates[idx])


def diebold_mariano_test(
    benchmark_errors: pd.Series | np.ndarray,
    candidate_errors: pd.Series | np.ndarray,
    *,
    max_lag: int = 1,
) -> dict[str, float | int | str]:
    """Two-sided Diebold-Mariano test using a Bartlett HAC variance."""

    first = np.asarray(pd.Series(benchmark_errors).dropna(), dtype=float)
    second = np.asarray(pd.Series(candidate_errors).dropna(), dtype=float)
    count = min(len(first), len(second))
    if count < 8:
        return {"status": "insufficient_history", "count": count, "dm_stat": np.nan, "p_value": np.nan}
    loss_diff = first[:count] ** 2 - second[:count] ** 2
    demeaned = loss_diff - loss_diff.mean()
    long_run = float(np.dot(demeaned, demeaned) / count)
    for lag in range(1, min(max_lag, count - 1) + 1):
        covariance = float(np.dot(demeaned[lag:], demeaned[:-lag]) / count)
        long_run += 2.0 * (1.0 - lag / (max_lag + 1.0)) * covariance
    standard_error = sqrt(max(long_run, 0.0) / count)
    statistic = float(loss_diff.mean() / standard_error) if standard_error > 0 else np.nan
    p_value = 2.0 * (1.0 - 0.5 * (1.0 + erf(abs(statistic) / sqrt(2.0)))) if np.isfinite(statistic) else np.nan
    return {"status": "ok", "count": count, "dm_stat": statistic, "p_value": float(p_value)}


def superior_predictive_ability_test(
    loss_differentials: pd.DataFrame,
    *,
    bootstrap_samples: int = 500,
    block_length: int | None = None,
    seed: int = 0,
) -> dict[str, float | int | str]:
    """Hansen-style SPA test using a deterministic circular block bootstrap.

    Columns are candidate loss minus benchmark loss, so negative means that a
    candidate forecasts better. The null is that no candidate has positive
    expected loss advantage over the benchmark.
    """

    clean = loss_differentials.dropna(how="any").astype(float)
    count, model_count = clean.shape
    if count < 20 or model_count < 1:
        return {
            "status": "insufficient_history", "observations": count,
            "model_count": model_count, "spa_stat": np.nan, "p_value": np.nan,
        }
    advantage = -clean.to_numpy(dtype=float)
    means = advantage.mean(axis=0)
    scale = advantage.std(axis=0, ddof=1) / sqrt(count)
    valid = scale > 1e-12
    if not bool(valid.any()):
        return {
            "status": "degenerate", "observations": count, "model_count": model_count,
            "spa_stat": np.nan, "p_value": np.nan,
        }
    observed = float(np.max(np.where(valid, means / scale, -np.inf)))
    length = int(block_length or max(2, round(count ** (1.0 / 3.0))))
    length = min(max(length, 1), count)
    rng = np.random.default_rng(seed)
    # Truncate candidates with clearly negative performance while imposing the
    # least-favourable null on plausible competitors.
    threshold = -scale * sqrt(2.0 * log(max(log(count), 1.000001)))
    null_mean = np.where(means < threshold, means, 0.0)
    centered = advantage - null_mean
    bootstrap_stats = np.empty(int(bootstrap_samples), dtype=float)
    for sample_idx in range(int(bootstrap_samples)):
        blocks: list[np.ndarray] = []
        while sum(len(block) for block in blocks) < count:
            start = int(rng.integers(0, count))
            blocks.append((start + np.arange(length)) % count)
        indices = np.concatenate(blocks)[:count]
        boot_mean = centered[indices].mean(axis=0)
        bootstrap_stats[sample_idx] = float(np.max(np.where(valid, boot_mean / scale, -np.inf)))
    p_value = float((1.0 + np.sum(bootstrap_stats >= observed)) / (len(bootstrap_stats) + 1.0))
    return {
        "status": "ok", "observations": count, "model_count": model_count,
        "spa_stat": observed, "p_value": p_value, "bootstrap_samples": int(bootstrap_samples),
        "block_length": length,
    }


def deflated_sharpe_probability(
    returns: pd.Series | np.ndarray,
    *,
    trial_count: int = 1,
    periods_per_year: int = 252,
) -> dict[str, float | int | str]:
    """Approximate the Deflated Sharpe probability after multiple trials."""

    clean = pd.Series(returns).dropna().astype(float)
    count = len(clean)
    if count < 20:
        return {"status": "insufficient_history", "count": count, "probability": np.nan}
    std = float(clean.std(ddof=1))
    if std <= 0:
        return {"status": "degenerate", "count": count, "probability": np.nan}
    sharpe = float(clean.mean() / std * sqrt(periods_per_year))
    skew = float(clean.skew())
    kurtosis = float(clean.kurt() + 3.0)
    variance = max((1.0 - skew * sharpe + ((kurtosis - 1.0) / 4.0) * sharpe * sharpe) / (count - 1), 1e-12)
    sharpe_std = sqrt(variance)
    trials = max(int(trial_count), 1)
    if trials == 1:
        benchmark_sharpe = 0.0
    else:
        normal = NormalDist()
        euler_gamma = 0.5772156649015329
        benchmark_sharpe = sharpe_std * (
            (1.0 - euler_gamma) * normal.inv_cdf(1.0 - 1.0 / trials)
            + euler_gamma * normal.inv_cdf(1.0 - 1.0 / (trials * exp(1.0)))
        )
    statistic = (sharpe - benchmark_sharpe) / sharpe_std
    probability = NormalDist().cdf(statistic)
    return {
        "status": "ok", "count": count, "sharpe": sharpe, "benchmark_sharpe": benchmark_sharpe,
        "probability": float(probability), "trial_count": trials,
    }


def probability_of_backtest_overfitting(
    strategy_returns: pd.DataFrame,
    *,
    block_count: int = 8,
) -> dict[str, float | int | str]:
    """Estimate PBO with combinatorially symmetric cross-validation."""

    clean = strategy_returns.dropna(how="any").astype(float)
    if clean.shape[1] < 2 or clean.shape[0] < block_count * 5 or block_count % 2:
        return {
            "status": "insufficient_history", "observations": int(clean.shape[0]),
            "strategy_count": int(clean.shape[1]), "pbo": np.nan,
        }
    blocks = [np.asarray(block, dtype=int) for block in np.array_split(np.arange(len(clean)), block_count)]
    logits: list[float] = []
    for chosen in combinations(range(block_count), block_count // 2):
        in_idx = np.concatenate([blocks[idx] for idx in chosen])
        out_idx = np.concatenate([blocks[idx] for idx in range(block_count) if idx not in chosen])
        in_sample = clean.iloc[in_idx]
        out_sample = clean.iloc[out_idx]
        in_sharpe = in_sample.mean() / in_sample.std(ddof=1).replace(0.0, np.nan)
        if in_sharpe.dropna().empty:
            continue
        selected = str(in_sharpe.idxmax())
        out_sharpe = out_sample.mean() / out_sample.std(ddof=1).replace(0.0, np.nan)
        ranks = out_sharpe.rank(method="average", pct=True)
        relative_rank = float(ranks.get(selected, np.nan))
        if not np.isfinite(relative_rank):
            continue
        clipped = float(np.clip(relative_rank, 1e-6, 1.0 - 1e-6))
        logits.append(log(clipped / (1.0 - clipped)))
    if not logits:
        return {"status": "fit_failed", "observations": len(clean), "strategy_count": clean.shape[1], "pbo": np.nan}
    return {
        "status": "ok", "observations": int(len(clean)), "strategy_count": int(clean.shape[1]),
        "combinations": int(len(logits)), "pbo": float(np.mean(np.asarray(logits) <= 0.0)),
    }


def dcc_covariance(
    returns: pd.DataFrame,
    *,
    alpha: float = 0.02,
    beta: float = 0.97,
) -> pd.DataFrame:
    """Return the latest DCC covariance estimate for a small return block."""

    clean = returns.dropna(how="any").astype(float)
    if clean.shape[0] < 20 or clean.shape[1] < 2:
        return pd.DataFrame()
    if alpha < 0 or beta < 0 or alpha + beta >= 1:
        raise ValueError("DCC alpha and beta must be non-negative and sum to less than one")
    scale = clean.std(ddof=1).replace(0.0, np.nan)
    standardized = ((clean - clean.mean()) / scale).dropna(how="any")
    if len(standardized) < 20:
        return pd.DataFrame()
    values = standardized.to_numpy()
    q_bar = np.cov(values, rowvar=False)
    q = q_bar.copy()
    for row in values:
        q = (1.0 - alpha - beta) * q_bar + alpha * np.outer(row, row) + beta * q
    diagonal = np.sqrt(np.maximum(np.diag(q), 1e-12))
    correlation = q / np.outer(diagonal, diagonal)
    covariance = np.diag(scale.to_numpy()) @ correlation @ np.diag(scale.to_numpy())
    return pd.DataFrame(covariance, index=clean.columns, columns=clean.columns)
