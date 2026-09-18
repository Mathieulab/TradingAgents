from datetime import datetime, timedelta, timezone

import pytest

from finance_lab.astra.engines import BacktraderEngine, NautilusEngine
from finance_lab.astra.models import AccountSnapshot, GateResult, Instrument, Quote, SwingProposal


@pytest.mark.parametrize(
    "direction,target", [("LONG", True), ("LONG", False), ("SHORT", True), ("SHORT", False)]
)
@pytest.mark.parametrize("gap", [False, True])
@pytest.mark.parametrize("spread", [0, 0.0002])
def test_engine_execution_comparison(direction, target, gap, spread):
    pytest.importorskip("nautilus_trader")
    now = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
    sign = 1 if direction == "LONG" else -1
    instrument = Instrument(symbol="EURUSD", feed_id="fixture", provider="test")
    proposal = SwingProposal(
        instrument="EURUSD",
        direction=direction,
        confidence=0.5,
        reasoning_summary="Execution fixture, no performance claim",
        market_regime="fixture",
        h4_trend="fixture",
        d1_trend="fixture",
        entry_low=1.099,
        entry_high=1.101,
        stop_loss=1.1 - sign * 0.002,
        take_profits=[round(1.1 + sign * 0.004, 5)],
        invalidation_conditions=["Fixture stop"],
    )
    gate = GateResult(verdict="APPROVE", reasons=["Test fixture"], units=1000)
    account = AccountSnapshot(
        timestamp=now,
        feed_id="fixture",
        initial_balance=10000,
        balance=10000,
        equity=10000,
        day_start_balance=10000,
        day=now.date(),
        origin="manual_test",
    )
    move = (0.005 if gap else 0.004) if target else -0.003
    prices = [1.1, 1.1, 1.1 + sign * move, 1.1 + sign * move]
    quotes = [
        Quote(
            symbol="EURUSD",
            feed_id="fixture",
            timestamp=now + timedelta(seconds=i),
            bid=round(p - spread / 2, 5),
            ask=round(p + spread / 2, 5),
        )
        for i, p in enumerate(prices)
    ]
    bt = BacktraderEngine().run(quotes, instrument, proposal, gate, account)
    nt = NautilusEngine().run(quotes, instrument, proposal, gate, account)
    assert len(bt["fills"]) == 2
    assert nt["fills"][0]["price"] == pytest.approx(1.1 + sign * spread / 2)
    if spread == 0 and not (target and gap):
        assert len(nt["fills"]) == 2
        assert [f["price"] for f in bt["fills"]] == pytest.approx([f["price"] for f in nt["fills"]])
        assert bt["net_pnl"] == pytest.approx(nt["net_pnl"])
    if target and gap:
        assert len(nt["fills"]) == 2
        # Resting Nautilus limit fills at its limit; Backtrader gives open-gap improvement.
        assert nt["fills"][1]["price"] == pytest.approx(proposal.take_profits[0])
        assert bt["net_pnl"] > nt["net_pnl"]
    assert bt["scenario_hash"] == nt["scenario_hash"]
