from __future__ import annotations

import pandas as pd

from ashare_factor_research.factor_testing.ic_test import calc_ic
from ashare_factor_research.factor_testing.ic_test import summarize_ic


def calc_ic_decay(
    factor_df: pd.DataFrame,
    factor_col: str,
    horizons: list[int],
    date_col: str = "trade_date",
) -> pd.DataFrame:
    rows = []
    for horizon in horizons:
        return_col = f"future_return_{horizon}"
        if return_col not in factor_df:
            continue
        ic = calc_ic(factor_df, factor_col, return_col, date_col=date_col, method="spearman")
        summary = summarize_ic(ic)
        rows.append(
            {
                "factor": factor_col,
                "horizon": horizon,
                "mean_rank_ic": summary["mean"],
                "rank_icir": summary["icir"],
                "hit_rate": summary["hit_rate"],
                "t_stat": summary["t_stat"],
                "count": summary["count"],
            }
        )
    return pd.DataFrame(rows)


def calc_factor_decay_table(
    factor_df: pd.DataFrame,
    factor_cols: list[str],
    horizons: list[int],
    date_col: str = "trade_date",
) -> pd.DataFrame:
    rows = [calc_ic_decay(factor_df, factor_col, horizons, date_col=date_col) for factor_col in factor_cols]
    rows = [df for df in rows if not df.empty]
    if not rows:
        return pd.DataFrame(columns=["factor", "horizon", "mean_rank_ic", "rank_icir", "hit_rate", "t_stat", "count"])
    return pd.concat(rows, ignore_index=True)
