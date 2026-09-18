"""Deterministic finance-lab core functions.

This package intentionally has no TradingAgents graph dependency. MCP wrappers
and agent adapters should call these functions rather than reimplementing the
finance logic.
"""

from .backtesting import (
    run_backtest,
    run_backtest_on_frame,
    run_simple_backtest,
    run_simple_backtest_on_frame,
)
from .decision_backtesting import (
    run_decision_replay_backtest,
    run_decision_replay_backtest_on_frames,
)
from .indicators import (
    calculate_ema,
    calculate_ema_on_frame,
    calculate_macd,
    calculate_macd_on_frame,
    calculate_rsi,
    calculate_rsi_on_frame,
)
from .market_data import get_live_price, get_ohlcv
from .storage import FinanceMemoryStore
from .trade_gate import build_paper_trade_gate
from .trade_style_fit import build_trade_style_fit

__all__ = [
    "FinanceMemoryStore",
    "build_paper_trade_gate",
    "build_trade_style_fit",
    "calculate_ema",
    "calculate_ema_on_frame",
    "calculate_macd",
    "calculate_macd_on_frame",
    "calculate_rsi",
    "calculate_rsi_on_frame",
    "get_live_price",
    "get_ohlcv",
    "run_backtest",
    "run_backtest_on_frame",
    "run_decision_replay_backtest",
    "run_decision_replay_backtest_on_frames",
    "run_simple_backtest",
    "run_simple_backtest_on_frame",
]
