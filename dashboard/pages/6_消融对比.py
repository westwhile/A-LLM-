"""消融对比：A–G 七组曲线、共同区间、成本和增量解释（阶段 7）。"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st

from dashboard.adapters.performance_reader import (
    find_ablation_dirs,
    load_ablation_cost_sensitivity,
    load_ablation_incremental,
    load_ablation_nav,
    load_ablation_performance,
    load_ablation_portfolio_returns,
    load_ablation_status,
)
from dashboard.ui import PROJECT_ROOT, show_artifact, show_synthetic_banner

st.set_page_config(page_title="消融对比", layout="wide")
st.title("消融对比（A–G 七组方案）")
st.caption("来源：outputs/stage7*/ 下的 ablation_*.csv（只读）；共同投资区间，不重新计算绩效。")

dirs = find_ablation_dirs(PROJECT_ROOT)
if not dirs:
    st.warning("未发现 outputs/stage7*/ 消融产物目录。消融证据缺失（阶段 7 可能尚未运行）。")
    st.stop()

options = {str(path.relative_to(PROJECT_ROOT)): path for path in dirs}
choice = st.sidebar.selectbox("选择消融目录", list(options), key="ablation_dir")
ablation_dir = options[choice]

status = load_ablation_status(ablation_dir)
show_artifact(status, "ablation_status.csv", max_rows=50)
show_synthetic_banner(status.synthetic_engineering_only)

nav = load_ablation_nav(ablation_dir)
if nav.ok and nav.frame is not None:
    frame = nav.frame.copy()
    ok_rows = frame[frame["status"].astype(str).eq("ok")] if "status" in frame.columns else frame
    if ok_rows.empty:
        ok_rows = frame
    ok_rows = ok_rows.copy()
    ok_rows["date"] = pd.to_datetime(ok_rows["date"], errors="coerce")
    pivot = ok_rows.pivot_table(index="date", columns="portfolio_id", values="nav", aggfunc="mean")
    if not pivot.empty:
        st.subheader("七组方案净值曲线（共同区间）")
        st.line_chart(pivot)
        st.caption(
            f"run/目录：`{ablation_dir}` ｜ 数据区间：{ok_rows['date'].min()} — {ok_rows['date'].max()}"
        )
show_artifact(nav, "ablation_nav.csv")

show_artifact(load_ablation_performance(ablation_dir), "ablation_performance.csv")

incremental = load_ablation_incremental(ablation_dir)
st.markdown("增量解释约定：C−A（Kalman）、D−A（HMM）、E−A（GARCH）、F−C（状态增量）、G−F（波动控制增量）、G−A（总增量）。")
show_artifact(incremental, "ablation_incremental.csv")

show_artifact(load_ablation_cost_sensitivity(ablation_dir), "ablation_cost_sensitivity.csv")
show_artifact(load_ablation_portfolio_returns(ablation_dir), "ablation_portfolio_returns.csv")
