"""Offline setup and launcher regressions; no broker or model service calls."""

import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from pydantic import ValidationError
from typer.testing import CliRunner

from cli import ftmo, local_models
from finance_lab.astra.__main__ import Settings, load_settings
from finance_lab.astra.catalog import Catalog
from finance_lab.astra.models import AccountSnapshot, Instrument
from finance_lab.astra.providers import inspect_mt5_terminal


@pytest.mark.parametrize(
    "value",
    [
        r"C:\Users\mathi\.ollama\models\qwen3",
        "localhost:11434",
        "file:///models/qwen3",
        "http://",
        "http://localhost:invalid/v1",
        "http://localhost:0/v1",
        "http://user:secret@localhost/v1",
        "http://localhost/v1?key=secret",
        "http://localhost/v1#fragment",
        "http://local host/v1",
    ],
)
def test_reject_invalid_model_endpoint(value):
    with pytest.raises(ValueError):
        local_models.validate_endpoint(value)


@pytest.mark.parametrize("provider", ["ollama", "openai_compatible"])
def test_normalize_local_endpoint(provider):
    assert (
        local_models.local_endpoint(provider, "http://localhost:8000/")
        == "http://localhost:8000/v1"
    )
    assert (
        local_models.local_endpoint(provider, "https://server/proxy/v1/")
        == "https://server/proxy/v1"
    )


def response(payload):
    return SimpleNamespace(json=lambda: payload, raise_for_status=lambda: None)


def test_ollama_discovers_exact_installed_and_running_tags(monkeypatch):
    get = Mock(
        side_effect=[
            response(
                {"models": [{"name": "qwen3:8b"}, {"name": "qwen3:30b"}, {"name": "qwen3:8b"}]}
            ),
            response({"models": [{"name": "qwen3:8b"}]}),
        ]
    )
    monkeypatch.setattr(local_models.requests, "get", get)
    models = local_models.discover_models("ollama", "http://localhost:11434/v1")
    assert models == [("qwen3:30b [installed]", "qwen3:30b"), ("qwen3:8b [running]", "qwen3:8b")]
    assert [c.args[0] for c in get.call_args_list] == [
        "http://localhost:11434/api/tags",
        "http://localhost:11434/api/ps",
    ]
    assert all(
        c.kwargs["timeout"] <= 4 and not c.kwargs["allow_redirects"] for c in get.call_args_list
    )


def test_ollama_discovery_survives_unavailable_running_list(monkeypatch):
    monkeypatch.setattr(
        local_models.requests,
        "get",
        Mock(
            side_effect=[
                response({"models": [{"name": "qwen3:8b"}]}),
                requests.Timeout(),
            ]
        ),
    )
    assert local_models.discover_models("ollama", "http://localhost:11434") == [
        ("qwen3:8b [installed]", "qwen3:8b")
    ]


def test_vllm_discovers_served_ids(monkeypatch):
    get = Mock(return_value=response({"data": [{"id": "Qwen/Qwen3-8B"}]}))
    monkeypatch.setattr(local_models.requests, "get", get)
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "test-only")
    assert local_models.discover_models("openai_compatible", "http://localhost:8000") == [
        ("Qwen/Qwen3-8B [served]", "Qwen/Qwen3-8B")
    ]
    assert get.call_args.args[0] == "http://localhost:8000/v1/models"
    assert get.call_args.kwargs["headers"] == {"Authorization": "Bearer test-only"}


@pytest.mark.parametrize("provider", ["ollama", "openai_compatible"])
@pytest.mark.parametrize("payload", [[], {"models": None, "data": None}, "invalid"])
def test_discovery_rejects_malformed_payload(monkeypatch, provider, payload):
    monkeypatch.setattr(local_models.requests, "get", Mock(return_value=response(payload)))
    with pytest.raises(ValueError, match="model list"):
        local_models.discover_models(provider, "http://localhost:8000")


def test_shared_picker_uses_discovered_ids(monkeypatch):
    from cli import utils

    discovery = Mock(return_value=[("qwen3:8b [running]", "qwen3:8b")])
    select = Mock(return_value=SimpleNamespace(ask=lambda: "qwen3:8b"))
    monkeypatch.setattr(local_models, "discover_models", discovery)
    monkeypatch.setattr(utils.questionary, "select", select)
    assert utils.select_deep_thinking_agent("ollama", "http://host:11434/v1") == "qwen3:8b"
    discovery.assert_called_once_with("ollama", "http://host:11434/v1")
    assert [c.value for c in select.call_args.kwargs["choices"]] == ["qwen3:8b", "custom"]


def test_shared_picker_retains_manual_fallback(monkeypatch, capsys):
    from cli import utils

    monkeypatch.setattr(
        local_models, "discover_models", Mock(side_effect=requests.ConnectionError())
    )
    monkeypatch.setattr(
        utils.questionary, "select", Mock(return_value=SimpleNamespace(ask=lambda: "custom"))
    )
    monkeypatch.setattr(utils, "_prompt_custom_model_id", lambda: "qwen3:custom")
    assert utils.select_shallow_thinking_agent("ollama") == "qwen3:custom"
    assert "discovery unavailable" in capsys.readouterr().out


def test_repair_invalid_saved_setup_without_overwriting(tmp_path):
    path = tmp_path / ".astra.json"
    original = json.dumps(
        {
            "symbol": "USD",
            "mt5_login": 0,
            "initial_balance": -100,
            "backend_url": r"C:\Users\mathi\.ollama\models\qwen3",
            "llm_provider": "ollama",
            "deep_think_llm": "qwen3:8b",
        }
    )
    path.write_text(original, encoding="utf-8")
    with pytest.raises(ValidationError):
        load_settings(path)
    settings = load_settings(path, repair=True)
    assert settings.symbol == "EURUSD"
    assert settings.mt5_login is None and settings.initial_balance is None
    assert settings.backend_url is None
    assert settings.deep_think_llm == "qwen3:8b"
    assert path.read_text(encoding="utf-8") == original


def test_settings_normalize_pair_and_preserve_broker_suffix():
    assert Settings(symbol="eur/usd").symbol == "EURUSD"
    assert Settings(symbol="eurusd.pro").symbol == "EURUSD.pro"


def test_ftmo_uses_standard_model_wizard_even_with_env(monkeypatch):
    from cli import main

    for name, value in {
        "TRADINGAGENTS_LLM_PROVIDER": "openai",
        "TRADINGAGENTS_QUICK_THINK_LLM": "old",
        "TRADINGAGENTS_OUTPUT_LANGUAGE": "German",
    }.items():
        monkeypatch.setenv(name, value)
    forbidden = Mock(side_effect=AssertionError("Stock-only prompt used for FTMO"))
    for name in ("get_ticker", "get_analysis_date", "select_analysts", "fetch_announcements"):
        monkeypatch.setattr(main, name, forbidden)
    monkeypatch.setattr(main, "display_announcements", Mock())
    monkeypatch.setattr(main, "ask_output_language", lambda: "French")
    monkeypatch.setattr(main, "select_research_depth", lambda: 3)
    monkeypatch.setattr(
        main, "select_llm_provider", lambda: ("ollama", "http://localhost:11434/v1")
    )
    monkeypatch.setattr(local_models, "prompt_local_endpoint", lambda provider, url: url)
    monkeypatch.setattr(main, "confirm_ollama_endpoint", Mock())
    monkeypatch.setattr(main, "ensure_api_key", Mock())
    quick, deep = Mock(return_value="qwen3:8b"), Mock(return_value="qwen3:30b")
    monkeypatch.setattr(main, "select_shallow_thinking_agent", quick)
    monkeypatch.setattr(main, "select_deep_thinking_agent", deep)
    result = main.get_user_selections(ftmo=True, symbol="EURUSD.pro")
    assert result["ticker"] == "EURUSD.pro" and result["asset_type"] == "forex"
    assert result["output_language"] == "French" and result["research_depth"] == 3
    assert [a.value for a in result["analysts"]] == ["market", "news", "social"]
    quick.assert_called_once_with("ollama", "http://localhost:11434/v1")
    deep.assert_called_once_with("ollama", "http://localhost:11434/v1")


def test_save_models_keeps_account_and_clears_other_provider_endpoint(monkeypatch, tmp_path):
    from cli import main

    monkeypatch.setattr(
        main,
        "get_user_selections",
        Mock(
            return_value={
                "llm_provider": "google",
                "backend_url": None,
                "shallow_thinker": "quick",
                "deep_thinker": "deep",
                "research_depth": 3,
                "output_language": "French",
                "google_thinking_level": "high",
                "openai_reasoning_effort": None,
                "anthropic_effort": None,
            }
        ),
    )
    path = tmp_path / "settings.json"
    settings = ftmo.configure_models(path, Settings(mt5_login=123, backend_url="http://old/v1"))
    assert settings.mt5_login == 123
    assert load_settings(path) == settings
    config = ftmo.model_config(settings)
    assert config["backend_url"] is None and config["astra_snapshot_only"]
    assert config["max_debate_rounds"] == config["max_risk_discuss_rounds"] == 3
    assert config["google_thinking_level"] == "high"


def terminal_sdk():
    sdk = Mock()
    sdk.initialize.return_value = True
    sdk.account_info.return_value = SimpleNamespace(
        server="FTMO-Demo", login=123456, currency="USD"
    )
    sdk.symbols_get.return_value = [
        SimpleNamespace(name="EURUSD.pro", currency_base="EUR", currency_profit="USD"),
        SimpleNamespace(name="GBPUSD", currency_base="GBP", currency_profit="USD"),
    ]
    return sdk


def test_mt5_setup_discovers_account_and_shuts_down():
    sdk = terminal_sdk()
    assert inspect_mt5_terminal("terminal64.exe", sdk=sdk) == {
        "server": "FTMO-Demo",
        "login": 123456,
        "currency": "USD",
        "symbols": ["EURUSD.pro"],
    }
    sdk.initialize.assert_called_once_with("terminal64.exe")
    sdk.shutdown.assert_called_once()
    sdk.order_send.assert_not_called()


def test_mt5_setup_rejects_wrong_currency_and_shuts_down():
    sdk = terminal_sdk()
    sdk.account_info.return_value.currency = "EUR"
    with pytest.raises(ValueError, match="USD"):
        inspect_mt5_terminal(sdk=sdk)
    sdk.shutdown.assert_called_once()
    sdk.order_send.assert_not_called()


def test_configure_account_uses_detected_identity_not_old_input(monkeypatch, tmp_path):
    from finance_lab.astra import providers

    monkeypatch.setattr(
        providers,
        "inspect_mt5_terminal",
        lambda path: {
            "server": "FTMO-Demo2",
            "login": 123456,
            "currency": "USD",
            "symbols": ["EURUSD.pro"],
        },
    )
    monkeypatch.setattr(ftmo.questionary, "text", Mock())
    monkeypatch.setattr(ftmo.questionary, "confirm", Mock())
    monkeypatch.setattr(ftmo, "ask", Mock(side_effect=["", True]))
    monkeypatch.setattr(ftmo, "choose", lambda *args: "EURUSD.pro")
    monkeypatch.setattr(ftmo, "field_value", lambda *args: "10000")
    settings = ftmo.configure_account(tmp_path / "config.json", Settings(mt5_login=1000))
    assert settings.mt5_login == 123456 and settings.mt5_server == "FTMO-Demo2"
    assert settings.initial_balance == 10000 and settings.symbol == "EURUSD.pro"


def test_empty_dashboard_explains_next_step(tmp_path, capsys):
    ftmo.open_dashboard(Catalog(tmp_path / "market.sqlite"))
    output = capsys.readouterr().out
    assert "No agent decisions recorded yet" in output and "Live MT5 shadow analysis" in output


@pytest.mark.parametrize("mode", ["research", "ftmo", "exit"])
def test_standard_cli_workflow_routing(monkeypatch, mode):
    from cli import main

    research, shadow = Mock(), Mock()
    monkeypatch.setattr(main, "run_analysis", research)
    monkeypatch.setattr(ftmo, "run_ftmo_workspace", shadow)
    monkeypatch.setattr(
        ftmo.questionary, "select", Mock(return_value=SimpleNamespace(ask=lambda: mode))
    )
    result = CliRunner().invoke(main.app, [])
    assert result.exit_code == 0, result.exception
    assert research.call_count == (mode == "research")
    assert shadow.call_count == (mode == "ftmo")


def test_direct_ftmo_command_and_legacy_checkpoint(monkeypatch):
    from cli import main

    shadow, research = Mock(), Mock()
    monkeypatch.setattr(ftmo, "run_ftmo_workspace", shadow)
    monkeypatch.setattr(main, "run_analysis", research)
    runner = CliRunner()
    assert runner.invoke(main.app, ["ftmo"]).exit_code == 0
    shadow.assert_called_once()
    assert runner.invoke(main.app, ["--checkpoint"]).exit_code == 0
    research.assert_called_once_with(checkpoint=True)
    research.reset_mock()
    assert runner.invoke(main.app, ["analyze", "--checkpoint"]).exit_code == 0
    research.assert_called_once_with(checkpoint=True)


def test_corrupt_config_returns_instead_of_looping(tmp_path, capsys):
    path = tmp_path / "config.json"
    path.write_text("not json", encoding="utf-8")
    ftmo.run_ftmo_workspace(path)
    assert "Cannot continue this step" in capsys.readouterr().out


def test_invalid_replay_timestamp_returns_to_menu(monkeypatch, tmp_path, capsys):
    path = tmp_path / "config.json"
    path.write_text(
        Settings(catalog=str(tmp_path / "market.sqlite")).model_dump_json(), encoding="utf-8"
    )
    monkeypatch.setattr(ftmo, "choose", Mock(side_effect=["replay", "exit"]))
    monkeypatch.setattr(ftmo, "configure_models", lambda path, settings: settings)
    monkeypatch.setattr(
        ftmo,
        "recorded_replay",
        Mock(side_effect=argparse.ArgumentTypeError("Use an explicit offset or Z")),
    )
    ftmo.run_ftmo_workspace(path)
    assert "Use an explicit offset or Z" in capsys.readouterr().out


def append_account(catalog, settings, *, stale=False, wrong_account=False):
    login = 999 if wrong_account else settings.mt5_login
    account_ref = hashlib.sha256(f"{settings.mt5_server}:{login}".encode()).hexdigest()[:16]
    feed = f"mt5:{settings.mt5_server}:{account_ref}"
    now = datetime.now(timezone.utc) - timedelta(days=int(stale))
    catalog.instrument(Instrument(symbol="EURUSD", feed_id=feed, provider="mt5"))
    catalog.append(
        AccountSnapshot(
            timestamp=now,
            feed_id=feed,
            initial_balance=10000,
            balance=10000,
            equity=10000,
            day=now.date(),
            day_start_balance=10000,
            origin="mt5",
        )
    )
    return feed


@pytest.mark.parametrize("interrupt", [False, True])
def test_recorder_owned_process_is_cleaned_up(monkeypatch, tmp_path, interrupt):
    catalog = Catalog(tmp_path / "market.sqlite")
    settings = Settings(mt5_login=123456, mt5_server="FTMO-Demo", initial_balance=10000)
    process = Mock()
    process.poll.return_value = None
    feeds = []

    def start(*args, **kwargs):
        assert "record-mt5" in args[0]
        assert kwargs["stdin"] == ftmo.subprocess.DEVNULL
        feeds.append(append_account(catalog, settings))
        return process

    monkeypatch.setattr(ftmo.subprocess, "Popen", start)
    try:
        with ftmo.recording(tmp_path / "config.json", settings, catalog) as (child, feed):
            assert child is process and feed == feeds[0]
            process.terminate.assert_not_called()
            if interrupt:
                raise KeyboardInterrupt
    except KeyboardInterrupt:
        assert interrupt
    process.terminate.assert_called_once()
    process.wait.assert_called_once_with(timeout=10)


@pytest.mark.parametrize("stale,wrong_account", [(True, False), (False, True)])
def test_recorder_does_not_reuse_old_or_other_account(monkeypatch, tmp_path, stale, wrong_account):
    catalog = Catalog(tmp_path / "market.sqlite")
    settings = Settings(mt5_login=123456, mt5_server="FTMO-Demo", initial_balance=10000)
    process = Mock()
    process.poll.return_value = None

    def start(*args, **kwargs):
        append_account(catalog, settings, stale=stale, wrong_account=wrong_account)
        return process

    monkeypatch.setattr(ftmo.subprocess, "Popen", start)
    with (
        pytest.raises(RuntimeError, match="No new MT5 account data"),
        ftmo.recording(tmp_path / "config.json", settings, catalog, startup_timeout=0),
    ):
        pytest.fail("A fresh observation from the intended account was required")
    process.terminate.assert_called_once()
    process.wait.assert_called_once()


def test_recorder_exited_before_ready(monkeypatch, tmp_path):
    catalog = Catalog(tmp_path / "market.sqlite")
    process = Mock()
    process.poll.return_value = 1
    monkeypatch.setattr(ftmo.subprocess, "Popen", Mock(return_value=process))
    with (
        pytest.raises(RuntimeError, match="recorder stopped"),
        ftmo.recording(tmp_path / "config.json", Settings(), catalog),
    ):
        pytest.fail("Recorder must be alive")
    process.terminate.assert_not_called()


def test_result_displays_structured_direction(capsys):
    ftmo.show_result(
        {
            "status": "complete",
            "data": {
                "proposal": {"direction": "SHORT"},
                "gate": {"verdict": "REJECT", "reasons": ["Missing macro evidence"]},
            },
        }
    )
    output = capsys.readouterr().out
    assert "SHORT" in output and "REJECT" in output and "Missing macro evidence" in output


def test_repair_warning_is_not_repeated_for_menu_actions(monkeypatch, tmp_path, capsys):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"symbol": "USD", "catalog": str(tmp_path / "market.sqlite")}), encoding="utf-8"
    )
    monkeypatch.setattr(ftmo, "choose", Mock(side_effect=["status", "status", "exit"]))
    ftmo.run_ftmo_workspace(path)
    assert capsys.readouterr().out.count("Saved symbol needs correction") == 1
    assert json.loads(path.read_text(encoding="utf-8"))["symbol"] == "USD"


def test_cancelled_import_returns_to_workspace(monkeypatch, tmp_path, capsys):
    path = tmp_path / "config.json"
    path.write_text(
        Settings(catalog=str(tmp_path / "market.sqlite")).model_dump_json(), encoding="utf-8"
    )
    selection = Mock(side_effect=["import", "status", "exit"])
    monkeypatch.setattr(ftmo, "choose", selection)
    monkeypatch.setattr(ftmo, "import_data", Mock(side_effect=ftmo.StepCancelled()))
    ftmo.run_ftmo_workspace(path)
    assert selection.call_count == 3
    assert "Step cancelled" in capsys.readouterr().out


def test_live_pipeline_records_before_research_and_reviews_after_gate(monkeypatch, tmp_path):
    from contextlib import contextmanager

    from finance_lab.astra import evidence
    from tradingagents.graph import trading_graph

    order = []
    catalog = Catalog(tmp_path / "market.sqlite")
    settings = Settings()
    row = {"event_key": "test", "status": "complete", "data": {"gate": {"verdict": "NO TRADE"}}}
    process = Mock()
    process.poll.return_value = None

    @contextmanager
    def recorder(*args):
        order.append("record")
        try:
            yield process, "fixture"
        finally:
            order.append("stop_recording")

    monkeypatch.setattr(ftmo, "configure_account", lambda *args: settings)
    monkeypatch.setattr(ftmo, "choose", lambda *args: "once")
    monkeypatch.setattr(ftmo, "recording", recorder)
    monkeypatch.setattr(ftmo, "check_market_ready", lambda *args: order.append("preflight"))
    monkeypatch.setattr(
        evidence, "collect_macro_evidence", lambda *args: order.append("macro") or []
    )
    monkeypatch.setattr(trading_graph, "TradingAgentsGraph", Mock(return_value=object()))
    monkeypatch.setattr(ftmo, "analyze_event", lambda *args: order.append("research_gate") or row)
    monkeypatch.setattr(
        ftmo, "review_execution", lambda *args: order.append("review") or {"status": "not_run"}
    )
    monkeypatch.setattr(ftmo, "show_result", lambda *args: order.append("report"))
    assert ftmo.live_analysis(tmp_path / "config.json", settings, catalog) == settings
    assert order == [
        "record",
        "preflight",
        "macro",
        "research_gate",
        "review",
        "report",
        "stop_recording",
    ]
