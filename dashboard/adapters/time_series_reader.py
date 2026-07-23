"""阶段 4–6 时间序列产物读取（只读）。

期望 schema 与 ``src/ashare_factor_research/time_series/stage46.py`` 的
``SCHEMAS`` 保持一致（此处显式复制，使看板不依赖研究代码的导入路径；
旧版 ``runs/*/figures`` 产物列不一致时将按"旧 schema"显式降级）。
"""

from __future__ import annotations

from pathlib import Path

from .base import ArtifactResult, read_csv_artifact

#: 阶段 4–6 产物的期望列，复制自 stage46.SCHEMAS（time-series-v2）。
TIME_SERIES_SCHEMAS: dict[str, list[str]] = {
    "kalman_trial_registry": ["trial_id", "process_variance", "observation_variance", "turnover_penalty", "status", "prediction_count", "model_version"],
    "factor_ic_forecasts": ["test_date", "factor", "trial_id", "process_variance", "observation_variance", "turnover_penalty", "forecast_ic", "filtered_ic", "forecast_variance", "p_value", "fdr_q_value", "coverage", "observation_count", "train_label_end_max", "actual_ic", "model_version"],
    "dynamic_factor_weights": ["test_date", "factor", "trial_id", "direction", "weight", "filtered_ic", "forecast_ic", "forecast_variance", "p_value", "fdr_q_value", "coverage", "observation_count", "train_label_end_max", "model_version"],
    "factor_weight_turnover": ["test_date", "trial_id", "turnover", "identity_l1", "model_version"],
    "factor_weight_stability": ["test_date", "trial_id", "factor_count", "max_weight", "effective_factor_count", "weight_hhi", "model_version"],
    "factor_timing_comparison": ["scheme", "trial_id", "prediction_count", "rmse", "mae", "direction_accuracy", "oos_months", "sample_eligibility", "status", "model_version"],
    "regime_probabilities": ["as_of_date", "training_end", "forecast_target", "model", "state_count", "observation_count", "status", "bear_probability", "neutral_probability", "bull_probability", "log_likelihood", "seed", "model_version"],
    "regime_transition_matrix": ["as_of_date", "model", "from_state", "to_state", "probability", "model_version"],
    "regime_durations": ["as_of_date", "model", "state", "expected_duration", "model_version"],
    "regime_factor_performance": ["as_of_date", "model", "state", "factor", "mean_return", "observation_count", "model_version"],
    "regime_stability": ["as_of_date", "model", "previous_as_of_date", "probability_l1_change", "label_signature", "model_version"],
    "volatility_forecasts": ["as_of_date", "training_end", "forecast_target", "model", "status", "observation_count", "forecast_variance", "annualized_volatility_forecast", "actual_squared_return", "error", "absolute_error", "qlike", "arch_lm_p_value", "extreme_observation", "detail", "model_version"],
    "volatility_model_comparison": ["model", "prediction_count", "rmse", "mae", "mean_qlike", "residual_arch_rejection_rate", "extreme_period_mae", "volatility_target_bias", "status", "model_version"],
    "model_warnings": ["module", "as_of_date", "model", "warning_category", "message", "model_version"],
    "dynamic_covariance": ["as_of_date", "factor_left", "factor_right", "conditional_covariance", "model", "min_eigenvalue", "parameter_stable", "model_version"],
    "dcc_risk_contributions": ["as_of_date", "factor", "risk_contribution", "risk_contribution_fraction", "model", "model_version"],
    "stage46_status": ["module", "status", "sample_eligibility", "oos_months", "data_mode", "synthetic_engineering_only", "detail", "model_version"],
}


def find_time_series_dirs(project_root: Path) -> list[Path]:
    """定位可能包含阶段 4–6 产物的目录（只读）。

    覆盖 ``outputs/stage46*`` 目录以及含有任一已知阶段 4–6 产物（含旧版
    ``model_selection_audit.csv``）的 ``outputs/runs/*/figures`` 目录。
    """
    project_root = Path(project_root)
    outputs = project_root / "outputs"
    found: list[Path] = []
    if not outputs.is_dir():
        return found
    for path in sorted(outputs.iterdir()):
        if path.is_dir() and path.name.startswith("stage46"):
            found.append(path)
    runs_root = outputs / "runs"
    if runs_root.is_dir():
        for run_dir in sorted(runs_root.iterdir()):
            figures = run_dir / "figures"
            if not figures.is_dir():
                continue
            if any((figures / f"{name}.csv").is_file() for name in TIME_SERIES_SCHEMAS) or (
                figures / "model_selection_audit.csv"
            ).is_file():
                # 旧版 runs/*/figures 产物也会被列出；列不一致时按"旧 schema"显式降级。
                found.append(figures)
    return found


def load_time_series_artifact(series_dir: Path, artifact_name: str) -> ArtifactResult:
    """读取指定阶段 4–6 产物 CSV，并按期望 schema 校验。"""
    expected = TIME_SERIES_SCHEMAS.get(artifact_name, [])
    return read_csv_artifact(
        series_dir, f"{artifact_name}.csv", name=artifact_name, expected_columns=expected,
    )


def load_time_series_artifacts(
    series_dir: Path, names: list[str] | None = None,
) -> dict[str, ArtifactResult]:
    """批量读取阶段 4–6 产物；默认读取全部已知产物。"""
    selected = names if names is not None else list(TIME_SERIES_SCHEMAS)
    return {name: load_time_series_artifact(series_dir, name) for name in selected}


def load_stage46_status(series_dir: Path) -> ArtifactResult:
    """读取 stage46_status.csv（模块状态与 synthetic 标记）。"""
    result = load_time_series_artifact(series_dir, "stage46_status")
    if result.ok and "synthetic_engineering_only" in result.frame.columns:
        values = {str(v).lower() for v in result.frame["synthetic_engineering_only"].dropna().unique()}
        result.synthetic_engineering_only = bool(values & {"true", "1", "yes"})
    return result


def load_dynamic_factor_weights(series_dir: Path) -> ArtifactResult:
    """读取 dynamic_factor_weights.csv（Kalman 动态因子权重）。"""
    return load_time_series_artifact(series_dir, "dynamic_factor_weights")


def load_factor_weight_turnover(series_dir: Path) -> ArtifactResult:
    """读取 factor_weight_turnover.csv（权重换手）。"""
    return load_time_series_artifact(series_dir, "factor_weight_turnover")


def load_factor_weight_stability(series_dir: Path) -> ArtifactResult:
    """读取 factor_weight_stability.csv（权重稳定性）。"""
    return load_time_series_artifact(series_dir, "factor_weight_stability")


def load_factor_timing_comparison(series_dir: Path) -> ArtifactResult:
    """读取 factor_timing_comparison.csv（因子择时方案比较）。"""
    return load_time_series_artifact(series_dir, "factor_timing_comparison")


def load_regime_probabilities(series_dir: Path) -> ArtifactResult:
    """读取 regime_probabilities.csv（HMM filtered 状态概率）。"""
    return load_time_series_artifact(series_dir, "regime_probabilities")


def load_regime_transition_matrix(series_dir: Path) -> ArtifactResult:
    """读取 regime_transition_matrix.csv（状态转移矩阵）。"""
    return load_time_series_artifact(series_dir, "regime_transition_matrix")


def load_regime_durations(series_dir: Path) -> ArtifactResult:
    """读取 regime_durations.csv（状态期望持续期）。"""
    return load_time_series_artifact(series_dir, "regime_durations")


def load_regime_factor_performance(series_dir: Path) -> ArtifactResult:
    """读取 regime_factor_performance.csv（状态分段因子表现）。"""
    return load_time_series_artifact(series_dir, "regime_factor_performance")


def load_regime_stability(series_dir: Path) -> ArtifactResult:
    """读取 regime_stability.csv（状态标签稳定性）。"""
    return load_time_series_artifact(series_dir, "regime_stability")


def load_volatility_forecasts(series_dir: Path) -> ArtifactResult:
    """读取 volatility_forecasts.csv（GARCH 波动预测）。"""
    return load_time_series_artifact(series_dir, "volatility_forecasts")


def load_volatility_model_comparison(series_dir: Path) -> ArtifactResult:
    """读取 volatility_model_comparison.csv（波动模型比较）。"""
    return load_time_series_artifact(series_dir, "volatility_model_comparison")


def load_dynamic_covariance(series_dir: Path) -> ArtifactResult:
    """读取 dynamic_covariance.csv（DCC 动态协方差）。"""
    return load_time_series_artifact(series_dir, "dynamic_covariance")


def load_dcc_risk_contributions(series_dir: Path) -> ArtifactResult:
    """读取 dcc_risk_contributions.csv（风险贡献）。"""
    return load_time_series_artifact(series_dir, "dcc_risk_contributions")


def load_model_warnings(series_dir: Path) -> ArtifactResult:
    """读取 model_warnings.csv（模型警告登记）。"""
    return load_time_series_artifact(series_dir, "model_warnings")
