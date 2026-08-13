"""R1-E1 规则基准 artifact：把规则/词典标注结果固化为可审计、可复算的产出。

实验定位见 docs/plans/research_platform_v1/13_三大科研主线与AI工程分工.md 3.3
（R1-E1：规则/词典事件 × 固定 evaluator = 透明文本基准）。

artifact 目录结构：
- rule_baseline_labels.csv    标注明细（LABEL_COLUMNS，batch_label_events 产出）
- rule_baseline_manifest.json 规则词典版本与哈希、模型/prompt 版本、标签分布、
                              覆盖、输入文本 manifest 引用、质量状态

雏形边界：只登记规则基准自身事实；OOS 增量评价由固定 evaluator 阶段消费
event_sentiment 因子后完成，不在本模块内。
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

import pandas as pd

from ashare_factor_research.data.provenance import dataframe_sha256
from ashare_factor_research.llm.prompts import PROMPT_VERSION
from ashare_factor_research.llm.rule_lexicon import RuleLexicon, default_rule_lexicon, lexicon_sha256
from ashare_factor_research.llm.schema import LABEL_COLUMNS, validate_llm_event_labels
from ashare_factor_research.llm.text_manifest import text_manifest_sha256, validate_text_dataset_manifest


RULE_BASELINE_ARTIFACT_TYPE = "r1_e1_rule_baseline"
RULE_BASELINE_SCHEMA_VERSION = 1
LABELS_FILENAME = "rule_baseline_labels.csv"
MANIFEST_FILENAME = "rule_baseline_manifest.json"


def build_rule_baseline_artifact(
    labels: pd.DataFrame | None,
    *,
    lexicon: RuleLexicon | None = None,
    text_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """从规则标注结果构建 artifact manifest（不写盘）。"""
    if labels is None or labels.empty:
        labels = pd.DataFrame(columns=LABEL_COLUMNS)
    validate_llm_event_labels(labels)
    lex = lexicon or default_rule_lexicon()

    models = sorted(labels["model"].dropna().unique().tolist())
    if len(models) > 1:
        raise ValueError(f"Rule baseline artifact requires a single labeler model, got: {models}")
    prompt_versions = sorted(labels["prompt_version"].dropna().unique().tolist())
    if len(prompt_versions) > 1:
        raise ValueError(f"Rule baseline artifact requires a single prompt_version, got: {prompt_versions}")
    prompt_version = prompt_versions[0] if prompt_versions else PROMPT_VERSION

    if text_manifest is not None:
        validate_text_dataset_manifest(text_manifest)
        text_manifest_ref: str | None = text_manifest_sha256(text_manifest)
    else:
        text_manifest_ref = None

    publish_dates = pd.to_datetime(labels["publish_date"]) if len(labels) else pd.Series(dtype="datetime64[ns]")
    return {
        "artifact_type": RULE_BASELINE_ARTIFACT_TYPE,
        "schema_version": RULE_BASELINE_SCHEMA_VERSION,
        "status": "draft",
        "rule_lexicon": {
            "version": lex.version,
            "sha256": lexicon_sha256(lex),
            "growth_keywords": list(lex.growth_keywords),
            "negative_keywords": list(lex.negative_keywords),
            "litigation_keywords": list(lex.litigation_keywords),
        },
        "model": models[0] if models else None,
        "prompt_version": prompt_version,
        "labels": {
            "rows": int(len(labels)),
            "sha256": dataframe_sha256(labels),
            "event_type_distribution": _value_counts(labels, "event_type"),
            "sentiment_distribution": _value_counts(labels, "sentiment"),
        },
        "coverage": {
            "unique_stocks": int(labels["stock_code"].nunique()) if len(labels) else 0,
            "first_publish_date": publish_dates.min().date().isoformat() if len(labels) else None,
            "last_publish_date": publish_dates.max().date().isoformat() if len(labels) else None,
        },
        "text_manifest_sha256": text_manifest_ref,
        "quality": {"reviewed": False, "pass_ratio": None},
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def write_rule_baseline_artifact(
    labels: pd.DataFrame | None,
    output_dir: str | Path,
    *,
    lexicon: RuleLexicon | None = None,
    text_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """写 rule_baseline_labels.csv + rule_baseline_manifest.json，返回 manifest。"""
    if labels is None or labels.empty:
        labels = pd.DataFrame(columns=LABEL_COLUMNS)
    manifest = build_rule_baseline_artifact(labels, lexicon=lexicon, text_manifest=text_manifest)
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    labels.to_csv(root / LABELS_FILENAME, index=False, encoding="utf-8")
    (root / MANIFEST_FILENAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def validate_rule_baseline_artifact(artifact: dict[str, Any]) -> None:
    """校验 artifact manifest 结构；违例 raise ValueError。"""
    if artifact.get("artifact_type") != RULE_BASELINE_ARTIFACT_TYPE:
        raise ValueError(f"Invalid artifact_type: {artifact.get('artifact_type')}")
    if artifact.get("schema_version") != RULE_BASELINE_SCHEMA_VERSION:
        raise ValueError(f"Unsupported rule baseline schema_version: {artifact.get('schema_version')}")
    for key in ("rule_lexicon", "prompt_version", "labels", "coverage", "quality"):
        if key not in artifact:
            raise ValueError(f"Rule baseline artifact missing key: {key}")
    lexicon = artifact["rule_lexicon"]
    if not lexicon.get("version") or not lexicon.get("sha256"):
        raise ValueError("rule_lexicon must carry version and sha256")
    if artifact["labels"].get("sha256") is None:
        raise ValueError("labels.sha256 must be present")


def _value_counts(labels: pd.DataFrame, column: str) -> dict[str, int]:
    if labels.empty:
        return {}
    return {str(key): int(value) for key, value in labels[column].value_counts().sort_index().items()}
