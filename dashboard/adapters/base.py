"""只读适配层共享基础设施。

所有看板数据读取都必须经过本模块的 :func:`read_csv_artifact` /
:func:`read_json_artifact`，以获得统一的行为：

- 只读保证：绝不写入、修改或删除源文件；
- 缺文件显式降级（``status="missing"``），绝不抛异常崩溃、绝不补零/插值；
- schema 校验：期望列缺失时降级（``status="schema_mismatch"``）并报出期望/实际列；
- run_id 隔离：可校验 CSV 内 ``run_id`` 列与所选运行一致，混杂即拒绝；
- 透传 ``synthetic_engineering_only`` 标记；
- 每次读取记录文件 sha256 与修改时间，供缓存失效与追溯。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

STATUS_OK = "ok"
STATUS_MISSING = "missing"
STATUS_EMPTY = "empty"
STATUS_SCHEMA_MISMATCH = "schema_mismatch"
STATUS_RUN_ID_MISMATCH = "run_id_mismatch"
STATUS_ERROR = "error"


@dataclass
class ArtifactResult:
    """单个产物文件的只读读取结果。

    ``status`` 取值见模块级 ``STATUS_*`` 常量。除 ``ok`` 外均为显式降级，
    页面应展示 ``message`` 与期望/实际列，不得伪造数值。
    """

    name: str
    path: Path
    status: str
    frame: pd.DataFrame | None = None
    data: object = None
    expected_columns: list[str] = field(default_factory=list)
    actual_columns: list[str] = field(default_factory=list)
    message: str = ""
    sha256: str | None = None
    modified_at: str | None = None
    synthetic_engineering_only: bool | None = None

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK


def file_sha256(path: Path) -> str:
    """计算文件 sha256（只读）。"""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _modified_at(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")


def read_csv_artifact(
    directory: Path,
    filename: str,
    *,
    name: str | None = None,
    expected_columns: list[str] | None = None,
    expected_run_id: str | None = None,
    synthetic_engineering_only: bool | None = None,
) -> ArtifactResult:
    """只读读取一个 CSV 产物并做存在性、schema 与 run_id 校验。

    - 文件不存在 → ``missing``；文件为空或无数据行 → ``empty``；
    - ``expected_columns`` 中任何列缺失 → ``schema_mismatch``（多余列允许）；
    - ``expected_run_id`` 给定且 CSV 含 ``run_id`` 列时，若取值不是恰好等于该
      run_id → ``run_id_mismatch``（拒绝混杂展示）。
    """
    path = Path(directory) / filename
    artifact_name = name or filename.rsplit(".", 1)[0]
    expected = list(expected_columns or [])
    if not path.is_file():
        return ArtifactResult(
            name=artifact_name, path=path, status=STATUS_MISSING,
            expected_columns=expected, message=f"缺失文件：{path}",
            synthetic_engineering_only=synthetic_engineering_only,
        )
    try:
        frame = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return ArtifactResult(
            name=artifact_name, path=path, status=STATUS_EMPTY,
            expected_columns=expected, message=f"空文件：{path}",
            sha256=file_sha256(path), modified_at=_modified_at(path),
            synthetic_engineering_only=synthetic_engineering_only,
        )
    except Exception as exc:  # noqa: BLE001 - 读取失败必须降级而非崩溃
        return ArtifactResult(
            name=artifact_name, path=path, status=STATUS_ERROR,
            expected_columns=expected, message=f"读取失败：{exc}",
            sha256=file_sha256(path), modified_at=_modified_at(path),
            synthetic_engineering_only=synthetic_engineering_only,
        )
    actual = [str(column) for column in frame.columns]
    missing_columns = [column for column in expected if column not in actual]
    base = dict(
        name=artifact_name, path=path, expected_columns=expected,
        actual_columns=actual, sha256=file_sha256(path),
        modified_at=_modified_at(path),
        synthetic_engineering_only=synthetic_engineering_only,
    )
    if missing_columns:
        return ArtifactResult(
            status=STATUS_SCHEMA_MISMATCH,
            message=f"schema 不符，缺少列：{missing_columns}", **base,
        )
    if expected_run_id is not None and "run_id" in actual:
        observed = {str(value) for value in frame["run_id"].dropna().unique()}
        if observed != {expected_run_id}:
            return ArtifactResult(
                status=STATUS_RUN_ID_MISMATCH,
                message=(
                    f"run_id 混杂：期望仅 {expected_run_id}，实际 {sorted(observed)}"
                ),
                **base,
            )
    if frame.empty:
        return ArtifactResult(status=STATUS_EMPTY, frame=frame, message="文件无数据行", **base)
    return ArtifactResult(status=STATUS_OK, frame=frame, **base)


def read_json_artifact(
    directory: Path,
    filename: str,
    *,
    name: str | None = None,
    synthetic_engineering_only: bool | None = None,
) -> ArtifactResult:
    """只读读取一个 JSON 产物；缺文件或损坏均显式降级。"""
    path = Path(directory) / filename
    artifact_name = name or filename.rsplit(".", 1)[0]
    if not path.is_file():
        return ArtifactResult(
            name=artifact_name, path=path, status=STATUS_MISSING,
            message=f"缺失文件：{path}",
            synthetic_engineering_only=synthetic_engineering_only,
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - JSON 损坏必须降级而非崩溃
        return ArtifactResult(
            name=artifact_name, path=path, status=STATUS_ERROR,
            message=f"JSON 解析失败：{exc}",
            sha256=file_sha256(path), modified_at=_modified_at(path),
            synthetic_engineering_only=synthetic_engineering_only,
        )
    return ArtifactResult(
        name=artifact_name, path=path, status=STATUS_OK, data=data,
        sha256=file_sha256(path), modified_at=_modified_at(path),
        synthetic_engineering_only=synthetic_engineering_only,
    )


def validate_run_directory(run_dir: Path) -> list[str]:
    """校验运行目录的 run_id 一致性。

    若 ``run_metadata.json`` 存在且其 ``run_id`` 与目录名不一致，返回问题列表；
    该目录的产物随后不应与其他 run_id 的产物混合展示。
    """
    issues: list[str] = []
    run_dir = Path(run_dir)
    metadata_path = run_dir / "run_metadata.json"
    if not metadata_path.is_file():
        issues.append("缺少 run_metadata.json")
        return issues
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        issues.append(f"run_metadata.json 解析失败：{exc}")
        return issues
    recorded = metadata.get("run_id")
    if recorded and str(recorded) != run_dir.name:
        issues.append(f"目录名 {run_dir.name} 与 run_metadata.run_id {recorded} 不一致")
    return issues


def frame_run_ids(result: ArtifactResult) -> list[str]:
    """返回已读取 CSV 中出现的 run_id 取值（用于 UI 追溯展示）。"""
    if result.frame is None or "run_id" not in result.frame.columns:
        return []
    return sorted(str(value) for value in result.frame["run_id"].dropna().unique())
