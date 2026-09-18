import pandas as pd

from finance_lab.core.decision_backtesting import run_decision_replay_backtest_on_frames
from finance_lab.core.trade_style_fit import build_trade_style_fit


def row(horizon, decision, hold, bench, drawdown=-0.02):
    return {
        "horizon_days": horizon,
        "decision_return": decision,
        "buy_hold_return": hold,
        "benchmark_return": bench,
        "alpha_vs_buy_hold": decision - hold,
        "alpha_vs_benchmark": decision - bench if bench is not None else None,
        "asset_max_drawdown": drawdown,
    }


def make_frame(values):
    return pd.DataFrame(
        {"close": values, "low": values},
        index=pd.date_range("2024-01-02", periods=len(values), freq="D"),
    )


def test_trade_style_fit_scores_daily_profiles_and_flags_intraday_dataset():
    fit = build_trade_style_fit(
        {
            "horizons": [
                row(1, 0.01, 0.00, 0.00),
                row(2, 0.02, 0.00, 0.01),
                row(5, 0.03, 0.01, 0.01),
                row(10, 0.05, 0.02, 0.02),
                row(20, 0.08, 0.03, 0.03),
                row(60, -0.04, 0.10, 0.12, drawdown=-0.12),
            ]
        }
    )

    statuses = {style["style"]: style["status"] for style in fit["styles"]}
    assert statuses["scalping"] == "dataset_required"
    assert statuses["intraday"] == "dataset_required"
    assert statuses["short_term"] == "evaluated"
    assert statuses["swing"] == "evaluated"
    assert statuses["position"] == "evaluated"
    assert fit["best_style"] == "swing"
    assert fit["weakest_style"] == "position"


def test_decision_replay_includes_trade_style_fit_block():
    result = run_decision_replay_backtest_on_frames(
        make_frame([100, 101, 102, 103, 104, 105, 106]),
        final_state={"final_trade_decision": "**Rating**: Buy\n\nUse stop-loss at $95."},
        analysis_date="2024-01-02",
        symbol="TEST",
        benchmark_symbol="QQQ",
        benchmark_frame=make_frame([100, 100, 101, 101, 102, 102, 103]),
        horizons=(1, 2, 5),
    )

    assert result["ok"] is True
    fit = result["data"]["trade_style_fit"]
    assert fit["mode"] == "trade_style_fit"
    assert {style["style"] for style in fit["styles"]} >= {
        "scalping",
        "intraday",
        "short_term",
        "swing",
        "position",
    }
    assert fit["best_style"] in {"short_term", "swing"}
    gate = result["data"]["paper_trade_gate"]
    assert gate["mode"] == "paper_trade_gate"
    assert gate["candidate"] in {"yes", "no", "watchlist"}
