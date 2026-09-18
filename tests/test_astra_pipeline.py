"""Pipeline fixtures verify orchestration, not market profitability."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from finance_lab.astra.catalog import Catalog
from finance_lab.astra.evidence import collect_macro_evidence
from finance_lab.astra.models import AccountSnapshot, GateResult, Instrument, Quote, SwingProposal
from finance_lab.astra.pipeline import review_execution

NOW = datetime(2026, 9, 17, 12, tzinfo=timezone.utc)


def candidate(catalog):
    instrument = Instrument(symbol="EURUSD", feed_id="fixture", provider="test")
    account = AccountSnapshot(
        timestamp=NOW,
        feed_id="fixture",
        initial_balance=10000,
        balance=10000,
        equity=10000,
        day_start_balance=10000,
        day=NOW.date(),
        origin="manual_test",
    )
    proposal = SwingProposal(
        instrument="EURUSD",
        direction="LONG",
        confidence=0.5,
        reasoning_summary="Software fixture only",
        market_regime="fixture",
        h4_trend="fixture",
        d1_trend="fixture",
        entry_low=1.099,
        entry_high=1.101,
        stop_loss=1.098,
        take_profits=[1.104],
        invalidation_conditions=["Stop"],
    )
    gate = GateResult(verdict="APPROVE", reasons=["Fixture"], units=1000)
    catalog.instrument(instrument)
    data = {
        "snapshot": {"instrument": instrument.model_dump(mode="json")},
        "gate_as_of": NOW.isoformat(),
        "gate_account": account.model_dump(mode="json"),
        "proposal": proposal.model_dump(mode="json"),
        "gate": gate.model_dump(mode="json"),
    }
    catalog.claim("decision", NOW, data["snapshot"])
    catalog.complete("decision", data)
    return catalog.decisions()[0]


def ticks(catalog, *, gap=0):
    for i, price in enumerate([1.1, 1.1, 1.104, 1.104]):
        catalog.append(
            Quote(
                symbol="EURUSD",
                feed_id="fixture",
                timestamp=NOW + timedelta(seconds=i + gap),
                bid=price,
                ask=price,
            )
        )


def test_rejected_candidate_never_reaches_engines(tmp_path):
    catalog = Catalog(tmp_path / "data.sqlite")
    engine = Mock()
    row = {"event_key": "no-trade", "status": "complete", "data": {"gate": None}}
    result = review_execution(catalog, row, NOW, engines=[engine])
    assert result["status"] == "not_run" and not result["order_sent"]
    engine.run.assert_not_called()


def test_pending_review_waits_for_actual_quotes_and_preserves_decision(tmp_path):
    catalog = Catalog(tmp_path / "data.sqlite")
    row = candidate(catalog)
    engine = Mock()
    pending = review_execution(catalog, row, NOW + timedelta(seconds=2), engines=[engine])
    assert pending["status"] == "pending"
    engine.run.assert_not_called()
    ticks(catalog)
    engine.run.return_value = {"engine": "Fixture", "fills": [], "net_pnl": 0, "order_sent": False}
    result = review_execution(catalog, row, NOW + timedelta(seconds=4), engines=[engine])
    assert result["status"] == "evaluated" and result["quote_count"] == 4
    assert catalog.decisions()[0] == row
    assert catalog.execution_review("decision") == result
    assert review_execution(catalog, row, NOW + timedelta(seconds=20), engines=[engine]) == result
    engine.run.assert_called_once()


def test_pipeline_runs_real_backtrader_and_nautilus_engines(tmp_path):
    pytest.importorskip("nautilus_trader")
    catalog = Catalog(tmp_path / "data.sqlite")
    row = candidate(catalog)
    ticks(catalog)
    result = review_execution(catalog, row, NOW + timedelta(seconds=4))
    assert result["status"] == "evaluated", result
    bt, nt = result["engines"]
    assert bt["scenario_hash"] == nt["scenario_hash"]
    assert len(bt["fills"]) == len(nt["fills"]) == 2
    assert bt["net_pnl"] == pytest.approx(nt["net_pnl"])
    assert not result["order_sent"] and "not swing profitability" in result["scope"]


def test_replay_rejects_recording_gap(tmp_path):
    catalog = Catalog(tmp_path / "data.sqlite")
    row = candidate(catalog)
    ticks(catalog, gap=120)
    engine = Mock()
    result = review_execution(catalog, row, NOW + timedelta(minutes=3), engines=[engine])
    assert result["status"] == "blocked" and "gaps" in result["reason"]
    engine.run.assert_not_called()


def test_missing_quotes_do_not_wait_forever_outside_poc_window(tmp_path):
    catalog = Catalog(tmp_path / "data.sqlite")
    row = candidate(catalog)
    result = review_execution(catalog, row, NOW + timedelta(hours=5))
    assert result["status"] == "blocked" and result["window_end"].startswith("2026-09-17T16:00")


def test_macro_feed_records_publication_and_receipt_without_future_leak(tmp_path):
    catalog = Catalog(tmp_path / "data.sqlite")
    xml = b"""<rss><channel>
      <item><title>Current policy release</title><pubDate>Thu, 17 Sep 2026 10:00:00 GMT</pubDate></item>
      <item><title>Future release</title><pubDate>Fri, 18 Sep 2026 10:00:00 GMT</pubDate></item>
      <item><title>Unknown publication time</title></item>
      <item><title>Old release</title><pubDate>Thu, 03 Sep 2026 10:00:00 GMT</pubDate></item>
    </channel></rss>"""
    fetch = Mock(return_value=SimpleNamespace(content=xml, raise_for_status=lambda: None))
    statuses = collect_macro_evidence(catalog, fetch=fetch, clock=lambda: NOW)
    assert all(s["status"] == "recorded" and s["added"] == 1 for s in statuses)
    records = catalog.records("evidence", "evidence", "", NOW)
    assert len(records) == 2
    assert all(e.received_at == NOW and e.published_at < NOW for e in records)
    assert catalog.records("evidence", "evidence", "", NOW - timedelta(seconds=1)) == []
    repeated = collect_macro_evidence(
        catalog, fetch=fetch, clock=lambda: NOW + timedelta(seconds=1)
    )
    assert all(s["added"] == 0 and s["status"] == "recorded" for s in repeated)


def test_macro_feed_failure_does_not_fabricate_evidence(tmp_path):
    catalog = Catalog(tmp_path / "data.sqlite")
    statuses = collect_macro_evidence(
        catalog, fetch=Mock(side_effect=requests.Timeout()), clock=lambda: NOW
    )
    assert all(s["status"] == "unavailable" for s in statuses)
    assert catalog.records("evidence", "evidence", "", NOW) == []


def test_html_response_is_not_valid_macro_feed(tmp_path):
    catalog = Catalog(tmp_path / "data.sqlite")
    fetch = Mock(
        return_value=SimpleNamespace(content=b"<html>blocked</html>", raise_for_status=lambda: None)
    )
    assert all(s["status"] == "unavailable" for s in collect_macro_evidence(catalog, fetch=fetch))
