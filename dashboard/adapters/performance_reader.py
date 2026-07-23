"""策略/组合绩效与消融对比产物读取（阶段 7，只读）。

期望列与 ``src/ashare_factor_research/time_series/stage7.py`` 的
``STAGE7_SCHEMAS`` 保持一致（实际产物为权威）；列不一致时显式降级并报出
期望/实际列。``ablation_status`` 含 ``synthetic_engineering_only`` 标记，透传到 UI。
"""

from __future__ import annotations

from pathlib import Path

from .base import ArtifactResult, read_csv_artifact

#: 消融产物期望列，复制自 stage7.STAGE7_SCHEMAS（time-series-v2，权威）。
ABLATION_SCHEMAS: dict[str, list[str]] = {
    "ablation_portfolio_returns": ["date", "portfolio_id", "gross_return", "net_return", "turnover", "status", "model_version"],
    "ablation_nav": ["date", "portfolio_id", "nav", "status", "model_version"],
    "ablation_performance": [
        "portfolio_id", "status", "annual_return", "annual_volatility", "sharpe", "information_ratio",
        "max_drawdown", "monthly_win_rate", "annual_turnover", "oos_months", "model_version",
    ],
    "ablation_incremental": [
        "comparison", "treatment", "baseline", "status", "incremental_annual_return",
        "ir_improvement", "max_drawdown_change", "positive_year_ratio", "model_version",
    ],
    "ablation_cost_sensitivity": [
        "portfolio_id", "cost_scenario", "cost_multiplier", "status",
        "net_annual_return", "net_total_return", "model_version",
    ],
    "ablation_status": [
        "portfolio_id", "weight_scheme", "regime_adjustment", "volatility_control",
        "status", "oos_months", "data_mode", "synthetic_engineering_only", "detail", "model_version",
    ],
}

#: 运行目录 metrics.csv 的期望列（首列为指标名，value 为取值）。
RUN_METRICS_COLUMNS: list[str] = ["value"]


def find_ablation_dirs(project_root: Path) -> list[Path]:
    """定位可能包含消融产物的目录：``outputs/stage7*``（只读）。"""
    outputs = Path(project_root) / "outputs"
    if not outputs.is_dir():
        return []
    return sorted(
        path for path in outputs.iterdir()
        if path.is_dir() and path.name.startswith("stage7")
    )


def load_ablation_status(ablation_dir: Path) -> ArtifactResult:
    """读取 ablation_status.csv（七组方案状态与 synthetic 标记）。"""
    result = read_csv_artifact(
        ablation_dir, "ablation_status.csv", name="ablation_status",
        expected_columns=ABLATION_SCHEMAS["ablation_status"],
    )
    if result.ok and "synthetic_engineering_only" in result.frame.columns:
        values = {str(v).lower() for v in result.frame["synthetic_engineering_only"].dropna().unique()}
        result.synthetic_engineering_only = bool(values & {"true", "1", "yes"})
    return result


def load_ablation_nav(ablation_dir: Path) -> ArtifactResult:
    """读取 ablation_nav.csv（七组方案净值曲线，long 表，portfolio_id ∈ A–G）。"""
    return read_csv_artifact(
        ablation_dir, "ablation_nav.csv", name="ablation_nav",
        expected_columns=ABLATION_SCHEMAS["ablation_nav"],
    )


def load_ablation_performance(ablation_dir: Path) -> ArtifactResult:
    """读取 ablation_performance.csv（七组方案绩效指标）。"""
    return read_csv_artifact(
        ablation_dir, "ablation_performance.csv", name="ablation_performance",
        expected_columns=ABLATION_SCHEMAS["ablation_performance"],
    )


def load_ablation_incremental(ablation_dir: Path) -> ArtifactResult:
    """读取 ablation_incremental.csv（增量解释：C-A、D-A、E-A、F-C、G-F、G-A）。"""
    return read_csv_artifact(
        ablation_dir, "ablation_incremental.csv", name="ablation_incremental",
        expected_columns=ABLATION_SCHEMAS["ablation_incremental"],
    )


def load_ablation_portfolio_returns(ablation_dir: Path) -> ArtifactResult:
    """读取 ablation_portfolio_returns.csv（七组方案毛/净收益与换手）。"""
    return read_csv_artifact(
        ablation_dir, "ablation_portfolio_returns.csv", name="ablation_portfolio_returns",
        expected_columns=ABLATION_SCHEMAS["ablation_portfolio_returns"],
    )


def load_ablation_cost_sensitivity(ablation_dir: Path) -> ArtifactResult:
    """读取 ablation_cost_sensitivity.csv（成本敏感性：zero/standard/high）。"""
    return read_csv_artifact(
        ablation_dir, "ablation_cost_sensitivity.csv", name="ablation_cost_sensitivity",
        expected_columns=ABLATION_SCHEMAS["ablation_cost_sensitivity"],
    )


def load_ablation_artifacts(ablation_dir: Path) -> dict[str, ArtifactResult]:
    """批量读取全部消融产物。"""
    return {
        "ablation_status": load_ablation_status(ablation_dir),
        "ablation_nav": load_ablation_nav(ablation_dir),
        "ablation_performance": load_ablation_performance(ablation_dir),
        "ablation_incremental": load_ablation_incremental(ablation_dir),
        "ablation_portfolio_returns": load_ablation_portfolio_returns(ablation_dir),
        "ablation_cost_sensitivity": load_ablation_cost_sensitivity(ablation_dir),
    }


def load_run_metrics(run_dir: Path) -> ArtifactResult:
    """读取运行目录下的 metrics.csv（策略绩效指标）。

    读取后将首列规范化为 ``metric`` 列；不重新计算任何指标。
    """
    result = read_csv_artifact(
        run_dir, "metrics.csv", name="metrics", expected_columns=RUN_METRICS_COLUMNS,
    )
    if result.ok and result.frame is not None:
        first = result.frame.columns[0]
        if str(first).startswith("Unnamed"):
            result.frame = result.frame.rename(columns={first: "metric"})
            result.actual_columns = [str(c) for c in result.frame.columns]
    return result
