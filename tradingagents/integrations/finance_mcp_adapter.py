"""Thin adapter between TradingAgents and Finance Lab.

The current implementation calls the local ``finance_lab.core`` functions
directly. The public functions are intentionally shaped like an MCP client so a
future transport layer can replace the internals without changing graph code.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from finance_lab.core import (
    FinanceMemoryStore,
    calculate_ema,
    calculate_macd,
    calculate_rsi,
    get_live_price,
    get_ohlcv,
    run_backtest,
    run_decision_replay_backtest,
    run_simple_backtest,
)
from finance_lab.core.responses import fail, ok

logger = logging.getLogger(__name__)

DEFAULT_STRATEGY_NAME = "tradingagents_final_decision"
_RATING_LABEL_RE = re.compile(r"rating.*?[:\-][\s*]*(\w+)", re.IGNORECASE)
_RATING_SET = {"buy", "overweight", "hold", "underweight", "sell"}


def save_final_decision_to_finance_memory(
    config: dict[str, Any],
    *,
    symbol: str,
    final_state: dict[str, Any],
    trade_date: str | None = None,
) -> dict[str, Any]:
    """Persist the final TradingAgents decision to Finance Lab SQLite memory.

    This is intentionally optional and fail-open. It must not block analysis
    completion if the lab database is unavailable.
    """
    if not config.get("finance_memory_enabled", False):
        return ok({"saved": False, "reason": "finance_memory_disabled"})

    final_decision = final_state.get("final_trade_decision")
    if not isinstance(final_decision, str) or not final_decision.strip():
        return fail("final_state is missing final_trade_decision", code="VALIDATION_ERROR")

    rating = _parse_rating(final_decision)
    decision = _rating_to_trade_decision(rating)
    confidence = _confidence_from_rating(rating)
    store = FinanceMemoryStore(_finance_memory_path(config))
    result = store.save_trade_decision(
        symbol=symbol,
        decision=decision,
        confidence=confidence,
        thesis=final_decision,
        strategy_name=DEFAULT_STRATEGY_NAME,
        metadata={
            "source": "tradingagents",
            "trade_date": trade_date,
            "portfolio_rating": rating,
            "confidence_source": "rating_heuristic",
        },
    )
    if result.get("ok"):
        result["data"]["saved"] = True
        result["data"]["decision"] = decision
        result["data"]["portfolio_rating"] = rating
    return result


def save_trade_decision(
    config: dict[str, Any],
    *,
    symbol: str,
    decision: str,
    confidence: float,
    thesis: str,
    strategy_name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    store = FinanceMemoryStore(_finance_memory_path(config))
    return store.save_trade_decision(
        symbol=symbol,
        decision=decision,
        confidence=confidence,
        thesis=thesis,
        strategy_name=strategy_name,
        metadata=metadata,
    )


def evaluate_trade_result(
    config: dict[str, Any],
    *,
    decision_id: int,
    horizon_days: int,
) -> dict[str, Any]:
    store = FinanceMemoryStore(_finance_memory_path(config))
    return store.evaluate_trade_result(decision_id, horizon_days)


def save_decision_replay_to_finance_memory(
    config: dict[str, Any],
    *,
    decision_id: int,
    replay_result: dict[str, Any],
) -> dict[str, Any]:
    """Persist evaluated decision-replay horizons and lessons."""
    if not config.get("finance_memory_enabled", False):
        return ok({"saved": False, "reason": "finance_memory_disabled"})
    store = FinanceMemoryStore(_finance_memory_path(config))
    result = store.save_decision_replay_result(decision_id, replay_result)
    if result.get("ok"):
        result["data"]["saved"] = True
    return result


def get_strategy_memory(
    config: dict[str, Any],
    *,
    symbol: str | None = None,
    strategy_name: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    store = FinanceMemoryStore(_finance_memory_path(config))
    return store.get_strategy_memory(
        symbol=symbol,
        strategy_name=strategy_name,
        limit=limit,
    )


def get_finance_learning_context(
    config: dict[str, Any],
    *,
    symbol: str | None = None,
    strategy_name: str | None = DEFAULT_STRATEGY_NAME,
    as_of_date: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Return compact Finance Lab outcome lessons for agent prompt injection."""
    if not config.get("finance_memory_enabled", False):
        return ok({"context": "", "lesson_count": 0, "reason": "finance_memory_disabled"})
    store = FinanceMemoryStore(_finance_memory_path(config))
    return store.get_learning_context(
        symbol=symbol,
        strategy_name=strategy_name,
        as_of_date=as_of_date,
        limit=limit,
    )


def _finance_memory_path(config: dict[str, Any]) -> Path:
    path = config.get("finance_memory_path")
    if path:
        return Path(path).expanduser()
    data_cache_dir = config.get("data_cache_dir")
    if data_cache_dir:
        return Path(data_cache_dir).expanduser() / "finance_memory.db"
    return Path.home() / ".tradingagents" / "finance" / "finance_memory.db"


def _rating_to_trade_decision(rating: str) -> str:
    normalized = rating.strip().lower()
    if normalized in {"buy", "overweight"}:
        return "BUY"
    if normalized in {"sell", "underweight"}:
        return "SELL"
    return "HOLD"


def _parse_rating(text: str, default: str = "Hold") -> str:
    for line in text.splitlines():
        match = _RATING_LABEL_RE.search(line)
        if match and match.group(1).lower() in _RATING_SET:
            return match.group(1).capitalize()

    for line in text.splitlines():
        for word in line.lower().split():
            clean = word.strip("*:.,")
            if clean in _RATING_SET:
                return clean.capitalize()

    return default


def _confidence_from_rating(rating: str) -> float:
    """Conservative numeric confidence until PM output has a native score."""
    normalized = rating.strip().lower()
    if normalized in {"buy", "sell"}:
        return 0.6
    if normalized in {"overweight", "underweight"}:
        return 0.55
    return 0.5


__all__ = [
    "calculate_ema",
    "calculate_macd",
    "calculate_rsi",
    "evaluate_trade_result",
    "get_live_price",
    "get_ohlcv",
    "get_finance_learning_context",
    "get_strategy_memory",
    "run_backtest",
    "run_decision_replay_backtest",
    "run_simple_backtest",
    "save_decision_replay_to_finance_memory",
    "save_final_decision_to_finance_memory",
    "save_trade_decision",
]
