"""Optional NautilusTrader backtesting backend for Finance Lab.

The current Finance Lab backtester is intentionally small and vectorized. This
module is the boundary for a future event-driven NautilusTrader implementation
without making Nautilus a required dependency for normal TradingAgents runs.
"""

from __future__ import annotations

import importlib.util
from typing import Any

import pandas as pd

from .market_data import fetch_ohlcv_frame
from .responses import fail

NAUTILUS_PACKAGE = "nautilus_trader"
NAUTILUS_INSTALL_HINT = (
    "Install NautilusTrader with Python 3.12+ using: pip install 'tradingagents[nautilus]'"
)


def is_nautilus_available() -> bool:
    """Return whether NautilusTrader can be imported in this environment."""
    return importlib.util.find_spec(NAUTILUS_PACKAGE) is not None


def run_nautilus_backtest(
    symbol: str,
    strategy_name: str,
    start: str,
    end: str,
    interval: str = "1d",
    *,
    initial_cash: float = 10000.0,
    fast_period: int = 12,
    slow_period: int = 26,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> dict[str, Any]:
    """Run a NautilusTrader-backed simulation when the backend is installed."""
    meta = {
        "backend": "nautilus",
        "symbol": symbol,
        "strategy_name": strategy_name,
        "start": start,
        "end": end,
        "interval": interval,
    }
    try:
        frame = fetch_ohlcv_frame(symbol, interval=interval, start=start, end=end)
        result = run_nautilus_backtest_on_frame(
            frame,
            symbol=symbol,
            strategy_name=strategy_name,
            initial_cash=initial_cash,
            fast_period=fast_period,
            slow_period=slow_period,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
        result["meta"] = {**result.get("meta", {}), **meta}
        return result
    except Exception as exc:  # noqa: BLE001
        return fail(str(exc), code="BACKTEST_ERROR", meta=meta)


def run_nautilus_backtest_on_frame(
    frame: pd.DataFrame,
    *,
    symbol: str,
    strategy_name: str,
    initial_cash: float = 10000.0,
    fast_period: int = 12,
    slow_period: int = 26,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> dict[str, Any]:
    """Run a NautilusTrader-backed simulation from a normalized OHLCV frame.

    The boundary is intentionally present before the full engine adapter lands,
    so callers can choose the advanced backend without changing their call
    shape. Until Nautilus is installed and the engine adapter is wired, this
    returns structured failures instead of silently falling back.
    """
    meta = _nautilus_meta(
        symbol=symbol,
        strategy_name=strategy_name,
        initial_cash=initial_cash,
        fast_period=fast_period,
        slow_period=slow_period,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
    )
    if not is_nautilus_available():
        return fail(
            "NautilusTrader is not installed for this Python environment.",
            code="MISSING_DEPENDENCY",
            details={"install_hint": NAUTILUS_INSTALL_HINT},
            meta=meta,
        )

    _validate_frame(frame)
    return fail(
        "NautilusTrader is installed, but the Finance Lab engine adapter is not wired yet.",
        code="NOT_IMPLEMENTED",
        details={
            "next_step": (
                "Map normalized OHLCV bars into Nautilus instruments, venues, "
                "bar types, and a strategy class."
            ),
            "supported_initial_strategies": ["buy_and_hold", "ema_cross"],
        },
        meta=meta,
    )


def _nautilus_meta(
    *,
    symbol: str,
    strategy_name: str,
    initial_cash: float,
    fast_period: int,
    slow_period: int,
    fee_bps: float,
    slippage_bps: float,
) -> dict[str, Any]:
    return {
        "backend": "nautilus",
        "symbol": symbol,
        "strategy_name": strategy_name,
        "parameters": {
            "initial_cash": float(initial_cash),
            "fast_period": int(fast_period),
            "slow_period": int(slow_period),
            "fee_bps": float(fee_bps),
            "slippage_bps": float(slippage_bps),
        },
    }


def _validate_frame(frame: pd.DataFrame) -> None:
    if frame.empty:
        raise ValueError("frame must not be empty")
    if "close" not in frame.columns:
        raise ValueError("frame must contain a close column")
