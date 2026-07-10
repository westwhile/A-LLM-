from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

from ashare_factor_research.analysis.drawdown import drawdown_periods, drawdown_series
from ashare_factor_research.analysis.performance import monthly_return_matrix, yearly_performance


def save_placeholder_tables(output_dir: str | Path, metrics: dict[str, float], ic_table: pd.DataFrame) -> None:
    """Save text/CSV artifacts when plotting dependencies are unavailable."""

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    pd.Series(metrics).to_csv(out / "performance_metrics.csv", header=["value"])
    ic_table.to_csv(out / "ic_summary.csv")


def save_performance_report_tables(
    output_dir: str | Path,
    nav_df: pd.DataFrame,
    metrics: dict[str, float],
    trades: pd.DataFrame | None = None,
    cost_summary: pd.DataFrame | None = None,
) -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    pd.Series(metrics).to_csv(out / "performance_metrics.csv", header=["value"])
    yearly_performance(nav_df).to_csv(out / "yearly_performance.csv", index=False)
    returns = nav_df.assign(trade_date=pd.to_datetime(nav_df["trade_date"])).set_index("trade_date")["net_return"]
    monthly_return_matrix(returns).to_csv(out / "monthly_returns.csv")
    nav_series = nav_df.assign(trade_date=pd.to_datetime(nav_df["trade_date"])).set_index("trade_date")["nav"]
    drawdown_periods(nav_series).to_csv(out / "drawdown_periods.csv", index=False)
    if trades is not None:
        trades.to_csv(out / "sample_trades.csv", index=False)
    if cost_summary is not None:
        cost_summary.to_csv(out / "cost_attribution.csv", index=False)


def _font(size: int = 16) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("arial.ttf", size=size)
    except OSError:
        return ImageFont.load_default()


def _clean_series(values: pd.Series) -> pd.Series:
    return pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()


def _save_line_chart(values: pd.Series, title: str, path: Path) -> None:
    width, height, margin = 960, 540, 70
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw.text((margin, 20), title, fill="#111111", font=_font(22))
    draw.line([(margin, margin), (margin, height - margin)], fill="#333333", width=2)
    draw.line([(margin, height - margin), (width - margin, height - margin)], fill="#333333", width=2)
    y = _clean_series(values)
    if not y.empty:
        min_y = float(y.min())
        max_y = float(y.max())
        if abs(max_y - min_y) < 1e-12:
            min_y -= 1.0
            max_y += 1.0
        denom_x = max(len(y) - 1, 1)
        points = [
            (
                margin + idx / denom_x * (width - 2 * margin),
                height - margin - (float(value) - min_y) / (max_y - min_y) * (height - 2 * margin),
            )
            for idx, value in enumerate(y)
        ]
        if len(points) >= 2:
            draw.line(points, fill="#1f77b4", width=3)
        elif points:
            x, py = points[0]
            draw.ellipse((x - 3, py - 3, x + 3, py + 3), fill="#1f77b4")
        draw.text((width - margin - 190, margin - 25), f"min={y.min():.4f} max={y.max():.4f}", fill="#555555", font=_font(13))
        draw.text((margin, height - margin + 16), f"n={len(y)}", fill="#555555", font=_font(13))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def _save_bar_chart(values: pd.Series, title: str, path: Path) -> None:
    y = _clean_series(values)
    width, height, margin = 960, 540, 80
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw.text((margin, 20), title, fill="#111111", font=_font(22))
    draw.line([(margin, margin), (margin, height - margin)], fill="#333333", width=2)
    draw.line([(margin, height - margin), (width - margin, height - margin)], fill="#333333", width=2)
    if not y.empty:
        max_abs = max(float(y.abs().max()), 1e-12)
        zero_y = height - margin - (0.0 + max_abs) / (2 * max_abs) * (height - 2 * margin)
        draw.line([(margin, zero_y), (width - margin, zero_y)], fill="#999999", width=1)
        bar_w = max(8, int((width - 2 * margin) / len(y) * 0.65))
        for idx, (label, value) in enumerate(y.items()):
            x = margin + idx / max(len(y), 1) * (width - 2 * margin) + bar_w * 0.25
            y_pos = height - margin - (float(value) + max_abs) / (2 * max_abs) * (height - 2 * margin)
            color = "#2ca02c" if value >= 0 else "#d62728"
            draw.rectangle((x, min(y_pos, zero_y), x + bar_w, max(y_pos, zero_y)), fill=color)
            if len(y) <= 14:
                draw.text((x, height - margin + 14), str(label), fill="#555555", font=_font(11))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def _save_heatmap(frame: pd.DataFrame, title: str, path: Path) -> None:
    numeric = frame.apply(pd.to_numeric, errors="coerce")
    width, height = 960, 540
    left, top, cell_w, cell_h = 130, 80, 62, 32
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw.text((left, 25), title, fill="#111111", font=_font(22))
    max_abs = float(numeric.abs().max().max()) if not numeric.empty else 1.0
    max_abs = max(max_abs, 1e-12)
    for r_idx, (idx, row) in enumerate(numeric.iterrows()):
        y = top + r_idx * cell_h
        if y + cell_h > height - 30:
            break
        draw.text((20, y + 8), str(idx), fill="#333333", font=_font(12))
        for c_idx, col in enumerate(numeric.columns):
            x = left + c_idx * cell_w
            if x + cell_w > width - 20:
                break
            value = row[col]
            if not np.isfinite(value):
                color = "#eeeeee"
            else:
                intensity = min(abs(float(value)) / max_abs, 1.0)
                base = 255 - int(150 * intensity)
                color = f"#{base:02x}ff{base:02x}" if value >= 0 else f"#ff{base:02x}{base:02x}"
            draw.rectangle((x, y, x + cell_w - 2, y + cell_h - 2), fill=color)
            if r_idx == 0:
                draw.text((x, top - 20), str(col), fill="#333333", font=_font(10))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def save_report_artifacts(
    output_dir: str | Path,
    metrics: dict[str, float],
    ic_table: pd.DataFrame,
    group_returns: pd.DataFrame,
    corr: pd.DataFrame,
    nav_df: pd.DataFrame,
    trades: pd.DataFrame,
    industry_exposure: pd.DataFrame | None = None,
    score_ic_series: pd.Series | None = None,
    cost_summary: pd.DataFrame | None = None,
    benchmark_return: pd.Series | None = None,
) -> None:
    """Save report-ready CSV and PNG artifacts without requiring matplotlib."""

    out = Path(output_dir)
    save_performance_report_tables(out, nav_df, metrics, trades=trades, cost_summary=cost_summary)
    ic_table.to_csv(out / "ic_summary.csv")
    group_returns.to_csv(out / "group_returns.csv")
    corr.to_csv(out / "factor_corr.csv")

    nav = nav_df.copy()
    nav["trade_date"] = pd.to_datetime(nav["trade_date"])
    returns = nav.set_index("trade_date")["net_return"].astype(float).sort_index()
    nav_series = nav.set_index("trade_date")["nav"].astype(float).sort_index()

    nav[["trade_date", "nav"]].to_csv(out / "cumulative_return.csv", index=False)
    _save_line_chart(nav_series, "Sample cumulative NAV", out / "cumulative_return.png")

    dd = drawdown_series(nav_series).rename("drawdown")
    dd.to_csv(out / "drawdown.csv", header=True)
    _save_line_chart(dd, "Sample drawdown", out / "drawdown.png")

    if benchmark_return is not None:
        benchmark = benchmark_return.reindex(returns.index)
        if benchmark.isna().any():
            raise ValueError("benchmark_return dates must match strategy return dates before plotting excess return")
        benchmark_label = "benchmark"
    else:
        benchmark = pd.Series(0.0, index=returns.index, name="benchmark_return")
        benchmark_label = "cash"
    excess = pd.DataFrame({"strategy_return": returns, "benchmark_return": benchmark.astype(float)})
    excess["excess_return"] = excess["strategy_return"] - excess["benchmark_return"]
    excess["cumulative_excess"] = (1.0 + excess["excess_return"]).cumprod() - 1.0
    excess.to_csv(out / "excess_return.csv")
    _save_line_chart(excess["cumulative_excess"], f"Sample cumulative excess vs {benchmark_label}", out / "excess_return.png")

    yearly = yearly_performance(nav)
    yearly.to_csv(out / "yearly_return.csv", index=False)
    if not yearly.empty and "return" in yearly:
        _save_bar_chart(yearly.set_index("year")["return"], "Sample yearly return", out / "yearly_return.png")
    else:
        _save_bar_chart(pd.Series(dtype=float), "Sample yearly return", out / "yearly_return.png")

    monthly = monthly_return_matrix(returns).reindex(columns=range(1, 13))
    monthly.to_csv(out / "monthly_return_heatmap.csv")
    _save_heatmap(monthly, "Sample monthly return heatmap", out / "monthly_return_heatmap.png")

    if score_ic_series is not None:
        score_ic = _clean_series(score_ic_series)
        score_ic.to_csv(out / "ic_series.csv", header=["score_rank_ic"])
        _save_line_chart(score_ic, "Sample score Rank IC series", out / "ic_series.png")
    elif "mean" in ic_table:
        _save_bar_chart(ic_table["mean"], "Sample factor mean Rank IC", out / "ic_series.png")

    if "Q5-Q1" in group_returns:
        group_curve = (1.0 + group_returns["Q5-Q1"].fillna(0.0)).cumprod() - 1.0
    else:
        group_curve = group_returns.select_dtypes("number").mean(axis=1).fillna(0.0).cumsum()
    group_curve.to_csv(out / "group_return.csv", header=["long_short_cumulative"])
    _save_line_chart(group_curve, "Sample grouped long-short return", out / "group_return.png")

    _save_heatmap(corr.round(3), "Sample factor correlation", out / "factor_corr_heatmap.png")

    turnover = nav[["trade_date", "turnover"]].copy() if "turnover" in nav else pd.DataFrame(columns=["trade_date", "turnover"])
    turnover.to_csv(out / "turnover.csv", index=False)
    if not turnover.empty:
        _save_line_chart(turnover.set_index("trade_date")["turnover"], "Sample portfolio turnover", out / "turnover.png")
    else:
        _save_line_chart(pd.Series(dtype=float), "Sample portfolio turnover", out / "turnover.png")

    if industry_exposure is not None and not industry_exposure.empty:
        industry_exposure.to_csv(out / "industry_exposure.csv", index=False)
        latest_date = industry_exposure["trade_date"].max()
        latest = industry_exposure[industry_exposure["trade_date"] == latest_date].set_index("industry_code")["target_weight"]
        _save_bar_chart(latest, "Sample latest industry exposure", out / "industry_exposure.png")
    else:
        pd.DataFrame(columns=["trade_date", "industry_code", "target_weight"]).to_csv(
            out / "industry_exposure.csv", index=False
        )
        _save_bar_chart(pd.Series(dtype=float), "Sample latest industry exposure", out / "industry_exposure.png")


def save_research_extension_charts(
    output_dir: str | Path,
    factor_decay: pd.DataFrame | None = None,
    robustness: pd.DataFrame | None = None,
) -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    if factor_decay is not None and not factor_decay.empty and {"horizon", "mean_ic"}.issubset(factor_decay.columns):
        values = factor_decay.groupby("horizon")["mean_ic"].mean().sort_index()
        _save_line_chart(values, "Mean factor IC decay by horizon", out / "factor_decay.png")
    else:
        _save_line_chart(pd.Series(dtype=float), "Mean factor IC decay by horizon", out / "factor_decay.png")
    if robustness is not None and not robustness.empty:
        costs = robustness.groupby("cost_case")["total_return"].mean()
        _save_bar_chart(costs, "Average total return by cost scenario", out / "cost_scenarios.png")
        capacity = robustness.dropna(subset=["participation_rate"]).groupby("participation_rate")["total_return"].mean()
        _save_line_chart(capacity, "Average total return by participation cap", out / "capacity_scenarios.png")
