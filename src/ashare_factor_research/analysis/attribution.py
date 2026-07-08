from __future__ import annotations

import pandas as pd


def industry_exposure(weights: pd.DataFrame, industry: pd.DataFrame) -> pd.DataFrame:
    if weights.empty:
        return pd.DataFrame(columns=["trade_date", "industry_code", "target_weight"])
    merged = weights.merge(industry, on=["trade_date", "ts_code"], how="left")
    return (
        merged.groupby(["trade_date", "industry_code"], as_index=False)["target_weight"]
        .sum()
        .sort_values(["trade_date", "industry_code"])
    )
