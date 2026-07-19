from __future__ import annotations

from math import erfc, sqrt

import numpy as np
import pandas as pd

from ashare_factor_research.factor_testing.ic_test import calc_ic


def newey_west_mean_test(values: pd.Series, max_lag: int) -> dict[str, float]:
    clean = pd.Series(values, dtype=float).replace([np.inf, -np.inf], np.nan).dropna().to_numpy()
    n = len(clean)
    if n < 2:
        return {"mean": float(clean.mean()) if n else np.nan, "naive_t": np.nan, "hac_se": np.nan, "hac_t": np.nan, "p_value": np.nan, "count": float(n)}
    demeaned = clean - clean.mean()
    naive_se = clean.std(ddof=1) / np.sqrt(n)
    long_run_variance = float(np.dot(demeaned, demeaned) / n)
    lag = min(max(int(max_lag), 0), n - 1)
    for step in range(1, lag + 1):
        covariance = float(np.dot(demeaned[step:], demeaned[:-step]) / n)
        long_run_variance += 2.0 * (1.0 - step / (lag + 1.0)) * covariance
    long_run_variance = max(long_run_variance, 0.0)
    hac_se = np.sqrt(long_run_variance / n)
    hac_t = float(clean.mean() / hac_se) if hac_se > 0 else np.nan
    p_value = float(erfc(abs(hac_t) / sqrt(2.0))) if np.isfinite(hac_t) else np.nan
    return {
        "mean": float(clean.mean()),
        "naive_t": float(clean.mean() / naive_se) if naive_se > 0 else np.nan,
        "hac_se": float(hac_se),
        "hac_t": hac_t,
        "p_value": p_value,
        "count": float(n),
    }


def benjamini_hochberg(p_values: pd.Series) -> pd.Series:
    values = pd.to_numeric(p_values, errors="coerce")
    valid = values.dropna().sort_values()
    if valid.empty:
        return pd.Series(np.nan, index=values.index, dtype=float)
    m = len(valid)
    adjusted = valid * m / np.arange(1, m + 1)
    adjusted = adjusted.iloc[::-1].cummin().iloc[::-1].clip(upper=1.0)
    result = pd.Series(np.nan, index=values.index, dtype=float)
    result.loc[adjusted.index] = adjusted
    return result


def build_factor_inference(
    factor_df: pd.DataFrame,
    factor_cols: list[str],
    return_col: str,
    *,
    hac_lags: int,
    variant: str,
) -> pd.DataFrame:
    rows = []
    for factor in factor_cols:
        ic = calc_ic(factor_df, factor, return_col=return_col, method="spearman")
        row = newey_west_mean_test(ic, hac_lags)
        row.update({"factor": factor, "variant": variant, "hac_lags": int(hac_lags)})
        rows.append(row)
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    result["fdr_q_value"] = benjamini_hochberg(result["p_value"])
    result["fdr_5pct"] = result["fdr_q_value"].le(0.05)
    return result[["variant", "factor", "mean", "naive_t", "hac_se", "hac_t", "p_value", "fdr_q_value", "fdr_5pct", "count", "hac_lags"]]
