"""CLI helpers for optional Finance Lab backtesting."""

from __future__ import annotations

import datetime
from collections.abc import Callable
from typing import Any

from finance_lab.core.responses import fail
from tradingagents.integrations.finance_mcp_adapter import (
    run_backtest,
    run_decision_replay_backtest,
)

BacktestRunner = Callable[..., dict[str, Any]]


def run_configured_finance_backtest(
    config: dict[str, Any],
    ticker: str,
    analysis_date: str,
    final_state: dict[str, Any] | None = None,
    *,
    runner: BacktestRunner = run_backtest,
    decision_runner: BacktestRunner = run_decision_replay_backtest,
) -> dict[str, Any] | None:
    """Run the optional Finance Lab backtest from CLI configuration."""
    if not config.get("finance_backtest_enabled"):
        return None

    try:
        mode = str(config.get("finance_backtest_mode", "decision_replay")).strip().lower()
        if mode == "decision_replay" and final_state:
            return decision_runner(
                ticker,
                final_state,
                analysis_date,
                benchmark_symbol=str(
                    config.get("finance_backtest_benchmark")
                    or config.get("benchmark_ticker")
                    or "SPY"
                ),
                horizons=parse_horizons(str(config.get("finance_backtest_horizons", "1,2,5,10,20,60,120"))),
            )

        start, end = finance_backtest_window(
            analysis_date,
            int(config.get("finance_backtest_lookback_days", 365)),
        )
        return runner(
            ticker,
            str(config.get("finance_backtest_strategy", "buy_and_hold")),
            start,
            end,
            backend=str(config.get("finance_backtest_backend", "simple")),
            initial_cash=float(config.get("finance_backtest_initial_cash", 10000.0)),
            fast_period=int(config.get("finance_backtest_fast_period", 12)),
            slow_period=int(config.get("finance_backtest_slow_period", 26)),
            fee_bps=float(config.get("finance_backtest_fee_bps", 0.0)),
            slippage_bps=float(config.get("finance_backtest_slippage_bps", 0.0)),
        )
    except Exception as exc:  # noqa: BLE001 - optional lab tooling must fail open
        return fail(str(exc), code="BACKTEST_ERROR")


def finance_backtest_window(analysis_date: str, lookback_days: int) -> tuple[str, str]:
    """Return the date window used for post-analysis backtesting."""
    end_date = datetime.datetime.strptime(analysis_date, "%Y-%m-%d").date()
    days = max(1, int(lookback_days))
    start_date = end_date - datetime.timedelta(days=days)
    return start_date.isoformat(), end_date.isoformat()


def parse_horizons(value: str) -> tuple[int, ...]:
    horizons = tuple(
        int(part.strip())
        for part in value.split(",")
        if part.strip()
    )
    return horizons or (1, 2, 5, 10, 20, 60, 120)


def format_percent(value: Any) -> str:
    if value is None:
        return "n/a"
    percent = float(value) * 100
    if abs(percent) < 0.005:
        percent = 0.0
    return f"{percent:.2f}%"


def format_money(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"${float(value):,.2f}"
