from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Order:
    signal_date: pd.Timestamp
    order_date: pd.Timestamp
    execution_date: pd.Timestamp
    ts_code: str
    side: str
    target_weight: float
    current_weight: float
    delta_weight: float
    requested_quantity: int
    filled_quantity: int
    requested_value: float
    filled_value: float
    status: str
    reason: str


@dataclass(frozen=True)
class Fill:
    signal_date: pd.Timestamp
    execution_date: pd.Timestamp
    ts_code: str
    side: str
    quantity: int
    price: float
    notional: float
    commission: float
    stamp_tax: float
    slippage: float
    impact_cost: float
    total_cost: float


@dataclass(frozen=True)
class Position:
    mark_date: pd.Timestamp
    ts_code: str
    quantity: int
    close: float
    market_value: float
    weight: float
