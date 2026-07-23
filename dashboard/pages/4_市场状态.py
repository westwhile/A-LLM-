"""市场状态：filtered probability、转移矩阵、持续期、状态归因（HMM，阶段 5）。"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st

from dashboard.adapters.time_series_reader import (
    find_time_series_dirs,
    load_regime_durations,
    load_regime_factor_performance,
    load_regime_probabilities,
    load_regime_stability,
    load_regime_transition_matrix,
)
from dashboard.ui import PROJECT_ROOT, show_artifact

st.set_page_config(page_title="市场状态", layout="wide")
st.title("市场状态（HMM）")
st.caption("来源：阶段 4–6 输出目录中的 regime_* CSV（只读）；仅展示 filtered probability，不做前向推断。")

dirs = find_time_series_dirs(PROJECT_ROOT)
if not dirs:
    st.warning("未发现阶段 4–6 产物目录。市场状态证据缺失。")
    st.stop()

options = {str(path.relative_to(PROJECT_ROOT)): path for path in dirs}
choice = st.sidebar.selectbox("选择产物目录", list(options), key="ts_dir_regime")
series_dir = options[choice]

probabilities = load_regime_probabilities(series_dir)
if probabilities.ok and probabilities.frame is not None:
    frame = probabilities.frame.copy()
    ok_rows = frame[frame["status"].astype(str).eq("ok")] if "status" in frame.columns else frame
    probability_columns = [
        column for column in ("bear_probability", "neutral_probability", "bull_probability")
        if column in ok_rows.columns
    ]
    if not ok_rows.empty and probability_columns:
        st.subheader("filtered 状态概率")
        ok_rows = ok_rows.copy()
        ok_rows["as_of_date"] = pd.to_datetime(ok_rows["as_of_date"], errors="coerce")
        st.line_chart(ok_rows.set_index("as_of_date")[probability_columns])
        st.caption(
            f"run/目录：`{series_dir}` ｜ 数据区间：{ok_rows['as_of_date'].min()} — {ok_rows['as_of_date'].max()}"
        )
    else:
        st.warning("regime_probabilities.csv 中无 status=ok 的有效概率行（可能为 insufficient_history）。")
show_artifact(probabilities, "regime_probabilities.csv")

show_artifact(load_regime_transition_matrix(series_dir), "regime_transition_matrix.csv")
show_artifact(load_regime_durations(series_dir), "regime_durations.csv")
show_artifact(load_regime_factor_performance(series_dir), "regime_factor_performance.csv")
show_artifact(load_regime_stability(series_dir), "regime_stability.csv")
