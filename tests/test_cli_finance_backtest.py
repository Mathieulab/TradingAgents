import pytest


def test_finance_backtest_window_uses_analysis_date():
    from cli.finance_backtest import finance_backtest_window

    assert finance_backtest_window("2024-06-30", 30) == ("2024-05-31", "2024-06-30")


def test_run_finance_backtest_skips_when_disabled(monkeypatch):
    from cli.finance_backtest import run_configured_finance_backtest

    called = False

    def fake_run_backtest(*args, **kwargs):
        nonlocal called
        called = True

    result = run_configured_finance_backtest(
        {"finance_backtest_enabled": False},
        "AAPL",
        "2024-06-30",
        runner=fake_run_backtest,
    )

    assert result is None
    assert called is False


def test_run_finance_backtest_calls_selected_backend(monkeypatch):
    from cli.finance_backtest import run_configured_finance_backtest

    captured = {}

    def fake_run_backtest(symbol, strategy_name, start, end, **kwargs):
        captured.update(
            {
                "symbol": symbol,
                "strategy_name": strategy_name,
                "start": start,
                "end": end,
                **kwargs,
            }
        )
        return {
            "ok": True,
            "data": {
                "strategy_name": strategy_name,
                "metrics": {
                    "final_equity": 1100.0,
                    "total_return": 0.1,
                    "max_drawdown": -0.02,
                    "trade_count": 1,
                    "win_rate": 1.0,
                },
            },
            "meta": {"backend": kwargs["backend"]},
        }

    result = run_configured_finance_backtest(
        {
            "finance_backtest_enabled": True,
            "finance_backtest_backend": "simple",
            "finance_backtest_strategy": "ema_cross",
            "finance_backtest_lookback_days": 30,
            "finance_backtest_initial_cash": 1000.0,
            "finance_backtest_fast_period": 3,
            "finance_backtest_slow_period": 8,
            "finance_backtest_fee_bps": 1.5,
            "finance_backtest_slippage_bps": 2.5,
        },
        "AAPL",
        "2024-06-30",
        runner=fake_run_backtest,
    )

    assert result["ok"] is True
    assert captured == {
        "symbol": "AAPL",
        "strategy_name": "ema_cross",
        "start": "2024-05-31",
        "end": "2024-06-30",
        "backend": "simple",
        "initial_cash": 1000.0,
        "fast_period": 3,
        "slow_period": 8,
        "fee_bps": 1.5,
        "slippage_bps": 2.5,
    }


def test_run_finance_backtest_uses_decision_replay_when_final_state_exists():
    from cli.finance_backtest import run_configured_finance_backtest

    captured = {}

    def fake_decision_runner(symbol, final_state, analysis_date, **kwargs):
        captured.update(
            {
                "symbol": symbol,
                "final_state": final_state,
                "analysis_date": analysis_date,
                **kwargs,
            }
        )
        return {"ok": True, "data": {"mode": "decision_replay"}}

    final_state = {"final_trade_decision": "**Rating**: Sell"}
    result = run_configured_finance_backtest(
        {
            "finance_backtest_enabled": True,
            "finance_backtest_mode": "decision_replay",
            "finance_backtest_benchmark": "QQQ",
            "finance_backtest_horizons": "5,20",
        },
        "AAPL",
        "2024-06-30",
        final_state,
        decision_runner=fake_decision_runner,
    )

    assert result["ok"] is True
    assert captured == {
        "symbol": "AAPL",
        "final_state": final_state,
        "analysis_date": "2024-06-30",
        "benchmark_symbol": "QQQ",
        "horizons": (5, 20),
    }


def test_parse_horizons():
    from cli.finance_backtest import parse_horizons

    assert parse_horizons("5, 20,60") == (5, 20, 60)
    assert parse_horizons("") == (1, 2, 5, 10, 20, 60, 120)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.1234, "12.34%"),
        (-0.0, "0.00%"),
        (-0.0000001, "0.00%"),
        (None, "n/a"),
    ],
)
def test_format_percent(value, expected):
    from cli.finance_backtest import format_percent

    assert format_percent(value) == expected
