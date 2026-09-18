from pathlib import Path

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.integrations.finance_mcp_adapter import (
    get_finance_learning_context,
    get_strategy_memory,
    save_decision_replay_to_finance_memory,
    save_final_decision_to_finance_memory,
)


def config_for(tmp_path, enabled=True):
    config = DEFAULT_CONFIG.copy()
    config["finance_memory_enabled"] = enabled
    config["finance_memory_path"] = str(tmp_path / "finance_memory.db")
    return config


def test_default_finance_research_enabled_with_mcp_opt_in():
    assert DEFAULT_CONFIG["finance_mcp_enabled"] is False
    assert DEFAULT_CONFIG["finance_memory_enabled"] is True
    assert DEFAULT_CONFIG["finance_backtest_enabled"] is True
    assert DEFAULT_CONFIG["finance_backtest_mode"] == "decision_replay"
    assert DEFAULT_CONFIG["finance_backtest_backend"] == "simple"
    assert DEFAULT_CONFIG["finance_mcp_url"]
    assert DEFAULT_CONFIG["finance_memory_path"]
    assert DEFAULT_CONFIG["chart_output_dir"]


def test_save_final_decision_skips_when_finance_memory_disabled(tmp_path):
    config = config_for(tmp_path, enabled=False)

    result = save_final_decision_to_finance_memory(
        config,
        symbol="AAPL",
        final_state={"final_trade_decision": "**Rating**: Buy\n\nTest thesis"},
        trade_date="2024-01-02",
    )

    assert result["ok"] is True
    assert result["data"]["saved"] is False
    assert not Path(config["finance_memory_path"]).exists()


def test_save_final_decision_persists_to_sqlite_when_enabled(tmp_path):
    config = config_for(tmp_path)

    result = save_final_decision_to_finance_memory(
        config,
        symbol="aapl",
        final_state={"final_trade_decision": "**Rating**: Overweight\n\nTest thesis"},
        trade_date="2024-01-02",
    )

    assert result["ok"] is True
    assert result["data"]["saved"] is True
    assert result["data"]["decision"] == "BUY"
    assert result["data"]["portfolio_rating"] == "Overweight"

    memory = get_strategy_memory(config, symbol="AAPL")
    decision = memory["data"]["decisions"][0]
    assert decision["symbol"] == "AAPL"
    assert decision["decision"] == "BUY"
    assert decision["confidence"] == 0.55
    assert decision["metadata"]["trade_date"] == "2024-01-02"


def test_save_final_decision_maps_underweight_to_sell(tmp_path):
    config = config_for(tmp_path)

    result = save_final_decision_to_finance_memory(
        config,
        symbol="MSFT",
        final_state={"final_trade_decision": "**Rating**: Underweight\n\nRisk thesis"},
    )

    assert result["ok"] is True
    assert result["data"]["decision"] == "SELL"


def test_adapter_saves_decision_replay_and_returns_learning_context(tmp_path):
    config = config_for(tmp_path)
    saved = save_final_decision_to_finance_memory(
        config,
        symbol="BTC-USD",
        final_state={"final_trade_decision": "**Rating**: Overweight\n\nRisk-on thesis"},
        trade_date="2026-02-20",
    )
    decision_id = saved["data"]["decision_id"]

    replay = save_decision_replay_to_finance_memory(
        config,
        decision_id=decision_id,
        replay_result={
            "ok": True,
            "data": {
                "mode": "decision_replay",
                "symbol": "BTC-USD",
                "action": "Buy",
                "rating": "Overweight",
                "entry_date": "2026-02-20",
                "entry_price": 68005.42,
                "benchmark_symbol": "SPY",
                "pending_horizons": [],
                "status": "evaluated",
                "summary": {
                    "average_decision_return": 0.0258,
                    "average_alpha_vs_benchmark": 0.0505,
                    "worst_asset_max_drawdown": -0.259,
                },
                "learning": {
                    "verdict": "Useful call, but risk control was weak.",
                    "lessons": ["Future Buy decisions should include a stop-loss."],
                },
                "horizons": [
                    {
                        "horizon_days": 20,
                        "entry_date": "2026-02-20",
                        "entry_price": 68005.42,
                        "exit_date": "2026-03-12",
                        "exit_price": 70494.42,
                        "decision_return": 0.0366,
                        "buy_hold_return": 0.0366,
                        "benchmark_return": -0.0593,
                        "alpha_vs_buy_hold": 0.0,
                        "alpha_vs_benchmark": 0.0959,
                        "asset_max_drawdown": -0.0927,
                        "stop_loss": None,
                        "stop_hit": False,
                        "stop_date": None,
                    }
                ],
            },
        },
    )

    assert replay["ok"] is True
    assert replay["data"]["saved"] is True
    context = get_finance_learning_context(config, symbol="BTC-USD")
    assert context["ok"] is True
    assert context["data"]["lesson_count"] == 1
    assert "risk control was weak" in context["data"]["context"]

    early_context = get_finance_learning_context(
        config,
        symbol="BTC-USD",
        as_of_date="2026-02-01",
    )
    assert early_context["ok"] is True
    assert early_context["data"]["lesson_count"] == 0
