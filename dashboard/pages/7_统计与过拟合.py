"""统计与过拟合：DM、SPA、DSR、PBO、有效样本、试验登记覆盖率（阶段 8）。"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

from dashboard.adapters.audit_reader import (
    find_stage8_dirs,
    load_model_selection_audit,
    load_overfit_audit,
    load_prediction_test_results,
    load_promotion_conclusion,
    load_trial_registry_coverage,
)
from dashboard.adapters.time_series_reader import find_time_series_dirs
from dashboard.ui import PROJECT_ROOT, show_artifact

st.set_page_config(page_title="统计与过拟合", layout="wide")
st.title("统计与过拟合审计")
st.caption("来源：outputs/stage8*/ 审计 CSV（只读）；旧版 model_selection_audit.csv 作为补充证据。")

dirs = find_stage8_dirs(PROJECT_ROOT)
if not dirs:
    st.warning("未发现 outputs/stage8*/ 审计产物目录。统计与过拟合证据缺失（阶段 8 可能尚未运行）。")
else:
    options = {str(path.relative_to(PROJECT_ROOT)): path for path in dirs}
    choice = st.sidebar.selectbox("选择审计目录", list(options), key="audit_dir")
    audit_dir = options[choice]

    show_artifact(load_prediction_test_results(audit_dir), "prediction_test_results.csv（DM/SPA）")
    show_artifact(load_overfit_audit(audit_dir), "overfit_audit.csv（DSR/PBO）")
    show_artifact(load_trial_registry_coverage(audit_dir), "trial_registry_coverage.csv")
    show_artifact(load_promotion_conclusion(audit_dir), "promotion_conclusion.csv")

st.subheader("补充证据：旧版 model_selection_audit.csv")
ts_dirs = find_time_series_dirs(PROJECT_ROOT)
if not ts_dirs:
    st.info("未发现阶段 4–6 产物目录，无补充证据。")
else:
    options = {str(path.relative_to(PROJECT_ROOT)): path for path in ts_dirs}
    choice = st.sidebar.selectbox("选择产物目录", list(options), key="ts_dir_audit")
    show_artifact(load_model_selection_audit(options[choice]), "model_selection_audit.csv")
