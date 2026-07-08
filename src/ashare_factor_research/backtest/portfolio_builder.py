from __future__ import annotations

import pandas as pd

from ashare_factor_research.utils.helpers import require_columns


def build_portfolio(
    score_df: pd.DataFrame,
    score_col: str = "score",
    date_col: str = "trade_date",
    top_n: int = 50,
    max_weight: float = 0.05,
) -> pd.DataFrame:
    require_columns(score_df, [date_col, "ts_code", score_col], "score_df")
    rows = []
    for date, part in score_df.dropna(subset=[score_col]).groupby(date_col):
        selected = part.sort_values(score_col, ascending=False).head(top_n).copy()
        n = len(selected)
        if n == 0:
            continue
        if n * max_weight < 1 - 1e-12:
            raise ValueError(
                f"Cannot build fully invested portfolio on {date}: "
                f"{n} names with max_weight={max_weight}."
            )
        selected["target_weight"] = min(1.0 / n, max_weight)
        selected["target_weight"] = selected["target_weight"] / selected["target_weight"].sum()
        rows.append(selected[[date_col, "ts_code", "target_weight", score_col]])
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(
        columns=[date_col, "ts_code", "target_weight", score_col]
    )
