from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from finance_lab.astra.providers import MT5MarketDataProvider

NOW = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)


def terminal():
    sdk = Mock()
    info = SimpleNamespace(server="FTMO-Demo", login=123, currency="USD", balance=9944, equity=9944)
    sdk.account_info.return_value = info
    sdk.positions_get.return_value = []
    sdk.orders_get.return_value = []
    sdk.history_deals_get.return_value = [
        SimpleNamespace(profit=-50, commission=-2, swap=-3, fee=-1)
    ]
    provider = MT5MarketDataProvider(expected_server="FTMO-Demo", expected_login=123, sdk=sdk)
    return provider, sdk, info


def test_mt5_closed_bars_preserve_bid_basis_and_skip_open_bar():
    provider, sdk, _ = terminal()
    sdk.copy_rates_range.return_value = [
        {
            "time": int((NOW - timedelta(minutes=15)).timestamp()),
            "open": 1.1,
            "high": 1.11,
            "low": 1.09,
            "close": 1.105,
            "tick_volume": 400,
        },
        {
            "time": int(NOW.timestamp()),
            "open": 1.105,
            "high": 1.12,
            "low": 1.1,
            "close": 1.115,
            "tick_volume": 10,
        },
    ]
    bars = provider.get_bars("EURUSD", "M15", NOW - timedelta(hours=1), NOW)
    assert len(bars) == 1 and bars[0].complete and bars[0].basis == "bid"
    assert bars[0].close_time == NOW and bars[0].close == 1.105
    assert bars[0].feed_id == provider.feed_id
    sdk.order_send.assert_not_called()


def test_mt5_account_baseline_includes_costs_and_prague_midnight(monkeypatch):
    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

    monkeypatch.setattr("finance_lab.astra.providers.datetime", FixedClock)
    provider, sdk, _ = terminal()
    sdk.orders_get.return_value = [SimpleNamespace(ticket=123)]
    account = provider.get_account_snapshot(10000)
    assert account.day_start_balance == 10000
    assert account.pending_orders == 1 and account.origin == "mt5"
    assert sdk.history_deals_get.call_args.args[0] == datetime(2026, 9, 9, 22, tzinfo=timezone.utc)
    assert account.timestamp == NOW
    sdk.order_send.assert_not_called()


def test_mt5_rejects_incoherent_account_snapshot():
    provider, sdk, info = terminal()
    sdk.account_info.side_effect = [info, SimpleNamespace(**{**vars(info), "balance": 9940})]
    with pytest.raises(RuntimeError, match="Account changed"):
        provider.get_account_snapshot(10000)


def test_mt5_tick_history_keeps_bid_ask_and_bounds():
    provider, sdk, _ = terminal()
    ms = int(NOW.timestamp() * 1000)
    sdk.copy_ticks_range.return_value = [
        {"time_msc": ms - 1, "bid": 1.1, "ask": 1.1002, "flags": 6},
        {"time_msc": ms, "bid": 1.1, "ask": 1.1003, "flags": 6},
        {"time_msc": ms + 1, "bid": 1.2, "ask": 1.2002, "flags": 6},
    ]
    ticks = provider.get_ticks("EURUSD", NOW, NOW)
    assert len(ticks) == 1 and ticks[0].spread == pytest.approx(0.0003)
    sdk.copy_ticks_range.return_value = None
    with pytest.raises(RuntimeError, match="tick history failed"):
        provider.get_ticks("EURUSD", NOW, NOW)
