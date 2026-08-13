"""TextDatasetManifest schema 草案（R1 文本数据集的许可/PIT/去重登记）。

对应 docs/plans/research_platform_v1/13_三大科研主线与AI工程分工.md 3.4 主要产物
第一条与 modules/05_LLM事件表示与文本Alpha.md 的数据门禁。风格对齐
data/provenance.py 的 build/validate 函数式 manifest。

纪律要点（与项目治理一致）：
- 文本未签署许可前，status 不得进入 approved/frozen；
- publish_time 字段、可用时间规则、去重键为必填——时点与去重不可缺省；
- manifest 内容哈希剔除 created_at，供 artifact/报告稳定引用。
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Any


TEXT_DATASET_MANIFEST_SCHEMA_VERSION = 1
TEXT_MANIFEST_STATUSES = ("draft", "pending_review", "approved", "frozen")
TEXT_LICENSE_CATEGORIES = ("undecided", "research_only", "internal_only", "redistribution_allowed")

_REQUIRED_TOP_KEYS = ("dataset_id", "status", "source", "license", "pit", "dedup", "entity_mapping", "coverage")
_REQUIRED_SOURCE_KEYS = ("provider", "collection", "access_channel")
_REQUIRED_LICENSE_KEYS = ("category", "approved", "restrictions")
_REQUIRED_PIT_KEYS = ("publish_time_field", "available_time_rule", "revision_handling")
_REQUIRED_ENTITY_KEYS = ("stock_code_field", "mapping_source")
_REQUIRED_COVERAGE_KEYS = ("start_date", "end_date", "universe")


def build_text_dataset_manifest(
    *,
    dataset_id: str,
    source: dict[str, Any],
    license_info: dict[str, Any],
    pit: dict[str, Any],
    dedup: dict[str, Any],
    entity_mapping: dict[str, Any],
    coverage: dict[str, Any],
    files: list[dict[str, Any]] | None = None,
    status: str = "draft",
    notes: str = "",
) -> dict[str, Any]:
    """构建并校验 TextDatasetManifest。

    - source: provider / collection / access_channel（如 CnOpenData / 公告库 / cufe-library）
    - license_info: category / approved / restrictions [+ signoff_ref]
    - pit: publish_time_field / available_time_rule / revision_handling
    - dedup: dedup_key（非空列表）[+ near_dup_rule]
    - entity_mapping: stock_code_field / mapping_source
    - coverage: start_date / end_date / universe
    - files: 可选，每项 {path, sha256, rows?}
    """
    manifest = {
        "schema_version": TEXT_DATASET_MANIFEST_SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "status": status,
        "source": dict(source),
        "license": dict(license_info),
        "pit": dict(pit),
        "dedup": dict(dedup),
        "entity_mapping": dict(entity_mapping),
        "coverage": dict(coverage),
        "files": [dict(item) for item in (files or [])],
        "notes": notes,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    validate_text_dataset_manifest(manifest)
    return manifest


def validate_text_dataset_manifest(manifest: dict[str, Any]) -> None:
    """校验 manifest；任何违例 raise ValueError。"""
    missing = [key for key in _REQUIRED_TOP_KEYS if key not in manifest]
    if missing:
        raise ValueError(f"TextDatasetManifest missing top-level keys: {missing}")
    if manifest.get("schema_version") != TEXT_DATASET_MANIFEST_SCHEMA_VERSION:
        raise ValueError(f"Unsupported text manifest schema_version: {manifest.get('schema_version')}")
    if not isinstance(manifest["dataset_id"], str) or not manifest["dataset_id"].strip():
        raise ValueError("dataset_id must be a non-empty string")
    status = manifest["status"]
    if status not in TEXT_MANIFEST_STATUSES:
        raise ValueError(f"Invalid text manifest status: {status}")

    source = manifest["source"]
    _require_keys(source, _REQUIRED_SOURCE_KEYS, "source")
    license_info = manifest["license"]
    _require_keys(license_info, _REQUIRED_LICENSE_KEYS, "license")
    if license_info["category"] not in TEXT_LICENSE_CATEGORIES:
        raise ValueError(f"Invalid license category: {license_info['category']}")
    if not isinstance(license_info["approved"], bool):
        raise ValueError("license.approved must be a bool")
    if not isinstance(license_info["restrictions"], list):
        raise ValueError("license.restrictions must be a list")
    if status in ("approved", "frozen"):
        if not license_info["approved"]:
            raise ValueError("status approved/frozen requires license.approved = true")
        if not license_info.get("signoff_ref"):
            raise ValueError("status approved/frozen requires license.signoff_ref")

    pit = manifest["pit"]
    _require_keys(pit, _REQUIRED_PIT_KEYS, "pit")
    for key in _REQUIRED_PIT_KEYS:
        if not isinstance(pit[key], str) or not pit[key].strip():
            raise ValueError(f"pit.{key} must be a non-empty string")

    dedup = manifest["dedup"]
    dedup_key = dedup.get("dedup_key")
    if not isinstance(dedup_key, list) or not dedup_key:
        raise ValueError("dedup.dedup_key must be a non-empty list")

    _require_keys(manifest["entity_mapping"], _REQUIRED_ENTITY_KEYS, "entity_mapping")
    coverage = manifest["coverage"]
    _require_keys(coverage, _REQUIRED_COVERAGE_KEYS, "coverage")
    for key in ("start_date", "end_date"):
        if not isinstance(coverage[key], str) or not coverage[key].strip():
            raise ValueError(f"coverage.{key} must be a non-empty string")

    files = manifest.get("files", [])
    if not isinstance(files, list):
        raise ValueError("files must be a list")
    for item in files:
        if not isinstance(item, dict) or not item.get("path") or not item.get("sha256"):
            raise ValueError("each files entry must carry path and sha256")


def text_manifest_sha256(manifest: dict[str, Any]) -> str:
    """manifest 内容稳定哈希（剔除 created_at），供 artifact 与报告引用。"""
    payload = {key: value for key, value in manifest.items() if key != "created_at"}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def assess_text_manifest_research_readiness(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return the human-controlled gates that still block real R1 research.

    Schema validity alone is deliberately weaker than research readiness.  A
    draft manifest can support local engineering tests, while accepted/frozen
    research requires licence evidence, explicit availability semantics,
    reviewed dedup/entity mappings and immutable file hashes.
    """

    failures: list[str] = []
    try:
        validate_text_dataset_manifest(manifest)
    except ValueError as exc:
        failures.append(str(exc))
        return {"ready": False, "failures": failures}
    if manifest.get("status") not in {"approved", "frozen"}:
        failures.append("status must be approved or frozen")
    license_info = manifest.get("license", {})
    if not license_info.get("approved") or not license_info.get("signoff_ref"):
        failures.append("license approval and signoff_ref are required")
    pit = manifest.get("pit", {})
    for key in ("available_time_field", "timezone"):
        if not str(pit.get(key, "")).strip():
            failures.append(f"pit.{key} is required")
    dedup = manifest.get("dedup", {})
    if not str(dedup.get("dedup_group_field", "")).strip():
        failures.append("dedup.dedup_group_field is required")
    if dedup.get("review_status") != "approved":
        failures.append("dedup.review_status must be approved")
    entity = manifest.get("entity_mapping", {})
    if entity.get("review_status") != "approved":
        failures.append("entity_mapping.review_status must be approved")
    files = manifest.get("files", [])
    if not files:
        failures.append("at least one immutable files entry is required")
    for item in files:
        digest = str(item.get("sha256", ""))
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            failures.append(f"invalid files.sha256 for {item.get('path', '<unknown>')}")
    return {"ready": not failures, "failures": failures}


def assert_text_manifest_research_ready(manifest: dict[str, Any]) -> None:
    readiness = assess_text_manifest_research_readiness(manifest)
    if not readiness["ready"]:
        raise ValueError("TextDatasetManifest is not research-ready: " + "; ".join(readiness["failures"]))


def _require_keys(section: dict[str, Any], keys: tuple[str, ...], name: str) -> None:
    missing = [key for key in keys if key not in section]
    if missing:
        raise ValueError(f"TextDatasetManifest {name} missing keys: {missing}")
