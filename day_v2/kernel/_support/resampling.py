"""Deterministic fixed-timeframe OHLCV resampling for BTC-001 series."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from .market_data import (
    MarketBar,
    MarketSeries,
)
from .timeframe_service import (
    SeriesStructureError,
    TimeframeService,
    TimeframeServiceError,
    TimestampConvention,
)


class ResamplingError(TimeframeServiceError):
    """Raised when complete target bars cannot be proved without fabrication."""


class FixedTimeframeResampler:
    """Aggregate only complete, UTC-anchored, contiguous fixed-timeframe bars."""

    _UTC_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

    def __init__(self, timeframe_service: TimeframeService | None = None) -> None:
        self._timeframes = timeframe_service or TimeframeService()

    def resample(
        self,
        series: MarketSeries,
        target_timeframe: str,
        timestamp_convention: TimestampConvention | str,
    ) -> MarketSeries:
        convention = TimestampConvention.parse(timestamp_convention)
        source_timeframe = self._timeframes.normalize(series.timeframe)
        target_timeframe = self._timeframes.normalize(target_timeframe)
        ratio = self._timeframes.resampling_ratio(
            source_timeframe,
            target_timeframe,
        )
        source_duration = self._timeframes.duration(source_timeframe)
        target_duration = self._timeframes.duration(target_timeframe)
        validated = self._timeframes.validate_series(series)
        if not validated:
            raise ResamplingError("SOURCE_SERIES_EMPTY")

        timestamps = tuple(timestamp for _, timestamp in validated)
        self._validate_source_grid(timestamps, source_duration)

        buckets: dict[datetime, list[tuple[MarketBar, datetime]]] = {}
        for bar, timestamp in validated:
            bucket_timestamp = self._bucket_timestamp(
                timestamp,
                target_duration,
                convention,
            )
            buckets.setdefault(bucket_timestamp, []).append((bar, timestamp))

        bucket_items = tuple(buckets.items())
        target_bars: list[MarketBar] = []
        for index, (bucket_timestamp, members) in enumerate(bucket_items):
            expected = self._expected_timestamps(
                bucket_timestamp,
                source_duration,
                target_duration,
                ratio,
                convention,
            )
            actual = tuple(timestamp for _, timestamp in members)
            if actual != expected:
                if index not in (0, len(bucket_items) - 1):
                    raise ResamplingError(
                        f"INCOMPLETE_INTERNAL_BUCKET: {bucket_timestamp.isoformat()}"
                    )
                continue
            target_bars.append(
                self._aggregate(
                    members,
                    bucket_timestamp,
                    series.symbol,
                    target_timeframe,
                )
            )

        canonical_bars = tuple(target_bars)
        return MarketSeries(
            series_id=f"{series.symbol}_{target_timeframe}",
            symbol=series.symbol,
            timeframe=target_timeframe,
            bars=canonical_bars,
            first_datetime=(
                canonical_bars[0].datetime if canonical_bars else None
            ),
            last_datetime=(
                canonical_bars[-1].datetime if canonical_bars else None
            ),
            bar_count=len(canonical_bars),
        )

    def _validate_source_grid(
        self,
        timestamps: tuple[datetime, ...],
        source_duration: timedelta,
    ) -> None:
        duration_microseconds = _microseconds(source_duration)
        for timestamp in timestamps:
            elapsed = _microseconds(timestamp - self._UTC_EPOCH)
            if elapsed % duration_microseconds:
                raise SeriesStructureError(
                    f"SOURCE_BAR_OFF_UTC_GRID: {timestamp.isoformat()}"
                )
        for previous, current in zip(timestamps, timestamps[1:]):
            if current - previous != source_duration:
                raise ResamplingError(
                    "SOURCE_GAP_OR_OVERLAP: "
                    f"{previous.isoformat()}->{current.isoformat()}"
                )

    def _bucket_timestamp(
        self,
        timestamp: datetime,
        target_duration: timedelta,
        convention: TimestampConvention,
    ) -> datetime:
        target_microseconds = _microseconds(target_duration)
        elapsed = _microseconds(timestamp - self._UTC_EPOCH)
        quotient, remainder = divmod(elapsed, target_microseconds)
        if convention is TimestampConvention.OPEN:
            bucket_index = quotient
        else:
            bucket_index = quotient if remainder == 0 else quotient + 1
        return self._UTC_EPOCH + timedelta(
            microseconds=bucket_index * target_microseconds
        )

    @staticmethod
    def _expected_timestamps(
        bucket_timestamp: datetime,
        source_duration: timedelta,
        target_duration: timedelta,
        ratio: int,
        convention: TimestampConvention,
    ) -> tuple[datetime, ...]:
        if convention is TimestampConvention.OPEN:
            return tuple(
                bucket_timestamp + index * source_duration
                for index in range(ratio)
            )
        bucket_open = bucket_timestamp - target_duration
        return tuple(
            bucket_open + (index + 1) * source_duration
            for index in range(ratio)
        )

    @staticmethod
    def _aggregate(
        members: list[tuple[MarketBar, datetime]],
        bucket_timestamp: datetime,
        symbol: str,
        target_timeframe: str,
    ) -> MarketBar:
        bars = tuple(bar for bar, _ in members)
        return MarketBar(
            datetime=bucket_timestamp,
            symbol=symbol,
            timeframe=target_timeframe,
            open=bars[0].open,
            high=max(bar.high for bar in bars),
            low=min(bar.low for bar in bars),
            close=bars[-1].close,
            volume=sum((bar.volume for bar in bars), Decimal("0")),
        )


def _microseconds(duration: timedelta) -> int:
    return (
        duration.days * 86_400_000_000
        + duration.seconds * 1_000_000
        + duration.microseconds
    )
