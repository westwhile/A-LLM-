from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ashare_factor_research.utils.io import ensure_dir


def generate_sample_bundle(
    n_stocks: int = 60,
    n_days: int = 180,
    seed: int = 42,
) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2022-01-03", periods=n_days)
    stocks = [f"{i:06d}.SZ" for i in range(1, n_stocks + 1)]
    industries = ["bank", "tech", "health", "energy", "consumer", "industrial"]
    rows: list[dict[str, object]] = []
    basic_rows: list[dict[str, object]] = []
    industry_rows: list[dict[str, object]] = []

    stock_quality = rng.normal(0, 1, n_stocks)
    stock_size = rng.lognormal(mean=9.0, sigma=0.35, size=n_stocks)
    prices = rng.uniform(8, 40, n_stocks)

    for d_idx, date in enumerate(dates):
        market_ret = rng.normal(0.0002, 0.012)
        for s_idx, code in enumerate(stocks):
            alpha = 0.0004 * stock_quality[s_idx]
            ret = market_ret + alpha + rng.normal(0, 0.018)
            prev_close = prices[s_idx]
            close = max(1.0, prev_close * (1 + ret))
            open_price = max(1.0, prev_close * (1 + rng.normal(0, 0.006)))
            high = max(open_price, close) * (1 + rng.uniform(0, 0.015))
            low = min(open_price, close) * (1 - rng.uniform(0, 0.015))
            volume = rng.integers(500_000, 8_000_000)
            amount = float(volume * close)
            adj_factor = 1.0 + 0.00003 * d_idx
            prices[s_idx] = close

            rows.append(
                {
                    "trade_date": date,
                    "ts_code": code,
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                    "amount": amount,
                    "adj_factor": adj_factor,
                    "is_suspended": False,
                    "is_st": False,
                    "up_limit": prev_close * 1.1,
                    "down_limit": prev_close * 0.9,
                }
            )

            total_mv = stock_size[s_idx] * close * 10_000
            pe = max(3.0, 18 - 1.5 * stock_quality[s_idx] + rng.normal(0, 2))
            pb = max(0.4, 1.8 - 0.15 * stock_quality[s_idx] + rng.normal(0, 0.2))
            turnover = float(rng.uniform(0.2, 4.5))
            basic_rows.append(
                {
                    "trade_date": date,
                    "ts_code": code,
                    "pe_ttm": pe,
                    "pb": pb,
                    "total_mv": total_mv,
                    "turnover_rate": turnover,
                    "net_mf_amount": rng.normal(0, 1_000_000) + 50_000 * stock_quality[s_idx],
                }
            )
            ind = industries[s_idx % len(industries)]
            industry_rows.append(
                {
                    "trade_date": date,
                    "ts_code": code,
                    "industry_code": ind.upper(),
                    "industry_name": ind,
                }
            )

    financial_rows = []
    report_dates = pd.to_datetime(["2021-12-31", "2022-03-31", "2022-06-30"])
    ann_dates = pd.to_datetime(["2022-04-20", "2022-04-28", "2022-08-25"])
    for s_idx, code in enumerate(stocks):
        for report_date, ann_date in zip(report_dates, ann_dates):
            financial_rows.append(
                {
                    "report_period": report_date,
                    "ann_date": ann_date,
                    "usable_date": ann_date + pd.offsets.BDay(1),
                    "ts_code": code,
                    "roe": 0.08 + 0.025 * stock_quality[s_idx] + rng.normal(0, 0.01),
                    "gross_margin": 0.25 + 0.03 * stock_quality[s_idx] + rng.normal(0, 0.02),
                    "debt_ratio": 0.45 - 0.03 * stock_quality[s_idx] + rng.normal(0, 0.04),
                    "revenue_yoy": 0.08 + 0.04 * stock_quality[s_idx] + rng.normal(0, 0.04),
                    "profit_yoy": 0.06 + 0.05 * stock_quality[s_idx] + rng.normal(0, 0.06),
                }
            )

    news_rows = []
    for s_idx, code in enumerate(stocks[:20]):
        sentiment = "positive" if stock_quality[s_idx] > 0 else "negative"
        news_rows.append(
            {
                "stock_code": code,
                "publish_date": dates[min(60 + s_idx, len(dates) - 1)],
                "event_type": "业绩增长" if sentiment == "positive" else "业绩下滑",
                "sentiment": sentiment,
                "impact_horizon": "medium",
                "confidence": 0.65 + 0.2 * rng.random(),
                "reason": "Synthetic event for pipeline validation.",
            }
        )

    return {
        "daily_bar": pd.DataFrame(rows),
        "daily_basic": pd.DataFrame(basic_rows),
        "industry": pd.DataFrame(industry_rows),
        "financial_indicator": pd.DataFrame(financial_rows),
        "news_event": pd.DataFrame(news_rows),
    }


def write_sample_data(output_dir: str | Path = "data/sample") -> dict[str, Path]:
    out_dir = ensure_dir(output_dir)
    bundle = generate_sample_bundle()
    paths: dict[str, Path] = {}
    for name, df in bundle.items():
        path = out_dir / f"{name}.csv"
        df.to_csv(path, index=False, encoding="utf-8")
        paths[name] = path
    return paths
