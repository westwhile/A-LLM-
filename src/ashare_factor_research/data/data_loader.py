from __future__ import annotations

from pathlib import Path
from typing import Protocol

import pandas as pd

from ashare_factor_research.data.sample_data import write_sample_data
from ashare_factor_research.data.schema import normalize_dates, validate_schema


class MarketDataProvider(Protocol):
    def load_daily_bar(self) -> pd.DataFrame: ...

    def load_daily_basic(self) -> pd.DataFrame: ...


class AkShareProvider:
    """AkShare provider placeholder.

    Real collection should map AkShare output columns into this project's schema.
    It is intentionally not called by the sample pipeline to keep tests offline.
    """

    def __init__(self, start_date: str, end_date: str | None = None) -> None:
        self.start_date = start_date
        self.end_date = end_date

    def _akshare(self):
        try:
            import akshare as ak  # type: ignore
        except ImportError as exc:
            raise RuntimeError("AkShare is not installed. Install optional dependency akshare.") from exc
        return ak

    def load_daily_bar(self) -> pd.DataFrame:
        raise NotImplementedError(
            "TODO: implement AkShare daily bar collection and schema normalization."
        )

    def load_daily_basic(self) -> pd.DataFrame:
        raise NotImplementedError(
            "TODO: implement AkShare valuation/basic data collection and schema normalization."
        )


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
        df = normalize_dates(df, ["trade_date", "ann_date", "usable_date", "publish_date", "report_period"])
        validate_schema(df, table_name)
        return df

    def load_all(self) -> dict[str, pd.DataFrame]:
        return {
            name: self.load_table(name)
            for name in [
                "daily_bar",
                "daily_basic",
                "industry",
                "financial_indicator",
                "news_event",
            ]
        }
