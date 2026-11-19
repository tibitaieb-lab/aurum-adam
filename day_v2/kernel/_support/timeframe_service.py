"""Fixed-duration timeframe and timestamp-convention contracts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
import re
from types import MappingProxyType
from typing import Any, Mapping

from .market_data import (
    MarketBar,
    MarketSeries,
)


TIMESTAMP_CONVENTION_METADATA_KEY = "timestamp_convention"


class TimeframeServiceError(ValueError):
    """Base error for deterministic timeframe operations."""


class UnsupportedTimeframeError(TimeframeServiceError):
    """Raised when a timeframe has no fixed-duration LOT 04 definition."""


class TimeframeConversionError(TimeframeServiceError):
    """Raised when deterministic source-to-target conversion is impossible."""


class TimestampConventionError(TimeframeServiceError):
    """Raised when OPEN/CLOSE timestamp semantics are absent or invalid."""


class SeriesStructureError(TimeframeServiceError):
    """Raised when a BTC-001 series cannot support deterministic operations."""


class TimestampConvention(str, Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"

    @classmethod
    def parse(cls, value: object) -> "TimestampConvention":
        if isinstance(value, cls):
            return value
        if not isinstance(value, str) or not value.strip():
            raise TimestampConventionError("TIMESTAMP_CONVENTION_REQUIRED")
        try:
            return cls(value.strip().upper())
        except ValueError as exc:
            raise TimestampConventionError(
                f"UNSUPPORTED_TIMESTAMP_CONVENTION: {value}"
            ) from exc


class TimeframeService:
    """Validate fixed UTC durations and legal upward resampling relations."""

    _DURATIONS = MappingProxyType(
        {
            "M1": timedelta(minutes=1),
            "M5": timedelta(minutes=5),
            "M15": timedelta(minutes=15),
            "M30": timedelta(minutes=30),
            "H1": timedelta(hours=1),
            "H4": timedelta(hours=4),
        }
    )

    @property
    def supported_timeframes(self) -> tuple[str, ...]:
        return tuple(self._DURATIONS)

    def normalize(self, timeframe: object) -> str:
        if not isinstance(timeframe, str) or not timeframe.strip():
            raise UnsupportedTimeframeError("TIMEFRAME_REQUIRED")
        normalized = timeframe.strip().upper()
        if normalized not in self._DURATIONS:
            raise UnsupportedTimeframeError(
                f"UNSUPPORTED_FIXED_TIMEFRAME: {timeframe}"
            )
        return normalized

    def duration(self, timeframe: object) -> timedelta:
        return self._DURATIONS[self.normalize(timeframe)]

    def is_integer_multiple(self, source: object, target: object) -> bool:
        source_duration = self.duration(source)
        target_duration = self.duration(target)
        return target_duration % source_duration == timedelta(0)

    def resampling_ratio(self, source: object, target: object) -> int:
        source_name = self.normalize(source)
        target_name = self.normalize(target)
        source_duration = self._DURATIONS[source_name]
        target_duration = self._DURATIONS[target_name]

        if target_duration <= source_duration:
            raise TimeframeConversionError(
                f"TARGET_TIMEFRAME_MUST_BE_LARGER: {source_name}->{target_name}"
            )
        if target_duration % source_duration != timedelta(0):
            raise TimeframeConversionError(
                f"NON_INTEGER_TIMEFRAME_RATIO: {source_name}->{target_name}"
            )
        return int(target_duration / source_duration)

    def validate_series(
        self,
        series: MarketSeries,
    ) -> tuple[tuple[MarketBar, datetime], ...]:
        if not isinstance(series, MarketSeries):
            raise SeriesStructureError("BTC001_MARKET_SERIES_REQUIRED")

        series_timeframe = self.normalize(series.timeframe)
        previous: datetime | None = None
        validated: list[tuple[MarketBar, datetime]] = []
        for bar in series.bars:
            if not isinstance(bar, MarketBar):
                raise SeriesStructureError("BTC001_MARKET_BAR_REQUIRED")
            if bar.symbol != series.symbol:
                raise SeriesStructureError("MIXED_SERIES_SYMBOLS")
            if self.normalize(bar.timeframe) != series_timeframe:
                raise SeriesStructureError("MIXED_SERIES_TIMEFRAMES")

            timestamp = require_aware_utc(bar.datetime, "bar.datetime")
            if previous is not None and timestamp <= previous:
                raise SeriesStructureError("NON_CHRONOLOGICAL_BARS")
            previous = timestamp
            validated.append((bar, timestamp))
        return tuple(validated)


def require_aware_utc(value: object, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise SeriesStructureError(f"TIMEZONE_AWARE_DATETIME_REQUIRED: {field_name}")
    return value.astimezone(timezone.utc)



# Vector source timestamps are instants, never date-only business metadata.
_SOURCE_INSTANT = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt ](?:[01][0-9]|2[0-3]):[0-5][0-9]"
    r"(?::[0-5][0-9](?:[.,][0-9]{1,6})?)?"
    r"(?:[Zz]|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])?"
)
_SOURCE_OFFSET = re.compile(r"UTC([+-])([01][0-9]|2[0-3]):([0-5][0-9])")


def parse_source_timestamp(value: object, source_timezone: object) -> datetime:
    """Normalize a vector timestamp using its explicit source contract.

    An ISO offset is authoritative. Naive instants require UTC or a fixed
    UTC+HH:MM / UTC-HH:MM source label. Named zones must supply per-value
    offsets; ambiguous/nonexistent wall times are never guessed.
    """
    if not isinstance(value, str) or not _SOURCE_INSTANT.fullmatch(value.strip()):
        raise SeriesStructureError("INVALID_SOURCE_INSTANT: date and time required")
    text = value.strip()
    if text.endswith("-00:00"):
        raise SeriesStructureError("UNKNOWN_SOURCE_OFFSET: -00:00")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00").replace("z", "+00:00"))
        if parsed.tzinfo is None:
            label = source_timezone.strip() if isinstance(source_timezone, str) else ""
            if label == "UTC":
                source_tz = timezone.utc
            else:
                match = _SOURCE_OFFSET.fullmatch(label)
                if match is None or label == "UTC-00:00":
                    raise SeriesStructureError("SOURCE_TIMEZONE_REQUIRED_OR_UNSUPPORTED")
                sign, hours, minutes = match.groups()
                offset = timedelta(hours=int(hours), minutes=int(minutes))
                source_tz = timezone(offset if sign == "+" else -offset)
            parsed = parsed.replace(tzinfo=source_tz)
        return require_aware_utc(parsed, "source.timestamp")
    except (ValueError, OverflowError) as exc:
        raise SeriesStructureError(f"INVALID_SOURCE_INSTANT: {exc}") from exc


def timestamp_convention_from_metadata(
    metadata: Mapping[str, Any],
) -> TimestampConvention:
    if not isinstance(metadata, Mapping):
        raise TimestampConventionError("DESCRIPTOR_METADATA_MAPPING_REQUIRED")
    if TIMESTAMP_CONVENTION_METADATA_KEY not in metadata:
        raise TimestampConventionError("TIMESTAMP_CONVENTION_REQUIRED")
    return TimestampConvention.parse(
        metadata[TIMESTAMP_CONVENTION_METADATA_KEY]
    )
