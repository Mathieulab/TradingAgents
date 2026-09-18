"""Malformed optional-source responses must not crash research or invent coverage."""

from unittest.mock import Mock
from urllib.error import HTTPError

import pytest
import requests

from tradingagents.dataflows import polymarket, reddit, yfinance_news


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {"content": None},
        {"content": {"provider": None}},
        {"content": {"provider": "invalid", "canonicalUrl": "invalid"}},
    ],
)
def test_yahoo_nullable_article_fields(payload):
    article = yfinance_news._extract_article_data(payload)
    assert isinstance(article, dict)
    assert "publisher" in article and "pub_date" in article


@pytest.mark.parametrize("payload", [None, {"events": None}, [], "invalid"])
def test_polymarket_null_response_is_unavailable(monkeypatch, payload):
    monkeypatch.setattr(polymarket, "_request", lambda *args: payload)
    assert "unavailable" in polymarket.get_prediction_markets("Fed")


def test_polymarket_nullable_events_do_not_crash(monkeypatch):
    monkeypatch.setattr(
        polymarket,
        "_request",
        lambda *args: {"events": [None, {"markets": None}, {"markets": [None]}]},
    )
    assert "No open prediction markets" in polymarket.get_prediction_markets("Fed")


def test_polymarket_network_details_do_not_fill_agent_context(monkeypatch):
    monkeypatch.setattr(
        polymarket, "_request", Mock(side_effect=requests.ConnectionError("INTERNAL " * 500))
    )
    result = polymarket.get_prediction_markets("Fed")
    assert "unavailable" in result and "ConnectionError" in result
    assert "INTERNAL" not in result and len(result) < 250


def test_reddit_rate_limit_is_not_no_posts(monkeypatch):
    monkeypatch.setattr(
        reddit, "urlopen", Mock(side_effect=HTTPError("url", 429, "Limited", {}, None))
    )
    monkeypatch.setattr(reddit.time, "sleep", Mock())
    result = reddit.fetch_reddit_posts("SPY", subreddits=["stocks"])
    assert "unavailable" in result and "HTTP 429" in result
    assert "no Reddit posts found" not in result
    assert "No sentiment signal" in result


@pytest.mark.parametrize("result", [None, {"ok": True, "data": None}])
def test_null_memory_payload_does_not_crash_completed_report(monkeypatch, result):
    from cli import main

    monkeypatch.setattr(main, "save_final_decision_to_finance_memory", lambda *a, **k: result)
    assert (
        main.save_finance_memory_decision({"finance_memory_enabled": True}, "SPY", "2026-09-17", {})
        == result
    )


def test_fund_context_explains_inapplicable_statements():
    from tradingagents.agents.utils.agent_utils import build_instrument_context

    context = build_instrument_context("SPY", identity={"quote_type": "ETF"})
    assert "Quote type: ETF" in context
    assert "not an operating company" in context and "not applicable" in context


def test_cli_source_has_no_mojibake():
    from pathlib import Path

    source = (Path(__file__).parents[1] / "cli" / "main.py").read_text(encoding="utf-8")
    for marker in ("\u00e2\u201d", "\u00e2\u2020", "\u00c2\u00a9", "\u00e2\u0153"):
        assert marker not in source
