from __future__ import annotations

import numpy as np
import pandas as pd

from ashare_factor_research.utils.helpers import require_columns


def winsorize_mad(
    df: pd.DataFrame,
    factor_col: str,
    date_col: str = "trade_date",
    n: float = 3.0,
) -> pd.DataFrame:
    require_columns(df, [date_col, factor_col], "factor_df")
    out = df.copy()

    def clip_one(s: pd.Series) -> pd.Series:
        median = s.median(skipna=True)
        mad = (s - median).abs().median(skipna=True)
        if pd.isna(mad) or mad == 0:
            return s
        lower = median - n * 1.4826 * mad
        upper = median + n * 1.4826 * mad
        return s.clip(lower, upper)

    out[factor_col] = out.groupby(date_col)[factor_col].transform(clip_one)
    return out


def _winsorize_mad_with_counts(
    df: pd.DataFrame,
    factor_col: str,
    date_col: str,
    n: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    out = df.copy()
    clipped = pd.Series(False, index=out.index)
    for _, idx in out.groupby(date_col).groups.items():
        s = out.loc[idx, factor_col]
        median = s.median(skipna=True)
        mad = (s - median).abs().median(skipna=True)
        if pd.isna(mad) or mad == 0:
            continue
        lower = median - n * 1.4826 * mad
        upper = median + n * 1.4826 * mad
        clipped_values = s.clip(lower, upper)
        changed = s.notna() & clipped_values.notna() & ~np.isclose(s.astype(float), clipped_values.astype(float))
        out.loc[idx, factor_col] = clipped_values
        clipped.loc[idx] = changed
    counts = (
        pd.DataFrame({date_col: out[date_col], "clipped_count": clipped.astype(int)})
        .groupby(date_col, as_index=False)["clipped_count"]
        .sum()
    )
    return out, counts


def zscore_by_date(df: pd.DataFrame, factor_col: str, date_col: str = "trade_date") -> pd.DataFrame:
    require_columns(df, [date_col, factor_col], "factor_df")
    out = df.copy()

    def zscore(s: pd.Series) -> pd.Series:
        std = s.std(skipna=True, ddof=0)
        if pd.isna(std) or std == 0:
            return s * np.nan
        return (s - s.mean(skipna=True)) / std

    out[factor_col] = out.groupby(date_col)[factor_col].transform(zscore)
    return out


def neutralize_factor(
    df: pd.DataFrame,
    factor_col: str,
    size_col: str,
    industry_col: str,
    date_col: str = "trade_date",
    use_size: bool = True,
    use_industry: bool = True,
) -> pd.DataFrame:
    required = [date_col, factor_col]
    if use_size:
        required.append(size_col)
    if use_industry:
        required.append(industry_col)
    require_columns(df, required, "factor_df")
    out = df.copy()
    residuals = pd.Series(np.nan, index=out.index, dtype=float)

    for _, part in out.groupby(date_col):
        cols = [factor_col]
        if use_size:
            cols.append(size_col)
        if use_industry:
            cols.append(industry_col)
        use = part[cols].dropna()
        if len(use) < 3:
            continue
        y = use[factor_col].astype(float).to_numpy()
        x_parts = [np.ones(len(use))]
        if use_size:
            size = use[size_col].astype(float)
            size_std = size.std(ddof=0)
            size_x = ((size - size.mean()) / size_std).to_numpy() if size_std else np.zeros(len(size))
            x_parts.append(size_x)
        if use_industry:
            industry_dummies = pd.get_dummies(use[industry_col], drop_first=True, dtype=float)
            if not industry_dummies.empty:
                x_parts.append(industry_dummies.to_numpy())
        x = np.column_stack(x_parts)
        try:
            beta = np.linalg.lstsq(x, y, rcond=None)[0]
        except np.linalg.LinAlgError:
            continue
        residuals.loc[use.index] = y - x @ beta

    out[factor_col] = residuals
    return out


def _validate_unique_key(df: pd.DataFrame, date_col: str, asset_col: str) -> None:
    if date_col in df and asset_col in df and df.duplicated([date_col, asset_col]).any():
        sample = df.loc[df.duplicated([date_col, asset_col], keep=False), [date_col, asset_col]].head(5)
        raise ValueError(f"factor_df has duplicate {date_col}+{asset_col} keys: {sample.to_dict('records')}")


def _summary_by_date(
    df: pd.DataFrame,
    factor_col: str,
    step: str,
    date_col: str,
    clipped_counts: pd.DataFrame | None = None,
) -> pd.DataFrame:
    summary = df.groupby(date_col)[factor_col].agg(
        non_missing="count",
        mean="mean",
        std=lambda s: s.std(ddof=0),
        min="min",
        q25=lambda s: s.quantile(0.25),
        median="median",
        q75=lambda s: s.quantile(0.75),
        max="max",
    )
    summary = summary.reset_index()
    summary["factor"] = factor_col
    summary["step"] = step
    if clipped_counts is not None:
        summary = summary.merge(clipped_counts, on=date_col, how="left")
    else:
        summary["clipped_count"] = 0
    return summary[
        [
            date_col,
            "factor",
            "step",
            "non_missing",
            "mean",
            "std",
            "min",
            "q25",
            "median",
            "q75",
            "max",
            "clipped_count",
        ]
    ]


def process_factors(
    factor_df: pd.DataFrame,
    factor_cols: list[str],
    date_col: str = "trade_date",
    asset_col: str = "ts_code",
    size_col: str | None = "size",
    industry_col: str | None = "industry_code",
    winsor_n: float = 3.0,
    neutralize: bool = True,
    neutralize_modes: dict[str, str] | None = None,
    return_audit: bool = False,
) -> pd.DataFrame | tuple[pd.DataFrame, pd.DataFrame]:
    _validate_unique_key(factor_df, date_col, asset_col)
    out = factor_df.copy()
    audit_rows: list[pd.DataFrame] = []
    for col in factor_cols:
        if col not in out:
            continue
        audit_rows.append(_summary_by_date(out, col, "raw", date_col))
        out, clipped_counts = _winsorize_mad_with_counts(out, col, date_col=date_col, n=winsor_n)
        audit_rows.append(_summary_by_date(out, col, "winsorized", date_col, clipped_counts))
        neutralize_mode = (neutralize_modes or {}).get(col, "industry_size")
        use_size = neutralize_mode in {"size", "industry_size"}
        use_industry = neutralize_mode in {"industry", "industry_size"}
        if (
            neutralize
            and size_col
            and industry_col
            and col != size_col
            and size_col in out
            and industry_col in out
            and neutralize_mode != "none"
        ):
            out = neutralize_factor(
                out,
                col,
                size_col=size_col,
                industry_col=industry_col,
                date_col=date_col,
                use_size=use_size,
                use_industry=use_industry,
            )
            audit_rows.append(_summary_by_date(out, col, "neutralized", date_col))
        out = zscore_by_date(out, col, date_col=date_col)
        audit_rows.append(_summary_by_date(out, col, "standardized", date_col))
    _validate_unique_key(out, date_col, asset_col)
    if return_audit:
        audit = pd.concat(audit_rows, ignore_index=True) if audit_rows else pd.DataFrame()
        return out, audit
    return out


def factor_correlation(
    factor_df: pd.DataFrame,
    factor_cols: list[str],
    method: str = "spearman",
) -> pd.DataFrame:
    if method == "spearman":
        return factor_df[factor_cols].rank().corr(method="pearson")
    return factor_df[factor_cols].corr(method=method)
