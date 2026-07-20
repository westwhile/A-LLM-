"""Stage-1D live probe of AkShare endpoints (read-only, tiny samples).

Writes a JSON evidence summary to reports/data_sources/akshare_probe_20260719.json.
"""
from __future__ import annotations

import json
import traceback
from pathlib import Path

import akshare as ak
import pandas as pd

OUT = Path("reports/data_sources/akshare_probe_20260719.json")
results: dict[str, dict] = {}


def probe(name: str, func, **kwargs):
    try:
        df = func(**kwargs)
        info: dict = {"ok": True, "rows": int(len(df)), "columns": [str(c) for c in df.columns]}
        for col in df.columns:
            parsed = pd.to_datetime(df[col], errors="coerce")
            if parsed.notna().sum() > max(3, len(df) * 0.5):
                info.setdefault("date_like", {})[str(col)] = [
                    str(parsed.min().date()),
                    str(parsed.max().date()),
                ]
        info["head"] = df.head(3).astype(str).to_dict("records")
        results[name] = info
        print(f"[OK] {name}: rows={info['rows']} cols={info['columns'][:8]}")
    except Exception as exc:  # noqa: BLE001
        results[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-500:]}
        print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")


probe("trade_calendar", ak.tool_trade_date_hist_sina)
probe("benchmark_000905", ak.stock_zh_index_daily_em, symbol="csi000905")
probe("daily_bar_raw_600000", ak.stock_zh_a_hist, symbol="600000", period="daily",
      start_date="20150101", end_date="20260719", adjust="")
probe("daily_bar_qfq_600000", ak.stock_zh_a_hist, symbol="600000", period="daily",
      start_date="20150101", end_date="20260719", adjust="qfq")
probe("index_cons_now_000905", ak.index_stock_cons_csindex, symbol="000905")
probe("index_weight_now_000905", ak.index_stock_cons_weight_csindex, symbol="000905")
probe("delist_sh", ak.stock_info_sh_delist)
probe("delist_sz", ak.stock_info_sz_delist)
probe("name_code_sh", ak.stock_info_sh_name_code, symbol="主板A股")
probe("name_code_sz", ak.stock_info_sz_name_code, symbol="A股列表")
probe("change_name_600000", ak.stock_info_change_name, symbol="600000")
probe("industry_clf_hist_sw", ak.stock_industry_clf_hist_sw, symbol="000001")
probe("fund_flow_600000", ak.stock_individual_fund_flow, stock="600000", market="sh")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps({"akshare_version": ak.__version__, "probes": results}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print(f"written: {OUT}")
