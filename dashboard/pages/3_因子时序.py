"""因子时序：动态权重、稳定性和换手（Kalman，阶段 4）。"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st

from dashboard.adapters.time_series_reader import (
    find_time_series_dirs,
    load_dynamic_factor_weights,
    load_factor_timing_comparison,
    load_factor_weight_stability,
    load_factor_weight_turnover,
    load_stage46_status,
)
from dashboard.ui import (
    PROJECT_ROOT,
    show_artifact,
    show_synthetic_banner,
)

st.set_page_config(page_title="因子时序", layout="wide")
st.title("因子时序（Kalman 动态权重）")
st.caption("来源：阶段 4–6 输出目录（outputs/stage46* 或 runs/*/figures）中的权重、换手与稳定性 CSV（只读）。")

dirs = find_time_series_dirs(PROJECT_ROOT)
if not dirs:
    st.warning("未发现阶段 4–6 产物目录。因子时序证据缺失。")
    st.stop()

options = {str(path.relative_to(PROJECT_ROOT)): path for path in dirs}
choice = st.sidebar.selectbox("选择产物目录", list(options), key="ts_dir_factor")
series_dir = options[choice]

status = load_stage46_status(series_dir)
show_artifact(status, "stage46_status.csv", max_rows=50)
show_synthetic_banner(status.synthetic_engineering_only)

weights = load_dynamic_factor_weights(series_dir)
if weights.ok and weights.frame is not None:
    st.subheader("动态因子权重（按 test_date 透视展示，原始行见下表）")
    frame = weights.frame.copy()
    frame["test_date"] = pd.to_datetime(frame["test_date"], errors="coerce")
    pivot = frame.pivot_table(index="test_date", columns="factor", values="weight", aggfunc="mean")
    if not pivot.empty:
        st.line_chart(pivot)
    st.caption(
        f"run/目录：`{series_dir}` ｜ 数据区间：{frame['test_date'].min()} — {frame['test_date'].max()}"
    )
show_artifact(weights, "dynamic_factor_weights.csv")

show_artifact(load_factor_weight_turnover(series_dir), "factor_weight_turnover.csv")
show_artifact(load_factor_weight_stability(series_dir), "factor_weight_stability.csv")
show_artifact(load_factor_timing_comparison(series_dir), "factor_timing_comparison.csv")
