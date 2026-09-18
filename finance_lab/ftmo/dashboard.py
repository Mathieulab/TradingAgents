"""Interactive terminal charts for completed historical experiments."""

from rich.table import Table
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Select,
    Static,
    TabbedContent,
    TabPane,
)
from textual_plotext import PlotextPlot


def money(value):
    return f"${value:,.2f}"


def price_value(value):
    return f"{value:.5f}" if value is not None else "--"


def comparison_table(result):
    table = Table(expand=True, border_style="dim", header_style="bold cyan")
    for name in (
        "Period",
        "Net",
        "Trades",
        "Win %",
        "PF",
        "DD",
        "Objectives",
    ):
        table.add_column(name)
    for key, label in (
        ("development", "Dev 70%"),
        ("holdout", "Holdout 30%"),
        ("stress", "2x costs"),
    ):
        m = result[key]["metrics"]
        table.add_row(
            label,
            f"{m['return_pct']:+.2f}%",
            str(m["trades"]),
            f"{m['win_rate']:.0%}" if m["win_rate"] is not None else "n/a",
            f"{m['profit_factor']:.2f}" if m["profit_factor"] is not None else "n/a",
            f"{m['max_drawdown_pct']:.2f}%",
            m["status"],
        )
    return table


class TestDesk(App):
    TITLE = "FTMO TEST DESK"
    SUB_TITLE = "EUR/USD | H4 swing | Historical simulation"
    BINDINGS = [
        ("a", "astra", "Agent decisions"),
        ("q", "quit", "Quit"),
        ("space", "play", "Play/Pause"),
        ("left", "step(-1)", "Previous"),
        ("right", "step(1)", "Next"),
        ("home", "first", "Start"),
        ("end", "last", "End"),
        ("plus,equals", "zoom(-20)", "Zoom in"),
        ("minus", "zoom(20)", "Zoom out"),
        ("s", "screenshot", "Snapshot"),
    ]
    CSS = """
    Screen { background: #101413; color: #e1e7e3; }
    Header { background: #202924; }
    #provenance { height: auto; max-height: 4; padding: 0 1; color: #edbd67; }
    #account { height: auto; min-height: 3; padding: 1; background: #202924; }
    #controls { height: 3; }
    #period { width: 28; }
    #timeframe { width: 19; }
    #controls Button { min-width: 8; margin: 0 1 0 0; }
    #clock { width: 1fr; content-align: right middle; padding-right: 1; }
    TabbedContent { height: 1fr; }
    TabPane { padding: 0 1; }
    #market-layout { height: 1fr; }
    #charts { width: 1fr; height: 1fr; }
    #price { height: 3fr; min-height: 10; }
    #atr { height: 1fr; min-height: 5; }
    #equity { height: 2fr; min-height: 7; }
    #technical { width: 34; height: 1fr; padding: 1; border-left: solid #46544c; }
    #technical Static { height: auto; margin-bottom: 1; }
    .compact #market-layout { layout: vertical; height: auto; }
    .compact #charts { width: 100%; height: 30; }
    .compact #technical { width: 100%; height: auto; border-left: none; }
    .compact #clock { display: none; }
    #market { overflow-y: auto; }
    #journal { height: 1fr; }
    #validation Static, #rules Static { height: auto; padding: 1; }
    #validation, #rules { overflow-x: auto; overflow-y: auto; }
    Footer { background: #202924; }
    """

    def __init__(self, result, report_dir):
        super().__init__()
        self.result = result
        self.report_dir = report_dir
        self.period = "holdout"
        self.cursor = len(result[self.period]["curve"]) - 1
        self.window = 60
        self.playing = False
        self.timeframe = "H4"
        self.candles = {c["time"]: c for c in result["candles"]}
        self.swing_bars = {c["time"]: c for c in result["swing_candles"]}

    def action_astra(self):
        try:
            from finance_lab.astra.__main__ import ROOT, Settings
            from finance_lab.astra.catalog import Catalog
            from finance_lab.astra.dashboard import ShadowScreen

            config_path = ROOT / ".astra.json"
            settings = Settings.model_validate_json(config_path.read_text(encoding="utf-8")) if config_path.exists() else Settings()
            self.push_screen(ShadowScreen(Catalog(ROOT / settings.catalog)))
        except (ImportError, ValueError, OSError) as exc:
            self.notify(f"Agent ledger unavailable: {exc}. Use the Astra environment.", severity="warning")

    def compose(self) -> ComposeResult:
        yield Header()
        label = "SYNTHETIC DEMO" if self.result["synthetic"] else "HISTORICAL CSV"
        yield Static(
            Text(f"{label} | {self.result['source']} | FTMO 2-Step | USD account"), id="provenance"
        )
        yield Static(id="account")
        with Horizontal(id="controls"):
            yield Select(
                [
                    ("Holdout 30%", "holdout"),
                    ("Development 70%", "development"),
                    ("Stress 2x costs", "stress"),
                ],
                value="holdout",
                allow_blank=False,
                id="period",
            )
            yield Select(
                [("H4 swing", "H4"), ("M15 fills", "M15")],
                value="H4",
                allow_blank=False,
                id="timeframe",
            )
            yield Button("<", id="previous", tooltip="Previous candle")
            yield Button("Play", id="play", tooltip="Replay historical candles")
            yield Button(">", id="next", tooltip="Next candle")
            yield Static(id="clock")
        with TabbedContent():
            with TabPane("Market", id="market"), Horizontal(id="market-layout"):
                with Vertical(id="charts"):
                    yield PlotextPlot(id="price")
                    yield PlotextPlot(id="atr")
                    yield PlotextPlot(id="equity")
                with VerticalScroll(id="technical"):
                    yield Static(id="levels")
                    yield Static(id="risk")
                    yield Static(id="schema")
            with TabPane("Trade journal"):
                yield DataTable(id="journal", zebra_stripes=True, cursor_type="row")
            with TabPane("Validation"), VerticalScroll(id="validation"):
                yield Static(comparison_table(self.result))
                yield Static(Text(self.result["assessment"], style="bold yellow"))
                yield Static(Text("\n\n".join(self.result["reasons"])))
                yield Static(
                    Text(f"Split: {self.result['split_time']}\nSaved run: {self.report_dir}")
                )
            with TabPane("Account rules"), VerticalScroll(id="rules"):
                yield Static(self.rules_text())
        yield Footer()

    def on_mount(self):
        self.set_class(self.size.width < 110, "compact")
        self.query_one("#journal", DataTable).add_columns(
            "Entry UTC",
            "Exit UTC",
            "Side",
            "Lots",
            "Entry",
            "Stop",
            "Target",
            "Net P/L",
            "R",
            "Exit",
        )
        self.set_interval(0.25, self.tick)
        self.refresh_view()

    def on_resize(self):
        self.set_class(self.size.width < 110, "compact")

    def rules_text(self):
        c = self.result["config"]
        target = 10 if c["phase"] == "challenge" else 5
        return Text(
            f"FTMO 2-Step / {c['phase'].title()}\n\n"
            f"Initial simulated balance: {money(c['balance'])}\n"
            f"Profit target: {target}% | Minimum trading days: 4\n"
            "Daily loss: 5% of initial balance, reset at 00:00 Europe/Prague\n"
            "Overall loss: 10% of initial balance, static floor\n"
            f"Strategy daily cutoff: {c['daily_stop_pct']}% | Risk/trade: {c['risk_pct']}%\n"
            f"Maximum entries/day: {c['max_trades_per_day']} | Leverage cap: {c['leverage']}:1\n\n"
            f"Spread: {c['spread_pips']} pips | Slippage: {c['slippage_pips']} pips per side\n"
            f"Commission: ${c['commission_per_lot_side']:.2f} per 100k lot per side\n"
            f"Swap: long ${c['swap_long_per_lot']:.2f}, short ${c['swap_short_per_lot']:.2f} / lot / day\n"
            "Rollover: 17:00 New York, triple Wednesday (estimated broker convention)\n"
            f"Entries: 07:00-15:45 UTC | Maximum hold: {c['max_hold_days']} calendar days\n"
            "Completed H4 signal -> next M15 open -> stop-first OCO bracket\n"
            "Positions can remain open overnight and over weekends.\n\n"
            "One-step and funded-account rules are not modelled.\n"
            "Spread is charged as a fixed cost; all charts show midpoint prices.\n"
            "Bar highs/lows estimate floating loss; tick ordering is not observable.\n"
            "Daily cutoff liquidation occurs at the next available open. Gaps can exceed stops.\n"
            "No news calendar or live broker feed is connected.\n\n"
            f"Rules checked: {self.result['rules_checked']}\n{self.result['rules_source']}"
        )

    @on(Select.Changed, "#period")
    def period_changed(self, event):
        if event.value not in {"development", "holdout", "stress"}:
            return
        self.period = event.value
        self.cursor = len(self.result[self.period]["curve"]) - 1
        self.playing = False
        if self.is_mounted:
            self.refresh_view()

    @on(Button.Pressed)
    def control(self, event):
        if event.button.id == "play":
            self.action_play()
        elif event.button.id in {"previous", "next"}:
            self.action_step(-1 if event.button.id == "previous" else 1)

    @on(Select.Changed, "#timeframe")
    def timeframe_changed(self, event):
        if event.value in {"H4", "M15"}:
            self.timeframe = event.value
            if self.is_mounted:
                self.refresh_view()

    def action_play(self):
        if self.cursor == len(self.result[self.period]["curve"]) - 1:
            self.cursor = 0
        self.playing = not self.playing
        self.refresh_view()

    def tick(self):
        if self.playing:
            self.action_step(1)

    def action_step(self, delta):
        amount = delta * (16 if self.timeframe == "H4" else 1)
        self.cursor = max(0, min(self.cursor + amount, len(self.result[self.period]["curve"]) - 1))
        if self.cursor == len(self.result[self.period]["curve"]) - 1:
            self.playing = False
        self.refresh_view()

    def action_first(self):
        self.playing = False
        self.cursor = 0
        self.refresh_view()

    def action_last(self):
        self.playing = False
        self.cursor = len(self.result[self.period]["curve"]) - 1
        self.refresh_view()

    def action_zoom(self, delta):
        self.window = max(20, min(160, self.window + delta))
        self.refresh_view()

    def action_screenshot(self):
        path = self.save_screenshot(path=str(self.report_dir))
        self.notify(f"Snapshot: {path}")

    def refresh_view(self):
        run = self.result[self.period]
        row = run["curve"][self.cursor]
        c = self.result["config"]
        self.query_one("#play", Button).label = "Pause" if self.playing else "Play"
        self.query_one("#clock", Static).update(row["time"][:16] + " UTC")
        self.query_one("#account", Static).update(
            Text(
                f"Equity {money(row['equity'])}    Net {row['equity'] / c['balance'] - 1:+.2%}    "
                f"Daily room {money(row['daily_remaining'])}    Overall room {money(row['total_remaining'])}"
            )
        )
        latest = self.candles[row["time"]]
        trend = "UP" if row["fast"] is not None and row["fast"] > row["slow"] else "DOWN"
        fmt = price_value
        signal = {-1: "SHORT", 0: "WAIT", 1: "LONG"}[row["signal"]]
        self.query_one("#levels", Static).update(
            Text(
                f"{row['time'][:16]} UTC\n\nH4 TREND {trend}\nM15 close {latest['close']:.5f}\n"
                f"EMA {c['fast_period']:<5} {fmt(row['fast'])}\nEMA {c['slow_period']:<5} {fmt(row['slow'])}\n"
                f"Channel H {fmt(row['upper'])}\nChannel L {fmt(row['lower'])}\nATR       {fmt(row['atr'])}\n\n"
                f"Signal    {signal}"
            )
        )
        self.query_one("#risk", Static).update(
            Text(
                f"POSITION  {row['position'] / 100000:+.2f} lots\n"
                f"Stop      {fmt(row['stop'])}\nTarget    {fmt(row['target'])}\n\n"
                f"Daily floor  {money(row['daily_floor'])}\n"
                f"Day low      {money(row['day_low'])}\n"
                f"Cutoff floor {money(row['internal_floor'])}"
            )
        )
        self.query_one("#schema", Static).update(
            Text(
                "SWING STRATEGY\n\n"
                f"Completed H4 EMA {c['fast_period']}/{c['slow_period']}\n  |\n"
                f"Prior {c['breakout_period']} H4 bars breakout\n  |\n"
                "Session + risk checks\n  |\nNext M15 open\n  |\n"
                f"{c['atr_stop']} x ATR stop / {c['reward_risk']}R target\n  |\n"
                f"Multi-day hold / max {c['max_hold_days']} days"
            )
        )
        rows = run["curve"][: self.cursor + 1]
        if self.timeframe == "H4":
            rows = [r for r in rows if r["h4_close"]]
        rows = rows[-self.window :]
        self.draw_charts(rows, run, row)
        journal = self.query_one("#journal", DataTable)
        journal.clear()
        for t in run["trades"]:
            if t["exit_time"] > row["time"]:
                continue
            journal.add_row(
                t["entry_time"][:16],
                t["exit_time"][:16],
                t["side"],
                f"{abs(t['size']) / 100000:.2f}",
                f"{t['entry']:.5f}",
                f"{t['stop']:.5f}",
                f"{t['target']:.5f}",
                Text(f"{t['pnl']:+.2f}", style="green" if t["pnl"] > 0 else "red"),
                f"{t['r_multiple']:+.2f}",
                t["exit_reason"],
            )

    def draw_charts(self, rows, run, current):
        if not rows:
            for chart in self.query(PlotextPlot):
                chart.plt.clear_data()
                chart.plt.title("Waiting for the next completed H4 candle")
                chart.refresh()
            return
        x = list(range(len(rows)))
        price = self.query_one("#price", PlotextPlot)
        p = price.plt
        p.clear_data()
        source = self.swing_bars if self.timeframe == "H4" else self.candles
        bars = [source[r["time"]] for r in rows]
        p.candlestick(
            x,
            {k.title(): [b[k] for b in bars] for k in ("open", "high", "low", "close")},
            colors=["green+", "red+"],
        )
        for key, color, label in (
            ("fast", "cyan", "Fast EMA"),
            ("slow", "yellow", "Slow EMA"),
            ("upper", "gray", "Channel"),
            ("lower", "gray", None),
        ):
            points = [(i, r[key]) for i, r in enumerate(rows) if r[key] is not None]
            if points:
                p.plot([i for i, _ in points], [v for _, v in points], color=color, label=label)

        def marker_index(time):
            if time < rows[0]["time"] or time > current["time"]:
                return None
            return max(i for i, r in enumerate(rows) if r["time"] <= time)

        for trade in run["trades"]:
            entry_idx = marker_index(trade["entry_time"])
            exit_idx = marker_index(trade["exit_time"])
            if entry_idx is not None:
                p.scatter(
                    [entry_idx],
                    [trade["entry"]],
                    marker="^" if trade["side"] == "LONG" else "v",
                    color="white",
                )
            if exit_idx is not None:
                p.scatter([exit_idx], [trade["exit"]], marker="x", color="magenta")
        for key, color in (("stop", "red"), ("target", "green")):
            if current[key] is not None:
                p.hline(current[key], color=color)
        p.title(f"EUR/USD midpoint | {self.timeframe} swing setup")
        ticks = sorted({0, len(rows) // 2, len(rows) - 1})
        labels = [
            rows[i]["time"][5:10] if self.timeframe == "H4" else rows[i]["time"][11:16]
            for i in ticks
        ]
        p.xticks(ticks, labels)
        p.xlim(-1, max(1, len(rows)))
        price.refresh()

        for chart_id, key, title, color in (
            ("atr", "atr", "ATR (pips)", "yellow"),
            ("equity", "equity", "Equity / initial balance (USD)", "cyan"),
        ):
            widget = self.query_one(f"#{chart_id}", PlotextPlot)
            plot = widget.plt
            plot.clear_data()
            points = [
                (i, r[key] * (10000 if key == "atr" else 1))
                for i, r in enumerate(rows)
                if r[key] is not None
            ]
            if points:
                plot.plot([i for i, _ in points], [v for _, v in points], color=color)
            if key == "equity":
                plot.hline(self.result["config"]["balance"], color="gray")
            plot.title(title)
            plot.xticks(ticks, labels)
            plot.xlim(-1, max(1, len(rows)))
            widget.refresh()
