from __future__ import annotations

import pandas as pd

from ashare_factor_research.factor_testing.ic_test import calc_ic


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
        rows.append({"horizon": horizon, "mean_rank_ic": ic.mean(), "count": ic.count()})
    return pd.DataFrame(rows)
