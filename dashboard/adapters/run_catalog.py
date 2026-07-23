"""运行目录扫描：outputs/runs/、outputs/stage46/、outputs/stage7*/、outputs/stage8*/。

只读列出可用运行及其模式、状态与 ``synthetic_engineering_only`` 标记；
同时校验目录名与 ``run_metadata.json`` 中 run_id 的一致性。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .base import validate_run_directory

KIND_PIPELINE_RUN = "pipeline_run"
KIND_STAGE46 = "stage46"
KIND_STAGE7 = "stage7"
KIND_STAGE8 = "stage8"


@dataclass
class RunEntry:
    """一个可选择的运行/产物目录。"""

    run_id: str
    path: Path
    kind: str
    mode: str | None = None
    status: str | None = None
    created_at: str | None = None
    synthetic_engineering_only: bool | None = None
    metadata_present: bool = False
    last_modified: str | None = None
    issues: list[str] = field(default_factory=list)


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 目录扫描不得因单个文件损坏而中断
        return {}
    return data if isinstance(data, dict) else {}


def _last_modified(path: Path) -> str | None:
    try:
        mtime = max((item.stat().st_mtime for item in path.rglob("*") if item.is_file()), default=None)
    except OSError:
        return None
    if mtime is None:
        return None
    return datetime.fromtimestamp(mtime).isoformat(timespec="seconds")


def _pipeline_run_entry(run_dir: Path) -> RunEntry:
    metadata_path = run_dir / "run_metadata.json"
    metadata = _read_json(metadata_path)
    issues = validate_run_directory(run_dir)
    return RunEntry(
        run_id=run_dir.name,
        path=run_dir,
        kind=KIND_PIPELINE_RUN,
        mode=metadata.get("mode"),
        status=None,
        created_at=metadata.get("created_at"),
        synthetic_engineering_only=(metadata.get("mode") == "sample") if metadata else None,
        metadata_present=metadata_path.is_file(),
        last_modified=_last_modified(run_dir),
        issues=issues,
    )


def _summary_entry(stage_dir: Path, kind: str, summary_name: str) -> RunEntry:
    summary_path = stage_dir / summary_name
    summary = _read_json(summary_path)
    issues: list[str] = []
    if not summary_path.is_file():
        issues.append(f"缺少 {summary_name}")
    return RunEntry(
        run_id=stage_dir.name,
        path=stage_dir,
        kind=kind,
        mode=summary.get("mode"),
        status=summary.get("status"),
        created_at=None,
        synthetic_engineering_only=summary.get("synthetic_engineering_only"),
        metadata_present=summary_path.is_file(),
        last_modified=_last_modified(stage_dir),
        issues=issues,
    )


def discover_runs(project_root: Path) -> list[RunEntry]:
    """扫描项目 outputs/ 下的全部运行与阶段产物目录（只读）。

    覆盖 ``outputs/runs/*``、``outputs/stage46*``、``outputs/stage7*`` 与
    ``outputs/stage8*``。不存在 outputs/ 时返回空列表而非报错。
    """
    project_root = Path(project_root)
    outputs = project_root / "outputs"
    entries: list[RunEntry] = []
    if not outputs.is_dir():
        return entries

    runs_root = outputs / "runs"
    if runs_root.is_dir():
        for run_dir in sorted(path for path in runs_root.iterdir() if path.is_dir()):
            entries.append(_pipeline_run_entry(run_dir))

    for stage_dir in sorted(path for path in outputs.iterdir() if path.is_dir()):
        name = stage_dir.name
        if name == "runs":
            continue
        if name.startswith("stage46"):
            entries.append(_summary_entry(stage_dir, KIND_STAGE46, "stage46_summary.json"))
        elif name.startswith("stage7"):
            entries.append(_summary_entry(stage_dir, KIND_STAGE7, "stage7_summary.json"))
        elif name.startswith("stage8"):
            entries.append(_summary_entry(stage_dir, KIND_STAGE8, "stage8_summary.json"))
    return entries


def get_run(project_root: Path, run_id: str, kind: str | None = None) -> RunEntry | None:
    """按 run_id（目录名）定位运行；可选按 kind 过滤。"""
    for entry in discover_runs(project_root):
        if entry.run_id == run_id and (kind is None or entry.kind == kind):
            return entry
    return None
