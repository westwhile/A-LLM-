from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from ashare_factor_research.backtest.constraints import mark_tradability, trade_block_reason
from ashare_factor_research.backtest.cost_model import CostConfig, estimate_rebalance_cost, estimate_trade_cost
from ashare_factor_research.backtest.orders import Fill, Order, Position
from ashare_factor_research.data.trading_calendar import next_trade_date
from ashare_factor_research.utils.helpers import require_columns


@dataclass(frozen=True)
class BacktestResult:
    nav: pd.DataFrame
    trades: pd.DataFrame
    orders: pd.DataFrame
    fills: pd.DataFrame
    positions: pd.DataFrame


def run_backtest(
    portfolio_df: pd.DataFrame,
    returns_df: pd.DataFrame,
    cost_config: CostConfig | None = None,
    date_col: str = "trade_date",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run daily close-to-close backtest with next-trade-date execution.

    Signals dated T become active from the next available trading date. The
    function uses daily close-to-close returns as a proxy when open execution
    prices are unavailable in the sample dataset.
    """

    require_columns(portfolio_df, [date_col, "ts_code", "target_weight"], "portfolio_df")
    require_columns(returns_df, [date_col, "ts_code", "return_1d"], "returns_df")
    returns = returns_df[[date_col, "ts_code", "return_1d"]].copy()
    returns[date_col] = pd.to_datetime(returns[date_col])
    trade_dates = pd.DatetimeIndex(sorted(returns[date_col].dropna().unique()))

    effective_targets: dict[pd.Timestamp, pd.Series] = {}
    for signal_date, part in portfolio_df.groupby(date_col):
        eff_date = next_trade_date(trade_dates, pd.Timestamp(signal_date))
        if eff_date is None:
            continue
        effective_targets[eff_date] = part.set_index("ts_code")["target_weight"].astype(float)

    current_weights = pd.Series(dtype=float)
    nav = 1.0
    nav_rows = []
    trade_rows = []
    return_pivot = returns.pivot(index=date_col, columns="ts_code", values="return_1d").sort_index()

    for date in trade_dates:
        cost = 0.0
        turnover = 0.0
        if date in effective_targets:
            target = effective_targets[date]
            cost_info = estimate_rebalance_cost(current_weights, target, cost_config)
            cost = cost_info["cost"]
            turnover = cost_info["portfolio_turnover"]
            current_weights = target
            trade_rows.append({"trade_date": date, **cost_info})

        day_returns = return_pivot.loc[date].reindex(current_weights.index).fillna(0.0)
        gross_return = float((current_weights * day_returns).sum()) if not current_weights.empty else 0.0
        net_return = gross_return - cost
        nav *= 1.0 + net_return
        nav_rows.append(
            {
                "trade_date": date,
                "gross_return": gross_return,
                "cost": cost,
                "net_return": net_return,
                "nav": nav,
                "turnover": turnover,
                "holding_count": float((current_weights > 0).sum()),
            }
        )

    return pd.DataFrame(nav_rows), pd.DataFrame(trade_rows)


def run_event_backtest(
    portfolio_df: pd.DataFrame,
    market_df: pd.DataFrame,
    cost_config: CostConfig | None = None,
    date_col: str = "trade_date",
    initial_cash: float = 1_000_000.0,
    lot_size: int = 100,
    max_turnover: float | None = 0.5,
    max_participation_rate: float | None = None,
    min_trade_amount: float | None = None,
) -> BacktestResult:
    """Run next-open event backtest with orders, fills, positions, and cash.

    `portfolio_df[date_col]` is treated as the signal date after close. Orders
    are generated and executed on the next available trading date at `open`.
    Missing prices, suspensions, limit-up buys, limit-down sells, lot-size
    rounding, and insufficient cash can leave orders unfilled or partially
    filled.
    """

    require_columns(portfolio_df, [date_col, "ts_code", "target_weight"], "portfolio_df")
    require_columns(market_df, [date_col, "ts_code", "open", "close"], "market_df")
    if lot_size <= 0:
        raise ValueError("lot_size must be positive")
    if initial_cash <= 0:
        raise ValueError("initial_cash must be positive")

    market = mark_tradability(market_df.copy())
    market[date_col] = pd.to_datetime(market[date_col])
    trade_dates = pd.DatetimeIndex(sorted(market[date_col].dropna().unique()))
    market_by_date = {
        date: part.set_index("ts_code").sort_index()
        for date, part in market.sort_values([date_col, "ts_code"]).groupby(date_col)
    }

    schedules: dict[pd.Timestamp, tuple[pd.Timestamp, pd.Series]] = {}
    signals = portfolio_df.copy()
    signals[date_col] = pd.to_datetime(signals[date_col])
    for signal_date, part in signals.groupby(date_col):
        execution_date = next_trade_date(trade_dates, pd.Timestamp(signal_date))
        if execution_date is None:
            continue
        target = part.set_index("ts_code")["target_weight"].astype(float)
        schedules[execution_date] = (pd.Timestamp(signal_date), target[target > 0])

    cash = float(initial_cash)
    positions = pd.Series(dtype=float)
    previous_value = float(initial_cash)
    nav_rows: list[dict[str, object]] = []
    trade_rows: list[dict[str, object]] = []
    order_rows: list[dict[str, object]] = []
    fill_rows: list[dict[str, object]] = []
    position_rows: list[dict[str, object]] = []

    for mark_date in trade_dates:
        day_market = market_by_date[mark_date]
        day_cost = 0.0
        day_turnover = 0.0
        day_buy_turnover = 0.0
        day_sell_turnover = 0.0
        fill_count = 0
        unfilled_count = 0

        if mark_date in schedules:
            signal_date, target_weights = schedules[mark_date]
            rebalance = _rebalance_at_open(
                signal_date=signal_date,
                execution_date=mark_date,
                target_weights=target_weights,
                positions=positions,
                cash=cash,
                day_market=day_market,
                portfolio_value=_portfolio_value_at_price(cash, positions, day_market["open"]),
                cost_config=cost_config,
                lot_size=lot_size,
                max_turnover=max_turnover,
                max_participation_rate=max_participation_rate,
                min_trade_amount=min_trade_amount,
            )
            positions = rebalance["positions"]
            cash = float(rebalance["cash"])
            order_rows.extend(rebalance["orders"])
            fill_rows.extend(rebalance["fills"])
            day_cost = float(rebalance["cost"])
            day_turnover = float(rebalance["portfolio_turnover"])
            day_buy_turnover = float(rebalance["buy_turnover"])
            day_sell_turnover = float(rebalance["sell_turnover"])
            fill_count = int(rebalance["fill_count"])
            unfilled_count = int(rebalance["unfilled_count"])
            trade_rows.append(
                {
                    "signal_date": signal_date,
                    "order_date": mark_date,
                    "execution_date": mark_date,
                    "buy_turnover": day_buy_turnover,
                    "sell_turnover": day_sell_turnover,
                    "gross_turnover": day_buy_turnover + day_sell_turnover,
                    "portfolio_turnover": day_turnover,
                    "cost": day_cost,
                    "fill_count": fill_count,
                    "unfilled_order_count": unfilled_count,
                }
            )

        close_prices = day_market["close"]
        portfolio_value = _portfolio_value_at_price(cash, positions, close_prices)
        net_return = portfolio_value / previous_value - 1.0 if previous_value else 0.0
        gross_return = (portfolio_value + day_cost) / previous_value - 1.0 if previous_value else net_return
        nav_rows.append(
            {
                "trade_date": mark_date,
                "mark_date": mark_date,
                "gross_return": float(gross_return),
                "cost": day_cost / previous_value if previous_value else 0.0,
                "net_return": float(net_return),
                "nav": float(portfolio_value / initial_cash),
                "turnover": day_turnover,
                "buy_turnover": day_buy_turnover,
                "sell_turnover": day_sell_turnover,
                "cash": cash,
                "cash_weight": float(cash / portfolio_value) if portfolio_value else 0.0,
                "holding_count": float((positions > 0).sum()),
            }
        )
        position_rows.extend(_position_rows(mark_date, positions, close_prices, portfolio_value))
        previous_value = portfolio_value

    return BacktestResult(
        nav=pd.DataFrame(nav_rows),
        trades=pd.DataFrame(trade_rows),
        orders=pd.DataFrame(order_rows),
        fills=pd.DataFrame(fill_rows),
        positions=pd.DataFrame(position_rows),
    )


def _rebalance_at_open(
    signal_date: pd.Timestamp,
    execution_date: pd.Timestamp,
    target_weights: pd.Series,
    positions: pd.Series,
    cash: float,
    day_market: pd.DataFrame,
    portfolio_value: float,
    cost_config: CostConfig | None,
    lot_size: int,
    max_turnover: float | None,
    max_participation_rate: float | None,
    min_trade_amount: float | None,
) -> dict[str, object]:
    open_prices = day_market["open"]
    all_codes = positions.index.union(target_weights.index)
    current_values = positions.reindex(all_codes, fill_value=0.0) * open_prices.reindex(all_codes)
    current_values = current_values.fillna(0.0)
    current_weights = current_values / portfolio_value if portfolio_value else current_values
    target = target_weights.reindex(all_codes, fill_value=0.0).clip(lower=0.0)
    if target.sum() > 1.0 + 1e-12:
        raise ValueError("target weights must sum to 1 or less")

    delta_values = target * portfolio_value - current_values
    delta_values = _apply_max_turnover(delta_values, portfolio_value, max_turnover)
    implied_target_weights = current_weights + delta_values / portfolio_value if portfolio_value else current_weights

    next_positions = positions.copy()
    next_cash = float(cash)
    order_rows: list[dict[str, object]] = []
    fill_rows: list[dict[str, object]] = []
    total_buy_notional = 0.0
    total_sell_notional = 0.0
    total_cost = 0.0

    sell_codes = delta_values[delta_values < -1e-12].sort_values().index
    buy_codes = delta_values[delta_values > 1e-12].sort_values(ascending=False).index
    for code in list(sell_codes) + list(buy_codes):
        side = "buy" if delta_values.loc[code] > 0 else "sell"
        requested_value = abs(float(delta_values.loc[code]))
        order_result = _execute_order(
            signal_date=signal_date,
            execution_date=execution_date,
            code=str(code),
            side=side,
            requested_value=requested_value,
            target_weight=float(implied_target_weights.reindex([code], fill_value=0.0).iloc[0]),
            current_weight=float(current_weights.reindex([code], fill_value=0.0).iloc[0]),
            positions=next_positions,
            cash=next_cash,
            day_market=day_market,
            cost_config=cost_config,
            lot_size=lot_size,
            max_participation_rate=max_participation_rate,
            min_trade_amount=min_trade_amount,
        )
        next_positions = order_result["positions"]
        next_cash = float(order_result["cash"])
        order_rows.append(order_result["order"])
        if order_result["fill"] is not None:
            fill_rows.append(order_result["fill"])
            fill = order_result["fill"]
            total_cost += float(fill["total_cost"])
            if side == "buy":
                total_buy_notional += float(fill["notional"])
            else:
                total_sell_notional += float(fill["notional"])

    next_positions = next_positions[next_positions > 0].astype(float)
    buy_turnover = total_buy_notional / portfolio_value if portfolio_value else 0.0
    sell_turnover = total_sell_notional / portfolio_value if portfolio_value else 0.0
    return {
        "positions": next_positions,
        "cash": next_cash,
        "orders": order_rows,
        "fills": fill_rows,
        "cost": total_cost,
        "buy_turnover": buy_turnover,
        "sell_turnover": sell_turnover,
        "portfolio_turnover": (buy_turnover + sell_turnover) / 2.0,
        "fill_count": len(fill_rows),
        "unfilled_count": sum(1 for row in order_rows if row["status"] != "filled"),
    }


def _execute_order(
    signal_date: pd.Timestamp,
    execution_date: pd.Timestamp,
    code: str,
    side: str,
    requested_value: float,
    target_weight: float,
    current_weight: float,
    positions: pd.Series,
    cash: float,
    day_market: pd.DataFrame,
    cost_config: CostConfig | None,
    lot_size: int,
    max_participation_rate: float | None,
    min_trade_amount: float | None,
) -> dict[str, object]:
    if code not in day_market.index or pd.isna(day_market.at[code, "open"]):
        return _order_result(
            signal_date,
            execution_date,
            code,
            side,
            target_weight,
            current_weight,
            requested_value,
            0,
            0,
            "unfilled",
            "no_market_price",
            positions,
            cash,
            None,
        )

    row = day_market.loc[code]
    price = float(row["open"])
    amount = float(row["amount"]) if "amount" in row and pd.notna(row["amount"]) else None
    if min_trade_amount is not None and (amount is None or amount < min_trade_amount):
        return _order_result(
            signal_date,
            execution_date,
            code,
            side,
            target_weight,
            current_weight,
            requested_value,
            0,
            0,
            "unfilled",
            "low_liquidity",
            positions,
            cash,
            None,
        )
    block_reason = trade_block_reason(row, side)
    audit_reason = ""
    requested_quantity = int(requested_value // (price * lot_size) * lot_size)
    if max_participation_rate is not None:
        if max_participation_rate <= 0:
            raise ValueError("max_participation_rate must be positive")
        if amount is None:
            requested_quantity = 0
            audit_reason = "missing_amount"
        else:
            max_value = amount * max_participation_rate
            max_quantity = int(max_value // (price * lot_size) * lot_size)
            if max_quantity < requested_quantity:
                requested_quantity = max_quantity
                audit_reason = "volume_participation_limit"
    if requested_quantity <= 0:
        return _order_result(
            signal_date,
            execution_date,
            code,
            side,
            target_weight,
            current_weight,
            requested_value,
            0,
            0,
            "unfilled",
            block_reason or audit_reason or "lot_size",
            positions,
            cash,
            None,
        )
    if block_reason:
        return _order_result(
            signal_date,
            execution_date,
            code,
            side,
            target_weight,
            current_weight,
            requested_value,
            requested_quantity,
            0,
            "unfilled",
            block_reason,
            positions,
            cash,
            None,
        )

    next_positions = positions.copy()
    next_cash = float(cash)
    if side == "sell":
        held_quantity = int(next_positions.reindex([code], fill_value=0.0).iloc[0])
        quantity = min(requested_quantity, held_quantity)
        status = "filled" if quantity == requested_quantity else "partially_filled"
        reason = audit_reason if status == "filled" and audit_reason == "volume_participation_limit" else ""
        if status != "filled":
            reason = "insufficient_position"
    else:
        unit_cost = price * (1.0 + _buy_cost_rate(cost_config))
        affordable_quantity = int(next_cash // (unit_cost * lot_size) * lot_size)
        quantity = min(requested_quantity, affordable_quantity)
        status = "filled" if quantity == requested_quantity else "partially_filled"
        reason = audit_reason if status == "filled" and audit_reason == "volume_participation_limit" else ""
        if status != "filled":
            reason = "insufficient_cash"

    if quantity <= 0:
        return _order_result(
            signal_date,
            execution_date,
            code,
            side,
            target_weight,
            current_weight,
            requested_value,
            requested_quantity,
            0,
            "unfilled",
            reason or "insufficient_cash",
            positions,
            cash,
            None,
        )

    notional = float(quantity * price)
    cost = estimate_trade_cost(notional, side, cost_config)
    if side == "sell":
        next_positions.loc[code] = float(next_positions.reindex([code], fill_value=0.0).iloc[0] - quantity)
        next_cash += notional - cost["total_cost"]
    else:
        next_positions.loc[code] = float(next_positions.reindex([code], fill_value=0.0).iloc[0] + quantity)
        next_cash -= notional + cost["total_cost"]

    fill = asdict(
        Fill(
            signal_date=signal_date,
            execution_date=execution_date,
            ts_code=code,
            side=side,
            quantity=int(quantity),
            price=price,
            notional=notional,
            commission=cost["commission"],
            stamp_tax=cost["stamp_tax"],
            slippage=cost["slippage"],
            impact_cost=cost["impact_cost"],
            total_cost=cost["total_cost"],
        )
    )
    return _order_result(
        signal_date,
        execution_date,
        code,
        side,
        target_weight,
        current_weight,
        requested_value,
        requested_quantity,
        int(quantity),
        status,
        reason,
        next_positions,
        next_cash,
        fill,
    )


def _order_result(
    signal_date: pd.Timestamp,
    execution_date: pd.Timestamp,
    code: str,
    side: str,
    target_weight: float,
    current_weight: float,
    requested_value: float,
    requested_quantity: int,
    filled_quantity: int,
    status: str,
    reason: str,
    positions: pd.Series,
    cash: float,
    fill: dict[str, object] | None,
) -> dict[str, object]:
    order = asdict(
        Order(
            signal_date=signal_date,
            order_date=execution_date,
            execution_date=execution_date,
            ts_code=code,
            side=side,
            target_weight=target_weight,
            current_weight=current_weight,
            delta_weight=target_weight - current_weight,
            requested_quantity=int(requested_quantity),
            filled_quantity=int(filled_quantity),
            requested_value=float(requested_value),
            filled_value=float(fill["notional"]) if fill else 0.0,
            status=status,
            reason=reason,
        )
    )
    return {"positions": positions, "cash": cash, "order": order, "fill": fill}


def _portfolio_value_at_price(cash: float, positions: pd.Series, prices: pd.Series) -> float:
    position_values = positions.reindex(prices.index, fill_value=0.0) * prices
    return float(cash + position_values.fillna(0.0).sum())


def _position_rows(
    mark_date: pd.Timestamp,
    positions: pd.Series,
    close_prices: pd.Series,
    portfolio_value: float,
) -> list[dict[str, object]]:
    rows = []
    for code, quantity in positions[positions > 0].items():
        if code not in close_prices.index or pd.isna(close_prices.loc[code]):
            continue
        close = float(close_prices.loc[code])
        market_value = float(quantity * close)
        rows.append(
            asdict(
                Position(
                    mark_date=mark_date,
                    ts_code=str(code),
                    quantity=int(quantity),
                    close=close,
                    market_value=market_value,
                    weight=market_value / portfolio_value if portfolio_value else 0.0,
                )
            )
        )
    return rows


def _apply_max_turnover(
    delta_values: pd.Series,
    portfolio_value: float,
    max_turnover: float | None,
) -> pd.Series:
    if max_turnover is None or portfolio_value <= 0:
        return delta_values
    if max_turnover < 0:
        raise ValueError("max_turnover must be non-negative")
    gross_turnover = float(delta_values.abs().sum() / portfolio_value)
    allowed_gross_turnover = max_turnover * 2.0
    if gross_turnover <= allowed_gross_turnover or gross_turnover == 0:
        return delta_values
    return delta_values * (allowed_gross_turnover / gross_turnover)


def _buy_cost_rate(config: CostConfig | None) -> float:
    cfg = config or CostConfig()
    return cfg.commission_buy + cfg.slippage + cfg.impact_coef
