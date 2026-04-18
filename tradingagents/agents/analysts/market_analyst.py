from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
import time
import json
from tradingagents.agents.utils.agent_utils import get_stock_data, get_indicators
from tradingagents.dataflows.config import get_config


def create_market_analyst(llm):

    def market_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        company_name = state["company_of_interest"]
        
        # Get trading strategy information
        trading_strategy = state.get("trading_strategy", "swing")
        strategy_timeframe = state.get("strategy_timeframe", "3-10 days")

        tools = [
            get_stock_data,
            get_indicators,
        ]

        # Strategy-aware instructions
        strategy_context = ""
        if trading_strategy == "intraday":
            strategy_context = """\n\n**INTRADAY TRADING CONTEXT**:
You are analyzing for INTRADAY trading (1-day timeframe). Focus on:
- SHORT-TERM momentum indicators (RSI, MACD for quick signals)
- Intraday volatility measures (ATR, Bollinger Bands for entry/exit timing)
- Volume-weighted indicators for intraday liquidity
- Fast-moving averages (10 EMA) for immediate trend direction
- Look for SPECIFIC PRICE LEVELS for intraday entries and exits
- Consider recent price action within the last few trading sessions"""
        else:  # swing trading
            strategy_context = """\n\n**SWING TRADING CONTEXT**:
You are analyzing for SWING trading (3-10 day timeframe). Focus on:
- MEDIUM-TERM trend indicators (50 SMA, 200 SMA for overall direction)
- Multi-day momentum patterns (MACD, RSI for trend strength)
- Support/resistance levels that hold over multiple days
- Volume trends confirming price movements
- Look for SPECIFIC PRICE LEVELS for swing trade entries and exits
- Consider price patterns and trends over the past 3-4 weeks"""

        system_message = (
            f"""You are a trading assistant tasked with analyzing financial markets for {trading_strategy.upper()} trading (timeframe: {strategy_timeframe}). Your role is to select the **most relevant indicators** for this {trading_strategy} strategy and current market conditions from the following list. The goal is to choose up to **8 indicators** that provide complementary insights without redundancy.{strategy_context}

**CRITICAL INSTRUCTION FOR TOOL CALLS**: 
When calling get_indicators(), you MUST use the EXACT indicator names listed below (the part before the colon). DO NOT modify, translate, or use descriptive versions of these names. For example:
- Use "macds" NOT "macd_signal" or "MACD Signal"
- Use "macdh" NOT "macd_histogram" or "MACD Histogram"
- Use "boll_ub" NOT "bollinger_upper" or "boll_upper_band"

**Available Indicators** (use these EXACT names when calling get_indicators):

Moving Averages:
- close_50_sma: 50-day Simple Moving Average (medium-term trend indicator, dynamic support/resistance)
- close_200_sma: 200-day Simple Moving Average (long-term trend benchmark, golden/death cross setups)
- close_10_ema: 10-day Exponential Moving Average (short-term momentum, quick trend shifts)

MACD Related (use EXACT names: macd, macds, macdh):
- macd: MACD Line (momentum via EMA differences, crossovers signal trend changes)
- macds: MACD Signal Line (9-day EMA of MACD, crossover triggers)
- macdh: MACD Histogram (gap between MACD and signal line, momentum strength)

Momentum Indicators:
- rsi: Relative Strength Index (overbought/oversold 70/30 thresholds, divergence signals)

Volatility Indicators (use EXACT names: boll, boll_ub, boll_lb, atr):
- boll: Bollinger Middle Band (20-day SMA, dynamic price benchmark)
- boll_ub: Bollinger Upper Band (2 std dev above middle, overbought/breakout zones)
- boll_lb: Bollinger Lower Band (2 std dev below middle, oversold conditions)
- atr: Average True Range (volatility measure for stop-loss and position sizing)

Volume-Based Indicators:
- vwma: Volume Weighted Moving Average (price/volume integration, trend confirmation)

**EXECUTION SEQUENCE**:
1. First call get_stock_data() to retrieve historical price CSV
2. Then call get_indicators() multiple times with the EXACT indicator names listed above
3. Select 6-8 diverse indicators (avoid redundancy like both rsi and stochrsi)
4. Explain why each indicator suits the current market context

**CRITICAL for {trading_strategy.upper()} trading**: 

⚠️ **START YOUR REPORT WITH THE CURRENT PRICE** ⚠️
Begin your analysis by stating: "**CURRENT PRICE: $XX.XX (as of [date])**" using the most recent close price from the stock data.
This is CRITICAL for accurate trade planning.

Then IDENTIFY AND SPECIFY CONCRETE PRICE LEVELS:
- Support levels where price might find buying interest
- Resistance levels where price might face selling pressure
- Key breakout/breakdown levels to watch
- Potential entry zones based on technical indicators
- Potential exit/target zones based on technical indicators

ALL price levels must be REALISTIC and NEAR the current price:
- For intraday: within ±1-3% of current price
- For swing: within ±3-10% of current price

Write a very detailed and nuanced report of the trends you observe. Do not simply state the trends are mixed, provide detailed and fine-grained analysis and insights that may help traders make decisions with SPECIFIC ACTIONABLE PRICE LEVELS."""
            + """ Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read. Include a row for KEY PRICE LEVELS with specific prices to watch relative to the CURRENT PRICE you stated."""
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
                    "For your reference, the current date is {current_date}. The company we want to look at is {ticker}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(ticker=ticker)

        chain = prompt | llm.bind_tools(tools)

        result = chain.invoke(state["messages"])

        report = ""

        if len(result.tool_calls) == 0:
            report = result.content

        return {
            "messages": [result],
            "market_report": report,
        }

    return market_analyst_node
