"""Technical indicators used by Finance Lab tools."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from .market_data import fetch_ohlcv_frame
from .responses import fail, ok

logger = logging.getLogger(__name__)


def calculate_ema(
    symbol: str,
    period: int = 50,
    *,
    interval: str = "1d",
    lookback_period: str = "1y",
) -> dict[str, Any]:
    meta = {
        "symbol": symbol,
        "indicator": "ema",
        "period": period,
        "interval": interval,
        "lookback_period": lookback_period,
    }
    try:
        frame = fetch_ohlcv_frame(symbol, interval=interval, period=lookback_period)
        return ok(calculate_ema_on_frame(frame, period=period), meta=meta)
    except Exception as exc:  # noqa: BLE001
        logger.warning("EMA calculation failed for %s: %s", symbol, exc)
        return fail(str(exc), code="INDICATOR_ERROR", meta=meta)


def calculate_rsi(
    symbol: str,
    period: int = 14,
    *,
    interval: str = "1d",
    lookback_period: str = "1y",
) -> dict[str, Any]:
    meta = {
        "symbol": symbol,
        "indicator": "rsi",
        "period": period,
        "interval": interval,
        "lookback_period": lookback_period,
    }
    try:
        frame = fetch_ohlcv_frame(symbol, interval=interval, period=lookback_period)
        return ok(calculate_rsi_on_frame(frame, period=period), meta=meta)
    except Exception as exc:  # noqa: BLE001
        logger.warning("RSI calculation failed for %s: %s", symbol, exc)
        return fail(str(exc), code="INDICATOR_ERROR", meta=meta)


def calculate_macd(
    symbol: str,
    *,
    interval: str = "1d",
    lookback_period: str = "1y",
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> dict[str, Any]:
    meta = {
        "symbol": symbol,
        "indicator": "macd",
        "interval": interval,
        "lookback_period": lookback_period,
        "fast_period": fast_period,
        "slow_period": slow_period,
        "signal_period": signal_period,
    }
    try:
        frame = fetch_ohlcv_frame(symbol, interval=interval, period=lookback_period)
        return ok(
            calculate_macd_on_frame(
                frame,
                fast_period=fast_period,
                slow_period=slow_period,
                signal_period=signal_period,
            ),
            meta=meta,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("MACD calculation failed for %s: %s", symbol, exc)
        return fail(str(exc), code="INDICATOR_ERROR", meta=meta)


def calculate_ema_on_frame(frame: pd.DataFrame, period: int = 50) -> dict[str, Any]:
    _validate_period(period)
    close = _close_series(frame)
    ema = ema_series(close, period)
    return _series_payload("ema", ema)


def calculate_rsi_on_frame(frame: pd.DataFrame, period: int = 14) -> dict[str, Any]:
    _validate_period(period)
    close = _close_series(frame)
    rsi = rsi_series(close, period)
    return _series_payload("rsi", rsi)


def calculate_macd_on_frame(
    frame: pd.DataFrame,
    *,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> dict[str, Any]:
    _validate_period(fast_period)
    _validate_period(slow_period)
    _validate_period(signal_period)
    if fast_period >= slow_period:
        raise ValueError("fast_period must be smaller than slow_period")

    close = _close_series(frame)
    macd_frame = macd_series(
        close,
        fast_period=fast_period,
        slow_period=slow_period,
        signal_period=signal_period,
    )
    latest = macd_frame.dropna().tail(1)
    latest_payload = None
    if not latest.empty:
        row = latest.iloc[0]
        latest_payload = {
            "date": _date_value(latest.index[0]),
            "macd": float(row["macd"]),
            "signal": float(row["signal"]),
            "histogram": float(row["histogram"]),
        }
    return {
        "latest": latest_payload,
        "series": [
            {
                "date": _date_value(idx),
                "macd": _json_float(row["macd"]),
                "signal": _json_float(row["signal"]),
                "histogram": _json_float(row["histogram"]),
            }
            for idx, row in macd_frame.iterrows()
        ],
    }


def ema_series(close: pd.Series, period: int) -> pd.Series:
    _validate_period(period)
    return close.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi_series(close: pd.Series, period: int) -> pd.Series:
    _validate_period(period)
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    rsi = rsi.mask((avg_loss == 0) & (avg_gain == 0), 50.0)
    return rsi


def macd_series(
    close: pd.Series,
    *,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> pd.DataFrame:
    fast = ema_series(close, fast_period)
    slow = ema_series(close, slow_period)
    macd = fast - slow
    signal = macd.ewm(span=signal_period, adjust=False, min_periods=signal_period).mean()
    histogram = macd - signal
    return pd.DataFrame(
        {
            "macd": macd,
            "signal": signal,
            "histogram": histogram,
        },
        index=close.index,
    )


def _series_payload(name: str, values: pd.Series) -> dict[str, Any]:
    latest = values.dropna().tail(1)
    latest_payload = None
    if not latest.empty:
        latest_payload = {
            "date": _date_value(latest.index[0]),
            "value": float(latest.iloc[0]),
        }
    return {
        "latest": latest_payload,
        "series": [
            {
                "date": _date_value(idx),
                name: _json_float(value),
            }
            for idx, value in values.items()
        ],
    }


def _close_series(frame: pd.DataFrame) -> pd.Series:
    if "close" not in frame.columns:
        raise ValueError("frame must contain a close column")
    close = pd.to_numeric(frame["close"], errors="coerce").dropna()
    if close.empty:
        raise ValueError("frame has no usable close prices")
    return close.astype(float)


def _validate_period(period: int) -> None:
    if int(period) <= 0:
        raise ValueError("period must be positive")


def _json_float(value: Any) -> float | None:
    if pd.isna(value):
        return None
    return float(value)


def _date_value(index_value: Any) -> str:
    if hasattr(index_value, "date"):
        return index_value.date().isoformat()
    return str(index_value)
