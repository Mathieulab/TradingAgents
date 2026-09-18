"""Astra commands: real data recording, full-agent shadow, ledger and engine POC."""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field, ValidationError, field_validator
from rich.console import Console
from rich.prompt import Prompt

from .catalog import Catalog, canonical
from .models import AccountSnapshot, Bar, Evidence, GateResult, Instrument, Record, SwingProposal

ROOT = Path(__file__).resolve().parents[2]
console = Console()


class Settings(Record):
    catalog: str = "results/astra/market.sqlite"
    symbol: str = "EURUSD"
    mt5_server: str | None = None
    mt5_login: int | None = Field(default=None, gt=0)
    terminal_path: str | None = None
    initial_balance: float | None = Field(default=None, gt=0)
    llm_provider: str | None = None
    quick_think_llm: str | None = None
    deep_think_llm: str | None = None
    backend_url: str | None = None
    research_depth: int = Field(default=1, ge=1, le=5)
    output_language: str = "English"
    google_thinking_level: str | None = None
    openai_reasoning_effort: str | None = None
    anthropic_effort: str | None = None

    @field_validator("symbol")
    @classmethod
    def valid_symbol(cls, value):
        value = value.strip()
        if value.upper() == "EUR/USD":
            return "EURUSD"
        if not value.upper().startswith("EURUSD") or len(value) > 32 or not all(c.isalnum() or c in "._-" for c in value):
            raise ValueError("Choose the EUR/USD trading pair, usually EURUSD or a broker-suffixed EURUSD symbol. USD alone is an account currency")
        return value[:6].upper() + value[6:]

    @field_validator("backend_url")
    @classmethod
    def valid_endpoint(cls, value):
        if value is None:
            return None
        from cli.local_models import validate_endpoint
        return validate_endpoint(value)


def load_settings(path, *, repair=False):
    if not path.exists():
        return Settings()
    data = json.loads(path.read_text(encoding="utf-8"))
    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        if not repair or not isinstance(data, dict):
            raise
        for error in exc.errors():
            field = error["loc"][0]
            data.pop(field, None)
            console.print(f"Saved {field} needs correction; using its default until setup is saved.", style="yellow", markup=False)
        return Settings.model_validate(data)


def aware(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise argparse.ArgumentTypeError("Use an explicit offset or Z")
    return result.astimezone(timezone.utc)


def configure(path, settings):
    from cli.ftmo import configure_models
    return configure_models(path, settings)


def select_feed(catalog, symbol, explicit):
    if explicit:
        catalog.get_instrument(explicit, symbol)
        return explicit
    with catalog.connect() as db:
        rows = db.execute(
            "SELECT DISTINCT feed_id FROM instruments WHERE symbol=?", (symbol,)
        ).fetchall()
    feeds = [row[0] for row in rows]
    if not feeds:
        raise ValueError("No recorded instrument. Record MT5 or import real data first")
    return feeds[0] if len(feeds) == 1 else Prompt.ask("Select recorded feed", choices=feeds)


def main(argv=None):
    load_dotenv(ROOT / ".env", override=False)
    parser = argparse.ArgumentParser(
        description="Astra swing lab: recorded data and shadow decisions only"
    )
    parser.add_argument("--config", type=Path, default=ROOT / ".astra.json")
    parser.add_argument("--catalog", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("configure")
    sub.add_parser("dashboard")
    sub.add_parser("status")
    record = sub.add_parser("record-mt5")
    record.add_argument("--seconds", type=float, default=3600)
    record.add_argument("--history-days", type=int, default=180)
    quotes = sub.add_parser("import-quotes")
    quotes.add_argument("path", type=Path)
    quotes.add_argument("--instrument", type=Path, required=True)
    records = sub.add_parser("import-records")
    records.add_argument("kind", choices=("bar", "account", "evidence"))
    records.add_argument("path", type=Path)
    analyze = sub.add_parser("analyze")
    analyze.add_argument("--feed")
    analyze.add_argument("--mode", choices=("shadow", "replay"), default="shadow")
    analyze.add_argument("--as-of", type=aware)
    analyze.add_argument(
        "--event",
        choices=("h4_close", "news", "regime", "volatility", "position_risk"),
        default="h4_close",
    )
    analyze.add_argument("--event-id")
    analyze.add_argument("--watch-seconds", type=float, default=0)
    compare = sub.add_parser("compare-engines")
    compare.add_argument("decision_key")
    compare.add_argument("--until", type=aware, required=True)
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.config, repair=args.command == "configure")
        if args.command == "configure":
            configure(args.config, settings)
            return 0
        catalog = Catalog(args.catalog or ROOT / settings.catalog)
        if args.command == "status":
            with catalog.connect() as db:
                counts = db.execute(
                    "SELECT kind,COUNT(*) FROM observations GROUP BY kind"
                ).fetchall()
                instruments = db.execute("SELECT feed_id,symbol FROM instruments").fetchall()
            console.print(
                {
                    "catalog": str(catalog.path),
                    "records": dict(counts),
                    "instruments": instruments,
                    "decisions": len(catalog.decisions()),
                    "orders_enabled": False,
                }
            )
        elif args.command == "dashboard":
            from cli.ftmo import open_dashboard
            open_dashboard(catalog)
        elif args.command == "record-mt5":
            from .providers import MT5MarketDataProvider
            from .recorder import record_mt5

            if not settings.mt5_server or not settings.mt5_login or not settings.initial_balance:
                from cli.ftmo import configure_account
                settings = configure_account(args.config, settings)
            provider = MT5MarketDataProvider(
                expected_server=settings.mt5_server,
                expected_login=settings.mt5_login,
                terminal_path=settings.terminal_path,
            )
            try:
                console.print(
                    "Read-only MT5 recording. Keep this process separate from agent analysis."
                )
                console.print(
                    record_mt5(
                        provider,
                        catalog,
                        settings.symbol,
                        settings.initial_balance,
                        args.seconds,
                        history_days=args.history_days,
                    )
                )
            finally:
                provider.close()
        elif args.command == "import-quotes":
            from .providers import CSVMarketDataProvider

            instrument = Instrument.model_validate_json(args.instrument.read_text(encoding="utf-8"))
            provider = CSVMarketDataProvider(args.path, instrument)
            catalog.instrument(instrument)
            count = sum(catalog.append(q) for q in provider.subscribe_quotes(instrument.symbol))
            console.print(f"Imported {count} quote observations. No synthetic data generated.")
        elif args.command == "import-records":
            model = {"bar": Bar, "account": AccountSnapshot, "evidence": Evidence}[args.kind]
            rows = [
                model.model_validate_json(line)
                for line in args.path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            console.print(f"Imported {sum(catalog.append(row) for row in rows)} observations")
        elif args.command == "analyze":
            from cli.ftmo import model_config
            from tradingagents.graph.trading_graph import TradingAgentsGraph

            from .orchestrator import run_event

            if args.mode == "shadow" and args.as_of:
                raise ValueError(
                    "Shadow always uses current UTC; use replay for an explicit --as-of"
                )
            if args.mode == "replay" and (not args.as_of or args.watch_seconds):
                raise ValueError("Replay requires --as-of and cannot watch live events")
            if args.watch_seconds < 0 or (args.watch_seconds and args.event != "h4_close"):
                raise ValueError(
                    "Watch currently supports only H4-close events with a positive duration"
                )
            feed = select_feed(catalog, settings.symbol, args.feed)
            if not all((settings.llm_provider, settings.quick_think_llm, settings.deep_think_llm)):
                settings = configure(args.config, settings)
            config = model_config(settings)
            graph = TradingAgentsGraph(
                selected_analysts=("market", "news", "social"), config=config
            )
            deadline = time.monotonic() + args.watch_seconds
            while True:
                row = run_event(
                    catalog,
                    graph,
                    feed,
                    settings.symbol,
                    args.as_of or datetime.now(timezone.utc),
                    mode=args.mode,
                    event=args.event,
                    event_id=args.event_id,
                )
                console.print(
                    {
                        "event_key": row["event_key"],
                        "status": row["status"],
                        "proposal": row["data"].get("proposal"),
                        "gate": row["data"].get("gate"),
                    }
                )
                if time.monotonic() >= deadline:
                    break
                time.sleep(min(30, max(0, deadline - time.monotonic())))
        elif args.command == "compare-engines":
            from .engines import BacktraderEngine, NautilusEngine

            rows = [
                r
                for r in catalog.decisions()
                if r["event_key"] == args.decision_key and r["status"] == "complete"
            ]
            if not rows:
                raise ValueError("Completed decision not found")
            data = rows[0]["data"]
            instrument = Instrument.model_validate(data["snapshot"]["instrument"])
            account = AccountSnapshot.model_validate(data["gate_account"])
            quotes = catalog.records(
                "quote",
                instrument.feed_id,
                instrument.symbol,
                args.until,
                start=aware(data["gate_as_of"]),
            )
            proposal, gate = (
                SwingProposal.model_validate(data["proposal"]),
                GateResult.model_validate(data["gate"]),
            )
            results = [
                engine.run(quotes, instrument, proposal, gate, account)
                for engine in (BacktraderEngine(), NautilusEngine())
            ]
            destination = catalog.path.parent / f"execution-poc-{args.decision_key[:16]}.json"
            destination.write_text(canonical(results), encoding="utf-8")
            console.print(f"Execution POC only. Saved {destination}", markup=False)
            for result in results:
                console.print(
                    {k: result[k] for k in ("engine", "version", "fills", "net_pnl", "limitations")}
                )
        return 0
    except (ValueError, RuntimeError, OSError, ImportError) as exc:
        console.print(f"Astra stopped: {exc}", style="red", markup=False)
        return 1
    except KeyboardInterrupt:
        console.print("Stopped. Persisted observations are retained; no orders were sent.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
