import pytest

from finance_lab.core.storage import FinanceMemoryStore


def test_memory_store_saves_decision_and_strategy_memory(tmp_path):
    store = FinanceMemoryStore(tmp_path / "finance_memory.db")

    saved = store.save_trade_decision(
        "aapl",
        "buy",
        0.75,
        "Momentum remains constructive.",
        "buy_and_hold",
        metadata={"source": "test"},
    )

    assert saved["ok"] is True
    memory = store.get_strategy_memory(symbol="AAPL", strategy_name="buy_and_hold")
    assert memory["ok"] is True
    assert memory["data"]["decisions"][0]["symbol"] == "AAPL"
    assert memory["data"]["decisions"][0]["metadata"] == {"source": "test"}


def test_memory_store_records_trade_result(tmp_path):
    store = FinanceMemoryStore(tmp_path / "finance_memory.db")
    decision_id = store.save_trade_decision("MSFT", "BUY", 0.6, "Test thesis")["data"][
        "decision_id"
    ]

    result = store.save_trade_result(decision_id, 5, entry_price=100, exit_price=110)

    assert result["ok"] is True
    assert result["data"]["raw_return"] == pytest.approx(0.1)
    memory = store.get_strategy_memory(symbol="MSFT")
    decision = memory["data"]["decisions"][0]
    assert decision["status"] == "evaluated"
    assert decision["results"][0]["decision_return"] == pytest.approx(0.1)


def test_memory_store_records_decision_replay_result_and_learning_context(tmp_path):
    store = FinanceMemoryStore(tmp_path / "finance_memory.db")
    decision_id = store.save_trade_decision(
        "BTC-USD",
        "BUY",
        0.55,
        "Risk-on thesis.",
        "tradingagents_final_decision",
        metadata={"trade_date": "2026-02-20", "portfolio_rating": "Overweight"},
    )["data"]["decision_id"]

    result = store.save_decision_replay_result(
        decision_id,
        {
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

    assert result["ok"] is True
    assert result["data"]["saved_horizons"] == 1

    memory = store.get_strategy_memory(symbol="BTC-USD")
    decision = memory["data"]["decisions"][0]
    assert decision["status"] == "evaluated"
    assert decision["metadata"]["decision_replay"]["learning"]["verdict"].startswith("Useful")
    assert decision["replay_results"][0]["alpha_vs_benchmark"] == pytest.approx(0.0959)

    context = store.get_learning_context(symbol="BTC-USD")
    assert context["ok"] is True
    assert context["data"]["lesson_count"] == 1
    assert "Finance Lab replay outcome lessons" in context["data"]["context"]
    assert "risk control was weak" in context["data"]["context"]

    early_context = store.get_learning_context(symbol="BTC-USD", as_of_date="2026-02-01")
    assert early_context["ok"] is True
    assert early_context["data"]["lesson_count"] == 0
    assert early_context["data"]["context"] == ""

    known_context = store.get_learning_context(symbol="BTC-USD", as_of_date="2026-03-12")
    assert known_context["ok"] is True
    assert known_context["data"]["lesson_count"] == 1


def test_memory_store_upserts_global_strategy(tmp_path):
    store = FinanceMemoryStore(tmp_path / "finance_memory.db")

    first = store.save_strategy("ema_cross", description="first")
    second = store.save_strategy("ema_cross", description="updated")

    assert first["ok"] is True
    assert second["ok"] is True
    assert second["data"]["strategy_id"] == first["data"]["strategy_id"]


def test_memory_store_evaluates_with_injected_price_lookup(tmp_path):
    store = FinanceMemoryStore(tmp_path / "finance_memory.db")
    decision_id = store.save_trade_decision("SPY", "SELL", 0.55, "Downside risk")["data"][
        "decision_id"
    ]

    result = store.evaluate_trade_result(
        decision_id,
        3,
        price_lookup=lambda symbol, analysis_date, horizon_days: (100, 90),
    )

    assert result["ok"] is True
    assert result["data"]["raw_return"] == pytest.approx(-0.1)
    assert result["data"]["decision_return"] == pytest.approx(0.1)


def test_memory_store_validates_decision_inputs(tmp_path):
    store = FinanceMemoryStore(tmp_path / "finance_memory.db")

    result = store.save_trade_decision("AAPL", "WAIT", 0.5, "Invalid")

    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_ERROR"
