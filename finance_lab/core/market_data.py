"""Market data helpers for Finance Lab.

The first provider is yfinance. Provider-specific code stays in this module so
future MCP tools can swap providers without changing indicators or backtests.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from .responses import fail, ok

logger = logging.getLogger(__name__)

_COLUMN_MAP = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Adj Close": "adj_close",
    "Volume": "volume",
}


def fetch_ohlcv_frame(
    symbol: str,
    *,
    interval: str = "1d",
    period: str = "1y",
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Return raw OHLCV data from yfinance or raise a clear error."""
    if not symbol or not symbol.strip():
        raise ValueError("symbol is required")

    history_kwargs: dict[str, Any] = {
        "interval": interval,
        "auto_adjust": False,
    }
    if start or end:
        if start:
            history_kwargs["start"] = start
        if end:
            history_kwargs["end"] = end
    else:
        history_kwargs["period"] = period

    yf = _load_yfinance()
    data = yf.Ticker(symbol.strip().upper()).history(**history_kwargs)
    if data is None or data.empty:
        raise ValueError(f"no OHLCV data returned for {symbol}")
    return _normalize_frame(data)


def get_ohlcv(
    symbol: str,
    interval: str = "1d",
    period: str = "1y",
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    """Fetch OHLCV records and return a JSON-serializable response."""
    meta = {
        "provider": "yfinance",
        "symbol": symbol,
        "interval": interval,
        "period": period,
        "start": start,
        "end": end,
    }
    try:
        frame = fetch_ohlcv_frame(
            symbol,
            interval=interval,
            period=period,
            start=start,
            end=end,
        )
    except Exception as exc:  # noqa: BLE001 - surface errors as structured JSON
        logger.warning("OHLCV fetch failed for %s: %s", symbol, exc)
        return fail(str(exc), code="MARKET_DATA_ERROR", meta=meta)

    return ok(
        {
            "records": frame_to_records(frame),
            "record_count": int(len(frame)),
        },
        meta=meta,
    )


def get_live_price(symbol: str) -> dict[str, Any]:
    """Return the latest available yfinance price.

    This is not exchange-grade live data. It is intentionally labelled as the
    latest available provider price.
    """
    meta = {"provider": "yfinance", "symbol": symbol}
    try:
        yf = _load_yfinance()
        ticker = yf.Ticker(symbol.strip().upper())
        fast_info = getattr(ticker, "fast_info", {}) or {}
        price = _read_fast_info_price(fast_info)
        source = "fast_info"
        if price is None:
            history = ticker.history(period="5d", interval="1d", auto_adjust=False)
            history = _normalize_frame(history)
            price = float(history["close"].dropna().iloc[-1])
            source = "history_last_close"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Latest price fetch failed for %s: %s", symbol, exc)
        return fail(str(exc), code="MARKET_DATA_ERROR", meta=meta)

    return ok({"price": price, "source": source}, meta=meta)


def frame_to_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert a normalized OHLCV frame into JSON-safe row dictionaries."""
    if frame.empty:
        return []

    rows = []
    for idx, row in frame.iterrows():
        item: dict[str, Any] = {"date": _date_value(idx)}
        for column in ("open", "high", "low", "close", "adj_close", "volume"):
            if column not in frame.columns:
                continue
            value = row[column]
            if pd.isna(value):
                item[column] = None
            elif column == "volume":
                item[column] = int(value)
            else:
                item[column] = float(value)
        rows.append(item)
    return rows


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        raise ValueError("empty OHLCV frame")

    normalized = frame.copy()
    if isinstance(normalized.columns, pd.MultiIndex):
        normalized.columns = normalized.columns.get_level_values(0)
    normalized = normalized.rename(columns=_COLUMN_MAP)
    keep = [c for c in ("open", "high", "low", "close", "adj_close", "volume") if c in normalized]
    normalized = normalized[keep]
    if "close" not in normalized.columns:
        raise ValueError("OHLCV frame is missing close prices")
    normalized = normalized.dropna(subset=["close"])
    if normalized.empty:
        raise ValueError("OHLCV frame has no usable close prices")
    if normalized.index.tz is not None:
        normalized.index = normalized.index.tz_localize(None)
    return normalized.sort_index()


def _date_value(index_value: Any) -> str:
    if hasattr(index_value, "date"):
        return index_value.date().isoformat()
    return str(index_value)


def _read_fast_info_price(fast_info: Any) -> float | None:
    for key in ("last_price", "lastPrice", "regular_market_price"):
        try:
            value = fast_info[key]
        except Exception:  # noqa: BLE001 - yfinance fast_info can be dict-like
            value = getattr(fast_info, key, None)
        if value is not None and not pd.isna(value):
            return float(value)
    return None


def _load_yfinance():
    try:
        import yfinance as yf  # noqa: PLC0415
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "yfinance is required for live market data. Install project dependencies first."
        ) from exc
    return yf
