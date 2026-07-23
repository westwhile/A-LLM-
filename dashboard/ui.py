"""看板共享 UI 组件（只读展示，无任何写入口）。

约定：每个图表/表格下方都必须展示来源文件、sha256、修改时间与 run_id 等
追溯信息；``synthetic_engineering_only`` 与降级状态醒目可见。
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from dashboard.adapters import ArtifactResult, RunEntry, frame_run_ids

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_STATUS_LABEL = {
    "ok": ("success", "可用"),
    "missing": ("warning", "缺失"),
    "empty": ("warning", "空文件"),
    "schema_mismatch": ("error", "schema 不符"),
    "run_id_mismatch": ("error", "run_id 混杂"),
    "error": ("error", "读取失败"),
}


def show_synthetic_banner(flag: bool | None) -> None:
    """醒目展示 synthetic_engineering_only 标记。"""
    if flag is True:
        st.error("SYNTHETIC_ENGINEERING_ONLY：本视图来自样例/工程数据，仅用于流程验证，不构成真实研究结论。")
    elif flag is None:
        st.info("synthetic_engineering_only 标记未知（缺少运行元数据）。")


def show_run_issues(entry: RunEntry) -> None:
    """展示运行目录的一致性问题（如 run_id 与目录名不符、缺元数据）。"""
    for issue in entry.issues:
        st.warning(f"运行一致性：{issue}")


def provenance_caption(result: ArtifactResult) -> None:
    """在产物下方展示追溯信息：来源文件、sha256、修改时间、run_id。"""
    parts = [f"来源：`{result.path}`"]
    if result.sha256:
        parts.append(f"sha256 `{result.sha256[:16]}…`")
    if result.modified_at:
        parts.append(f"修改时间 {result.modified_at}")
    run_ids = frame_run_ids(result)
    if run_ids:
        parts.append(f"run_id：{', '.join(run_ids)}")
    st.caption(" ｜ ".join(parts))


def show_artifact(
    result: ArtifactResult,
    title: str | None = None,
    *,
    show_frame: bool = True,
    max_rows: int = 500,
) -> None:
    """统一渲染一个适配层读取结果：状态横幅 + 数据表 + 追溯信息。"""
    if title:
        st.subheader(title)
    kind, label = _STATUS_LABEL.get(result.status, ("error", result.status))
    message = f"{label}：{result.message}" if result.message else label
    getattr(st, kind)(message)
    if result.synthetic_engineering_only:
        show_synthetic_banner(True)
    if result.ok and show_frame and result.frame is not None:
        if len(result.frame) > max_rows:
            st.caption(f"共 {len(result.frame)} 行，仅展示前 {max_rows} 行（看板不全量载入大表）。")
        st.dataframe(result.frame.head(max_rows), use_container_width=True)
    provenance_caption(result)


def show_json_artifact(result: ArtifactResult, title: str | None = None) -> None:
    """渲染 JSON 产物：状态横幅 + 格式化 JSON + 追溯信息。"""
    if title:
        st.subheader(title)
    kind, label = _STATUS_LABEL.get(result.status, ("error", result.status))
    message = f"{label}：{result.message}" if result.message else label
    getattr(st, kind)(message)
    if result.synthetic_engineering_only:
        show_synthetic_banner(True)
    if result.ok:
        st.json(result.data)
    provenance_caption(result)


def select_entry(entries: list[RunEntry], label: str, key: str) -> RunEntry | None:
    """侧边栏运行选择器；返回选中的 RunEntry。"""
    if not entries:
        st.warning("未发现任何运行目录。请先运行研究流水线生成产物；看板不伪造数据。")
        return None
    options = {
        f"{entry.run_id}（{entry.kind}｜mode={entry.mode or '?'}｜status={entry.status or '?'}）": entry
        for entry in entries
    }
    choice = st.sidebar.selectbox(label, list(options), key=key)
    entry = options[choice]
    st.sidebar.caption(f"目录：`{entry.path}`")
    if entry.last_modified:
        st.sidebar.caption(f"最近修改：{entry.last_modified}")
    if entry.synthetic_engineering_only:
        st.sidebar.error("synthetic_engineering_only")
    return entry
