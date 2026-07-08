from __future__ import annotations

import numpy as np
import pandas as pd


def safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    out = numerator.astype(float) / denominator.replace(0, np.nan).astype(float)
    return out.replace([np.inf, -np.inf], np.nan)


def require_columns(df: pd.DataFrame, columns: list[str], name: str = "DataFrame") -> None:
    missing = sorted(set(columns) - set(df.columns))
    if missing:
        raise ValueError(f"{name} missing required columns: {missing}")
