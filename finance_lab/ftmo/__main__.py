"""Run with python -m finance_lab.ftmo; no API keys or environment variables."""

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.prompt import FloatPrompt, Prompt
from rich.text import Text

from .config import TestConfig
from .data import demo_bars, load_csv
from .engine import evaluate
from .report import save_run


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="FTMO 2-Step EUR/USD H4 swing test desk (M15 execution data)"
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--demo", action="store_true", help="Use labelled synthetic candles")
    source.add_argument("--csv", type=Path, help="EUR/USD M15 CSV with bar-open timestamps")
    parser.add_argument("--timezone", help="IANA timezone of naive CSV timestamps, e.g. Etc/GMT-2")
    parser.add_argument("--price-basis", choices=("bid", "mid"), default=None)
    parser.add_argument("--balance", type=float, default=None)
    parser.add_argument("--risk", type=float, default=None, help="Risk per trade, in percent")
    parser.add_argument("--phase", choices=("challenge", "verification"), default=None)
    parser.add_argument("--spread-pips", type=float, default=1.0)
    parser.add_argument("--slippage-pips", type=float, default=0.2)
    parser.add_argument("--commission", type=float, default=3.5, help="USD per 100k lot per side")
    parser.add_argument(
        "--swap-long", type=float, default=-8.0, help="Long swap USD/lot/day; negative is a debit"
    )
    parser.add_argument(
        "--swap-short", type=float, default=-4.0, help="Short swap USD/lot/day; negative is a debit"
    )
    parser.add_argument(
        "--no-ui", action="store_true", help="Print comparison and save run, then exit"
    )
    parser.add_argument("--output", type=Path, default=Path("reports/ftmo"))
    args = parser.parse_args(argv)
    console = Console()
    interactive = not args.demo and args.csv is None and sys.stdin.isatty()
    if interactive:
        console.print(
            "[bold]FTMO Swing Test Desk[/bold] | EUR/USD | H4 signals / M15 execution | Two-step"
        )
        selected = Prompt.ask("Dataset", choices=["demo", "csv"], default="demo")
        if selected == "csv":
            args.csv = Path(Prompt.ask("CSV path").strip().strip('"'))
            args.timezone = args.timezone or Prompt.ask(
                "Broker export timezone (IANA, confirmed from broker)"
            )
            args.price_basis = args.price_basis or Prompt.ask(
                "Candle prices", choices=["bid", "mid"], default="bid"
            )
        args.balance = (
            args.balance
            if args.balance is not None
            else FloatPrompt.ask("Account balance (USD)", default=10000)
        )
        args.risk = (
            args.risk
            if args.risk is not None
            else FloatPrompt.ask("Risk per trade (%)", default=0.25)
        )
        args.phase = args.phase or Prompt.ask(
            "Two-step phase", choices=["challenge", "verification"], default="challenge"
        )
        args.spread_pips = FloatPrompt.ask("Spread (pips)", default=args.spread_pips)
        args.slippage_pips = FloatPrompt.ask("Slippage per side (pips)", default=args.slippage_pips)
        args.commission = FloatPrompt.ask(
            "Commission per lot per side (USD)", default=args.commission
        )
        args.swap_long = FloatPrompt.ask(
            "Long swap USD/lot/day (negative = debit)", default=args.swap_long
        )
        args.swap_short = FloatPrompt.ask(
            "Short swap USD/lot/day (negative = debit)", default=args.swap_short
        )
    if args.csv and args.price_basis is None:
        parser.error("CSV runs require --price-basis bid or --price-basis mid.")
    try:
        cfg = TestConfig(
            balance=args.balance if args.balance is not None else 10000,
            risk_pct=args.risk if args.risk is not None else 0.25,
            phase=args.phase or "challenge",
            spread_pips=args.spread_pips,
            slippage_pips=args.slippage_pips,
            commission_per_lot_side=args.commission,
            swap_long_per_lot=args.swap_long,
            swap_short_per_lot=args.swap_short,
        )
        bars = (
            load_csv(
                args.csv,
                timezone=args.timezone,
                price_basis=args.price_basis,
                spread_pips=cfg.spread_pips,
            )
            if args.csv
            else demo_bars()
        )
        with console.status("Running development, holdout and doubled-cost tests..."):
            result = evaluate(
                bars,
                cfg,
                source=str(args.csv.resolve()) if args.csv else "Seed 731 / synthetic M15 candles",
                synthetic=args.csv is None,
            )
        result["input"] = {"timezone": args.timezone, "price_basis": args.price_basis or "mid"}
        folder = save_run(result, args.output)
    except (ValueError, OSError, RuntimeError) as exc:
        console.print(Text(f"Test failed: {exc}", style="red"))
        return 2
    from .dashboard import TestDesk, comparison_table

    if args.no_ui or not sys.stdout.isatty():
        console.print(result["assessment"])
        console.print(comparison_table(result))
        for reason in result["reasons"]:
            console.print(Text(reason))
        console.print(f"Saved run: {folder}")
    else:
        TestDesk(result, folder).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
