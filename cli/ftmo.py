"""Guided FTMO workspace for the standard TradingAgents launcher. No order API."""

import argparse
import hashlib
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import questionary
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from finance_lab.astra.__main__ import ROOT, Settings, aware, load_settings, select_feed
from finance_lab.astra.catalog import Catalog
from finance_lab.astra.context import build_snapshot
from finance_lab.astra.pipeline import review_execution

console = Console()


class StepCancelled(Exception):
    """Return from an optional setup step without closing the workspace."""


def ask(prompt):
    value = prompt.ask()
    if value is None:
        raise StepCancelled
    return value


def choose(message, choices):
    return ask(
        questionary.select(
            message, choices=[questionary.Choice(label, value=value) for label, value in choices]
        )
    )


def field_value(name, message, default=""):
    def valid(value):
        try:
            Settings.model_validate({name: value})
            return True
        except ValueError as exc:
            return str(exc)

    return ask(questionary.text(message, default=str(default), validate=valid)).strip()


def save_settings(path, settings, **updates):
    settings = Settings.model_validate({**settings.model_dump(), **updates})
    path.write_text(settings.model_dump_json(indent=2) + "\n", encoding="utf-8")
    console.print("Setup saved. Broker passwords and API keys are not stored in .astra.json.")
    return settings


def configure_models(path, settings):
    # Reuse the normal provider/model/depth/language wizard and the actual graph.
    from cli.main import get_user_selections

    selected = get_user_selections(ftmo=True, symbol=settings.symbol)
    return save_settings(
        path,
        settings,
        llm_provider=selected["llm_provider"],
        backend_url=selected["backend_url"],
        quick_think_llm=selected["shallow_thinker"],
        deep_think_llm=selected["deep_thinker"],
        research_depth=selected["research_depth"],
        output_language=selected["output_language"],
        google_thinking_level=selected["google_thinking_level"],
        openai_reasoning_effort=selected["openai_reasoning_effort"],
        anthropic_effort=selected["anthropic_effort"],
    )


def configure_account(path, settings):
    from finance_lab.astra.providers import inspect_mt5_terminal

    console.print(
        "Open your FTMO MT5 terminal and log in there first. This connection is read-only."
    )
    terminal = (
        ask(
            questionary.text(
                "MT5 terminal64.exe path (blank uses the selected terminal):",
                default=settings.terminal_path or "",
            )
        )
        .strip()
        .strip('"')
        or None
    )
    identity = inspect_mt5_terminal(terminal)
    console.print(
        f"Detected server: {identity['server']} | Account: {identity['login']} | "
        f"Currency: {identity['currency']}",
        markup=False,
    )
    if not ask(
        questionary.confirm("Is this your intended FTMO demo / Free Trial account?", default=False)
    ):
        raise ValueError(
            "Account not confirmed. Select the intended account in MT5, then reconnect."
        )
    symbol = choose("Exact EUR/USD symbol on this account:", [(s, s) for s in identity["symbols"]])
    balance = field_value(
        "initial_balance",
        "Original account balance in USD (from FTMO account details, not your login):",
    )
    return save_settings(
        path,
        settings,
        terminal_path=terminal,
        symbol=symbol,
        mt5_server=identity["server"],
        mt5_login=identity["login"],
        initial_balance=balance,
    )


def model_config(settings):
    from tradingagents.default_config import DEFAULT_CONFIG

    config = dict(DEFAULT_CONFIG)
    for key in (
        "llm_provider",
        "quick_think_llm",
        "deep_think_llm",
        "backend_url",
        "google_thinking_level",
        "openai_reasoning_effort",
        "anthropic_effort",
    ):
        # Explicitly clear a stale endpoint/effort inherited from another provider.
        config[key] = getattr(settings, key)
    config.update(
        astra_snapshot_only=True,
        output_language=settings.output_language,
        max_debate_rounds=settings.research_depth,
        max_risk_discuss_rounds=settings.research_depth,
    )
    return config


def open_dashboard(catalog):
    if not catalog.decisions():
        console.print(
            Panel(
                "No agent decisions recorded yet.\n"
                "Choose 'Live MT5 shadow analysis' to record data and run the team, or import "
                "historical data and choose 'Recorded replay'. No orders will be sent.",
                title="FTMO Dashboard",
                border_style="yellow",
            )
        )
        return
    from finance_lab.astra.dashboard import ShadowDesk

    ShadowDesk(catalog).run()


def show_status(catalog, settings):
    with catalog.connect() as db:
        counts = dict(db.execute("SELECT kind, COUNT(*) FROM observations GROUP BY kind"))
    table = Table("Item", "Status")
    for name, value in (
        ("Instrument", settings.symbol),
        ("Provider", settings.llm_provider or "Not configured"),
        ("Analysis model", settings.quick_think_llm or "Not configured"),
        ("Reasoning model", settings.deep_think_llm or "Not configured"),
        ("Recorded quotes", counts.get("quote", 0)),
        ("Recorded bars", counts.get("bar", 0)),
        ("News / macro evidence", counts.get("evidence", 0)),
        ("Agent decisions", len(catalog.decisions())),
        ("Catalog", catalog.path),
        ("Broker orders", "DISABLED"),
    ):
        table.add_row(name, str(value))
    console.print(table)
    if not counts.get("quote") or not counts.get("bar"):
        console.print(
            "Next step: Live MT5 shadow analysis. It records market data before research.\n"
            "Imports and engine comparison are optional advanced steps, not initial setup."
        )


@contextmanager
def recording(path, settings, catalog, *, startup_timeout=120):
    """Own a separate recorder so slow reasoning cannot suspend market capture."""
    log_path = catalog.path.parent / "recorder.log"
    started = datetime.now(timezone.utc).isoformat()
    account_ref = hashlib.sha256(
        f"{settings.mt5_server}:{settings.mt5_login}".encode()
    ).hexdigest()[:16]
    expected_feed = f"mt5:{settings.mt5_server}:{account_ref}"
    command = [
        sys.executable,
        "-m",
        "finance_lab.astra",
        "--config",
        str(path.resolve()),
        "--catalog",
        str(catalog.path.resolve()),
        "record-mt5",
        "--seconds",
        "86400",
    ]
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            deadline = time.monotonic() + startup_timeout
            with console.status("Recording MT5 history and waiting for account data..."):
                while True:
                    if process.poll() is not None:
                        raise RuntimeError(f"MT5 recorder stopped. Check {log_path}")
                    # Require a new observation, not stale data left by a previous session.
                    with catalog.connect() as db:
                        row = db.execute(
                            "SELECT feed_id FROM observations WHERE kind='account' AND feed_id=? "
                            "AND event_at>=? ORDER BY event_at DESC LIMIT 1",
                            (expected_feed, started),
                        ).fetchone()
                    if row:
                        catalog.get_instrument(row[0], settings.symbol)
                        yield_feed = row[0]
                        break
                    if time.monotonic() >= deadline:
                        raise RuntimeError(f"No new MT5 account data received. Check {log_path}")
                    time.sleep(1)
            yield process, yield_feed
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def analyze_event(catalog, graph, feed, symbol, as_of, mode):
    from finance_lab.astra.orchestrator import run_event

    completed = set()
    with console.status("TradingAgents: preparing recorded market context...") as progress:

        def on_update(state):
            for name in state.get("astra_trace", []):
                if name not in completed:
                    completed.add(name)
                    console.print(f"  {name}: complete", markup=False)
                    progress.update(f"TradingAgents: {name} complete; continuing reasoning...")

        row = run_event(catalog, graph, feed, symbol, as_of, mode=mode, on_update=on_update)
    return row


def show_result(row, execution=None):
    data = row.get("data") or {}
    proposal, gate = data.get("proposal") or {}, data.get("gate") or {}
    table = Table("Decision", "Value")
    for label, value in (
        ("Status", row["status"]),
        ("Proposal", proposal.get("direction", "Pending")),
        ("FTMO gate", gate.get("verdict", "Pending")),
        ("Reasons", "; ".join(gate.get("reasons", []))),
        ("Orders sent", "None (shadow only)"),
    ):
        table.add_row(label, str(value))
    console.print(table)
    pipeline = Table("Pipeline stage", "Result")
    snapshot = data.get("snapshot") or {}
    pipeline.add_row("1. Market data", "Recorded as-of snapshot" if snapshot else "Unavailable")
    pipeline.add_row("2. TradingAgents research", row["status"])
    pipeline.add_row("3. Swing contract", proposal.get("direction", "Unavailable"))
    pipeline.add_row("4. FTMO risk gate", gate.get("verdict", "Unavailable"))
    execution = execution or {}
    pipeline.add_row("5. Nautilus / Backtrader replay", execution.get("status", "Not run"))
    pipeline.add_row("6. Shadow ledger", "Decision recorded; broker orders disabled")
    console.print(pipeline)
    if execution:
        console.print(execution.get("reason", ""), markup=False)
        console.print(execution.get("scope", ""), style="dim", markup=False)
    console.print("The dashboard contains the recorded chart and full reasoning chain.")


def check_market_ready(catalog, feed, symbol, as_of):
    snapshot = build_snapshot(catalog, feed, symbol, as_of)
    technical = snapshot.get("technical") or {}
    if not snapshot.get("quote"):
        raise ValueError(
            "No recent recorded bid/ask. Check MT5 connection and whether the FX market is open."
        )
    if not technical.get("ready") or not technical.get("last_h4_close"):
        raise ValueError(
            f"Market history not ready: {technical.get('reason', 'No closed H4')}. "
            "Let MT5 synchronize M15 history before running the agent team."
        )
    return snapshot


def live_analysis(path, settings, catalog):
    from finance_lab.astra.evidence import collect_macro_evidence
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    settings = configure_account(path, settings)
    mode = choose(
        "Shadow session:",
        [
            ("Analyze the latest closed H4 once", "once"),
            ("Watch H4 closes for 4 hours (Ctrl+C stops)", "watch"),
        ],
    )
    console.print("Missing news/macro evidence or stale market/account data blocks approval.")
    with recording(path, settings, catalog) as (process, feed):
        check_market_ready(catalog, feed, settings.symbol, datetime.now(timezone.utc))
        with console.status("Recording dated Fed / ECB publications..."):
            sources = collect_macro_evidence(catalog)
        for source in sources:
            console.print(
                f"{source['source']}: {source['status']} ({source['added']} new items)",
                markup=False,
            )
        console.print(
            "Central-bank publications are partial macro evidence, not a verified economic calendar."
        )
        graph = TradingAgentsGraph(
            selected_analysts=["market", "news", "social"], config=model_config(settings)
        )
        deadline = time.monotonic() + (4 * 3600 if mode == "watch" else 0)
        last_key = None
        last_review = None
        while True:
            if process.poll() is not None:
                raise RuntimeError(
                    f"MT5 recorder stopped. Check {catalog.path.parent / 'recorder.log'}"
                )
            row = analyze_event(
                catalog, graph, feed, settings.symbol, datetime.now(timezone.utc), "shadow"
            )
            execution = review_execution(catalog, row, datetime.now(timezone.utc))
            if row["event_key"] != last_key or execution["status"] != last_review:
                show_result(row, execution)
                last_key = row["event_key"]
                last_review = execution["status"]
            if mode == "once" or time.monotonic() >= deadline:
                break
            time.sleep(min(30, max(0, deadline - time.monotonic())))
    return settings


def recorded_replay(catalog, settings):
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    feed = select_feed(catalog, settings.symbol, None)
    as_of = aware(
        ask(questionary.text("Replay timestamp with timezone (e.g. 2026-09-10T12:00:30Z):"))
    )
    check_market_ready(catalog, feed, settings.symbol, as_of)
    graph = TradingAgentsGraph(
        selected_analysts=["market", "news", "social"], config=model_config(settings)
    )
    row = analyze_event(catalog, graph, feed, settings.symbol, as_of, "replay")
    show_result(row, review_execution(catalog, row, datetime.now(timezone.utc)))


def file_path(message):
    def valid(value):
        return Path(value.strip().strip('"')).is_file() or "Choose an existing file"

    return ask(questionary.text(message, validate=valid)).strip().strip('"')


def import_data(path):
    from finance_lab.astra.__main__ import main

    kind = choose(
        "Historical data to import:",
        [
            ("Bid/ask quotes (CSV + instrument JSON)", "quotes"),
            ("Closed M15 bars (JSONL)", "bar"),
            ("Account snapshots (JSONL)", "account"),
            ("News / macro / sentiment evidence (JSONL)", "evidence"),
        ],
    )
    source = file_path("Data file:")
    args = (
        ["import-quotes", source, "--instrument", file_path("Instrument specification JSON:")]
        if kind == "quotes"
        else ["import-records", kind, source]
    )
    main(["--config", str(path), *args])


def historical_baseline():
    from rich.prompt import FloatPrompt, Prompt

    from finance_lab.ftmo.__main__ import main

    console.print(
        "Historical Backtrader baseline: deterministic swing study, not a full-agent replay."
    )
    source = file_path("Real EUR/USD M15 OHLC CSV:")
    args = [
        "--csv",
        source,
        "--timezone",
        Prompt.ask("Broker CSV timezone (IANA)"),
        "--price-basis",
        Prompt.ask("Price basis", choices=["bid", "mid"], default="bid"),
        "--balance",
        field_value("initial_balance", "Original test account balance (USD):"),
        "--phase",
        Prompt.ask("Two-step phase", choices=["challenge", "verification"], default="challenge"),
    ]
    for flag, label, default in (
        ("--risk", "Risk per trade (%)", 0.25),
        ("--spread-pips", "Spread (pips)", 1.0),
        ("--slippage-pips", "Slippage per side (pips)", 0.2),
        ("--commission", "Commission per 100k lot per side (USD)", 3.5),
        ("--swap-long", "Long swap USD/lot/day (negative is debit)", -8.0),
        ("--swap-short", "Short swap USD/lot/day (negative is debit)", -4.0),
    ):
        args.extend([flag, str(FloatPrompt.ask(label, default=default))])
    main(args)


def compare_engines(path, catalog):
    from finance_lab.astra.__main__ import main

    rows = [
        r
        for r in catalog.decisions()
        if r["status"] == "complete"
        and ((r.get("data") or {}).get("gate") or {}).get("verdict") == "APPROVE"
    ]
    if not rows:
        console.print(
            "No approved recorded candidate to compare. Run shadow or recorded replay first."
        )
        return
    key = choose(
        "Frozen candidate:",
        [(r["timestamp"] + " " + r["event_key"][:12], r["event_key"]) for r in rows],
    )
    console.print(
        "Execution POC only: up to four hours, one Prague day; not a multi-day swing validation."
    )
    until = ask(questionary.text("End timestamp with timezone (ISO 8601):"))
    aware(until)
    main(["--config", str(path), "compare-engines", key, "--until", until])


def run_ftmo_workspace(config_path=None):
    path = Path(config_path or ROOT / ".astra.json")
    load_dotenv(ROOT / ".env", override=False)
    console.print(
        Panel(
            "MT5 market data -> TradingAgents research -> swing contract\n"
            "-> FTMO risk gate -> Nautilus / Backtrader replay -> shadow ledger\n"
            "EUR/USD only | Broker orders disabled",
            title="TradingAgents / FTMO",
        )
    )
    try:
        settings = load_settings(path, repair=True)
        catalog = Catalog(ROOT / settings.catalog)
    except (ValueError, OSError) as exc:
        console.print(f"Cannot continue this step: {exc}", style="yellow", markup=False)
        return
    while True:
        action = None
        try:
            action = choose(
                "FTMO workspace:",
                [
                    ("Start full pipeline: Live MT5 shadow analysis", "live"),
                    ("Recorded replay (historical full-agent reasoning)", "replay"),
                    ("Dashboard (charts and agent reasoning)", "dashboard"),
                    ("Model and language setup", "models"),
                    ("Connect / change MT5 account", "account"),
                    ("Import historical data / news evidence", "import"),
                    ("Historical CSV swing study (Backtrader baseline)", "baseline"),
                    ("Compare Backtrader / Nautilus (execution POC)", "compare"),
                    ("Status", "status"),
                    ("Exit", "exit"),
                ],
            )
            if action == "exit":
                return
            if action in {"live", "replay"}:
                settings = configure_models(path, settings)
                if action == "live":
                    settings = live_analysis(path, settings, catalog)
                else:
                    recorded_replay(catalog, settings)
                if catalog.decisions() and ask(
                    questionary.confirm("Open the decision dashboard?", default=True)
                ):
                    open_dashboard(catalog)
            elif action == "models":
                settings = configure_models(path, settings)
            elif action == "account":
                settings = configure_account(path, settings)
            elif action == "dashboard":
                open_dashboard(catalog)
            elif action == "status":
                show_status(catalog, settings)
            elif action == "import":
                import_data(path)
            elif action == "baseline":
                historical_baseline()
            elif action == "compare":
                compare_engines(path, catalog)
        except StepCancelled:
            if action is None:
                return
            console.print("Step cancelled. Back to the FTMO workspace.")
        except KeyboardInterrupt:
            console.print("Stopped. Recorded data retained; no broker orders sent.")
            return
        except (ValueError, RuntimeError, OSError, ImportError, argparse.ArgumentTypeError) as exc:
            console.print(f"Cannot continue this step: {exc}", style="yellow", markup=False)
            if action is None:
                return
