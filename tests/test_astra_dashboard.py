import asyncio
from datetime import datetime, timezone

import pytest
from textual.widgets import DataTable, Static, TabbedContent

from finance_lab.astra.catalog import Catalog
from finance_lab.astra.dashboard import ShadowDesk


def test_dashboard_handles_null_fields_and_refreshes_execution_review(tmp_path):
    catalog = Catalog(tmp_path / "desk.db")
    now = datetime.now(timezone.utc)
    catalog.claim("null-fields", now, {})
    catalog.complete("null-fields", {"snapshot": {"instrument": None, "technical": None},
                                     "proposal": None, "gate": None, "reasoning": None})

    async def check():
        app = ShadowDesk(catalog)
        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.pause()
            catalog.save_execution_review("null-fields", {"status": "pending", "reason": "Waiting for real quotes"})
            app.screen.action_reload()
            await pilot.pause()
            assert "Waiting for real quotes" in str(app.screen.query_one("#validation", Static).render())

    asyncio.run(check())


@pytest.mark.parametrize("size", [(150, 50), (60, 25)])
def test_shadow_dashboard_charts_and_tabs(tmp_path, size):
    catalog = Catalog(tmp_path / "desk.db")
    now = datetime.now(timezone.utc)
    snapshot = {
        "instrument": {"symbol": "EURUSD"},
        "quote": {"bid": 1.1, "ask": 1.1002},
        "technical": {
            "basis": "bid",
            "support": 1.09,
            "resistance": 1.12,
            "chart": [{"close": price} for price in (1.1, 1.11, 1.105, 1.112)],
        },
        "validation": dict.fromkeys(
            ("development", "validation", "holdout", "stress", "live_forward")
        ),
    }
    catalog.claim("fixture", now, snapshot)
    catalog.complete(
        "fixture",
        {
            "mode": "replay",
            "snapshot": snapshot,
            "proposal": {"direction": "NO TRADE", "confidence": 0, "reasoning_summary": "Fixture"},
            "gate": {"verdict": "NO TRADE", "reasons": ["Fixture, not a trading result"]},
            "reasoning": {"market_report": "Recorded fixture market report"},
        },
    )

    async def check():
        app = ShadowDesk(catalog)
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            assert app.screen.query_one("#decisions", DataTable).row_count == 1
            assert "NO TRADE" in str(app.screen.query_one("#summary", Static).content)
            assert "Recorded fixture" in str(app.screen.query_one("#reasoning", Static).content)
            assert app.screen.query_one("#agents", DataTable).row_count == 12
            tabs = app.screen.query_one(TabbedContent)
            for pane in tabs.query("TabPane"):
                tabs.active = pane.id
                await pilot.pause()
            app.save_screenshot(filename=f"astra-{size[0]}.svg", path=str(tmp_path))
            await pilot.press("r")
            await pilot.pause()

    asyncio.run(check())


def test_existing_ftmo_desk_opens_and_returns_from_agent_ledger(tmp_path, monkeypatch):
    from finance_lab.astra.dashboard import ShadowScreen
    from finance_lab.ftmo.dashboard import TestDesk
    from finance_lab.ftmo.data import demo_bars
    from finance_lab.ftmo.engine import evaluate

    monkeypatch.setattr("finance_lab.astra.__main__.ROOT", tmp_path)
    experiment = evaluate(demo_bars(days=40))

    async def check():
        app = TestDesk(experiment, tmp_path)
        async with app.run_test(size=(140, 48)) as pilot:
            await pilot.pause()
            original = app.screen
            await pilot.press("a")
            await pilot.pause()
            assert isinstance(app.screen, ShadowScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert app.screen is original
            assert (
                app.query_one("#journal", DataTable).row_count
                == experiment["holdout"]["metrics"]["trades"]
            )

    asyncio.run(check())
