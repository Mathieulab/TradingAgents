import functools
import time
import json


def create_trader(llm, memory):
    def trader_node(state, name):
        company_name = state["company_of_interest"]
        investment_plan = state["investment_plan"]
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        
        # Get trading strategy information
        trading_strategy = state.get("trading_strategy", "swing")
        strategy_timeframe = state.get("strategy_timeframe", "3-10 days")

        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
        past_memory_str = memory.get_prompt_context(curr_situation, n_matches=2)

        # Enhanced context with strategy and level requirements
        context = {
            "role": "user",
            "content": f"""Based on a comprehensive analysis by a team of analysts, here is an investment plan tailored for {company_name}. This plan incorporates insights from current technical market trends, macroeconomic indicators, and social media sentiment.

TRADING STRATEGY: {trading_strategy.upper()}
TIMEFRAME: {strategy_timeframe}

Proposed Investment Plan: {investment_plan}

Use this plan as a foundation for evaluating your next trading decision. Leverage these insights to make an informed and strategic decision.""",
        }

        # Enhanced system message with specific level requirements
        strategy_guidance = ""
        if trading_strategy == "intraday":
            strategy_guidance = """For INTRADAY trading:
- Focus on SHORT-TERM price movements and momentum
- Consider intraday volatility and quick profit-taking opportunities
- Set tight stop-losses to manage intraday risk
- Look for technical entry/exit signals within the trading day
- Consider volume patterns and liquidity for quick entries/exits"""
        else:  # swing trading
            strategy_guidance = """For SWING trading:
- Focus on MEDIUM-TERM trends and price patterns
- Consider multi-day support/resistance levels
- Set stop-losses based on key technical levels
- Look for trend continuation or reversal setups
- Consider fundamental catalysts over the coming days/weeks"""

        messages = [
            {
                "role": "system",
                "content": f"""You are a professional trading agent analyzing market data to make investment decisions for {trading_strategy.upper()} trading (timeframe: {strategy_timeframe}).

{strategy_guidance}

⚠️ **CRITICAL PRICE GROUNDING INSTRUCTIONS** ⚠️
BEFORE suggesting any entry/exit levels:
1. **IDENTIFY THE CURRENT PRICE** from the most recent trading day in the market data provided by analysts
2. ALL entry and exit price levels MUST be NEAR and REALISTIC relative to this current price
3. For INTRADAY trades: prices should be within ±1-3% of current price
4. For SWING trades: prices should be within ±3-10% of current price
5. NEVER use historical high/low prices that are far from the current price
6. Example: If current price is $32, entry might be $31.50, targets $33-35, stop $30.50
           WRONG: If current price is $32, don't suggest entry at $97 or targets at $150

Based on your analysis, provide a DETAILED trading recommendation with SPECIFIC entry and exit levels:

Your response MUST include:

1. **TRADING DECISION**: BUY, SELL, or HOLD

2. **ENTRY LEVELS** (if BUY/SELL):
   - Primary Entry: $X.XX (ideal entry price)
   - Secondary Entry: $X.XX (alternative if primary missed)
   - Entry Rationale: Why these levels?

3. **EXIT LEVELS** (profit targets):
   - Target 1: $X.XX (conservative target, take XX% profit)
   - Target 2: $X.XX (moderate target, take XX% profit)
   - Target 3: $X.XX (aggressive target, remaining position)
   - Exit Rationale: Based on what technical/fundamental factors?

4. **STOP LOSS**:
   - Stop Loss: $X.XX (maximum acceptable loss)
   - Stop Loss Rationale: Why this level protects capital?

5. **POSITION SIZING**:
   - Recommended position size as % of portfolio
   - Risk per trade (should be 1-2% of capital max)

6. **TIMEFRAME**:
   - Expected holding period for this {trading_strategy} trade
   - Key dates or events to watch

7. **RISK/REWARD RATIO**:
   - Calculate and state the risk/reward ratio
   - Expected win rate for this setup

IMPORTANT: Use lessons from past decisions to avoid repeating mistakes.

Past Trading Memories:
{past_memory_str}

Always conclude your response with 'FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**' to confirm your recommendation.""",
            },
            context,
        ]

        result = llm.invoke(messages)

        return {
            "messages": [result],
            "trader_investment_plan": result.content,
            "sender": name,
        }

    return functools.partial(trader_node, name="Trader")
