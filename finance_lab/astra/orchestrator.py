"""Event-triggered, idempotent full-agent shadow decisions. No order transport."""

from datetime import datetime, timezone
from importlib.metadata import version

from tradingagents.graph.propagation import Propagator

from .audit import PromptAudit, source_manifest
from .catalog import digest
from .context import build_snapshot
from .models import AccountSnapshot, GateResult, Instrument, Quote, RiskPolicy, SwingProposal
from .risk import evaluate

REQUIRED_NODES = {
    "Market Analyst",
    "News Analyst",
    "Sentiment Analyst",
    "Bull Researcher",
    "Bear Researcher",
    "Research Manager",
    "Trader",
    "Aggressive Analyst",
    "Conservative Analyst",
    "Neutral Analyst",
    "Portfolio Manager",
}


def run_event(
    catalog,
    trading_graph,
    feed_id,
    symbol,
    as_of,
    *,
    mode="replay",
    event="h4_close",
    event_id=None,
    policy=None,
    on_update=None,
):
    if mode not in {"replay", "shadow"}:
        raise ValueError("Only replay and shadow modes exist; execution is disabled")
    if event not in {"h4_close", "news", "regime", "volatility", "position_risk"}:
        raise ValueError("Unknown decision event")
    if not trading_graph.config.get("astra_snapshot_only"):
        raise ValueError("A snapshot-only TradingAgentsGraph is required")
    policy = policy or RiskPolicy()
    snapshot = build_snapshot(catalog, feed_id, symbol, as_of)
    if event == "h4_close":
        event_id = snapshot["technical"].get("last_h4_close")
    if not event_id:
        raise ValueError("A closed H4 or explicit source event ID is required")
    key = digest({"feed": feed_id, "symbol": symbol, "mode": mode, "event": event, "id": event_id})
    if not catalog.claim(key, as_of, snapshot):
        return next(row for row in catalog.decisions() if row["event_key"] == key)
    result = {
        "mode": mode,
        "event": event,
        "event_id": event_id,
        "snapshot": snapshot,
        "snapshot_hash": digest(snapshot),
        "policy": policy.model_dump(mode="json"),
        "versions": {name: version(name) for name in ("tradingagents", "langgraph", "pydantic")},
        "models": {
            k: trading_graph.config.get(k)
            for k in (
                "llm_provider",
                "quick_think_llm",
                "deep_think_llm",
                "temperature",
                "max_debate_rounds",
                "max_risk_discuss_rounds",
            )
        },
    }
    status = "complete"
    audit = PromptAudit()
    try:
        result["source_hashes"] = source_manifest()
        state = Propagator().create_initial_state(
            symbol, as_of.date().isoformat(), asset_type="forex"
        )
        state.update(astra_snapshot=snapshot, astra_trace=[], astra_proposal_error=None)
        graph_config = {"recursion_limit": 100, "callbacks": [audit]}
        if on_update is None:
            final = trading_graph.graph.invoke(state, config=graph_config)
        else:
            final = state
            for final in trading_graph.graph.stream(state, config=graph_config, stream_mode="values"):
                on_update(final)
        trace = final.get("astra_trace", [])
        if not set(trace) >= REQUIRED_NODES:
            raise ValueError("The complete reasoning chain did not execute")
        proposal = SwingProposal.model_validate(final["astra_proposal"])
        result["reasoning"] = {
            k: final.get(k)
            for k in (
                "market_report",
                "news_report",
                "sentiment_report",
                "fundamentals_report",
                "investment_debate_state",
                "investment_plan",
                "trader_investment_plan",
                "risk_debate_state",
                "final_trade_decision",
                "astra_trader_proposal",
                "astra_trace",
                "astra_proposal_error",
            )
        }
        gate_time = datetime.now(timezone.utc) if mode == "shadow" else as_of
        gate_snapshot = (
            build_snapshot(catalog, feed_id, symbol, gate_time) if mode == "shadow" else snapshot
        )
        quote = Quote.model_validate(gate_snapshot["quote"]) if gate_snapshot["quote"] else None
        account = (
            AccountSnapshot.model_validate(gate_snapshot["account"])
            if gate_snapshot["account"]
            else None
        )
        gate = evaluate(
            proposal,
            Instrument.model_validate(snapshot["instrument"]),
            quote,
            account,
            gate_time,
            policy,
        )
        blockers = []
        if not snapshot["technical"].get("ready"):
            blockers.append("Technical history unavailable or stale")
        if snapshot["technical"].get("d1_trend") == "unavailable":
            blockers.append("D1 trend lacks sufficient complete source candles")
        if not any(e["kind"] in {"macro", "news"} for e in snapshot["evidence"]):
            blockers.append("No recorded news/macro evidence; event risk is unknown")
        if mode == "shadow" and (not account or account.origin != "mt5"):
            blockers.append("Shadow approval requires a recorded MT5 account snapshot")
        if blockers and gate.verdict == "APPROVE":
            gate = gate.model_copy(
                update={"verdict": "REJECT", "reasons": blockers, "units": 0, "risk_at_stop": 0}
            )
        result.update(
            proposal=proposal.model_dump(mode="json"),
            gate=gate.model_dump(mode="json"),
            gate_as_of=gate_time.isoformat(),
            gate_quote=gate_snapshot["quote"],
            gate_account=gate_snapshot["account"],
        )
    except Exception as exc:
        status = "error"
        reason = f"Reasoning/gate failed ({type(exc).__name__}); no trade authorized"
        result.update(
            error=reason,
            proposal=SwingProposal.no_trade(symbol, reason).model_dump(mode="json"),
            gate=GateResult(verdict="NO TRADE", reasons=[reason]).model_dump(mode="json"),
        )
    result["completed_at"] = datetime.now(timezone.utc).isoformat()
    result["model_prompts"] = audit.calls
    catalog.complete(key, result, status=status)
    return next(row for row in catalog.decisions() if row["event_key"] == key)
