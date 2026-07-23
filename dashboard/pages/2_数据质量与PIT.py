"""数据质量与 PIT：覆盖率、缺失、公告/可用日、修订、幸存者偏差。"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

from dashboard.adapters.data_quality_reader import (
    AUDIT_SCHEMAS,
    list_gate_dirs,
    load_audit_csv,
    load_data_gate_summary,
)
from dashboard.ui import PROJECT_ROOT, show_artifact, show_json_artifact

st.set_page_config(page_title="数据质量与 PIT", layout="wide")
st.title("数据质量与 PIT 审计")
st.caption("来源：reports/gate/*/data_gate_summary.json 与五项审计 CSV（只读）；缺失/阻断一律醒目展示，不伪造通过。")

gate_dirs = list_gate_dirs(PROJECT_ROOT)
if not gate_dirs:
    st.warning("未发现 reports/gate/ 下的门禁目录。数据质量与 PIT 证据缺失。")
    st.stop()

options = {path.name: path for path in gate_dirs}
choice = st.sidebar.selectbox("选择门禁批次", list(options), key="gate_dir")
gate_dir = options[choice]
st.sidebar.caption(f"目录：`{gate_dir}`")

summary = load_data_gate_summary(gate_dir)
if summary.ok and isinstance(summary.data, dict):
    status = str(summary.data.get("status", "未知"))
    if status == "passed":
        st.success(f"门禁状态：{status}")
    else:
        st.error(f"门禁状态：{status}")
show_json_artifact(summary, "data_gate_summary.json")

for audit_name in AUDIT_SCHEMAS:
    show_artifact(load_audit_csv(gate_dir, audit_name), f"{audit_name}.csv")
