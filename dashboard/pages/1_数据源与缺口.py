"""数据源与缺口：开源/iFinD/不可用字段、权限与探针状态。"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

from dashboard.adapters.data_quality_reader import load_data_source_gap_matrix
from dashboard.ui import PROJECT_ROOT, show_artifact

st.set_page_config(page_title="数据源与缺口", layout="wide")
st.title("数据源与缺口")
st.caption("来源：项目根目录 data_source_gap_matrix.csv 与 reports/data_sources/ 探针报告（只读）。")

gap = load_data_source_gap_matrix(PROJECT_ROOT)
show_artifact(gap, "数据源缺口矩阵（data_source_gap_matrix.csv）")

if gap.ok and gap.frame is not None:
    st.subheader("决策与探针状态分布")
    columns = st.columns(3)
    for column, field in zip(columns, ["decision", "probe_status", "license_status"]):
        if field in gap.frame.columns:
            column.markdown(f"**{field}**")
            column.dataframe(
                gap.frame[field].value_counts().rename_axis(field).reset_index(name="count"),
                use_container_width=True,
            )
