"""Validated M15 midpoint candles, including MetaTrader CSV exports."""

from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import pandas as pd


def validate_bars(frame):
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError("Candles require timezone-aware timestamps.")
    frame = frame.copy()
    frame.index = frame.index.tz_convert("UTC")
    if frame.index.hasnans or not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise ValueError("Timestamps must be valid, strictly increasing, and unique.")
    required = ["open", "high", "low", "close"]
    if not set(required) <= set(frame.columns):
        raise ValueError("CSV needs open, high, low, close columns.")
    for col in required:
        frame[col] = pd.to_numeric(frame[col], errors="raise")
    values = frame[required].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("OHLC prices must be finite and positive.")
    if (frame.high < frame[["open", "close", "low"]].max(axis=1)).any() or (
        frame.low > frame[["open", "close", "high"]].min(axis=1)
    ).any():
        raise ValueError("Invalid OHLC range: high/low must contain open and close.")
    if len(frame) < 200:
        raise ValueError("At least 200 M15 candles are required for a split test.")
    deltas = frame.index.to_series().diff().dropna()
    if (deltas < pd.Timedelta(minutes=15)).any() or deltas.median() != pd.Timedelta(minutes=15):
        raise ValueError("This strategy requires 15-minute candles; resample the source first.")
    if ((frame.index.minute % 15 != 0) | (frame.index.second != 0)).any():
        raise ValueError("Timestamps must be aligned to 15-minute bar opens.")
    frame["volume"] = pd.to_numeric(
        frame.get("volume", pd.Series(0, index=frame.index)), errors="raise"
    )
    if not np.isfinite(frame.volume).all() or (frame.volume < 0).any():
        raise ValueError("Volume must be finite and non-negative.")
    return frame


def load_csv(path: Path, *, timezone: str | None, price_basis: str, spread_pips: float):
    frame = pd.read_csv(path, sep=None, engine="python")
    frame.columns = [str(col).strip().strip("<>").lower() for col in frame.columns]
    if {"date", "time"} <= set(frame.columns):
        dates = frame["date"].astype(str) + " " + frame["time"].astype(str)
    elif "timestamp" in frame.columns:
        dates = frame["timestamp"]
    elif "datetime" in frame.columns:
        dates = frame["datetime"]
    else:
        raise ValueError("CSV needs timestamp, datetime, or MetaTrader <DATE>/<TIME> columns.")
    dates = pd.DatetimeIndex(pd.to_datetime(dates, errors="raise"))
    if dates.tz is None:
        if not timezone:
            raise ValueError(
                "CSV has naive timestamps: supply --timezone with the broker's export timezone."
            )
        try:
            broker_zone = ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown broker timezone: {timezone}") from exc
        dates = dates.tz_localize(broker_zone, ambiguous="raise", nonexistent="raise")
    frame.index = dates
    if "tickvol" in frame and "volume" not in frame:
        frame["volume"] = frame["tickvol"]
    frame = validate_bars(frame)
    if price_basis not in {"bid", "mid"}:
        raise ValueError("Price basis must be bid or mid.")
    if price_basis == "bid":
        frame[["open", "high", "low", "close"]] += spread_pips * 0.0001 / 2
    return frame


def demo_bars(days=90, seed=731):
    """Reproducible synthetic regimes for exercising the software, not assessing edge."""
    rng = np.random.default_rng(seed)
    index = pd.date_range("2025-01-06", periods=days * 96 * 2, freq="15min", tz="UTC")
    index = index[index.dayofweek < 5][: days * 96]
    drift = np.repeat(rng.choice([-0.00004, 0.0, 0.00004], size=days), 96)
    changes = rng.normal(0, 0.00023, len(index)) + drift
    close = 1.09 + changes.cumsum()
    opens = np.r_[1.09, close[:-1]]
    wick = rng.uniform(0.00003, 0.0003, len(index))
    return validate_bars(
        pd.DataFrame(
            {
                "open": opens,
                "high": np.maximum(opens, close) + wick,
                "low": np.minimum(opens, close) - wick,
                "close": close,
                "volume": rng.integers(50, 500, len(index)),
            },
            index=index,
        )
    )


def data_summary(frame):
    gaps = 0
    weekends = 0
    for before, after in zip(frame.index[:-1], frame.index[1:], strict=True):
        delta = after - before
        if delta <= pd.Timedelta(minutes=15):
            continue
        if (
            before.dayofweek == 4
            and before.hour >= 20
            and after.dayofweek in {6, 0}
            and delta <= pd.Timedelta(hours=52)
        ):
            weekends += 1
        else:
            gaps += 1
    return {
        "bars": len(frame),
        "start": frame.index[0].isoformat(),
        "end": frame.index[-1].isoformat(),
        "unexpected_gaps": gaps,
        "weekend_gaps": weekends,
    }


def swing_candles(frame):
    """Only complete H4 candles; index is their final M15 bar's opening time."""
    grouped = frame.resample("4h", closed="left", label="right")
    bars = grouped.agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    bars = bars[grouped.close.count() == 16]
    bars.index -= pd.Timedelta(minutes=15)
    return bars
