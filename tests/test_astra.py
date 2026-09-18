from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from finance_lab.astra.catalog import Catalog
from finance_lab.astra.context import technical_context
from finance_lab.astra.models import (
    AccountSnapshot,
    Bar,
    Evidence,
    Instrument,
    Quote,
    SwingProposal,
)
from finance_lab.astra.orchestrator import REQUIRED_NODES, run_event
from finance_lab.astra.providers import (
    CSVMarketDataProvider,
    MT5MarketDataProvider,
    bars_from_quotes,
)
from finance_lab.astra.risk import evaluate
from tradingagents.agents.schemas import ResearchPlan, SentimentReport
from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.setup import GraphSetup

NOW = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)


@pytest.fixture
def instrument():
    return Instrument(symbol="EURUSD", feed_id="test-feed", provider="recorded")


@pytest.fixture
def quote(instrument):
    return Quote(
        symbol=instrument.symbol, feed_id=instrument.feed_id, timestamp=NOW, bid=1.10, ask=1.1001
    )


@pytest.fixture
def account(instrument):
    return AccountSnapshot(
        timestamp=NOW,
        feed_id=instrument.feed_id,
        initial_balance=10000,
        balance=10000,
        equity=10000,
        day_start_balance=10000,
        day=NOW.date(),
        origin="recorded",
    )


@pytest.fixture
def proposal(instrument):
    return SwingProposal(
        instrument=instrument.symbol,
        direction="LONG",
        confidence=0.7,
        reasoning_summary="Fixture only",
        market_regime="trend",
        h4_trend="bullish",
        d1_trend="bullish",
        entry_low=1.099,
        entry_high=1.101,
        stop_loss=1.095,
        take_profits=[1.115],
        invalidation_conditions=["Break below stop"],
        holding_hours=48,
    )


def test_gate_calculates_conservative_size(instrument, quote, account, proposal):
    result = evaluate(proposal, instrument, quote, account, NOW)
    assert result.verdict == "APPROVE"
    assert result.units % instrument.step_units == 0
    assert 0 < result.risk_at_stop <= 25
    assert result.daily_remaining == 500
    assert result.total_remaining == 1000
    assert result.order_sent is False


@pytest.mark.parametrize(
    "change",
    [
        {"timestamp": NOW - timedelta(minutes=2)},
        {"timestamp": NOW + timedelta(seconds=1)},
        {"day_start_balance": None},
        {"equity": 9800, "balance": 9800},
        {"breached": True},
        {"currency": "EUR"},
        {"feed_id": "wrong"},
        {"day": NOW.date() - timedelta(days=1)},
        {"equity": 9999},
        {"pending_orders": 1},
    ],
)
def test_gate_fails_closed(instrument, quote, account, proposal, change):
    assert (
        evaluate(proposal, instrument, quote, account.model_copy(update=change), NOW).verdict
        == "REJECT"
    )


def test_gate_short_uses_bid(instrument, quote, account, proposal):
    short = SwingProposal.model_validate(
        {**proposal.model_dump(), "direction": "SHORT", "stop_loss": 1.105, "take_profits": [1.085]}
    )
    assert evaluate(short, instrument, quote, account, NOW).verdict == "APPROVE"
    assert (
        evaluate(
            proposal, instrument, quote.model_copy(update={"ask": 1.102}), account, NOW
        ).verdict
        == "REJECT"
    )


def test_no_trade_is_first_class(instrument):
    result = evaluate(
        SwingProposal.no_trade("EURUSD", "Insufficient evidence"), instrument, None, None, NOW
    )
    assert result.verdict == "NO TRADE" and result.units == 0


def test_reject_naive_crossed_and_invalid_prices(quote, proposal):
    for changes in ({"timestamp": NOW.replace(tzinfo=None)}, {"ask": 1.09}, {"bid": float("nan")}):
        with pytest.raises(ValidationError):
            Quote.model_validate({**quote.model_dump(), **changes})
    with pytest.raises(ValidationError):
        SwingProposal.model_validate({**proposal.model_dump(), "stop_loss": 1.12})


def test_catalog_receipt_asof_and_dedup(tmp_path, quote):
    catalog = Catalog(tmp_path / "events.db")
    delayed = quote.model_copy(update={"received_at": NOW + timedelta(minutes=1)})
    assert catalog.append(delayed)
    assert not catalog.append(delayed)
    assert not catalog.records("quote", quote.feed_id, quote.symbol, NOW)
    assert (
        len(catalog.records("quote", quote.feed_id, quote.symbol, NOW + timedelta(minutes=2))) == 1
    )
    catalog.append(
        Evidence(
            kind="news", published_at=NOW + timedelta(hours=1), source="fixture", summary="FUTURE"
        )
    )
    assert not catalog.records("evidence", "evidence", "", NOW)


def test_quote_bars_do_not_claim_full_coverage(quote):
    late = quote.model_copy(
        update={"timestamp": NOW - timedelta(minutes=1), "received_at": NOW + timedelta(minutes=1)}
    )
    earlier = quote.model_copy(update={"timestamp": NOW - timedelta(minutes=15)})
    bars = bars_from_quotes([earlier, late, quote], "M15", NOW)
    assert len(bars) == 1
    assert bars[0].close == earlier.mid and not bars[0].complete
    assert bars[0].close_time == NOW


def test_no_incomplete_h4_or_future_receipt(instrument):
    bars = [
        Bar(
            symbol=instrument.symbol,
            feed_id=instrument.feed_id,
            timeframe="M15",
            basis="bid",
            complete=True,
            open_time=NOW - timedelta(hours=4) + timedelta(minutes=15 * i),
            close_time=NOW - timedelta(hours=4) + timedelta(minutes=15 * (i + 1)),
            open=1.1,
            high=1.11,
            low=1.09,
            close=1.1,
        )
        for i in range(16)
    ]
    assert not technical_context(bars, NOW - timedelta(seconds=1))["h4"]
    assert len(technical_context(bars, NOW)["h4"]) == 1
    bars[-1] = bars[-1].model_copy(update={"received_at": NOW + timedelta(seconds=1)})
    assert not technical_context(bars, NOW)["h4"]


def test_csv_real_sides_and_timezone(tmp_path, instrument):
    path = tmp_path / "quotes.csv"
    path.write_text("timestamp,bid,ask\n2026-09-10T12:00:00Z,1.1,1.1002\n", encoding="utf-8")
    provider = CSVMarketDataProvider(path, instrument)
    assert provider.get_quote("EURUSD", NOW).spread == pytest.approx(0.0002)
    with pytest.raises(ValueError):
        provider.get_quote("OTHER", NOW)


def test_mt5_identity_locked_without_orders():
    sdk = Mock()
    sdk.account_info.return_value = SimpleNamespace(server="FTMO-Demo", login=123)
    provider = MT5MarketDataProvider(expected_server="FTMO-Demo", expected_login=123, sdk=sdk)
    sdk.account_info.return_value = SimpleNamespace(server="OTHER", login=123)
    with pytest.raises(RuntimeError):
        provider.get_ticks("EURUSD", NOW, NOW)
    sdk.order_send.assert_not_called()
    with pytest.raises(ValueError):
        MT5MarketDataProvider(expected_server="FTMO-Demo", expected_login=123, sdk=sdk)


class FakeLLM:
    def __init__(self, *, broken=False):
        self.broken = broken
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return AIMessage(content="Recorded evidence is insufficient. No trade supported.")

    def with_structured_output(self, schema):
        def invoke(prompt):
            self.prompts.append(prompt)
            if schema is SwingProposal:
                if self.broken:
                    return {"direction": "LONG"}
                return SwingProposal.no_trade("EURUSD", "No recorded macro evidence")
            if schema is SentimentReport:
                return SentimentReport(
                    overall_band="Neutral",
                    overall_score=5,
                    confidence="low",
                    narrative="Unavailable, not evidence of neutrality.",
                )
            if schema is ResearchPlan:
                return ResearchPlan(
                    recommendation="Hold",
                    rationale="Insufficient evidence",
                    strategic_actions="No trade",
                )
            raise AssertionError(f"Unexpected invocation: {schema}")

        return SimpleNamespace(invoke=invoke)


@pytest.mark.parametrize("broken", [False, True])
@pytest.mark.parametrize("streamed", [False, True])
def test_full_existing_graph_shadow_no_vendor_calls(
    tmp_path, instrument, quote, account, monkeypatch, broken, streamed
):
    def forbidden(*args, **kwargs):
        raise AssertionError("External vendor fetch during snapshot reasoning")

    monkeypatch.setattr(
        "tradingagents.agents.analysts.sentiment_analyst.fetch_reddit_posts", forbidden
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.sentiment_analyst.fetch_stocktwits_messages", forbidden
    )
    monkeypatch.setattr("tradingagents.agents.analysts.sentiment_analyst.get_news.func", forbidden)
    catalog = Catalog(tmp_path / "shadow.db")
    catalog.instrument(instrument)
    catalog.append(quote)
    catalog.append(account)
    llm = FakeLLM(broken=broken)
    graph = (
        GraphSetup(llm, llm, {}, ConditionalLogic(), snapshot_only=True)
        .setup_graph(("market", "social", "news", "fundamentals"))
        .compile()
    )
    trading_graph = SimpleNamespace(config={"astra_snapshot_only": True}, graph=graph)
    updates = []
    row = run_event(
        catalog,
        trading_graph,
        instrument.feed_id,
        instrument.symbol,
        NOW,
        event="news",
        event_id="fixture-1",
        on_update=updates.append if streamed else None,
    )
    assert row["status"] == "complete", row
    assert set(row["data"]["reasoning"]["astra_trace"]) >= REQUIRED_NODES
    assert "Fundamentals Analyst" in row["data"]["reasoning"]["astra_trace"]
    assert row["data"]["gate"]["verdict"] == "NO TRADE"
    assert row["data"]["gate"]["order_sent"] is False
    if streamed:
        assert set(updates[-1]["astra_trace"]) >= REQUIRED_NODES
    count = len(llm.prompts)
    assert (
        run_event(
            catalog,
            trading_graph,
            instrument.feed_id,
            instrument.symbol,
            NOW,
            event="news",
            event_id="fixture-1",
        )
        == row
    )
    assert len(llm.prompts) == count
    if broken:
        assert row["data"]["reasoning"]["astra_proposal_error"]


def test_prague_day_is_not_utc_day(instrument, quote, account, proposal):
    instant = NOW.replace(hour=22, minute=30)
    account = account.model_copy(
        update={"timestamp": instant, "day": instant.astimezone(ZoneInfo("Europe/Prague")).date()}
    )
    quote = quote.model_copy(update={"timestamp": instant})
    assert evaluate(proposal, instrument, quote, account, instant).verdict == "APPROVE"


def test_breach_latches_after_recovery_but_not_in_past(tmp_path, account):
    catalog = Catalog(tmp_path / "account.db")
    catalog.append(account)
    catalog.append(
        account.model_copy(
            update={"timestamp": NOW + timedelta(seconds=1), "balance": 9400, "equity": 9400}
        )
    )
    catalog.append(account.model_copy(update={"timestamp": NOW + timedelta(seconds=2)}))
    assert not catalog.records("account", account.feed_id, "", NOW)[-1].breached
    assert catalog.records("account", account.feed_id, "", NOW + timedelta(seconds=2))[-1].breached


def test_flat_account_gate_rejects_existing_positions(instrument, quote, account, proposal):
    from finance_lab.astra.models import Position

    held = Position(symbol="EURUSD", side="LONG", units=1000, entry=1.1, unrealized_pnl=0)
    result = evaluate(
        proposal, instrument, quote, account.model_copy(update={"positions": (held,)}), NOW
    )
    assert result.verdict == "REJECT"


def test_recorder_terminates_when_market_has_no_ticks(tmp_path, instrument, account):
    from finance_lab.astra.recorder import record_mt5

    provider = Mock()
    provider.get_instrument_metadata.return_value = instrument
    provider.get_ticks.return_value = []
    provider.get_account_snapshot.return_value = account
    result = record_mt5(
        provider, Catalog(tmp_path / "record.db"), "EURUSD", 10000, 0.01, history_days=0
    )
    assert result["polls"] >= 1 and result["quotes"] == 0
    provider.order_send.assert_not_called()


def test_conflicting_bar_revisions_fail_closed(instrument):
    bar = Bar(
        symbol="EURUSD",
        feed_id=instrument.feed_id,
        timeframe="M15",
        basis="bid",
        complete=True,
        open_time=NOW - timedelta(minutes=15),
        close_time=NOW,
        open=1.1,
        high=1.11,
        low=1.09,
        close=1.1,
    )
    with pytest.raises(ValueError, match="Conflicting"):
        technical_context([bar, bar.model_copy(update={"close": 1.101})], NOW)


@pytest.mark.parametrize("streamed", [False, True])
def test_real_langchain_callbacks_record_snapshot_prompts(tmp_path, instrument, streamed):
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    catalog = Catalog(tmp_path / "audit.db")
    catalog.instrument(instrument)
    llm = FakeListChatModel(responses=["Recorded evidence unavailable; no trade."])
    workflow = GraphSetup(llm, llm, {}, ConditionalLogic(), snapshot_only=True).setup_graph(
        ("market", "social", "news")
    )
    graph = SimpleNamespace(config={"astra_snapshot_only": True}, graph=workflow.compile())
    row = run_event(
        catalog,
        graph,
        instrument.feed_id,
        instrument.symbol,
        NOW,
        event="news",
        event_id="audit-fixture",
        on_update=(lambda state: None) if streamed else None,
    )
    assert row["status"] == "complete", row["data"].get("error")
    assert len(row["data"]["model_prompts"]) >= 9
    assert all(call["messages"] for call in row["data"]["model_prompts"])
    assert row["data"]["source_hashes"]["tradingagents/graph/setup.py"]
