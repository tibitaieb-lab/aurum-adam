"""BTC-001 — Market Data Contract V1."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime


@dataclass(frozen=True)
class MarketBar:
    datetime: datetime
    symbol: str
    timeframe: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal = Decimal("0")


@dataclass(frozen=True)
class MarketSeries:
    series_id: str
    symbol: str
    timeframe: str
    bars: tuple[MarketBar, ...]
    first_datetime: datetime | None = None
    last_datetime: datetime | None = None
    bar_count: int | None = None


@dataclass(frozen=True)
class MarketDataset:
    dataset_id: str
    series: tuple[MarketSeries, ...]
    dataset_name: str | None = None
    created_at: datetime | None = None
    series_count: int | None = None
    total_bar_count: int | None = None
