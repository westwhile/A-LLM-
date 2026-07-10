from __future__ import annotations

import pandas as pd

from ashare_factor_research.utils.helpers import require_columns


def build_portfolio(
    score_df: pd.DataFrame,
    score_col: str = "score",
    date_col: str = "trade_date",
    top_n: int = 50,
    max_weight: float = 0.05,
    min_holding_count: int | None = None,
    industry_col: str | None = None,
    max_industry_weight: float | None = None,
) -> pd.DataFrame:
    require_columns(score_df, [date_col, "ts_code", score_col], "score_df")
    rows = []
    for date, part in score_df.dropna(subset=[score_col]).groupby(date_col):
        selected = part.sort_values(score_col, ascending=False).head(top_n).copy()
        n = len(selected)
        if n == 0:
            continue
        if min_holding_count is not None and n < min_holding_count:
            raise ValueError(f"Only {n} eligible holdings on {date}; minimum is {min_holding_count}.")
        if n * max_weight < 1 - 1e-12:
            raise ValueError(
                f"Cannot build fully invested portfolio on {date}: "
                f"{n} names with max_weight={max_weight}."
            )
        selected["target_weight"] = min(1.0 / n, max_weight)
        selected["target_weight"] = selected["target_weight"] / selected["target_weight"].sum()
        if industry_col and max_industry_weight is not None:
            if industry_col not in selected:
                raise ValueError(f"industry_col {industry_col!r} is missing from score_df")
            selected = _apply_industry_cap(selected, industry_col, max_industry_weight, max_weight)
        keep = [date_col, "ts_code", "target_weight", score_col]
        if industry_col:
            keep.append(industry_col)
        rows.append(selected[keep])
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(
        columns=[date_col, "ts_code", "target_weight", score_col]
    )


def _apply_industry_cap(
    selected: pd.DataFrame,
    industry_col: str,
    max_industry_weight: float,
    max_weight: float,
) -> pd.DataFrame:
    if not 0 < max_industry_weight <= 1:
        raise ValueError("max_industry_weight must be in (0, 1]")
    out = selected.copy()
    for _ in range(100):
        totals = out.groupby(industry_col, dropna=False)["target_weight"].sum()
        excess_groups = totals[totals > max_industry_weight + 1e-12]
        if excess_groups.empty:
            break
        freed = 0.0
        for group, total in excess_groups.items():
            mask = out[industry_col].eq(group) if pd.notna(group) else out[industry_col].isna()
            scale = max_industry_weight / float(total)
            old = out.loc[mask, "target_weight"].sum()
            out.loc[mask, "target_weight"] *= scale
            freed += float(old - out.loc[mask, "target_weight"].sum())
        eligible = out.groupby(industry_col, dropna=False)["target_weight"].transform("sum") < max_industry_weight - 1e-12
        eligible &= out["target_weight"] < max_weight - 1e-12
        if not eligible.any():
            raise ValueError("Industry and single-name caps are infeasible for selected holdings.")
        room = (max_weight - out.loc[eligible, "target_weight"]).clip(lower=0)
        allocation = freed * room / room.sum()
        out.loc[eligible, "target_weight"] += allocation.clip(upper=room)
    if abs(float(out["target_weight"].sum()) - 1.0) > 1e-8:
        raise ValueError("Unable to construct fully invested portfolio under industry caps.")
    return out
