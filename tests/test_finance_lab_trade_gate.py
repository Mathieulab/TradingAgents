from finance_lab.core.trade_gate import build_paper_trade_gate


def style_fit(*, fit="Strong", avg_return=0.04, alpha_bench=0.03, drawdown=-0.04):
    return {
        "best_style": "swing",
        "styles": [
            {
                "style": "swing",
                "label": "Swing",
                "status": "evaluated",
                "fit": fit,
                "score": 0.05,
                "average_decision_return": avg_return,
                "average_alpha_vs_hold": 0.02,
                "average_alpha_vs_buy_hold": 0.02,
                "average_alpha_vs_benchmark": alpha_bench,
                "worst_asset_max_drawdown": drawdown,
            }
        ],
    }


def test_paper_trade_gate_allows_strong_buy_with_stop():
    gate = build_paper_trade_gate(
        {
            "action": "Buy",
            "stop_loss": 95.0,
            "trade_style_fit": style_fit(),
        }
    )

    assert gate["candidate"] == "yes"
    assert gate["execution_intent"] == "paper_long"
    assert gate["position_size"] == 0.5
    assert gate["requires_manual_approval"] is True
    assert "stop_loss_present" in gate["passed_rules"]


def test_paper_trade_gate_rejects_buy_without_stop():
    gate = build_paper_trade_gate(
        {
            "action": "Buy",
            "stop_loss": None,
            "trade_style_fit": style_fit(),
        }
    )

    assert gate["candidate"] == "no"
    assert gate["position_size"] == 0.0
    assert "missing_stop_loss" in gate["failed_rules"]


def test_paper_trade_gate_does_not_execute_hold_as_new_entry():
    gate = build_paper_trade_gate(
        {
            "action": "Hold",
            "stop_loss": 95.0,
            "trade_style_fit": style_fit(fit="Weak", avg_return=-0.01, alpha_bench=0.01),
        }
    )

    assert gate["candidate"] == "no"
    assert gate["execution_intent"] == "skip"
    assert "hold_is_not_new_entry" in gate["failed_rules"]


def test_paper_trade_gate_requires_position_context_for_sell():
    gate = build_paper_trade_gate(
        {
            "action": "Sell",
            "stop_loss": 95.0,
            "trade_style_fit": style_fit(fit="Strong", avg_return=0.02, alpha_bench=0.03),
        }
    )

    assert gate["candidate"] == "watchlist"
    assert gate["execution_intent"] == "reduce_or_exit_existing"
    assert gate["position_size"] == 0.0
    assert "position_context_required" in gate["failed_rules"]
