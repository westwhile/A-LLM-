from __future__ import annotations

from pathlib import Path

import pandas as pd


def select_factors(
    ic_summary: pd.DataFrame,
    factor_corr: pd.DataFrame | None = None,
    min_abs_ic: float = 0.01,
    min_abs_icir: float = 0.05,
    max_corr: float = 0.85,
) -> pd.DataFrame:
    """Create an auditable factor selection table from in-sample diagnostics."""

    rows: list[dict[str, object]] = []
    selected: list[str] = []
    for factor, row in ic_summary.sort_values("mean", key=lambda s: s.abs(), ascending=False).iterrows():
        mean_ic = float(row.get("mean", float("nan")))
        icir = float(row.get("icir", float("nan")))
        reasons: list[str] = []
        keep = True
        if pd.isna(mean_ic) or abs(mean_ic) < min_abs_ic:
            keep = False
            reasons.append(f"abs IC below {min_abs_ic:g}")
        else:
            reasons.append("direction is positive" if mean_ic > 0 else "direction is negative")
        if pd.isna(icir) or abs(icir) < min_abs_icir:
            keep = False
            reasons.append(f"abs ICIR below {min_abs_icir:g}")
        if keep and factor_corr is not None and selected and factor in factor_corr.index:
            overlaps = factor_corr.loc[factor, [x for x in selected if x in factor_corr.columns]].abs()
            if not overlaps.empty and overlaps.max() > max_corr:
                keep = False
                reasons.append(f"correlation conflict with {overlaps.idxmax()} ({overlaps.max():.2f})")
        if keep:
            selected.append(str(factor))
            reasons.append("selected for next-stage research")
        rows.append(
            {
                "factor": factor,
                "direction": 1 if mean_ic > 0 else -1 if mean_ic < 0 else 0,
                "mean_ic": mean_ic,
                "icir": icir,
                "selected": keep,
                "reason": "; ".join(reasons),
            }
        )
    return pd.DataFrame(rows)


def write_selected_factors_report(selection: pd.DataFrame, output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Selected Factors",
        "",
        "This report is based on the current in-sample factor diagnostics. It is an input",
        "to walk-forward research, not proof of live tradability or out-of-sample alpha.",
        "",
        "| factor | selected | direction | mean_ic | icir | reason |",
        "| --- | --- | --- | ---: | ---: | --- |",
    ]
    if selection.empty:
        lines.append("| NA | false | 0 | nan | nan | no candidate factors |")
    else:
        for _, row in selection.iterrows():
            lines.append(
                "| {factor} | {selected} | {direction} | {mean_ic:.6f} | {icir:.6f} | {reason} |".format(
                    factor=row["factor"],
                    selected=str(bool(row["selected"])).lower(),
                    direction=int(row["direction"]),
                    mean_ic=float(row["mean_ic"]),
                    icir=float(row["icir"]),
                    reason=str(row["reason"]).replace("|", "/"),
                )
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
