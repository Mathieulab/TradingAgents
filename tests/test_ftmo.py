import asyncio
import json
import xml.etree.ElementTree as ET

import pandas as pd
import pytest

from finance_lab.ftmo.config import TestConfig, rule_headroom
from finance_lab.ftmo.data import demo_bars, load_csv, swing_candles, validate_bars
from finance_lab.ftmo.engine import add_swing_features, evaluate, financing_cost, run_backtest
from finance_lab.ftmo.report import save_run

SIGNAL = 127
ENTRY = SIGNAL + 1


def short_config():
    return TestConfig(fast_period=3, slow_period=5, breakout_period=3, atr_period=3)


def breakout_frame(*, short=False, gap=False):
    index = pd.date_range("2025-01-06", periods=400, freq="15min", tz="UTC")
    frame = pd.DataFrame(
        {"open": 1.1, "close": 1.1, "high": 1.1001, "low": 1.0999, "volume": 100}, index=index
    )
    frame.loc[index[SIGNAL], ["close", "high"]] = [1.102, 1.1021]
    frame.loc[index[ENTRY], ["open", "close", "high", "low"]] = [1.102, 1.102, 1.12, 1.08]
    if gap:
        frame.loc[index[ENTRY], ["high", "low"]] = [1.1021, 1.1019]
        frame.loc[index[ENTRY + 1], ["open", "close", "high", "low"]] = [0.94, 0.941, 0.945, 0.92]
    if short:
        old = frame.copy()
        frame["open"] = 2.2 - old.open
        frame["close"] = 2.2 - old.close
        frame["high"] = 2.2 - old.low
        frame["low"] = 2.2 - old.high
    return frame


@pytest.mark.parametrize("short", [False, True])
def test_entry_uses_next_open_and_stop_wins_on_ambiguous_entry_bar(short):
    frame = breakout_frame(short=short)
    result = run_backtest(frame, short_config())
    trade = result["trades"][0]
    direction = -1 if short else 1
    assert pd.Timestamp(trade["signal_time"]) == frame.index[SIGNAL]
    assert pd.Timestamp(trade["entry_time"]) == frame.index[ENTRY]
    assert trade["entry"] == pytest.approx(frame.open.iloc[ENTRY] + direction * 0.00002)
    assert trade["exit_time"] == trade["entry_time"]
    assert trade["exit_reason"] == "stop"
    assert trade["pnl"] < 0
    assert trade["costs"] == pytest.approx(abs(trade["size"]) * TestConfig().cost_per_unit_side * 2)
    assert -trade["pnl"] <= trade["risk"] + 1e-6
    assert result["metrics"]["final_equity"] == pytest.approx(
        10000 + sum(t["pnl"] for t in result["trades"])
    )


@pytest.mark.parametrize("short", [False, True])
def test_gap_through_stop_uses_gap_price_and_latches_ftmo_breach(short):
    frame = breakout_frame(short=short, gap=True)
    result = run_backtest(frame, short_config())
    first = result["trades"][0]
    assert pd.Timestamp(first["exit_time"]) == frame.index[ENTRY + 1]
    assert first["exit"] == pytest.approx(
        frame.open.iloc[ENTRY + 1] + (0.00002 if short else -0.00002)
    )
    assert result["metrics"]["status"] == "BREACHED"
    assert {b["rule"] for b in result["breaches"]} == {"daily_remaining", "total_remaining"}
    assert len(result["trades"]) == 1
    assert result["metrics"]["max_drawdown_pct"] > 10


def test_loss_floor_uses_midnight_balance_but_initial_capital_for_amount():
    room = rule_headroom(TestConfig(), 10200, 9600)
    assert room["daily_remaining"] == -100
    assert room["total_remaining"] == 600
    assert rule_headroom(TestConfig(), 10000, 9500)["daily_remaining"] == 0


def test_prague_midnight_resets_daily_floor_with_dst():
    frame = breakout_frame()
    frame.index = frame.index + pd.Timedelta(days=90)
    result = run_backtest(frame, short_config())
    previous = None
    observed = 0
    for row in result["curve"]:
        if (
            previous
            and pd.Timestamp(row["time"]).tz_convert("Europe/Prague").hour == 0
            and pd.Timestamp(previous["time"]).tz_convert("Europe/Prague").date()
            != pd.Timestamp(row["time"]).tz_convert("Europe/Prague").date()
        ):
            assert row["daily_floor"] == pytest.approx(previous["balance"] - 500)
            assert pd.Timestamp(row["time"]).hour == 22
            observed += 1
        previous = row
    assert observed > 0


def test_future_candles_do_not_change_completed_trades_or_indicators():
    frame = breakout_frame()
    small = run_backtest(frame.iloc[:250], short_config())
    frame.loc[frame.index[250:], ["open", "close", "low", "high"]] *= 2
    large = run_backtest(frame, short_config())
    assert small["trades"] == [
        t for t in large["trades"] if pd.Timestamp(t["exit_time"]) < frame.index[249]
    ]
    assert small["curve"][:-1] == large["curve"][: len(small["curve"]) - 1]


def test_flat_data_produces_no_fake_trades():
    frame = breakout_frame()
    frame.loc[:, ["open", "close"]] = 1.1
    frame.loc[:, "high"] = 1.1001
    frame.loc[:, "low"] = 1.0999
    result = run_backtest(frame, short_config())
    assert result["metrics"]["trades"] == 0
    assert result["metrics"]["final_equity"] == 10000
    assert result["metrics"]["status"] == "INCOMPLETE"
    assert result["metrics"]["expectancy"] is None


@pytest.mark.parametrize(
    "updates",
    [
        {"risk_pct": 5},
        {"balance": float("nan")},
        {"spread_pips": -1},
        {"phase": "one-step"},
        {"fast_period": 100},
        {"atr_period": 1.5},
    ],
)
def test_reject_invalid_config(updates):
    with pytest.raises(ValueError):
        TestConfig(**updates)


def test_csv_requires_timezone_and_converts_bid_to_mid(tmp_path):
    frame = breakout_frame()
    frame.index = frame.index.tz_localize(None)
    path = tmp_path / "EURUSD.csv"
    frame.to_csv(path, index_label="timestamp")
    with pytest.raises(ValueError, match="timezone"):
        load_csv(path, timezone=None, price_basis="bid", spread_pips=1)
    loaded = load_csv(path, timezone="Etc/GMT-2", price_basis="bid", spread_pips=1)
    assert loaded.index[0] == pd.Timestamp("2025-01-05T22:00:00Z")
    assert loaded.open.iloc[0] == pytest.approx(1.10005)


def test_metatrader_tab_export(tmp_path):
    frame = breakout_frame()
    frame["<DATE>"] = frame.index.strftime("%Y.%m.%d")
    frame["<TIME>"] = frame.index.strftime("%H:%M:%S")
    frame = frame.rename(columns={k: f"<{k.upper()}>" for k in ("open", "high", "low", "close")})
    path = tmp_path / "mt5.csv"
    frame.to_csv(path, sep="\t", index=False)
    loaded = load_csv(path, timezone="UTC", price_basis="mid", spread_pips=0)
    assert loaded.close.iloc[SIGNAL] == 1.102


@pytest.mark.parametrize("bad", ["duplicate", "reverse", "nan", "range", "daily", "naive"])
def test_reject_malformed_data(bad):
    frame = breakout_frame()
    if bad == "duplicate":
        frame.index = pd.DatetimeIndex([frame.index[0], *frame.index[:-1]])
    elif bad == "reverse":
        frame = frame.iloc[::-1]
    elif bad == "nan":
        frame.iloc[0, 0] = float("nan")
    elif bad == "range":
        frame.iloc[0, frame.columns.get_loc("high")] = 1
    elif bad == "daily":
        frame.index = pd.date_range("2025-01-01", periods=len(frame), freq="D", tz="UTC")
    else:
        frame.index = frame.index.tz_localize(None)
    with pytest.raises(ValueError):
        validate_bars(frame)


@pytest.fixture(scope="module")
def experiment():
    return evaluate(demo_bars(days=40))


def test_holdout_starts_with_fresh_account_and_fixed_parameters(experiment):
    result = experiment
    split = pd.Timestamp(result["split_time"])
    assert result["assessment"] == "SOFTWARE DEMO"
    assert result["holdout"]["curve"][0]["balance"] == 10000
    assert all(pd.Timestamp(t["entry_time"]) >= split for t in result["holdout"]["trades"])
    assert all(pd.Timestamp(r["time"]) < split for r in result["development"]["curve"])
    assert result["stress"]["metrics"]["costs"] > result["holdout"]["metrics"]["costs"]
    json.dumps(result, allow_nan=False)


def test_saved_run_contains_reproducible_candles_config_and_ledger(experiment, tmp_path):
    folder = save_run(experiment, tmp_path)
    stored = json.loads((folder / "result.json").read_text(encoding="utf-8"))
    assert stored["candles"] == experiment["candles"]
    assert stored["config"] == experiment["config"]
    assert (folder / "holdout_trades.csv").read_text().startswith("entry_time,")


@pytest.mark.parametrize("size", [(140, 48), (80, 30)])
def test_dashboard_charts_navigation_tabs_and_snapshot(experiment, tmp_path, size):
    from textual.widgets import DataTable, Select, TabbedContent
    from textual_plotext import PlotextPlot

    from finance_lab.ftmo.dashboard import TestDesk

    async def check():
        app = TestDesk(experiment, tmp_path)
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            assert (
                app.query_one("#journal", DataTable).row_count
                == experiment["holdout"]["metrics"]["trades"]
            )
            for chart_id in ("price", "atr", "equity"):
                plot = app.query_one(f"#{chart_id}", PlotextPlot)
                assert plot.size.width > 10
                assert plot.size.height >= 5
                assert len(plot.plt.build()) > 100
            app.action_first()
            await pilot.pause()
            assert app.cursor == 0
            assert app.query_one("#journal", DataTable).row_count == 0
            app.query_one("#timeframe", Select).value = "M15"
            await pilot.pause()
            await pilot.click("#next")
            assert app.cursor == 1
            app.action_zoom(-20)
            assert app.window == 40
            app.action_play()
            await pilot.pause(0.6)
            assert app.cursor > 1
            app.action_last()
            app.query_one("#period", Select).value = "development"
            await pilot.pause()
            assert app.period == "development"
            tabs = app.query_one(TabbedContent)
            for pane in tabs.query("TabPane"):
                tabs.active = pane.id
                await pilot.pause()
            tabs.active = "market"
            app.query_one("#timeframe", Select).value = "H4"
            await pilot.pause()
            name = app.save_screenshot(filename=f"ftmo-{size[0]}.svg", path=str(tmp_path))
            texts = " ".join(ET.parse(name).getroot().itertext()).replace("\xa0", " ")
            assert "FTMO TEST DESK" in texts

    asyncio.run(check())


def test_cli_invalid_arguments_do_not_start_simulation():
    from finance_lab.ftmo.__main__ import main

    assert main(["--demo", "--no-ui", "--risk", "nan"]) == 2


def test_incomplete_h4_candle_cannot_change_existing_signal():
    frame = breakout_frame()
    before = add_swing_features(frame, short_config())
    frame.loc[frame.index[ENTRY], ["high", "close"]] = 1.15
    after = add_swing_features(frame, short_config())
    assert before.fast.iloc[ENTRY] == after.fast.iloc[ENTRY]
    assert before.upper.iloc[ENTRY] == after.upper.iloc[ENTRY]
    assert before.atr.iloc[ENTRY] == after.atr.iloc[ENTRY]
    assert before.atr.iloc[ENTRY + 15] != after.atr.iloc[ENTRY + 15]
    partial = swing_candles(frame.iloc[: ENTRY + 5])
    assert partial.index[-1] == frame.index[SIGNAL]


@pytest.mark.parametrize(
    "start,end,expected",
    [
        ("2025-01-08T21:45Z", "2025-01-08T22:00Z", 24),
        ("2025-07-09T20:45Z", "2025-07-09T21:00Z", 24),
        ("2025-01-10T21:45Z", "2025-01-13T20:00Z", 8),
        ("2025-01-08T22:00Z", "2025-01-08T22:15Z", 0),
    ],
)
def test_rollover_triple_wednesday_dst_and_no_double_charge(start, end, expected):
    assert financing_cost(pd.Timestamp(start), pd.Timestamp(end), 100000, -8, -4) == expected
    assert financing_cost(pd.Timestamp(start), pd.Timestamp(end), -100000, -8, -4) == expected / 2


def test_swing_remains_open_overnight_and_financing_reconciles():
    frame = breakout_frame()
    frame.loc[frame.index[ENTRY:], ["open", "close", "high", "low"]] = [
        1.102,
        1.102,
        1.1021,
        1.1019,
    ]
    result = run_backtest(frame, short_config())
    trade = result["trades"][0]
    assert pd.Timestamp(trade["exit_time"]) - pd.Timestamp(trade["entry_time"]) > pd.Timedelta(
        days=2
    )
    assert trade["financing"] > 0
    assert result["metrics"]["trading_days"] == 1
    assert trade["exit_reason"] == "time/end"
    assert result["metrics"]["final_equity"] == pytest.approx(
        10000 + sum(t["pnl"] for t in result["trades"])
    )


@pytest.mark.parametrize("short", [False, True])
def test_gap_to_target_exits_at_open_before_later_adverse_extreme(short):
    frame = breakout_frame()
    frame.loc[frame.index[ENTRY], ["high", "low"]] = [1.1021, 1.1019]
    frame.loc[frame.index[ENTRY + 1], ["open", "close", "high", "low"]] = [1.12, 1.10, 1.13, 1.05]
    if short:
        old = frame.copy()
        frame["open"], frame["close"] = 2.2 - old.open, 2.2 - old.close
        frame["high"], frame["low"] = 2.2 - old.low, 2.2 - old.high
    result = run_backtest(frame, short_config())
    trade = result["trades"][0]
    assert trade["exit_reason"] == "target"
    assert trade["exit_at_open"]
    assert trade["pnl"] > 0
    assert not result["breaches"]
