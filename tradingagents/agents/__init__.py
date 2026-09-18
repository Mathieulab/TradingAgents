"""Lazy public exports for agent factory helpers.

Keeping these imports lazy lets lightweight utility modules under
``tradingagents.agents`` be imported without requiring the full LangChain graph
dependency stack.
"""

from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "AgentState": ".utils.agent_states",
    "InvestDebateState": ".utils.agent_states",
    "RiskDebateState": ".utils.agent_states",
    "create_msg_delete": ".utils.agent_utils",
    "create_bear_researcher": ".researchers.bear_researcher",
    "create_bull_researcher": ".researchers.bull_researcher",
    "create_research_manager": ".managers.research_manager",
    "create_fundamentals_analyst": ".analysts.fundamentals_analyst",
    "create_market_analyst": ".analysts.market_analyst",
    "create_neutral_debator": ".risk_mgmt.neutral_debator",
    "create_news_analyst": ".analysts.news_analyst",
    "create_aggressive_debator": ".risk_mgmt.aggressive_debator",
    "create_portfolio_manager": ".managers.portfolio_manager",
    "create_conservative_debator": ".risk_mgmt.conservative_debator",
    "create_sentiment_analyst": ".analysts.sentiment_analyst",
    "create_social_media_analyst": ".analysts.sentiment_analyst",
    "create_trader": ".trader.trader",
}

__all__ = [
    "AgentState",
    "create_msg_delete",
    "InvestDebateState",
    "RiskDebateState",
    "create_bear_researcher",
    "create_bull_researcher",
    "create_research_manager",
    "create_fundamentals_analyst",
    "create_market_analyst",
    "create_neutral_debator",
    "create_news_analyst",
    "create_aggressive_debator",
    "create_portfolio_manager",
    "create_conservative_debator",
    "create_sentiment_analyst",
    "create_social_media_analyst",
    "create_trader",
]


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(_EXPORTS[name], __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
