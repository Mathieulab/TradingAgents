"""Recorded reasoning companion to the existing FTMO historical chart desk."""

from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static, TabbedContent, TabPane
from textual_plotext import PlotextPlot


def details(title, values):
    table = Table(title=title, show_header=False, expand=True, box=None)
    table.add_column(style="cyan", ratio=1)
    table.add_column(ratio=3, overflow="fold")
    for name, value in values.items():
        if isinstance(value, list):
            value = "; ".join(str(item) for item in value)
        table.add_row(
            Text(name.replace("_", " ").title()),
            Text("Unavailable" if value is None else str(value)),
        )
    return table


class ShadowScreen(Screen):
    BINDINGS = [("q,escape", "back", "Back"), ("r", "reload", "Refresh")]
    DEFAULT_CSS = """
    Screen { background: #101413; color: #e1e7e3; }
    Header, Footer { background: #202924; }
    #decisions { height: 9; }
    #summary { height: auto; max-height: 8; padding: 1; color: #edbd67; }
    TabbedContent { height: 1fr; }
    TabPane { padding: 0 1; }
    #price { height: 20; }
    #agents { height: 12; }
    .detail { height: auto; padding: 1; }
    """

    def __init__(self, catalog, *, standalone=False):
        super().__init__()
        self.catalog = catalog
        self.standalone = standalone
        self.rows = {}
        self.execution_reviews = {}
        self.selected = None
        self.agent_reports = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("No recorded decisions", id="summary")
        yield DataTable(id="decisions", cursor_type="row")
        with TabbedContent():
            with TabPane("Market"), VerticalScroll():
                yield PlotextPlot(id="price")
                yield Static(id="market", classes="detail")
            with TabPane("Reasoning Chain"), VerticalScroll():
                yield DataTable(id="agents", cursor_type="row")
                yield Static(id="reasoning", classes="detail")
            with TabPane("Proposal / FTMO"), VerticalScroll():
                yield Static(id="risk", classes="detail")
            with TabPane("Validation"):
                yield Static(id="validation", classes="detail")
        yield Footer()

    def on_mount(self):
        table = self.query_one("#decisions", DataTable)
        table.add_columns("UTC", "Mode", "Event", "State", "Direction", "Gate")
        agents = self.query_one("#agents", DataTable)
        agents.add_column("Agent", width=23)
        agents.add_column("Conclusion", width=85)
        self.action_reload()
        self.set_interval(5, self.action_reload)

    def action_back(self):
        if not self.standalone:
            self.app.pop_screen()
        else:
            self.app.exit()

    def action_reload(self):
        rows = self.catalog.decisions()
        new = {r["event_key"]: r for r in rows}
        reviews = {key: self.catalog.execution_review(key) for key in new}
        if new == self.rows and reviews == self.execution_reviews:
            return
        self.rows = new
        self.execution_reviews = reviews
        table = self.query_one("#decisions", DataTable)
        table.clear()
        for row in reversed(rows[-200:]):
            data = row.get("data") or {}
            table.add_row(
                row["timestamp"],
                data.get("mode", "--"),
                data.get("event", "--"),
                row["status"],
                (data.get("proposal") or {}).get("direction", "--"),
                (data.get("gate") or {}).get("verdict", "--"),
                key=row["event_key"],
            )
        if rows:
            self.show_decision(
                self.selected if self.selected in self.rows else rows[-1]["event_key"]
            )

    @on(DataTable.RowSelected, "#decisions")
    def select_decision(self, event):
        self.show_decision(event.row_key.value)

    @on(DataTable.RowSelected, "#agents")
    def select_agent(self, event):
        name = event.row_key.value
        self.query_one("#reasoning", Static).update(Text(f"{name}\n\n{self.agent_reports[name]}"))

    def show_decision(self, key):
        self.selected = key
        row = self.rows[key]
        data = row.get("data") or {}
        snapshot = data.get("snapshot") or data
        proposal, gate = data.get("proposal") or {}, data.get("gate") or {}
        self.query_one("#summary", Static).update(
            Text(
                f"{(snapshot.get('instrument') or {}).get('symbol', '--')} | {row['timestamp']} | {row['status']}\n"
                f"{proposal.get('direction', '--')} | Confidence {proposal.get('confidence', '--')} | "
                f"Gate: {gate.get('verdict', '--')} | Orders sent: NONE\n"
                + "; ".join(gate.get("reasons", []))
            )
        )
        technical = snapshot.get("technical") or {}
        self.query_one("#market", Static).update(
            Group(
                details("RECORDED QUOTE", snapshot.get("quote") or {"state": "Unavailable"}),
                details(
                    "TECHNICAL EVIDENCE",
                    {k: v for k, v in technical.items() if k not in {"chart", "m15", "h4", "d1"}},
                ),
            )
        )
        chain = data.get("reasoning") or {}
        reports = {}
        for name, field in (
            ("Technical", "market_report"),
            ("News / Macro", "news_report"),
            ("Sentiment", "sentiment_report"),
            ("Fundamentals", "fundamentals_report"),
            ("Research Manager", "investment_plan"),
        ):
            reports[name] = chain.get(field) or "Unavailable"
        debate = chain.get("investment_debate_state") or {}
        risk_debate = chain.get("risk_debate_state") or {}
        reports.update(
            {
                "Bull Researcher": debate.get("bull_history") or "Unavailable",
                "Bear Researcher": debate.get("bear_history") or "Unavailable",
                "Trader": (chain.get("astra_trader_proposal") or {}).get("reasoning_summary")
                or chain.get("trader_investment_plan")
                or "Unavailable",
                "Aggressive Risk": risk_debate.get("aggressive_history") or "Unavailable",
                "Conservative Risk": risk_debate.get("conservative_history") or "Unavailable",
                "Neutral Risk": risk_debate.get("neutral_history") or "Unavailable",
                "Portfolio Manager": proposal.get("reasoning_summary") or "Unavailable",
            }
        )
        self.agent_reports = reports
        agents = self.query_one("#agents", DataTable)
        agents.clear()
        for name in (
            "Technical",
            "News / Macro",
            "Sentiment",
            "Fundamentals",
            "Bull Researcher",
            "Bear Researcher",
            "Research Manager",
            "Trader",
            "Aggressive Risk",
            "Conservative Risk",
            "Neutral Risk",
            "Portfolio Manager",
        ):
            summary = " ".join(reports[name].split())
            agents.add_row(name, summary[:160] + ("..." if len(summary) > 160 else ""), key=name)
        self.query_one("#reasoning", Static).update(Text("Technical\n\n" + reports["Technical"]))
        self.query_one("#risk", Static).update(
            Group(
                details("PROPOSAL", proposal),
                details("DETERMINISTIC GATE", gate),
                details("ACCOUNT AT GATE", data.get("gate_account") or {}),
                details("COST RESERVES", data.get("policy") or {}),
            )
        )
        stages = snapshot.get("validation") or {}
        execution = self.catalog.execution_review(key) or {}
        self.query_one("#validation", Static).update(
            Text(
                "\n".join(
                    f"{stage}: {'Unavailable' if value is None else value}"
                    for stage, value in stages.items()
                )
                + "\n\nEXECUTION POC: " + execution.get("status", "Not run")
                + "\n" + execution.get("reason", "")
                + "\n" + "\n".join(
                    f"{r['engine']}: {len(r.get('fills') or [])} simulated fills; net PnL {r.get('net_pnl', 'n/a')}"
                    for r in execution.get("engines", [])
                )
                + "\n\nNo profitability inferred from shadow approval or execution POC. "
                "Commissions, swaps, latency and multi-day swing outcomes remain unvalidated."
            )
        )
        plot = self.query_one("#price", PlotextPlot)
        plot.plt.clear_figure()
        chart = technical.get("chart", [])
        if chart:
            plot.plt.plot(list(range(len(chart))), [c["close"] for c in chart], label="H4 close")
            indices = sorted({0, len(chart) // 2, len(chart) - 1})
            plot.plt.xticks(
                indices,
                [
                    chart[i]["time"][5:16].replace("T", " ") if "time" in chart[i] else str(i)
                    for i in indices
                ],
            )
            for field, label in (("support", "Support"), ("resistance", "Resistance")):
                if technical.get(field) is not None:
                    plot.plt.plot([0, len(chart) - 1], [technical[field]] * 2, label=label)
            if proposal.get("stop_loss"):
                plot.plt.plot([0, len(chart) - 1], [proposal["stop_loss"]] * 2, label="Proposed SL")
            for target in proposal.get("take_profits", []):
                plot.plt.plot([0, len(chart) - 1], [target] * 2, label="Proposed TP")
        plot.plt.title("Recorded H4 closes | UTC | " + technical.get("basis", "Unavailable"))
        plot.refresh()


class ShadowDesk(App):
    TITLE = "ASTRA | SWING SHADOW DESK"
    SUB_TITLE = "Recorded decisions | Orders disabled"

    def __init__(self, catalog):
        super().__init__()
        self.catalog = catalog

    def on_mount(self):
        self.push_screen(ShadowScreen(self.catalog, standalone=True))
