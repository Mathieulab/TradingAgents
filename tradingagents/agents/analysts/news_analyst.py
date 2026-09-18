from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    get_global_news,
    get_instrument_context_from_state,
    get_language_instruction,
    get_macro_indicators,
    get_news,
    get_prediction_markets,
)
from tradingagents.agents.utils.macro_data_tools import macro_indicators_available


def get_news_analyst_tools():
    """Return news analyst tools, omitting FRED macro tools when no key exists."""
    tools = [
        get_news,
        get_global_news,
        get_prediction_markets,
    ]
    if macro_indicators_available():
        tools.insert(2, get_macro_indicators)
    return tools


def get_news_tool_instruction(asset_label: str) -> str:
    """Return prompt text matching the actually exposed news tools."""
    parts = [
        f"get_news(query, start_date, end_date) for {asset_label}-specific or targeted news searches",
        "get_global_news(curr_date, look_back_days, limit) for broader macroeconomic news",
    ]
    if macro_indicators_available():
        parts.append(
            "get_macro_indicators(indicator, curr_date, look_back_days) to ground macro commentary "
            "in actual data from FRED (e.g. 'cpi', 'core_pce', 'unemployment', "
            "'fed_funds_rate', '10y_treasury', 'yield_curve')"
        )
    else:
        parts.append(
            "FRED macro indicators are not configured, so do not call get_macro_indicators "
            "and do not fabricate FRED values"
        )
    parts.append(
        "get_prediction_markets(topic, limit) for live market-implied probabilities of "
        "forward-looking events (e.g. 'Fed rate cut', 'recession 2026', geopolitical or sector events)"
    )
    return "; ".join(parts)


def create_news_analyst(llm):
    def news_analyst_node(state):
        if state.get("astra_snapshot"):
            from tradingagents.integrations.astra_context import analyze_snapshot
            return analyze_snapshot(llm, state, "News Analyst", "news_report")
        current_date = state["trade_date"]
        asset_type = state.get("asset_type", "stock")
        asset_label = "company" if asset_type == "stock" else "asset"
        instrument_context = get_instrument_context_from_state(state)

        tools = get_news_analyst_tools()
        tool_instruction = get_news_tool_instruction(asset_label)

        system_message = (
            f"You are a news researcher tasked with analyzing recent news and trends over the past week. Please write a comprehensive report of the current state of the world that is relevant for trading and macroeconomics. Use the available tools: {tool_instruction}. Provide specific, actionable insights with supporting evidence to help traders make informed decisions."
            + """ Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."""
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    " You have access to the following tools: {tool_names}.\n{system_message}"
                    "For your reference, the current date is {current_date}. {instrument_context}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])

        report = ""

        if len(result.tool_calls) == 0:
            report = result.content

        return {
            "messages": [result],
            "news_report": report,
        }

    return news_analyst_node
