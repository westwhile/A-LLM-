"""运行清单与证据清单读取：evidence_manifest.json、data_manifest.json、stage46_summary.json 等。

全部为只读 JSON 读取；缺文件显式降级；``synthetic_engineering_only`` 标记透传。
"""

from __future__ import annotations

from pathlib import Path

from .base import ArtifactResult, read_json_artifact


def load_run_metadata(run_dir: Path) -> ArtifactResult:
    """读取运行目录下的 run_metadata.json。"""
    return read_json_artifact(run_dir, "run_metadata.json")


def load_evidence_manifest(run_dir: Path) -> ArtifactResult:
    """读取运行目录下的 evidence_manifest.json（证据清单）。"""
    return read_json_artifact(run_dir, "evidence_manifest.json")


def load_data_manifest(run_dir: Path) -> ArtifactResult:
    """读取运行目录下的 data_manifest.json（数据版本清单）。"""
    return read_json_artifact(run_dir, "data_manifest.json")


def load_research_protocol_snapshot(run_dir: Path) -> ArtifactResult:
    """读取运行目录下的 research_protocol_snapshot.json（协议快照）。"""
    return read_json_artifact(run_dir, "research_protocol_snapshot.json")


def load_stage46_summary(stage_dir: Path) -> ArtifactResult:
    """读取阶段 4–6 输出目录下的 stage46_summary.json，并透传 synthetic 标记。"""
    result = read_json_artifact(stage_dir, "stage46_summary.json")
    if result.ok and isinstance(result.data, dict):
        flag = result.data.get("synthetic_engineering_only")
        result.synthetic_engineering_only = bool(flag) if flag is not None else None
    return result


def load_stage_summary(stage_dir: Path, stage: str) -> ArtifactResult:
    """读取阶段输出目录下的 ``<stage>_summary.json``（如 stage7_summary.json）。"""
    result = read_json_artifact(stage_dir, f"{stage}_summary.json")
    if result.ok and isinstance(result.data, dict):
        flag = result.data.get("synthetic_engineering_only")
        result.synthetic_engineering_only = bool(flag) if flag is not None else None
    return result


def manifest_synthetic_flag(result: ArtifactResult) -> bool | None:
    """从 summary/manifest 读取结果中提取 synthetic_engineering_only 标记。"""
    if result.synthetic_engineering_only is not None:
        return result.synthetic_engineering_only
    if result.ok and isinstance(result.data, dict):
        flag = result.data.get("synthetic_engineering_only")
        if flag is None and result.data.get("mode") == "sample":
            return True
        return bool(flag) if flag is not None else None
    return None
