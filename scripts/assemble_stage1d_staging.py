"""Assemble standardized staging tables from the stage-1D raw batch.

Reads data/raw/<batch>/ and writes review-ready standard tables to
data/staging/<batch>/ together with an assembly manifest carrying row counts,
date ranges and content hashes used by the source-registry review files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

STANDARD_BAR_COLUMNS = [
    "trade_date", "ts_code", "open", "high", "low", "close",
    "volume", "amount", "adj_factor", "price_adjustment",
    # ``qfq_factor_raw`` is present for corrected Sina qfq-factor snapshots.
    "qfq_factor_raw",
]

# Legacy schema (pre-correction): the ``adj_factor`` column stored the raw
# Sina qfq-factor *divisor* and ``price_adjustment`` used the old label.
# Correction converts it to the reciprocal under the project contract
# ``adjusted_price = raw_price * adj_factor``.
LEGACY_PRICE_ADJUSTMENT = "raw_close_with_sina_qfq_factor_snapshot"
CORRECTED_PRICE_ADJUSTMENT = "raw_close_with_sina_qfq_divisor_snapshot"
CORRECTED_ADJ_SEMANTICS = "adj_factor = 1 / qfq_factor_raw (Sina qfq-factor divisor snapshot)"


def _convert_legacy_adj_factor(df: pd.DataFrame, entry_semantics: str | None) -> pd.DataFrame:
    """Convert legacy batches that stored the qfq divisor instead of adj_factor.

    A legacy batch is identified either by missing ``adj_factor_semantics`` in
    the per-stock bars manifest entry or by the old ``price_adjustment`` label.
    The old ``adj_factor`` value is preserved as ``qfq_factor_raw`` and then
    replaced by ``1 / qfq_factor_raw``.
    """
    is_legacy = entry_semantics != CORRECTED_ADJ_SEMANTICS and (
        df.get("price_adjustment") == LEGACY_PRICE_ADJUSTMENT
    ).any()
    if not is_legacy:
        return df

    out = df.copy()
    if "qfq_factor_raw" not in out.columns:
        out["qfq_factor_raw"] = out["adj_factor"]

    divisor = pd.to_numeric(out["adj_factor"], errors="coerce").to_numpy(dtype=float)
    # Missing factors are preserved so coverage can be measured and blocked
    # downstream.  Present factors must nevertheless be positive and finite.
    invalid = (~np.isnan(divisor)) & (~np.isfinite(divisor) | (divisor <= 0.0))
    if invalid.any():
        bad_dates = out.loc[invalid, "trade_date"].head(5).tolist()
        raise ValueError(
            f"legacy adj_factor contains non-positive/non-finite qfq divisor rows "
            f"(dates {bad_dates}); cannot convert to reciprocal safely"
        )

    out["adj_factor"] = 1.0 / divisor
    out["price_adjustment"] = CORRECTED_PRICE_ADJUSTMENT
    return out


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _frame_hash(df: pd.DataFrame) -> str:
    return hashlib.sha256(pd.util.hash_pandas_object(df, index=False).values.tobytes()).hexdigest()


def _write(df: pd.DataFrame, path: Path) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".parquet":
        df.to_parquet(path, index=False)
    else:
        df.to_csv(path, index=False, encoding="utf-8")
    return {
        "path": str(path),
        "rows": int(len(df)),
        "file_sha256": _sha256(path),
        "content_sha256": _frame_hash(df),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", default="data/raw/real-20260719")
    parser.add_argument("--staging", default="data/staging/real-20260719")
    args = parser.parse_args()
    batch = Path(args.batch)
    staging = Path(args.staging)
    manifest: dict = {"assembled_at": datetime.now().isoformat(timespec="seconds"), "source_batch": str(batch), "tables": {}}

    calendar = pd.read_csv(batch / "trade_calendar.csv", parse_dates=["trade_date"])
    benchmark = pd.read_csv(batch / "benchmark_index.csv", parse_dates=["trade_date"])
    # Sina publishes the forward exchange calendar; open days beyond the last
    # completed session have no bars yet and would trip benchmark alignment,
    # so staging clips the calendar at the last completed trading day.
    last_completed = benchmark["trade_date"].max()
    clipped = int((calendar["trade_date"] > last_completed).sum())
    calendar = calendar[calendar["trade_date"] <= last_completed].reset_index(drop=True)
    manifest["tables"]["trade_calendar"] = {
        **_write(calendar, staging / "trade_calendar.csv"),
        "date_range": [str(calendar["trade_date"].min().date()), str(calendar["trade_date"].max().date())],
        "forward_days_clipped": clipped,
    }

    manifest["tables"]["benchmark_index"] = {
        **_write(benchmark, staging / "benchmark_index.csv"),
        "date_range": [str(benchmark["trade_date"].min().date()), str(benchmark["trade_date"].max().date())],
    }

    basic = pd.read_csv(batch / "stock_basic.csv", parse_dates=["list_date", "delist_date"])
    manifest["tables"]["stock_basic"] = {
        **_write(basic, staging / "stock_basic.csv"),
        "total": int(len(basic)),
        "delisted": int(basic["delist_date"].notna().sum()),
        "list_date_range": [str(basic["list_date"].min().date()), str(basic["list_date"].max().date())],
    }

    bars_manifest = json.loads((batch / "bars_manifest.json").read_text(encoding="utf-8"))
    ok = {k: v for k, v in bars_manifest["tables"].items() if v.get("status") == "ok"}
    frames = []
    per_source_rows: dict[str, int] = {}
    legacy_converted_stocks: set[str] = set()
    for ts_code, entry in sorted(ok.items()):
        df = pd.read_csv(batch / "bars" / f"{ts_code}.csv", parse_dates=["trade_date"])
        semantics = entry.get("adj_factor_semantics") if isinstance(entry, dict) else None
        converted = _convert_legacy_adj_factor(df, semantics)
        if converted is not df:
            legacy_converted_stocks.add(ts_code)
        frames.append(converted)
        src = str(entry.get("bar_source", "?")).split(" ")[0]
        per_source_rows[src] = per_source_rows.get(src, 0) + len(df)
    bars = pd.concat(frames, ignore_index=True)
    dup = int(bars.duplicated(["trade_date", "ts_code"]).sum())
    if dup:
        raise ValueError(f"daily_bar duplicate (trade_date, ts_code): {dup}")
    bars = bars.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
    amount_missing = float(bars["amount"].isna().mean())
    adj_missing = float(bars["adj_factor"].isna().mean())
    manifest["tables"]["daily_bar"] = {
        **_write(bars, staging / "daily_bar.parquet"),
        "stocks": int(bars["ts_code"].nunique()),
        "date_range": [str(bars["trade_date"].min().date()), str(bars["trade_date"].max().date())],
        "rows_by_source": per_source_rows,
        "amount_missing_rate": round(amount_missing, 6),
        "adj_factor_missing_rate": round(adj_missing, 6),
        "fetch_failures": len(bars_manifest["tables"]) - len(ok),
        "adj_factor_semantics": CORRECTED_ADJ_SEMANTICS,
        "price_adjustment_note": "snapshot semantics: only suitable for returns/ratio use; level prices change on re-snapshot",
        "legacy_adj_factor_converted_stocks": sorted(legacy_converted_stocks),
    }
    # volume unit sanity: amount / (volume * close) should center near 1 for full-amount sources
    check = bars.dropna(subset=["amount"]).copy()
    ratio = check["amount"] / (check["volume"] * check["close"])
    manifest["tables"]["daily_bar"]["amount_vwap_ratio"] = {
        "p05": round(float(ratio.quantile(0.05)), 4),
        "p50": round(float(ratio.quantile(0.50)), 4),
        "p95": round(float(ratio.quantile(0.95)), 4),
    }
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "assembly_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
