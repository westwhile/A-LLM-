"""Uniform point-in-time interface for deployable time-series forecasts."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ashare_factor_research.time_series.models import (
    MODEL_VERSION,
    gjr_garch_forecast,
    kalman_local_level,
)


@dataclass(frozen=True)
class ForecastEnvelope:
    """Auditable forecast returned by every supported model."""

    as_of_date: pd.Timestamp
    training_end: pd.Timestamp | pd.NaT
    forecast_target: pd.Timestamp
    model: str
    model_version: str
    observation_count: int
    forecast: float
    passed_validity_gate: bool
    status: str

    def as_dict(self) -> dict[str, object]:
        return {
            "as_of_date": self.as_of_date,
            "training_end": self.training_end,
            "forecast_target": self.forecast_target,
            "model": self.model,
            "model_version": self.model_version,
            "observation_count": self.observation_count,
            "forecast": self.forecast,
            "passed_validity_gate": self.passed_validity_gate,
            "status": self.status,
        }


class PointInTimeForecaster:
    """Small stateful facade with consistent fit, update and forecast semantics.

    Supported models are deliberately interpretable first-version baselines:
    historical mean, EWMA, local-level Kalman and GJR-GARCH variance.
    """

    SUPPORTED_MODELS = {"historical_mean", "ewma", "kalman_local_level", "gjr_garch"}

    def __init__(
        self,
        model: str,
        *,
        min_observations: int = 12,
        ewma_alpha: float = 0.2,
        process_variance: float = 0.001,
        observation_variance: float = 0.01,
    ) -> None:
        if model not in self.SUPPORTED_MODELS:
            raise ValueError(f"unsupported time-series model: {model}")
        if min_observations < 2:
            raise ValueError("min_observations must be at least 2")
        self.model = model
        self.min_observations = int(min_observations)
        self.ewma_alpha = float(ewma_alpha)
        self.process_variance = float(process_variance)
        self.observation_variance = float(observation_variance)
        self._history = pd.Series(dtype=float)
        self._as_of_date: pd.Timestamp | None = None

    def fit(self, series: pd.Series, *, as_of_date: str | pd.Timestamp) -> "PointInTimeForecaster":
        cutoff = pd.Timestamp(as_of_date)
        history = pd.Series(series, copy=True).dropna().astype(float).sort_index()
        history.index = pd.to_datetime(history.index)
        if history.index.has_duplicates:
            raise ValueError("time-series history index must be unique")
        if bool((history.index > cutoff).any()):
            raise ValueError("training history contains observations after as_of_date")
        self._history = history
        self._as_of_date = cutoff
        return self

    def update(self, value: float, *, as_of_date: str | pd.Timestamp) -> "PointInTimeForecaster":
        update_date = pd.Timestamp(as_of_date)
        if self._as_of_date is not None and update_date <= self._as_of_date:
            raise ValueError("update as_of_date must be later than the current cutoff")
        self._history.loc[update_date] = float(value)
        self._history = self._history.sort_index()
        self._as_of_date = update_date
        return self

    def forecast(self, *, target_date: str | pd.Timestamp) -> ForecastEnvelope:
        if self._as_of_date is None:
            raise RuntimeError("fit must be called before forecast")
        target = pd.Timestamp(target_date)
        if target <= self._as_of_date:
            raise ValueError("forecast target must be later than as_of_date")
        observation_count = int(len(self._history))
        passed = observation_count >= self.min_observations
        value = np.nan
        status = "insufficient_history"
        if passed:
            if self.model == "historical_mean":
                value = float(self._history.mean())
            elif self.model == "ewma":
                value = float(self._history.ewm(alpha=self.ewma_alpha, adjust=False).mean().iloc[-1])
            elif self.model == "kalman_local_level":
                result = kalman_local_level(
                    self._history,
                    process_variance=self.process_variance,
                    observation_variance=self.observation_variance,
                )
                value = float(result.forecast_mean)
            else:
                result = gjr_garch_forecast(self._history)
                value = float(result.get("forecast_variance", np.nan))
                passed = result.get("status") == "ok" and np.isfinite(value)
            status = "ok" if passed and np.isfinite(value) else "model_failed"
        training_end = self._history.index.max() if observation_count else pd.NaT
        return ForecastEnvelope(
            as_of_date=self._as_of_date,
            training_end=training_end,
            forecast_target=target,
            model=self.model,
            model_version=MODEL_VERSION,
            observation_count=observation_count,
            forecast=float(value),
            passed_validity_gate=bool(passed),
            status=status,
        )
