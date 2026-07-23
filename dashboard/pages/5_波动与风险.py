"""波动与风险：波动预测、目标偏差、风险贡献（GARCH/DCC，阶段 6）。"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st

from dashboard.adapters.time_series_reader import (
    find_time_series_dirs,
    load_dcc_risk_contributions,
    load_dynamic_covariance,
    load_model_warnings,
    load_volatility_forecasts,
    load_volatility_model_comparison,
)
from dashboard.ui import PROJECT_ROOT, show_artifact

st.set_page_config(page_title="波动与风险", layout="wide")
st.title("波动与风险（GARCH / DCC）")
st.caption("来源：阶段 4–6 输出目录中的 volatility_*、dynamic_covariance、dcc_risk_contributions CSV（只读）。")

dirs = find_time_series_dirs(PROJECT_ROOT)
if not dirs:
    st.warning("未发现阶段 4–6 产物目录。波动与风险证据缺失。")
    st.stop()

options = {str(path.relative_to(PROJECT_ROOT)): path for path in dirs}
choice = st.sidebar.selectbox("选择产物目录", list(options), key="ts_dir_vol")
series_dir = options[choice]

forecasts = load_volatility_forecasts(series_dir)
if forecasts.ok and forecasts.frame is not None:
    frame = forecasts.frame.copy()
    ok_rows = frame[frame["status"].astype(str).eq("ok")] if "status" in frame.columns else frame
    if not ok_rows.empty and "annualized_volatility_forecast" in ok_rows.columns:
        st.subheader("年化波动预测（status=ok）")
        ok_rows = ok_rows.copy()
        ok_rows["as_of_date"] = pd.to_datetime(ok_rows["as_of_date"], errors="coerce")
        pivot = ok_rows.pivot_table(
            index="as_of_date", columns="model",
            values="annualized_volatility_forecast", aggfunc="mean",
        )
        if not pivot.empty:
            st.line_chart(pivot)
        st.caption(
            f"run/目录：`{series_dir}` ｜ 数据区间：{ok_rows['as_of_date'].min()} — {ok_rows['as_of_date'].max()}"
        )
    else:
        st.warning("volatility_forecasts.csv 中无 status=ok 的有效预测行（可能为 insufficient_history）。")
show_artifact(forecasts, "volatility_forecasts.csv")

show_artifact(load_volatility_model_comparison(series_dir), "volatility_model_comparison.csv")
show_artifact(load_dynamic_covariance(series_dir), "dynamic_covariance.csv")
show_artifact(load_dcc_risk_contributions(series_dir), "dcc_risk_contributions.csv")
show_artifact(load_model_warnings(series_dir), "model_warnings.csv")
