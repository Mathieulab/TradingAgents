"""Small deterministic backtesting helpers for Finance Lab."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from .indicators import ema_series
from .market_data import fetch_ohlcv_frame
from .responses import fail, ok

logger = logging.getLogger(__name__)


def run_backtest(
    symbol: str,
    strategy_name: str,
    start: str,
    end: str,
    interval: str = "1d",
    *,
    backend: str = "simple",
    initial_cash: float = 10000.0,
    fast_period: int = 12,
    slow_period: int = 26,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> dict[str, Any]:
    """Run a Finance Lab backtest through the selected backend."""
    normalized_backend = backend.strip().lower()
    if normalized_backend in {"simple", "vectorized"}:
        return run_simple_backtest(
            symbol,
            strategy_name,
            start,
            end,
            interval=interval,
            initial_cash=initial_cash,
            fast_period=fast_period,
            slow_period=slow_period,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
    if normalized_backend == "nautilus":
        from .nautilus_backtesting import run_nautilus_backtest

        return run_nautilus_backtest(
            symbol,
            strategy_name,
            start,
            end,
            interval=interval,
            initial_cash=initial_cash,
            fast_period=fast_period,
            slow_period=slow_period,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
    return fail("unsupported backtest backend", code="VALIDATION_ERROR")


def run_simple_backtest(
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
    meta = {
        "symbol": symbol,
        "strategy_name": strategy_name,
        "start": start,
        "end": end,
        "interval": interval,
    }
    try:
        frame = fetch_ohlcv_frame(symbol, interval=interval, start=start, end=end)
        result = run_simple_backtest_on_frame(
            frame,
            strategy_name=strategy_name,
            initial_cash=initial_cash,
            fast_period=fast_period,
            slow_period=slow_period,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
        return ok(result, meta=meta)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Backtest failed for %s/%s: %s", symbol, strategy_name, exc)
        return fail(str(exc), code="BACKTEST_ERROR", meta=meta)


def run_backtest_on_frame(
    frame: pd.DataFrame,
    *,
    strategy_name: str,
    backend: str = "simple",
    symbol: str = "",
    initial_cash: float = 10000.0,
    fast_period: int = 12,
    slow_period: int = 26,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> dict[str, Any]:
    """Run a Finance Lab backtest from a frame through the selected backend."""
    normalized_backend = backend.strip().lower()
    if normalized_backend in {"simple", "vectorized"}:
        return run_simple_backtest_on_frame(
            frame,
            strategy_name=strategy_name,
            initial_cash=initial_cash,
            fast_period=fast_period,
            slow_period=slow_period,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
    if normalized_backend == "nautilus":
        from .nautilus_backtesting import run_nautilus_backtest_on_frame

        return run_nautilus_backtest_on_frame(
            frame,
            symbol=symbol,
            strategy_name=strategy_name,
            initial_cash=initial_cash,
            fast_period=fast_period,
            slow_period=slow_period,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
    return fail("unsupported backtest backend", code="VALIDATION_ERROR")


def run_simple_backtest_on_frame(
    frame: pd.DataFrame,
    *,
    strategy_name: str,
    initial_cash: float = 10000.0,
    fast_period: int = 12,
    slow_period: int = 26,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> dict[str, Any]:
    if initial_cash <= 0:
        raise ValueError("initial_cash must be positive")
    close = _close_series(frame)
    if len(close) < 2:
        raise ValueError("at least two close prices are required")

    normalized_strategy = strategy_name.strip().lower()
    if normalized_strategy in {"buy_and_hold", "buy-hold", "buy hold"}:
        target_position = pd.Series(1, index=close.index, dtype=int)
    elif normalized_strategy in {"ema_cross", "ema-crossover", "ema crossover"}:
        if fast_period >= slow_period:
            raise ValueError("fast_period must be smaller than slow_period")
        target_position = (ema_series(close, fast_period) > ema_series(close, slow_period)).astype(int)
    else:
        raise ValueError("unsupported strategy_name; use buy_and_hold or ema_cross")

    cost_rate = (fee_bps + slippage_bps) / 10000.0
    effective_position = target_position.shift(1).fillna(0)
    price_returns = close.pct_change().fillna(0)
    turnover = target_position.diff().abs().fillna(target_position.abs())
    strategy_returns = (price_returns * effective_position) - (turnover * cost_rate)
    equity = (1 + strategy_returns).cumprod() * initial_cash
    drawdown = (equity / equity.cummax()) - 1
    trade_returns = _trade_returns(close, target_position, cost_rate=cost_rate)

    return {
        "strategy_name": normalized_strategy,
        "parameters": {
            "initial_cash": float(initial_cash),
            "fast_period": int(fast_period),
            "slow_period": int(slow_period),
            "fee_bps": float(fee_bps),
            "slippage_bps": float(slippage_bps),
        },
        "metrics": _metrics(equity, drawdown, trade_returns, initial_cash),
        "equity_curve": [
            {
                "date": _date_value(idx),
                "equity": float(equity_value),
                "drawdown": float(drawdown.loc[idx]),
                "strategy_return": float(strategy_returns.loc[idx]),
                "position": int(target_position.loc[idx]),
            }
            for idx, equity_value in equity.items()
        ],
    }


def _metrics(
    equity: pd.Series,
    drawdown: pd.Series,
    trade_returns: list[float],
    initial_cash: float,
) -> dict[str, Any]:
    total_return = float(equity.iloc[-1] / initial_cash - 1)
    wins = [value for value in trade_returns if value > 0]
    losses = [value for value in trade_returns if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = None
    else:
        profit_factor = 0.0

    return {
        "initial_cash": float(initial_cash),
        "final_equity": float(equity.iloc[-1]),
        "total_return": total_return,
        "max_drawdown": float(drawdown.min()),
        "trade_count": len(trade_returns),
        "win_rate": (len(wins) / len(trade_returns)) if trade_returns else 0.0,
        "average_win": (sum(wins) / len(wins)) if wins else 0.0,
        "average_loss": (sum(losses) / len(losses)) if losses else 0.0,
        "expectancy": (sum(trade_returns) / len(trade_returns)) if trade_returns else 0.0,
        "profit_factor": profit_factor,
    }


def _trade_returns(close: pd.Series, target_position: pd.Series, *, cost_rate: float) -> list[float]:
    returns: list[float] = []
    entry_price: float | None = None

    previous = 0
    for idx, position in target_position.items():
        current = int(position)
        price = float(close.loc[idx])
        if previous == 0 and current == 1:
            entry_price = price * (1 + cost_rate)
        elif previous == 1 and current == 0 and entry_price is not None:
            exit_price = price * (1 - cost_rate)
            returns.append(exit_price / entry_price - 1)
            entry_price = None
        previous = current

    if previous == 1 and entry_price is not None:
        exit_price = float(close.iloc[-1]) * (1 - cost_rate)
        returns.append(exit_price / entry_price - 1)
    return returns


def _close_series(frame: pd.DataFrame) -> pd.Series:
    if "close" not in frame.columns:
        raise ValueError("frame must contain a close column")
    close = pd.to_numeric(frame["close"], errors="coerce").dropna()
    if close.empty:
        raise ValueError("frame has no usable close prices")
    return close.astype(float)


def _date_value(index_value: Any) -> str:
    if hasattr(index_value, "date"):
        return index_value.date().isoformat()
    return str(index_value)
