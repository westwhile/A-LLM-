"""研究总览（看板主页）。

只读展示：当前 run_id、数据模式、研究阶段、门禁状态与结论等级；
所有数据经 dashboard.adapters 适配层读取，看板不修改任何源文件。
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

from dashboard.adapters import discover_runs
from dashboard.adapters.manifest_reader import (
    load_evidence_manifest,
    load_research_protocol_snapshot,
    load_run_metadata,
    load_stage_summary,
)
from dashboard.ui import (
    PROJECT_ROOT,
    provenance_caption,
    select_entry,
    show_json_artifact,
    show_run_issues,
    show_synthetic_banner,
)

st.set_page_config(page_title="研究总览", layout="wide")
st.title("研究总览")
st.caption("只读研究看板 ｜ 数据全部来自本地已生成产物，经 dashboard.adapters 适配层读取；本看板无任何写数据、改配置或交易入口。")

entries = discover_runs(PROJECT_ROOT)
entry = select_entry(entries, "选择运行", key="overview_run")
if entry is None:
    st.stop()

show_run_issues(entry)
show_synthetic_banner(entry.synthetic_engineering_only)

st.subheader("运行标识")
columns = st.columns(4)
columns[0].metric("run_id", entry.run_id)
columns[1].metric("数据模式", entry.mode or "未知")
columns[2].metric("类型", entry.kind)
columns[3].metric("创建时间", entry.created_at or "未知")

metadata = load_run_metadata(entry.path)
show_json_artifact(metadata, "运行元数据（run_metadata.json）")

protocol = load_research_protocol_snapshot(entry.path)
show_json_artifact(protocol, "研究协议快照（research_protocol_snapshot.json）")

evidence = load_evidence_manifest(entry.path)
if evidence.ok and isinstance(evidence.data, dict):
    st.subheader("证据清单摘要（evidence_manifest.json）")
    claims = evidence.data.get("claims", [])
    if claims:
        import pandas as pd

        st.dataframe(pd.DataFrame(claims), use_container_width=True)
    st.caption(f"data_gate_status：{evidence.data.get('data_gate_status')}")
    provenance_caption(evidence)
else:
    show_json_artifact(evidence, "证据清单（evidence_manifest.json）")

if entry.kind != "pipeline_run":
    summary = load_stage_summary(entry.path, entry.kind)
    show_json_artifact(summary, f"阶段摘要（{entry.kind}_summary.json）")

st.sidebar.markdown("---")
st.sidebar.caption("仅监听 127.0.0.1 ｜ 只读 ｜ 无后台任务")
