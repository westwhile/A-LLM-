"""Point-in-time time-series research utilities."""

from ashare_factor_research.time_series.interface import ForecastEnvelope, PointInTimeForecaster

from ashare_factor_research.time_series.models import (
    GaussianHMM,
    dcc_covariance,
    deflated_sharpe_probability,
    diebold_mariano_test,
    gjr_garch_forecast,
    kalman_local_level,
    probability_of_backtest_overfitting,
    superior_predictive_ability_test,
)
from ashare_factor_research.time_series.research import (
    build_dynamic_scores,
    run_time_series_research,
)

__all__ = [
    "GaussianHMM",
    "ForecastEnvelope",
    "PointInTimeForecaster",
    "build_dynamic_scores",
    "dcc_covariance",
    "deflated_sharpe_probability",
    "diebold_mariano_test",
    "gjr_garch_forecast",
    "kalman_local_level",
    "probability_of_backtest_overfitting",
    "superior_predictive_ability_test",
    "run_time_series_research",
]
