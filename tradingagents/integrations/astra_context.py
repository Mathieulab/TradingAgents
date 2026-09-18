"""Opt-in recorded-snapshot boundary around the existing TradingAgents nodes."""

from langchain_core.messages import AIMessage


def scoped_node(node, role):
    def run(state):
        from finance_lab.astra.context import role_context

        if not state.get("astra_snapshot"):
            raise ValueError("Snapshot-only graph requires recorded context")
        scoped = dict(state)
        scoped["instrument_context"] = role_context(state["astra_snapshot"], role)
        scoped["past_context"] = ""
        result = node(scoped)
        return {**result, "astra_trace": [role]}

    return run


def forbidden_tools(state):
    raise RuntimeError("External data tools are disabled for recorded snapshot analysis")


def analyze_snapshot(llm, state, role, report_field, *, structured=None, render=None):
    """Same analyst and model, with recorded evidence replacing vendor fetching."""
    from tradingagents.agents.utils.structured import invoke_structured_or_freetext

    prompt = [
        {
            "role": "system",
            "content": f"You are the {role} in the existing swing reasoning team. "
            "Analyze only this recorded role-specific evidence. Report direction, evidence, uncertainty and invalidation. "
            "Missing news/sentiment is unavailable, not neutral evidence. No tools, fabricated events, investment guarantees or orders. "
            "FX fundamentals concern currencies and macroeconomics, not company balance sheets. Keep the report below 500 words.",
        },
        {"role": "user", "content": state["instrument_context"]},
    ]
    if render:
        content = invoke_structured_or_freetext(structured, llm, prompt, render, role)
    else:
        response = llm.invoke(prompt)
        if getattr(response, "tool_calls", None):
            raise RuntimeError("Snapshot analyst attempted an external tool call")
        content = response.content
    return {"messages": [AIMessage(content=content)], report_field: content}


def swing_proposal(llm, state, role):
    from finance_lab.astra.models import SwingProposal

    context = {
        "recorded_context": state["instrument_context"],
        "research": state.get("investment_plan", ""),
        "trader": state.get("trader_investment_plan", ""),
        "risk_debate": state.get("risk_debate_state", {}).get("history", ""),
    }
    prompt = [
        {
            "role": "system",
            "content": f"You are the {role}. Return a typed swing proposal, LONG, SHORT or NO TRADE. "
            "Do not map legacy Buy/Hold/Sell mechanically to FX direction. Debate the evidence and abstain when it is insufficient. "
            "Entry zone, stop, targets, invalidation and macro risks must be grounded in recorded evidence. "
            "EMA/Donchian setup is only a capability, never automatic authorization. Position size is only a suggestion; "
            "a deterministic FTMO gate calculates allowed size, costs and headroom after your decision. No orders are sent.",
        },
        {"role": "user", "content": str(context)},
    ]
    error = state.get("astra_proposal_error")
    try:
        if error:
            raise ValueError("Earlier structured proposal failed")
        result = llm.with_structured_output(SwingProposal).invoke(prompt)
        proposal = SwingProposal.model_validate(result)
        if proposal.instrument != state["company_of_interest"]:
            raise ValueError("Proposal instrument mismatch")
    except Exception as exc:
        error = f"{role} structured proposal unavailable ({type(exc).__name__})"
        proposal = SwingProposal.no_trade(state["company_of_interest"], error)
    return proposal.model_dump(mode="json"), error
