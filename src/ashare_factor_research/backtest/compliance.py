from __future__ import annotations

import pandas as pd


def audit_execution_compliance(
    portfolio: pd.DataFrame,
    nav: pd.DataFrame,
    positions: pd.DataFrame,
    *,
    orders: pd.DataFrame | None = None,
    market: pd.DataFrame | None = None,
    min_holding_count: int,
    max_weight: float,
    max_industry_weight: float,
    max_cash_weight: float,
    max_turnover: float,
    max_participation_rate: float | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    nav_data = nav.copy()
    nav_data["trade_date"] = pd.to_datetime(nav_data["trade_date"])
    first_invested = nav_data.loc[nav_data["holding_count"].gt(0), "trade_date"].min()
    position_max = positions.groupby("mark_date")["weight"].max() if not positions.empty else pd.Series(dtype=float)
    for row in nav_data.itertuples(index=False):
        date = pd.Timestamp(row.trade_date)
        invested = pd.notna(first_invested) and date >= first_invested
        checks = {
            "holding_count": (float(row.holding_count), float(min_holding_count), bool(not invested or row.holding_count >= min_holding_count)),
            "single_name_weight": (float(position_max.get(date, 0.0)), float(max_weight), bool(position_max.get(date, 0.0) <= max_weight + 1e-9)),
            "cash_weight": (float(row.cash_weight), float(max_cash_weight), bool(not invested or row.cash_weight <= max_cash_weight + 1e-9)),
            "turnover": (float(row.turnover), float(max_turnover), bool(row.turnover <= max_turnover + 1e-9)),
        }
        for check, (value, limit, passed) in checks.items():
            rows.append({"trade_date": date, "check": check, "value": value, "limit": limit, "passed": passed, "invested": invested})

    if not portfolio.empty and "industry_code" in portfolio:
        industry = portfolio.groupby(["trade_date", "industry_code"], dropna=False)["target_weight"].sum()
        for (date, code), value in industry.items():
            rows.append({
                "trade_date": pd.Timestamp(date),
                "check": "target_industry_weight",
                "dimension": str(code),
                "value": float(value),
                "limit": float(max_industry_weight),
                "passed": bool(value <= max_industry_weight + 1e-9),
                "invested": True,
            })
        if not positions.empty:
            industry_history = portfolio[["trade_date", "ts_code", "industry_code"]].copy()
            industry_history["trade_date"] = pd.to_datetime(industry_history["trade_date"])
            position_industry = positions.copy()
            position_industry["mark_date"] = pd.to_datetime(position_industry["mark_date"])
            parts = []
            for code, part in position_industry.groupby("ts_code"):
                history = industry_history[industry_history["ts_code"].eq(code)].sort_values("trade_date")
                if history.empty:
                    continue
                parts.append(pd.merge_asof(part.sort_values("mark_date"), history[["trade_date", "industry_code"]], left_on="mark_date", right_on="trade_date", direction="backward"))
            if parts:
                actual = pd.concat(parts, ignore_index=True).dropna(subset=["industry_code"])
                actual_industry = actual.groupby(["mark_date", "industry_code"], dropna=False)["weight"].sum()
                for (date, code), value in actual_industry.items():
                    rows.append({
                        "trade_date": pd.Timestamp(date), "check": "actual_industry_weight", "dimension": str(code),
                        "value": float(value), "limit": float(max_industry_weight),
                        "passed": bool(value <= max_industry_weight + 1e-9), "invested": True,
                    })

    if max_participation_rate is not None and orders is not None and market is not None and not orders.empty:
        order_values = orders[["execution_date", "ts_code", "filled_value"]].copy()
        order_values["execution_date"] = pd.to_datetime(order_values["execution_date"])
        daily_amount = market[["trade_date", "ts_code", "amount"]].copy()
        daily_amount["trade_date"] = pd.to_datetime(daily_amount["trade_date"])
        participation = order_values.merge(
            daily_amount, left_on=["execution_date", "ts_code"], right_on=["trade_date", "ts_code"], how="left"
        )
        participation["participation_rate"] = participation["filled_value"] / participation["amount"].replace(0, pd.NA)
        for item in participation.dropna(subset=["participation_rate"]).itertuples(index=False):
            value = float(item.participation_rate)
            rows.append({
                "trade_date": pd.Timestamp(item.execution_date), "check": "participation_rate", "dimension": str(item.ts_code),
                "value": value, "limit": float(max_participation_rate),
                "passed": bool(value <= max_participation_rate + 1e-9), "invested": True,
            })
    result = pd.DataFrame(rows)
    if not result.empty:
        result["violation_reason"] = result.apply(
            lambda item: "" if bool(item["passed"]) else f"{item['check']}: value={item['value']:.8g}, limit={item['limit']:.8g}",
            axis=1,
        )
    return result


def summarize_execution_compliance(compliance: pd.DataFrame) -> pd.DataFrame:
    if compliance.empty:
        return pd.DataFrame(columns=["check", "observations", "violations", "max_value", "limit"])
    relevant = compliance[
        compliance["invested"].astype(bool) | ~compliance["check"].isin(["holding_count", "cash_weight"])
    ]
    return (
        relevant.groupby("check", as_index=False)
        .agg(
            observations=("passed", "size"),
            violations=("passed", lambda s: int((~s.astype(bool)).sum())),
            max_value=("value", "max"),
            limit=("limit", "first"),
        )
    )
