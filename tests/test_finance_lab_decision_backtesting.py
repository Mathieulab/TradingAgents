import pandas as pd
import pytest

from finance_lab.core.decision_backtesting import run_decision_replay_backtest_on_frames


def make_frame(values, lows=None):
    return pd.DataFrame(
        {
            "close": values,
            "low": lows or values,
        },
        index=pd.date_range("2024-01-02", periods=len(values), freq="D"),
    )


def final_state(text):
    return {"final_trade_decision": text}


def test_decision_replay_buy_respects_stop_loss():
    result = run_decision_replay_backtest_on_frames(
        make_frame([100, 98, 95, 110, 120], lows=[100, 97, 94, 109, 119]),
        final_state=final_state("**Rating**: Buy\n\nUse a stop-loss at $96."),
        analysis_date="2024-01-02",
        symbol="TEST",
        horizons=(2, 4),
    )

    assert result["ok"] is True
    data = result["data"]
    assert data["action"] == "Buy"
    assert data["stop_loss"] == 96
    first = data["horizons"][0]
    assert first["stop_hit"] is True
    assert first["stop_date"] == "2024-01-04"
    assert first["decision_return"] == pytest.approx(-0.04)
    assert first["buy_hold_return"] == pytest.approx(-0.05)


def test_decision_replay_underweight_trim_reduces_exposure():
    result = run_decision_replay_backtest_on_frames(
        make_frame([100, 90, 80, 70, 60]),
        final_state=final_state("**Rating**: Underweight\n\nTrim 20% of current holdings."),
        analysis_date="2024-01-02",
        symbol="TEST",
        horizons=(4,),
    )

    assert result["ok"] is True
    row = result["data"]["horizons"][0]
    assert result["data"]["action"] == "Sell"
    assert result["data"]["post_decision_exposure"] == pytest.approx(0.8)
    assert row["buy_hold_return"] == pytest.approx(-0.4)
    assert row["decision_return"] == pytest.approx(-0.32)
    assert row["alpha_vs_buy_hold"] == pytest.approx(0.08)
    assert result["data"]["summary"]["average_alpha_vs_buy_hold"] == pytest.approx(0.08)
    assert result["data"]["summary"]["positive_alpha_vs_buy_hold"] == 1
    assert result["data"]["summary"]["average_decision_return"] == pytest.approx(-0.32)
    assert result["data"]["learning"]["verdict"]


def test_decision_replay_full_sell_flat_return_learning_is_not_negative():
    result = run_decision_replay_backtest_on_frames(
        make_frame([100, 99, 98, 112]),
        benchmark_frame=make_frame([100, 101, 102, 120]),
        final_state=final_state("**Rating**: Sell\n\nExit the position."),
        analysis_date="2024-01-02",
        symbol="TEST",
        benchmark_symbol="QQQ",
        horizons=(1, 2, 3),
    )

    assert result["ok"] is True
    data = result["data"]
    assert data["post_decision_exposure"] == 0.0
    assert data["summary"]["average_decision_return"] == pytest.approx(0.0)
    assert data["summary"]["best_decision_return_horizon"] is None
    assert data["summary"]["worst_decision_return_horizon"] is None
    assert any("average decision return was flat" in lesson for lesson in data["learning"]["lessons"])
    assert not any("average decision return was negative" in lesson for lesson in data["learning"]["lessons"])


def test_decision_replay_compares_to_benchmark():
    result = run_decision_replay_backtest_on_frames(
        make_frame([100, 102, 104, 106]),
        benchmark_frame=make_frame([100, 101, 102, 103]),
        final_state=final_state("**Rating**: Hold"),
        analysis_date="2024-01-02",
        symbol="TEST",
        benchmark_symbol="SPY",
        horizons=(3,),
    )

    assert result["ok"] is True
    row = result["data"]["horizons"][0]
    assert result["data"]["action"] == "Hold"
    assert row["decision_return"] == pytest.approx(0.06)
    assert row["benchmark_return"] == pytest.approx(0.03)
    assert row["alpha_vs_benchmark"] == pytest.approx(0.03)
    assert result["data"]["summary"]["best_decision_return_horizon"] == 3
    assert result["data"]["summary"]["worst_decision_return_horizon"] == 3


def test_decision_replay_converts_relative_stop_below_close():
    result = run_decision_replay_backtest_on_frames(
        make_frame([739.30, 735.00, 732.00], lows=[739.30, 727.00, 731.00]),
        final_state=final_state(
            "**Rating**: Hold\n\nMaintain current position with ATR-based stops "
            "(11.52 below close)."
        ),
        analysis_date="2024-01-02",
        symbol="TEST",
        horizons=(2,),
    )

    assert result["ok"] is True
    data = result["data"]
    assert data["stop_loss"] == pytest.approx(727.78)
    row = data["horizons"][0]
    assert row["stop_hit"] is True
    assert row["stop_date"] == "2024-01-03"
    assert row["decision_return"] == pytest.approx(727.78 / 739.30 - 1)


def test_decision_replay_disables_benchmark_alpha_for_same_symbol():
    result = run_decision_replay_backtest_on_frames(
        make_frame([100, 99, 98, 97]),
        benchmark_frame=make_frame([100, 200, 300, 400]),
        final_state=final_state("**Rating**: Hold"),
        analysis_date="2024-01-02",
        symbol="SPY",
        benchmark_symbol="spy",
        horizons=(3,),
    )

    assert result["ok"] is True
    data = result["data"]
    row = data["horizons"][0]
    assert data["benchmark_identity_match"] is True
    assert "benchmark alpha is disabled" in data["benchmark_warning"]
    assert row["benchmark_return"] is None
    assert row["alpha_vs_benchmark"] is None
    assert data["summary"]["average_alpha_vs_benchmark"] is None
    assert "benchmark edge was not evaluated" in data["learning"]["verdict"]


def test_decision_replay_reports_pending_when_no_forward_horizon_exists():
    result = run_decision_replay_backtest_on_frames(
        make_frame([100]),
        final_state=final_state("**Rating**: Buy"),
        analysis_date="2024-01-02",
        symbol="TEST",
        horizons=(5,),
    )

    assert result["ok"] is True
    assert result["data"]["status"] == "pending"
    assert result["data"]["horizons"] == []
    assert result["data"]["pending_horizons"] == [5]


def test_decision_replay_reports_pending_when_no_entry_bar_exists():
    result = run_decision_replay_backtest_on_frames(
        make_frame([100]),
        final_state=final_state("**Rating**: Hold"),
        analysis_date="2024-01-10",
        symbol="TEST",
        horizons=(5,),
    )

    assert result["ok"] is True
    assert result["data"]["status"] == "pending"
    assert result["data"]["entry_date"] is None
    assert result["data"]["pending_reason"] == "no forward price data on or after analysis_date"
    assert result["data"]["pending_horizons"] == [5]
