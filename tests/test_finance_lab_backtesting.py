import pandas as pd
import pytest

from finance_lab.core.backtesting import run_backtest_on_frame, run_simple_backtest_on_frame


def make_frame(values):
    return pd.DataFrame(
        {"close": values},
        index=pd.date_range("2024-01-01", periods=len(values), freq="D"),
    )


def test_buy_and_hold_backtest_reports_positive_return():
    result = run_simple_backtest_on_frame(
        make_frame([100, 105, 110]),
        strategy_name="buy_and_hold",
        initial_cash=1000,
    )

    assert result["metrics"]["final_equity"] == pytest.approx(1100)
    assert result["metrics"]["total_return"] == pytest.approx(0.10)
    assert result["metrics"]["trade_count"] == 1
    assert len(result["equity_curve"]) == 3


def test_ema_cross_backtest_returns_metrics_and_curve():
    result = run_simple_backtest_on_frame(
        make_frame(list(range(100, 170))),
        strategy_name="ema_cross",
        fast_period=3,
        slow_period=8,
    )

    assert result["strategy_name"] == "ema_cross"
    assert result["metrics"]["trade_count"] >= 1
    assert result["metrics"]["max_drawdown"] <= 0
    assert result["equity_curve"][-1]["equity"] > 0


def test_backtest_rejects_unknown_strategy():
    with pytest.raises(ValueError, match="unsupported strategy_name"):
        run_simple_backtest_on_frame(make_frame([100, 101]), strategy_name="unknown")


def test_backtest_selector_runs_simple_backend():
    result = run_backtest_on_frame(
        make_frame([100, 105, 110]),
        strategy_name="buy_and_hold",
        backend="simple",
        initial_cash=1000,
    )

    assert result["metrics"]["final_equity"] == pytest.approx(1100)


def test_backtest_selector_reports_unknown_backend():
    result = run_backtest_on_frame(
        make_frame([100, 105, 110]),
        strategy_name="buy_and_hold",
        backend="unknown",
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_ERROR"


def test_nautilus_backend_reports_missing_dependency(monkeypatch):
    from finance_lab.core import nautilus_backtesting

    monkeypatch.setattr(nautilus_backtesting, "is_nautilus_available", lambda: False)

    result = run_backtest_on_frame(
        make_frame([100, 105, 110]),
        symbol="AAPL",
        strategy_name="buy_and_hold",
        backend="nautilus",
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "MISSING_DEPENDENCY"
    assert "tradingagents[nautilus]" in result["error"]["details"]["install_hint"]
