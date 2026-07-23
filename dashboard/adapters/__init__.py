"""只读适配层：看板的唯一数据入口。

页面只能从本包读取数据；适配层保证只读、缺文件显式降级、schema 校验、
run_id 隔离与 ``synthetic_engineering_only`` 标记透传。
"""

from .base import (
    STATUS_EMPTY,
    STATUS_ERROR,
    STATUS_MISSING,
    STATUS_OK,
    STATUS_RUN_ID_MISMATCH,
    STATUS_SCHEMA_MISMATCH,
    ArtifactResult,
    file_sha256,
    frame_run_ids,
    read_csv_artifact,
    read_json_artifact,
    validate_run_directory,
)
from .run_catalog import RunEntry, discover_runs, get_run

__all__ = [
    "ArtifactResult",
    "RunEntry",
    "STATUS_EMPTY",
    "STATUS_ERROR",
    "STATUS_MISSING",
    "STATUS_OK",
    "STATUS_RUN_ID_MISMATCH",
    "STATUS_SCHEMA_MISMATCH",
    "discover_runs",
    "file_sha256",
    "frame_run_ids",
    "get_run",
    "read_csv_artifact",
    "read_json_artifact",
    "validate_run_directory",
]
