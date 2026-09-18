"""MCP server for Finance Lab paper-trading memory.

This server exposes local SQLite research memory only. It does not connect to a
broker and does not implement real-money order execution.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any, Literal

from finance_lab.core import FinanceMemoryStore
from finance_lab.core.responses import fail, ok

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:  # pragma: no cover - exercised only without mcp extra
    FastMCP = None  # type: ignore[assignment]

DEFAULT_MEMORY_PATH = Path.home() / ".tradingagents" / "finance" / "finance_memory.db"
MEMORY_PATH_ENV = "TRADINGAGENTS_FINANCE_MEMORY_PATH"


def memory_path_from_env() -> Path:
    """Return the configured Finance Lab memory path."""
    value = os.environ.get(MEMORY_PATH_ENV)
    if value and value.strip():
        return Path(value).expanduser()
    return DEFAULT_MEMORY_PATH


def create_server(
    memory_path: str | Path | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> Any:
    """Create the Portfolio Memory MCP server."""
    if FastMCP is None:
        raise RuntimeError(
            "The mcp package is required to run this server. "
            "Install with: pip install 'tradingagents[mcp]'"
        )

    db_path = Path(memory_path).expanduser() if memory_path else memory_path_from_env()
    server = FastMCP(
        "finance-lab-portfolio-memory",
        instructions=(
            "Paper-trading memory tools for Finance Lab. "
            "These tools never place broker orders."
        ),
        host=host,
        port=port,
    )

    def store() -> FinanceMemoryStore:
        return FinanceMemoryStore(db_path)

    @server.tool()
    def health_check() -> dict[str, Any]:
        """Confirm the memory database path and server mode."""
        store()
        return ok(
            {
                "server": "finance-lab-portfolio-memory",
                "memory_path": str(db_path),
                "mode": "paper",
                "real_trading_enabled": False,
            }
        )

    @server.tool()
    def save_strategy(
        strategy_name: str,
        symbol: str | None = None,
        description: str = "",
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Save or update a paper-trading strategy definition."""
        return store().save_strategy(
            strategy_name,
            symbol=symbol,
            description=description,
            parameters=parameters,
        )

    @server.tool()
    def save_trade_decision(
        symbol: str,
        decision: Literal["BUY", "HOLD", "SELL"],
        confidence: float,
        thesis: str,
        strategy_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Save a paper-trading decision for later review."""
        paper_metadata = {
            **(metadata or {}),
            "mode": "paper",
            "source": "portfolio_memory_mcp",
        }
        return store().save_trade_decision(
            symbol=symbol,
            decision=decision,
            confidence=confidence,
            thesis=thesis,
            strategy_name=strategy_name,
            metadata=paper_metadata,
        )

    @server.tool()
    def save_trade_result(
        decision_id: int,
        horizon_days: int,
        entry_price: float,
        exit_price: float,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Save a deterministic paper-trade result from known prices."""
        paper_metadata = {
            **(metadata or {}),
            "mode": "paper",
            "source": "portfolio_memory_mcp",
        }
        return store().save_trade_result(
            decision_id=decision_id,
            horizon_days=horizon_days,
            entry_price=entry_price,
            exit_price=exit_price,
            metadata=paper_metadata,
        )

    @server.tool()
    def evaluate_trade_result(decision_id: int, horizon_days: int) -> dict[str, Any]:
        """Evaluate a saved decision using the configured market-data provider."""
        return store().evaluate_trade_result(
            decision_id=decision_id,
            horizon_days=horizon_days,
        )

    @server.tool()
    def get_strategy_memory(
        symbol: str | None = None,
        strategy_name: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Return recent paper-trading decisions and their saved results."""
        bounded_limit = _validate_limit(limit)
        if isinstance(bounded_limit, dict):
            return bounded_limit
        return store().get_strategy_memory(
            symbol=symbol,
            strategy_name=strategy_name,
            limit=bounded_limit,
        )

    @server.tool()
    def summarize_strategy_memory(
        symbol: str | None = None,
        strategy_name: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Summarize recurring outcomes from paper-trading memory."""
        bounded_limit = _validate_limit(limit)
        if isinstance(bounded_limit, dict):
            return bounded_limit
        memory = store().get_strategy_memory(
            symbol=symbol,
            strategy_name=strategy_name,
            limit=bounded_limit,
        )
        if not memory.get("ok"):
            return memory
        return ok(_summarize_decisions(memory["data"]["decisions"]))

    return server


def _validate_limit(limit: int) -> int | dict[str, Any]:
    value = int(limit)
    if value < 1:
        return fail("limit must be positive", code="VALIDATION_ERROR")
    if value > 500:
        return fail("limit must be 500 or less", code="VALIDATION_ERROR")
    return value


def _summarize_decisions(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    decision_counts = {"BUY": 0, "HOLD": 0, "SELL": 0}
    status_counts: dict[str, int] = {}
    evaluated_results: list[dict[str, Any]] = []
    mistake_counts = {
        "directional_call_loss": 0,
        "missed_move_on_hold": 0,
    }

    for decision in decisions:
        decision_value = decision.get("decision")
        if decision_value in decision_counts:
            decision_counts[decision_value] += 1
        status = str(decision.get("status", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1
        for result in decision.get("results", []):
            evaluated_results.append(result)
            decision_return = float(result.get("decision_return", 0.0))
            raw_return = float(result.get("raw_return", 0.0))
            if decision_value in {"BUY", "SELL"} and decision_return < 0:
                mistake_counts["directional_call_loss"] += 1
            if decision_value == "HOLD" and abs(raw_return) >= 0.02:
                mistake_counts["missed_move_on_hold"] += 1

    decision_returns = [float(result["decision_return"]) for result in evaluated_results]
    average_decision_return = (
        sum(decision_returns) / len(decision_returns) if decision_returns else None
    )
    win_rate = (
        len([value for value in decision_returns if value > 0]) / len(decision_returns)
        if decision_returns
        else None
    )
    recurring_mistakes = [
        {"type": name, "count": count}
        for name, count in mistake_counts.items()
        if count > 0
    ]

    return {
        "decision_count": len(decisions),
        "evaluated_result_count": len(evaluated_results),
        "decision_counts": decision_counts,
        "status_counts": status_counts,
        "average_decision_return": average_decision_return,
        "win_rate": win_rate,
        "recurring_mistakes": recurring_mistakes,
    }


def main(argv: list[str] | None = None) -> None:
    """Run the MCP server."""
    parser = argparse.ArgumentParser(description="Run the Finance Lab portfolio memory MCP server.")
    parser.add_argument("--memory-path", default=None, help=f"SQLite path. Defaults to ${MEMORY_PATH_ENV}.")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="MCP transport.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP transport host.")
    parser.add_argument("--port", type=int, default=8765, help="HTTP transport port.")
    args = parser.parse_args(argv)

    server = create_server(args.memory_path, host=args.host, port=args.port)
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
