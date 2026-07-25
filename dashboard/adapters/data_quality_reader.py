"""数据质量与 PIT 审计读取：reports/gate/*/data_gate_summary.json 与五项审计 CSV。

同样适用于把门禁产物直接写在运行目录下的情况（如真实门禁负向 smoke 运行）。
全部为只读读取；缺文件显式降级；schema 不符报出期望/实际列。
"""

from __future__ import annotations

from pathlib import Path

from .base import ArtifactResult, read_csv_artifact, read_json_artifact

#: 五项门禁审计 CSV 及其期望列（与 src 中门禁实现写出的表头一致）。
AUDIT_SCHEMAS: dict[str, list[str]] = {
    "pit_timing_audit": [
        "table", "ts_code", "report_period", "announcement_date",
        "revision_date", "usable_date", "source_id", "passed", "issue",
    ],
    "survivorship_audit": [
        "ts_code", "list_date", "delist_date", "has_security_master",
        "has_index_membership", "has_daily_bar", "passed", "issue",
    ],
    "financial_revision_audit": [
        "ts_code", "report_period", "revision_count", "first_announcement_date",
        "last_revision_date", "revision_ids_unique", "passed", "issue",
    ],
    "universe_coverage": [
        "trade_date", "active_member_count", "daily_bar_coverage",
        "daily_basic_coverage", "industry_coverage", "limit_price_coverage",
        "minimum_coverage", "passed", "issue",
    ],
    "benchmark_alignment": [
        "trade_date", "has_open_calendar", "has_benchmark", "has_daily_bar",
        "passed", "issue",
    ],
}

#: 数据源缺口矩阵（项目根目录）的期望列。
GAP_MATRIX_COLUMNS: list[str] = [
    "required_field", "research_purpose", "preferred_source", "fallback_source",
    "account_permission", "pit_ready", "license_status", "probe_status",
    "decision", "evidence_path",
]


def list_gate_dirs(project_root: Path) -> list[Path]:
    """列出 reports/gate/ 下的全部门禁目录（只读）。"""
    gate_root = Path(project_root) / "reports" / "gate"
    if not gate_root.is_dir():
        return []
    return sorted(path for path in gate_root.iterdir() if path.is_dir())


def load_data_gate_summary(gate_dir: Path) -> ArtifactResult:
    """读取门禁目录下的 data_gate_summary.json。"""
    return read_json_artifact(gate_dir, "data_gate_summary.json")


def load_audit_csv(gate_dir: Path, audit_name: str) -> ArtifactResult:
    """读取指定审计 CSV（如 ``pit_timing_audit``），做 schema 校验。"""
    expected = AUDIT_SCHEMAS.get(audit_name, [])
    return read_csv_artifact(
        gate_dir, f"{audit_name}.csv", name=audit_name, expected_columns=expected,
    )


def load_gate_artifacts(gate_dir: Path) -> dict[str, ArtifactResult]:
    """读取门禁目录下的 data_gate_summary.json 与全部五项审计 CSV。"""
    results: dict[str, ArtifactResult] = {
        "data_gate_summary": load_data_gate_summary(gate_dir),
    }
    for audit_name in AUDIT_SCHEMAS:
        results[audit_name] = load_audit_csv(gate_dir, audit_name)
    return results


def load_data_source_gap_matrix(project_root: Path) -> ArtifactResult:
    """读取 reports/data_sources/ 下的 data_source_gap_matrix.csv（数据源与缺口）。"""
    return read_csv_artifact(
        project_root / "reports" / "data_sources", "data_source_gap_matrix.csv",
        name="data_source_gap_matrix", expected_columns=GAP_MATRIX_COLUMNS,
    )
