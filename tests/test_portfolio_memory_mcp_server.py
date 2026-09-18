import asyncio

import pytest

pytest.importorskip("mcp")

from finance_lab.mcp.servers.portfolio_memory_mcp.server import (  # noqa: E402
    create_server,
    memory_path_from_env,
)


def call_tool(server, name, arguments):
    result = asyncio.run(server.call_tool(name, arguments))
    if isinstance(result, tuple):
        return result[1]
    return result


def test_portfolio_memory_mcp_registers_expected_tools(tmp_path):
    server = create_server(tmp_path / "finance_memory.db")

    tools = asyncio.run(server.list_tools())

    assert {
        "health_check",
        "save_strategy",
        "save_trade_decision",
        "save_trade_result",
        "evaluate_trade_result",
        "get_strategy_memory",
        "summarize_strategy_memory",
    }.issubset({tool.name for tool in tools})


def test_portfolio_memory_mcp_saves_and_reads_paper_decisions(tmp_path):
    server = create_server(tmp_path / "finance_memory.db")

    saved = call_tool(
        server,
        "save_trade_decision",
        {
            "symbol": "aapl",
            "decision": "BUY",
            "confidence": 0.7,
            "thesis": "Breakout with improving risk/reward.",
            "strategy_name": "paper_breakout",
            "metadata": {"trade_date": "2024-01-02"},
        },
    )

    assert saved["ok"] is True
    decision_id = saved["data"]["decision_id"]

    result = call_tool(
        server,
        "save_trade_result",
        {
            "decision_id": decision_id,
            "horizon_days": 5,
            "entry_price": 100.0,
            "exit_price": 110.0,
        },
    )
    assert result["ok"] is True
    assert result["data"]["decision_return"] == pytest.approx(0.1)

    memory = call_tool(
        server,
        "get_strategy_memory",
        {"symbol": "AAPL", "strategy_name": "paper_breakout"},
    )

    assert memory["ok"] is True
    decision = memory["data"]["decisions"][0]
    assert decision["symbol"] == "AAPL"
    assert decision["decision"] == "BUY"
    assert decision["metadata"]["mode"] == "paper"
    assert decision["metadata"]["source"] == "portfolio_memory_mcp"
    assert decision["metadata"]["trade_date"] == "2024-01-02"
    assert decision["results"][0]["decision_return"] == pytest.approx(0.1)


def test_portfolio_memory_mcp_summarizes_recurring_outcomes(tmp_path):
    server = create_server(tmp_path / "finance_memory.db")

    hold = call_tool(
        server,
        "save_trade_decision",
        {
            "symbol": "MSFT",
            "decision": "HOLD",
            "confidence": 0.5,
            "thesis": "No edge.",
            "strategy_name": "paper_review",
        },
    )
    assert hold["ok"] is True
    call_tool(
        server,
        "save_trade_result",
        {
            "decision_id": hold["data"]["decision_id"],
            "horizon_days": 3,
            "entry_price": 100.0,
            "exit_price": 104.0,
        },
    )

    summary = call_tool(
        server,
        "summarize_strategy_memory",
        {"symbol": "MSFT", "strategy_name": "paper_review"},
    )

    assert summary["ok"] is True
    assert summary["data"]["decision_count"] == 1
    assert summary["data"]["evaluated_result_count"] == 1
    assert summary["data"]["decision_counts"]["HOLD"] == 1
    assert summary["data"]["recurring_mistakes"] == [
        {"type": "missed_move_on_hold", "count": 1}
    ]


def test_memory_path_defaults_to_env(monkeypatch, tmp_path):
    db_path = tmp_path / "env_memory.db"
    monkeypatch.setenv("TRADINGAGENTS_FINANCE_MEMORY_PATH", str(db_path))

    assert memory_path_from_env() == db_path
