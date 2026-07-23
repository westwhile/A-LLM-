"""证据与运行：文件存在性、哈希、生成时间、配置版本、过期状态。"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st

from dashboard.adapters import discover_runs, file_sha256
from dashboard.adapters.manifest_reader import (
    load_data_manifest,
    load_evidence_manifest,
)
from dashboard.ui import (
    PROJECT_ROOT,
    provenance_caption,
    select_entry,
    show_json_artifact,
    show_run_issues,
    show_synthetic_banner,
)

st.set_page_config(page_title="证据与运行", layout="wide")
st.title("证据与运行")
st.caption("来源：evidence_manifest.json、data_manifest.json 与运行目录文件清单（只读）；哈希现场计算，不修改源文件。")

entries = discover_runs(PROJECT_ROOT)

st.subheader("全部运行目录")
if entries:
    st.dataframe(
        pd.DataFrame([
            {
                "run_id": entry.run_id,
                "kind": entry.kind,
                "mode": entry.mode,
                "status": entry.status,
                "created_at": entry.created_at,
                "synthetic_engineering_only": entry.synthetic_engineering_only,
                "last_modified": entry.last_modified,
                "issues": "；".join(entry.issues),
                "path": str(entry.path),
            }
            for entry in entries
        ]),
        use_container_width=True,
    )
    stale = [e for e in entries if e.issues]
    if stale:
        st.warning(f"{len(stale)} 个运行存在一致性问题（见 issues 列），其产物不应与其他 run_id 混合展示。")
else:
    st.warning("未发现任何运行目录。")

entry = select_entry(entries, "选择运行查看证据", key="evidence_run")
if entry is None:
    st.stop()

show_run_issues(entry)
show_synthetic_banner(entry.synthetic_engineering_only)

evidence = load_evidence_manifest(entry.path)
show_json_artifact(evidence, "evidence_manifest.json")

data_manifest = load_data_manifest(entry.path)
show_json_artifact(data_manifest, "data_manifest.json")

st.subheader("运行目录文件存在性与哈希")
if entry.path.is_dir():
    rows = []
    for item in sorted(p for p in entry.path.rglob("*") if p.is_file()):
        rows.append({
            "file": str(item.relative_to(entry.path)),
            "size_bytes": item.stat().st_size,
            "sha256": file_sha256(item),
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True)
    else:
        st.info("运行目录为空。")
    st.caption(f"目录：`{entry.path}`")
else:
    st.error(f"运行目录缺失：{entry.path}")

for result in (evidence, data_manifest):
    provenance_caption(result)
