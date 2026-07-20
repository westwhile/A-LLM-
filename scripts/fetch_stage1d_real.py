"""Stage-1D real-data acquisition for the A-share multi-factor research project.

Fetches verifiable open-source tables through AkShare into immutable raw batches
under ``data/raw/<batch-id>/`` and assembles standardized staging tables under
``data/staging/<batch-id>/`` for review-then-import.

Scope boundaries (per frozen plan):
- AkShare officially covers: trade calendar, benchmark index, daily bars,
  security master (exchange lists + delist lists), corporate-action factors
  (Sina qfq-factor) used to derive ``adj_factor``.
- Historical index membership, daily valuation, industry history, financial
  revision chains, SSE ST intervals remain user-supplied licensed tables and
  are NOT fabricated here.

Every per-stock failure is recorded in the manifest instead of being silently
skipped. Batches are append-only: re-running a finished chunk is skipped unless
it is missing from the manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# Snapshot semantics for the Sina qfq-factor endpoint.
# AkShare 1.18.64 ``stock_zh_a_daily(adjust='qfq-factor')`` returns the
# *divisor* used by Sina to produce forward-adjusted prices as
# ``raw_price / qfq_factor_raw``.  This project keeps the contract
# ``adjusted_price = raw_price * adj_factor``, hence
# ``adj_factor = 1 / qfq_factor_raw``.
QFQ_DIVISOR_COLUMN = "qfq_factor_raw"
ADJ_FACTOR_SEMANTICS = "adj_factor = 1 / qfq_factor_raw (Sina qfq-factor divisor snapshot)"
PRICE_ADJUSTMENT_LABEL = "raw_close_with_sina_qfq_divisor_snapshot"

FETCH_START = "2014-01-01"  # fetch margin before protocol data_start 2015-01-01
BENCH_SINA_SYMBOL = "sh000905"
BENCH_TS_CODE = "000905.SH"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_csv(df: pd.DataFrame, path: Path) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8")
    return {"path": str(path), "rows": int(len(df)), "file_sha256": _sha256(path)}


def _load_manifest(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"manifest_version": 1, "created_at": datetime.now().isoformat(timespec="seconds"), "tables": {}}


def _save_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest["updated_at"] = datetime.now().isoformat(timespec="seconds")
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _call_with_retry(func, *, retries: int = 4, base_sleep: float = 2.0, **kwargs):
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return func(**kwargs)
        except Exception as exc:  # noqa: BLE001 - network endpoints are flaky behind proxy
            last_exc = exc
            time.sleep(base_sleep * (attempt + 1))
    raise RuntimeError(f"endpoint failed after {retries + 1} attempts: {last_exc}") from last_exc


def _normalize_ts_code(code: str, exchange: str | None = None) -> str:
    text = str(code).strip().zfill(6)
    if exchange:
        raw = str(exchange).strip().upper()
        mapping = {
            "SH": "SH", "SS": "SH", "SSE": "SH", "XSHG": "SH", "上海证券交易所": "SH",
            "SZ": "SZ", "XSHE": "SZ", "SZSE": "SZ", "深圳证券交易所": "SZ",
        }
        suffix = mapping.get(raw) or mapping.get(str(exchange).strip())
        if suffix is None:
            raise ValueError(f"unrecognized exchange for ts_code normalization: {exchange!r}")
        return f"{text}.{suffix}"
    suffix = "SH" if text.startswith(("5", "6", "9")) else "SZ"
    return f"{text}.{suffix}"


def _sina_symbol(ts_code: str) -> str:
    code, suffix = ts_code.split(".")
    return f"{suffix.lower()}{code}"


# ---------------------------------------------------------------- universe
def phase_universe(ak, batch: Path, manifest: dict) -> pd.DataFrame:
    out_dir = batch / "universe"
    cons = _call_with_retry(ak.index_stock_cons_csindex, symbol="000905")
    cons = cons.rename(columns={"成分券代码": "code", "成分券名称": "name", "交易所": "exchange", "日期": "snapshot_date"})
    cons["ts_code"] = [_normalize_ts_code(c, e) for c, e in zip(cons["code"], cons["exchange"])]
    cons_frame = cons[["ts_code", "code", "name", "exchange", "snapshot_date"]]
    manifest["tables"]["universe_csi500_snapshot"] = {
        **_write_csv(cons_frame, out_dir / "csi500_snapshot.csv"),
        "source": "akshare.index_stock_cons_csindex(000905)",
        "note": "current snapshot only; NOT a point-in-time historical membership table",
    }

    delist_sh = _call_with_retry(ak.stock_info_sh_delist)
    delist_sh = delist_sh.rename(columns={"公司代码": "code", "公司简称": "name", "上市日期": "list_date", "暂停上市日期": "delist_date"})
    delist_sh = delist_sh[delist_sh["code"].astype(str).str.startswith(("600", "601", "603", "605", "688"))]
    delist_sh["ts_code"] = delist_sh["code"].map(lambda c: _normalize_ts_code(c, "SH"))
    manifest["tables"]["universe_delist_sh"] = {
        **_write_csv(delist_sh[["ts_code", "code", "name", "list_date", "delist_date"]], out_dir / "delist_sh.csv"),
        "source": "akshare.stock_info_sh_delist",
    }

    delist_sz = _call_with_retry(ak.stock_info_sz_delist)
    delist_sz = delist_sz.rename(columns={"证券代码": "code", "证券简称": "name", "上市日期": "list_date", "终止上市日期": "delist_date"})
    delist_sz = delist_sz[delist_sz["code"].astype(str).str.startswith(("000", "001", "002", "003", "300", "301", "302"))]
    delist_sz["ts_code"] = delist_sz["code"].map(lambda c: _normalize_ts_code(c, "SZ"))
    manifest["tables"]["universe_delist_sz"] = {
        **_write_csv(delist_sz[["ts_code", "code", "name", "list_date", "delist_date"]], out_dir / "delist_sz.csv"),
        "source": "akshare.stock_info_sz_delist",
    }

    universe = pd.concat(
        [
            cons_frame[["ts_code", "name"]].assign(universe_source="csi500_snapshot_202607"),
            delist_sh[["ts_code", "name"]].assign(universe_source="delist_sh"),
            delist_sz[["ts_code", "name"]].assign(universe_source="delist_sz"),
        ],
        ignore_index=True,
    ).drop_duplicates("ts_code")
    universe = universe.sort_values("ts_code").reset_index(drop=True)
    manifest["tables"]["universe_final"] = {
        **_write_csv(universe, out_dir / "universe_final.csv"),
        "note": "fetch universe = current CSI500 snapshot + exchange delisted A-shares; reconnaissance-grade, not PIT membership",
    }
    return universe


# --------------------------------------------------------------- calendar
def phase_calendar(ak, batch: Path, manifest: dict) -> None:
    raw = _call_with_retry(ak.tool_trade_date_hist_sina)
    date_col = "trade_date" if "trade_date" in raw.columns else raw.columns[0]
    cal = pd.DataFrame({"trade_date": pd.to_datetime(raw[date_col]), "is_open": True})
    cal = cal[cal["trade_date"] >= pd.Timestamp(FETCH_START)].reset_index(drop=True)
    manifest["tables"]["trade_calendar"] = {
        **_write_csv(cal, batch / "trade_calendar.csv"),
        "source": "akshare.tool_trade_date_hist_sina (Sina exchange calendar)",
        "units": {"is_open": "boolean"},
    }


# -------------------------------------------------------------- benchmark
def phase_benchmark(ak, batch: Path, manifest: dict) -> None:
    errors = []
    raw = pd.DataFrame()
    try:
        raw = _call_with_retry(ak.stock_zh_index_daily_em, symbol="csi000905", retries=1)
        source = "akshare.stock_zh_index_daily_em(csi000905) eastmoney"
    except Exception as exc:  # noqa: BLE001
        errors.append(f"eastmoney failed: {type(exc).__name__}: {exc}")
    if raw.empty:
        raw = _call_with_retry(ak.stock_zh_index_daily, symbol=BENCH_SINA_SYMBOL)
        source = "akshare.stock_zh_index_daily(sh000905) sina fallback"
    date_col = "date" if "date" in raw.columns else "日期"
    close_col = "close" if "close" in raw.columns else "收盘"
    bench = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(raw[date_col]),
            "index_code": BENCH_TS_CODE,
            "close": pd.to_numeric(raw[close_col], errors="coerce"),
        }
    )
    bench = bench[bench["trade_date"] >= pd.Timestamp(FETCH_START)].reset_index(drop=True)
    manifest["tables"]["benchmark_index"] = {
        **_write_csv(bench, batch / "benchmark_index.csv"),
        "source": source,
        "fallback_errors": errors,
        "units": {"close": "index_points"},
    }


# ------------------------------------------------------------ stock_basic
def phase_stock_basic(ak, batch: Path, manifest: dict) -> None:
    sh = _call_with_retry(ak.stock_info_sh_name_code, symbol="主板A股")
    sh = sh.rename(columns={"证券代码": "code", "证券简称": "name", "上市日期": "list_date"})
    kcb = pd.DataFrame()
    try:
        kcb = _call_with_retry(ak.stock_info_sh_name_code, symbol="科创板")
        kcb = kcb.rename(columns={"证券代码": "code", "证券简称": "name", "上市日期": "list_date"})
    except Exception as exc:  # noqa: BLE001
        manifest.setdefault("warnings", []).append(f"sse star list failed: {exc}")
    sh_all = pd.concat([sh[["code", "name", "list_date"]], kcb[["code", "name", "list_date"]]], ignore_index=True)
    sh_all["ts_code"] = sh_all["code"].map(lambda c: _normalize_ts_code(c, "SH"))
    sh_all["exchange"] = "SH"

    sz = _call_with_retry(ak.stock_info_sz_name_code, symbol="A股列表")
    sz = sz.rename(columns={"A股代码": "code", "A股简称": "name", "A股上市日期": "list_date"})
    sz["ts_code"] = sz["code"].map(lambda c: _normalize_ts_code(c, "SZ"))
    sz["exchange"] = "SZ"
    _write_csv(sz[["ts_code", "code", "name", "list_date", "A股总股本", "A股流通股本", "所属行业"]], batch / "raw_sources" / "szse_name_code.csv")

    master = pd.concat(
        [sh_all[["ts_code", "name", "list_date", "exchange"]], sz[["ts_code", "name", "list_date", "exchange"]]],
        ignore_index=True,
    )
    master["list_date"] = pd.to_datetime(master["list_date"], errors="coerce")
    master["delist_date"] = pd.NaT

    for table_name, exchange in [("universe_delist_sh", "SH"), ("universe_delist_sz", "SZ")]:
        delist_path = batch / "universe" / f"delist_{exchange.lower()}.csv"
        if not delist_path.exists():
            continue
        dl = pd.read_csv(delist_path)
        dl["delist_date"] = pd.to_datetime(dl["delist_date"], errors="coerce")
        dl["list_date"] = pd.to_datetime(dl["list_date"], errors="coerce")
        known = set(master["ts_code"])
        for row in dl.itertuples(index=False):
            if row.ts_code in known:
                master.loc[master["ts_code"].eq(row.ts_code), "delist_date"] = row.delist_date
            else:
                master = pd.concat(
                    [
                        master,
                        pd.DataFrame(
                            [{"ts_code": row.ts_code, "name": row.name, "list_date": row.list_date,
                              "delist_date": row.delist_date, "exchange": exchange}]
                        ),
                    ],
                    ignore_index=True,
                )
    master["name"] = master["name"].astype(str)
    dup_codes = sorted(master.loc[master.duplicated("ts_code", keep=False), "ts_code"].unique())
    if dup_codes:
        # Relisted stocks can appear in both exchange lists and delist lists.
        # Keep the row that carries a delist date when one exists; record the merge.
        manifest.setdefault("warnings", []).append(
            f"stock_basic merged duplicate ts_code (relist/multi-event): {dup_codes}"
        )
        master["_has_delist"] = master["delist_date"].notna().astype(int)
        master = (
            master.sort_values(["ts_code", "_has_delist"], ascending=[True, False])
            .drop_duplicates("ts_code", keep="first")
            .drop(columns=["_has_delist"])
        )
    master = master.sort_values("ts_code").reset_index(drop=True)
    dup = int(master.duplicated("ts_code").sum())
    if dup:
        raise ValueError(f"stock_basic duplicate ts_code after merge: {dup}")
    manifest["tables"]["stock_basic"] = {
        **_write_csv(master, batch / "stock_basic.csv"),
        "source": "akshare.stock_info_sh_name_code(主板A股+科创板) + stock_info_sz_name_code(A股列表) + stock_info_sh_delist + stock_info_sz_delist",
        "delisted_count": int(master["delist_date"].notna().sum()),
        "units": {"list_date": "date", "delist_date": "date"},
    }


# ---------------------------------------------------------------- bars
def _fetch_one_stock_bars(ak, ts_code: str, start: str, end: str | None, *, eastmoney_enabled: bool = True, sina_enabled: bool = True) -> tuple[pd.DataFrame, str]:
    """Fetch raw daily bars. Sina first (stable here); eastmoney then Tencent as fallback.

    Units are normalized to shares (股) for volume and CNY (元) for amount;
    eastmoney/Tencent report volume in lots (手) and are converted x100.
    Delisted stocks are not served by Sina, so callers pass sina_enabled=False.
    """
    end_str = (end or datetime.now().date().isoformat()).replace("-", "")
    start_str = start.replace("-", "")
    sina_error: Exception | None = None
    if sina_enabled:
        try:
            raw = _call_with_retry(
                ak.stock_zh_a_daily, symbol=_sina_symbol(ts_code), start_date=start_str, end_date=end_str, adjust="", retries=2
            )
            if raw is None or raw.empty:
                raise RuntimeError("empty sina frame")
            mapped = pd.DataFrame(
                {
                    "trade_date": pd.to_datetime(raw["date"]),
                    "ts_code": ts_code,
                    "open": pd.to_numeric(raw["open"], errors="coerce"),
                    "high": pd.to_numeric(raw["high"], errors="coerce"),
                    "low": pd.to_numeric(raw["low"], errors="coerce"),
                    "close": pd.to_numeric(raw["close"], errors="coerce"),
                    "volume": pd.to_numeric(raw["volume"], errors="coerce"),
                    "amount": pd.to_numeric(raw["amount"], errors="coerce"),
                }
            )
            for extra in ("outstanding_share", "turnover"):
                if extra in raw.columns:
                    mapped[extra] = pd.to_numeric(raw[extra], errors="coerce")
            return mapped, "sina stock_zh_a_daily (volume=shares, amount=CNY)"
        except Exception as exc:  # noqa: BLE001 - fall through to eastmoney
            sina_error = exc
    code = ts_code.split(".")[0]
    if eastmoney_enabled:
        try:
            raw = _call_with_retry(
                ak.stock_zh_a_hist, symbol=code, period="daily", start_date=start_str, end_date=end_str, adjust="", retries=1, base_sleep=1.0
            )
            if raw is not None and not raw.empty:
                mapped = pd.DataFrame(
                    {
                        "trade_date": pd.to_datetime(raw["日期"]),
                        "ts_code": ts_code,
                        "open": pd.to_numeric(raw["开盘"], errors="coerce"),
                        "high": pd.to_numeric(raw["最高"], errors="coerce"),
                        "low": pd.to_numeric(raw["最低"], errors="coerce"),
                        "close": pd.to_numeric(raw["收盘"], errors="coerce"),
                        "volume": pd.to_numeric(raw["成交量"], errors="coerce") * 100.0,
                        "amount": pd.to_numeric(raw["成交额"], errors="coerce"),
                    }
                )
                return mapped, "eastmoney stock_zh_a_hist (volume converted lots->shares, amount=CNY)"
        except Exception:
            pass
    # Tencent keeps history for many delisted stocks but reports volume (lots) only,
    # so the money amount column is left missing and flagged as a data-quality warning.
    raw = _call_with_retry(
        ak.stock_zh_a_hist_tx, symbol=_sina_symbol(ts_code), start_date=start_str, end_date=end_str, adjust="", retries=1, base_sleep=1.0
    )
    if raw is None or raw.empty:
        raise RuntimeError("all three providers returned no rows (sina/eastmoney/tencent)")
    mapped = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(raw["date"]),
            "ts_code": ts_code,
            "open": pd.to_numeric(raw["open"], errors="coerce"),
            "high": pd.to_numeric(raw["high"], errors="coerce"),
            "low": pd.to_numeric(raw["low"], errors="coerce"),
            "close": pd.to_numeric(raw["close"], errors="coerce"),
            "volume": pd.to_numeric(raw["amount"], errors="coerce") * 100.0,
            "amount": pd.NA,
        }
    )
    return mapped, "tencent stock_zh_a_hist_tx (volume lots->shares; money amount unavailable)"


def _fetch_qfq_factor(ak, ts_code: str) -> pd.DataFrame:
    """Fetch Sina qfq-factor divisor and derive ``adj_factor`` as its reciprocal.

    The raw endpoint returns the divisor ``qfq_factor_raw`` such that Sina's
    locally-computed forward-adjusted price equals ``close / qfq_factor_raw``.
    This project keeps the uniform contract ``adj_close = close * adj_factor``,
    so ``adj_factor = 1 / qfq_factor_raw``.
    """
    raw = _call_with_retry(ak.stock_zh_a_daily, symbol=_sina_symbol(ts_code), adjust="qfq-factor", retries=3)
    if raw is None or raw.empty:
        raise RuntimeError("empty sina qfq-factor frame")
    out = raw.rename(columns={"date": "trade_date", "qfq_factor": QFQ_DIVISOR_COLUMN})[
        ["trade_date", QFQ_DIVISOR_COLUMN]
    ]
    out["trade_date"] = pd.to_datetime(out["trade_date"])
    out[QFQ_DIVISOR_COLUMN] = pd.to_numeric(out[QFQ_DIVISOR_COLUMN], errors="coerce")
    out = out.dropna(subset=["trade_date", QFQ_DIVISOR_COLUMN])
    if out.empty:
        raise RuntimeError("no valid qfq-factor rows after parsing")

    divisor = out[QFQ_DIVISOR_COLUMN].to_numpy(dtype=float)
    invalid = ~np.isfinite(divisor) | (divisor <= 0.0)
    if invalid.any():
        bad = out.loc[invalid, ["trade_date", QFQ_DIVISOR_COLUMN]].head(5).to_dict("records")
        raise ValueError(f"qfq-factor divisor must be positive and finite; got invalid rows: {bad}")

    out["adj_factor"] = 1.0 / divisor
    return out[["trade_date", QFQ_DIVISOR_COLUMN, "adj_factor"]]


def attach_adj_factor(bars: pd.DataFrame, factors: pd.DataFrame) -> pd.DataFrame:
    """Map each trade date to the applicable Sina qfq factor (as-of snapshot).

    Carries both the raw divisor ``qfq_factor_raw`` and the derived
    ``adj_factor`` forward to every bar date.
    """
    bars = bars.sort_values("trade_date").reset_index(drop=True)
    factors = factors.sort_values("trade_date").reset_index(drop=True)
    merged = pd.merge_asof(bars, factors, on="trade_date", direction="backward")
    for col in (QFQ_DIVISOR_COLUMN, "adj_factor"):
        if col in merged.columns:
            # Match AkShare's as-of forward fill without inventing a neutral
            # factor before the first published divisor.  Such rows remain
            # missing and are handled by the historical-member coverage gate.
            merged[col] = merged[col].ffill()
    return merged


def phase_bars(ak, batch: Path, manifest: dict, universe: pd.DataFrame, chunk_start: int, chunk_size: int, fetch_end: str | None, retry_failed: bool = False) -> None:
    bars_dir = batch / "bars"
    bars_manifest_path = batch / "bars_manifest.json"
    bars_manifest = _load_manifest(bars_manifest_path)
    stocks = universe["ts_code"].tolist()[chunk_start:chunk_start + chunk_size]
    delisted_hint = set()
    if "universe_source" in universe.columns:
        delisted_hint = set(universe.loc[~universe["universe_source"].astype(str).str.contains("snapshot"), "ts_code"])
    eastmoney_enabled = True
    eastmoney_consecutive_failures = 0
    for ts_code in stocks:
        entry = bars_manifest["tables"].get(ts_code)
        if entry and entry.get("status") == "ok":
            continue
        if entry and entry.get("status") == "failed" and not retry_failed:
            continue
        try:
            bars, bar_source = _fetch_one_stock_bars(
                ak, ts_code, FETCH_START, fetch_end,
                eastmoney_enabled=eastmoney_enabled,
                sina_enabled=ts_code not in delisted_hint,
            )
            if bar_source.startswith("eastmoney"):
                eastmoney_consecutive_failures = 0
            try:
                factors = _fetch_qfq_factor(ak, ts_code)
                bars = attach_adj_factor(bars, factors)
                adj_source = "sina stock_zh_a_daily qfq-factor (snapshot)"
            except Exception as factor_exc:  # noqa: BLE001
                bars[QFQ_DIVISOR_COLUMN] = pd.NA
                bars["adj_factor"] = pd.NA
                adj_source = f"MISSING: {type(factor_exc).__name__}: {factor_exc}"
            bars["price_adjustment"] = PRICE_ADJUSTMENT_LABEL
            out = _write_csv(bars, bars_dir / f"{ts_code}.csv")
            bars_manifest["tables"][ts_code] = {
                **out,
                "status": "ok",
                "bar_source": bar_source,
                "adj_factor_source": adj_source,
                "adj_factor_semantics": ADJ_FACTOR_SEMANTICS,
                "price_adjustment_note": "snapshot semantics: only suitable for returns/ratio use; level prices change on re-snapshot",
                "date_range": [str(bars["trade_date"].min().date()), str(bars["trade_date"].max().date())],
            }
        except Exception as exc:  # noqa: BLE001
            if "ProxyError" in f"{type(exc).__name__}: {exc}" and eastmoney_enabled:
                eastmoney_consecutive_failures += 1
                if eastmoney_consecutive_failures >= 3:
                    eastmoney_enabled = False
                    bars_manifest.setdefault("warnings", []).append(
                        "eastmoney fallback disabled for the rest of this run after 3 consecutive proxy failures"
                    )
            bars_manifest["tables"][ts_code] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
        _save_manifest(bars_manifest_path, bars_manifest)
        time.sleep(0.25)


# ------------------------------------------------------------------ st
def phase_st_sz(ak, batch: Path, manifest: dict) -> None:
    raw = _call_with_retry(ak.stock_info_sz_change_name, symbol="简称变更")
    raw = raw.rename(columns={"变更日期": "change_date", "证券代码": "code", "变更前简称": "name_before", "变更后简称": "name_after"})
    raw["change_date"] = pd.to_datetime(raw["change_date"], errors="coerce")
    raw["ts_code"] = raw["code"].map(lambda c: _normalize_ts_code(c, "SZ"))
    manifest["tables"]["st_name_change_sz_staging"] = {
        **_write_csv(raw[["ts_code", "change_date", "证券简称", "name_before", "name_after"]], batch / "st_name_change_sz_staging.csv"),
        "source": "akshare.stock_info_sz_change_name(简称变更) SZSE official",
        "note": "staging evidence for ST-interval derivation; SSE equivalent lacks dates and remains blocked",
    }


def run(args: argparse.Namespace) -> None:
    import akshare as ak  # imported lazily so --help works without network

    batch = Path(args.batch_root)
    batch.mkdir(parents=True, exist_ok=True)
    manifest_path = batch / "fetch_manifest.json"
    manifest = _load_manifest(manifest_path)
    manifest.update(
        {
            "batch_id": batch.name,
            "provider": "akshare",
            "provider_version": ak.__version__,
            "fetch_start": FETCH_START,
            "fetch_end": args.end_date or "today",
            "scope": "trade_calendar, benchmark_index, stock_basic, daily_bar(+sina qfq-factor divisor snapshot), SZ name-change staging",
            "adj_factor_semantics": ADJ_FACTOR_SEMANTICS,
        }
    )
    phases = set(args.phases.split(","))
    universe_path = batch / "universe" / "universe_final.csv"
    if "universe" in phases:
        universe = phase_universe(ak, batch, manifest)
        _save_manifest(manifest_path, manifest)
    else:
        universe = pd.read_csv(universe_path)
    if "calendar" in phases:
        phase_calendar(ak, batch, manifest)
        _save_manifest(manifest_path, manifest)
    if "benchmark" in phases:
        phase_benchmark(ak, batch, manifest)
        _save_manifest(manifest_path, manifest)
    if "basic" in phases:
        phase_stock_basic(ak, batch, manifest)
        _save_manifest(manifest_path, manifest)
    if "st" in phases:
        phase_st_sz(ak, batch, manifest)
        _save_manifest(manifest_path, manifest)
    if "bars" in phases:
        phase_bars(ak, batch, manifest, universe, args.chunk_start, args.chunk_size, args.end_date, retry_failed=args.retry_failed)
    print(json.dumps({"batch": str(batch), "phases": sorted(phases), "tables": sorted(manifest.get("tables", {}))}, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-root", default="data/raw/real-20260719")
    parser.add_argument("--phases", default="universe,calendar,benchmark,basic,st")
    parser.add_argument("--chunk-start", type=int, default=0)
    parser.add_argument("--chunk-size", type=int, default=50)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--retry-failed", action="store_true",
                        help="Retry stocks already recorded as failed (default: skip them).")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
