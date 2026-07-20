from __future__ import annotations

import importlib.metadata
from pathlib import Path
import time
from typing import Protocol

import pandas as pd

from ashare_factor_research.data.sample_data import write_sample_data
from ashare_factor_research.data.schema import normalize_dates, normalize_table_dates, validate_schema


STANDARD_TABLES = [
    "trade_calendar",
    "stock_basic",
    "daily_bar",
    "daily_basic",
    "industry",
    "index_member",
    "financial_indicator",
    "suspension",
    "st_status",
    "limit_price",
    "benchmark_index",
    "news_event",
]

AKSHARE_TABLE_ENDPOINTS = {
    "trade_calendar": "tool_trade_date_hist_sina",
    "stock_basic": "stock_info_a_code_name",
    "daily_bar": "stock_zh_a_hist (fallback stock_zh_a_daily)",
    "benchmark_index": "stock_zh_index_daily_em (fallback stock_zh_index_daily)",
}


class MarketDataProvider(Protocol):
    def load_trade_calendar(self) -> pd.DataFrame: ...

    def load_stock_basic(self) -> pd.DataFrame: ...

    def load_daily_bar(self) -> pd.DataFrame: ...

    def load_daily_basic(self) -> pd.DataFrame: ...

    def load_benchmark_index(self) -> pd.DataFrame: ...


class AkShareProvider:
    """Conservative AkShare provider for stable real-data endpoints.

    Tables that require reliable point-in-time history, such as index
    membership, ST status, suspensions, industry and daily valuation, should be
    supplied as standardized local files until their provider mapping is
    explicitly validated.
    """

    def __init__(
        self,
        start_date: str,
        end_date: str | None = None,
        symbols: list[str] | None = None,
        index_code: str = "000905",
    ) -> None:
        self.start_date = start_date
        self.end_date = end_date
        self.symbols = symbols or []
        self.index_code = index_code

    def _akshare(self):
        try:
            import akshare as ak  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "AkShare is not installed. Install with `python -m pip install akshare pyarrow` "
                "or use local standardized data files."
            ) from exc
        return ak

    def provider_version(self) -> str:
        try:
            return importlib.metadata.version("akshare")
        except importlib.metadata.PackageNotFoundError:
            return str(getattr(self._akshare(), "__version__", "unknown"))

    @staticmethod
    def _date_arg(date: str | None) -> str | None:
        if date is None:
            return None
        return pd.Timestamp(date).strftime("%Y%m%d")

    @staticmethod
    def _normalize_ts_code(symbol: str) -> str:
        text = str(symbol).strip()
        if "." in text and len(text.split(".")[-1]) == 2:
            code, suffix = text.split(".")[:2]
            return f"{code.zfill(6)}.{suffix.upper()}"
        code = text.split(".")[0].zfill(6)
        suffix = "SH" if code.startswith(("5", "6", "9")) else "SZ"
        return f"{code}.{suffix}"

    @staticmethod
    def _sina_symbol(ts_code: str) -> str:
        code, suffix = ts_code.split(".")
        return f"{suffix.lower()}{code}"

    @staticmethod
    def _sina_index_symbol(index_code: str) -> str:
        if index_code.startswith(("sh", "sz")):
            return index_code
        code = index_code.split(".")[0]
        suffix = index_code.split(".")[1].upper() if "." in index_code else "SH"
        return f"{suffix.lower()}{code}"

    @staticmethod
    def _first_column(raw: pd.DataFrame, candidates: tuple[str, ...], table: str) -> str:
        for col in candidates:
            if col in raw.columns:
                return col
        raise RuntimeError(f"Cannot map {table}: none of {candidates} found. Actual columns: {list(raw.columns)}")

    @staticmethod
    def _call_with_retry(endpoint_name: str, func, *args, retries: int = 2, **kwargs):
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                return func(*args, **kwargs)
            except Exception as exc:  # pragma: no cover - depends on external provider/network
                last_exc = exc
                if attempt >= retries:
                    break
                time.sleep(1.0 + attempt)
        raise RuntimeError(f"AkShare endpoint failed after retries: {endpoint_name}. Last error: {last_exc}") from last_exc

    def load_trade_calendar(self) -> pd.DataFrame:
        ak = self._akshare()
        if not hasattr(ak, "tool_trade_date_hist_sina"):
            raise RuntimeError("AkShare tool_trade_date_hist_sina is unavailable in this installed version.")
        raw = self._call_with_retry("tool_trade_date_hist_sina", ak.tool_trade_date_hist_sina)
        date_col = "trade_date" if "trade_date" in raw.columns else raw.columns[0]
        out = pd.DataFrame({"trade_date": pd.to_datetime(raw[date_col]), "is_open": True})
        out = out[
            (out["trade_date"] >= pd.Timestamp(self.start_date))
            & (out["trade_date"] <= pd.Timestamp(self.end_date or pd.Timestamp.today()))
        ].reset_index(drop=True)
        validate_schema(out, "trade_calendar", check_primary_key=True)
        return out

    def load_stock_basic(self) -> pd.DataFrame:
        ak = self._akshare()
        if not hasattr(ak, "stock_info_a_code_name"):
            raise RuntimeError("AkShare stock_info_a_code_name is unavailable in this installed version.")
        raw = self._call_with_retry("stock_info_a_code_name", ak.stock_info_a_code_name)
        code_col = "code" if "code" in raw.columns else "代码"
        name_col = "name" if "name" in raw.columns else "名称"
        codes = raw[code_col].astype(str).map(self._normalize_ts_code)
        out = pd.DataFrame(
            {
                "ts_code": codes,
                "name": raw[name_col].astype(str),
                "list_date": pd.NaT,
                "delist_date": pd.NaT,
                "exchange": codes.str[-2:],
            }
        )
        validate_schema(out, "stock_basic", check_primary_key=True)
        return out

    def load_daily_bar(self) -> pd.DataFrame:
        if not self.symbols:
            raise RuntimeError("AkShare daily bar collection requires symbols, e.g. --symbols 000001.SZ,600000.SH.")
        ak = self._akshare()
        rows: list[pd.DataFrame] = []
        for symbol in self.symbols:
            ts_code = self._normalize_ts_code(symbol)
            try:
                raw = self._call_with_retry(
                    "stock_zh_a_hist",
                    ak.stock_zh_a_hist,
                    symbol=ts_code.split(".")[0],
                    period="daily",
                    start_date=self._date_arg(self.start_date),
                    end_date=self._date_arg(self.end_date),
                    adjust="",
                )
            except RuntimeError:
                if not hasattr(ak, "stock_zh_a_daily"):
                    raise
                raw = self._call_with_retry(
                    "stock_zh_a_daily",
                    ak.stock_zh_a_daily,
                    symbol=self._sina_symbol(ts_code),
                    start_date=self._date_arg(self.start_date),
                    end_date=self._date_arg(self.end_date),
                    adjust="",
                )
            if raw.empty:
                raise RuntimeError(f"AkShare returned empty daily bar data for {ts_code}.")
            date_col = self._first_column(raw, ("日期", "date", "trade_date"), "daily_bar")
            open_col = self._first_column(raw, ("开盘", "open"), "daily_bar")
            high_col = self._first_column(raw, ("最高", "high"), "daily_bar")
            low_col = self._first_column(raw, ("最低", "low"), "daily_bar")
            close_col = self._first_column(raw, ("收盘", "close"), "daily_bar")
            volume_col = self._first_column(raw, ("成交量", "volume", "vol"), "daily_bar")
            amount_col = self._first_column(raw, ("成交额", "amount"), "daily_bar")
            mapped = pd.DataFrame(
                {
                    "trade_date": pd.to_datetime(raw[date_col]),
                    "ts_code": ts_code,
                    "open": pd.to_numeric(raw[open_col], errors="coerce"),
                    "high": pd.to_numeric(raw[high_col], errors="coerce"),
                    "low": pd.to_numeric(raw[low_col], errors="coerce"),
                    "close": pd.to_numeric(raw[close_col], errors="coerce"),
                    "volume": pd.to_numeric(raw[volume_col], errors="coerce"),
                    "amount": pd.to_numeric(raw[amount_col], errors="coerce"),
                    "adj_factor": 1.0,
                    "price_adjustment": "unadjusted_placeholder_factor",
                }
            )
            rows.append(mapped)
        out = pd.concat(rows, ignore_index=True)
        validate_schema(out, "daily_bar", check_primary_key=True)
        return out

    def load_benchmark_index(self) -> pd.DataFrame:
        ak = self._akshare()
        index_code = self.index_code.split(".")[0]
        raw = pd.DataFrame()
        if hasattr(ak, "stock_zh_index_daily_em"):
            raw = self._call_with_retry(
                "stock_zh_index_daily_em", ak.stock_zh_index_daily_em, symbol=f"csi{index_code}"
            )
        if raw.empty and hasattr(ak, "stock_zh_index_daily"):
            raw = self._call_with_retry(
                "stock_zh_index_daily",
                ak.stock_zh_index_daily,
                symbol=self._sina_index_symbol(self.index_code),
            )
        if raw.empty:
            raise RuntimeError("No supported AkShare index daily endpoint is available.")
        date_col = self._first_column(raw, ("date", "日期", "trade_date"), "benchmark_index")
        close_col = self._first_column(raw, ("close", "收盘"), "benchmark_index")
        out = pd.DataFrame(
            {
                "trade_date": pd.to_datetime(raw[date_col]),
                "index_code": self.index_code if "." in self.index_code else f"{index_code}.SH",
                "close": pd.to_numeric(raw[close_col], errors="coerce"),
            }
        )
        out = out[
            (out["trade_date"] >= pd.Timestamp(self.start_date))
            & (out["trade_date"] <= pd.Timestamp(self.end_date or pd.Timestamp.today()))
        ].reset_index(drop=True)
        validate_schema(out, "benchmark_index", check_primary_key=True)
        return out

    def load_daily_basic(self) -> pd.DataFrame:
        raise RuntimeError(
            "AkShare historical daily_basic mapping is not enabled. Provide standardized local daily_basic data."
        )

    def load_index_member(self) -> pd.DataFrame:
        raise RuntimeError("Historical point-in-time index membership must be supplied as standardized local data.")

    def load_industry(self) -> pd.DataFrame:
        raise RuntimeError("Historical point-in-time industry classification must be supplied as standardized local data.")

    def load_limit_price(self) -> pd.DataFrame:
        raise RuntimeError("Historical limit-up/down prices must be supplied as standardized local data.")


class LocalDataLoader:
    def __init__(self, data_dir: str | Path = "data/sample", create_if_missing: bool = True) -> None:
        self.data_dir = Path(data_dir)
        if create_if_missing and not (self.data_dir / "daily_bar.csv").exists():
            write_sample_data(self.data_dir)

    def load_table(self, table_name: str) -> pd.DataFrame:
        csv_path = self.data_dir / f"{table_name}.csv"
        parquet_path = self.data_dir / f"{table_name}.parquet"
        if parquet_path.exists():
            df = pd.read_parquet(parquet_path)
        elif csv_path.exists():
            df = pd.read_csv(csv_path)
        else:
            raise FileNotFoundError(f"Missing table file for {table_name}: {self.data_dir}")
        df = normalize_dates(
            df,
            [
                "trade_date",
                "ann_date",
                "usable_date",
                "revision_date",
                "revision_time",
                "update_time",
                "publish_date",
                "publish_time",
                "report_period",
                "list_date",
                "delist_date",
                "in_date",
                "out_date",
                "suspend_date",
                "resume_date",
                "start_date",
                "end_date",
            ],
        )
        df = normalize_table_dates(df, table_name)
        validate_schema(df, table_name)
        return df

    def load_all(self) -> dict[str, pd.DataFrame]:
        tables: dict[str, pd.DataFrame] = {}
        for name in STANDARD_TABLES:
            if (self.data_dir / f"{name}.csv").exists() or (self.data_dir / f"{name}.parquet").exists():
                tables[name] = self.load_table(name)
        return tables
