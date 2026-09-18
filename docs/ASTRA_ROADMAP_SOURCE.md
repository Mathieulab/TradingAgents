I want to evolve the FTMO swing lab into a real component of the existing TradingAgents architecture rather than keeping it as an isolated deterministic strategy.

Before changing code, inspect the current project architecture and explain how you will connect these components together. Do not remove or bypass the existing TradingAgents agents.

There are 3 major things I want you to investigate and implement.

## 1. Plug the FTMO swing system into the existing TradingAgents multi-agent reasoning

Right now the FTMO swing module appears to create a swing decision mainly from deterministic H4 indicators/breakouts.

I do NOT want the system to blindly generate trades simply because an EMA/ATR/breakout condition occurred.

The existing TradingAgents pipeline should perform its complete reasoning first.

I want the flow to become approximately:

LIVE MARKET DATA
        ↓
Market / Technical Analyst
News / Macro Analyst
Sentiment Analyst
Fundamental Analyst when relevant
        ↓
Bull Researcher ↔ Bear Researcher
        ↓
Research Manager
        ↓
Trader Agent
        ↓
Risk Management Agents
        ↓
Portfolio Manager
        ↓
SWING TRADE CANDIDATE
        ↓
FTMO RULE / RISK ENGINE
        ↓
Backtest / replay / validation
        ↓
APPROVE / REJECT / NO TRADE

Inspect the actual agents currently implemented in this fork rather than assuming their names or interfaces.

The swing strategy should become a tool/capability available to the Trader/Portfolio decision process, NOT an independent trading bot bypassing the agents.

A trade proposal should contain structured information such as:

- instrument
- LONG / SHORT / NO TRADE
- confidence
- reasoning summary
- market regime
- H4/D1 trend
- proposed entry zone
- stop loss
- take profit(s)
- expected reward/risk
- position size
- expected holding duration
- invalidation conditions
- relevant macro/news risks
- current FTMO daily-loss headroom
- current FTMO maximum-loss headroom
- spread/slippage conditions
- reason for rejecting the trade if NO TRADE

NO TRADE must be a first-class decision.

It should be completely valid for the agents to conclude that there is no sufficiently strong opportunity.

Very important: do NOT send huge raw datasets to every LLM agent.

Create a market-data/context layer that receives the full dataset/live feed and gives each agent only the information useful for its role.

For example:

Technical Analyst:
- recent D1/H4/M15 structure
- OHLC
- ATR
- EMA
- RSI/MACD if useful
- important support/resistance
- volatility
- spread
- session
- recent price structure

News/Macro Analyst:
- relevant economic events
- central-bank information
- significant market news
- event timestamps

Risk Agent:
- open positions
- exposure
- current equity
- realised/unrealised PnL
- FTMO daily-loss remaining
- FTMO maximum-loss remaining
- volatility
- stop distance
- risk per trade
- correlated positions

Portfolio Manager:
- condensed conclusions from the other agents
- not all of their raw datasets

For swing trading, the LLM agents should NOT rerun on every tick.

Prefer event-driven analysis such as:

- H4 candle close
- important market regime change
- major economic/news event
- abnormal volatility
- an existing position approaching its invalidation/risk threshold

M15/tick data can continue running underneath for execution simulation, spread, SL/TP and FTMO risk calculations.

Make this architecture explicit and show me where it plugs into the existing LangGraph/TradingAgents flow.

---

## 2. Investigate replacing/augmenting Backtrader with NautilusTrader

Investigate this project seriously:

https://github.com/nautechsystems/nautilus_trader

I want to know whether NautilusTrader would be a better long-term engine for this Finance Lab than Backtrader.

Do NOT replace Backtrader immediately without an architectural comparison.

Evaluate NautilusTrader specifically for:

- event-driven backtesting
- tick-level backtesting
- bid/ask prices
- spread
- slippage
- commissions
- swaps/overnight financing
- gaps
- stop/target conflicts
- partial fills if supported
- realistic order execution
- multi-timeframe data
- account/equity state
- multiple instruments
- replay
- paper trading
- live trading
- deterministic results
- parity between backtest and live strategy code
- performance
- integration with our Python TradingAgents code
- persistence/reproducibility
- Windows compatibility
- FTMO-specific risk modelling

I am particularly interested in using Nautilus as the deterministic market/execution engine while TradingAgents remains the intelligence/reasoning layer.

Conceptually:

TradingAgents = WHY / WHETHER we should trade
Strategy layer = WHAT setup we want
NautilusTrader = MARKET SIMULATION / ORDER / POSITION / EXECUTION ENGINE
FTMO risk engine = WHETHER THE TRADE IS ALLOWED

I want the LLM to recommend trades, but I do NOT want the LLM to simulate executions, calculate fills, or decide whether an FTMO loss rule was technically breached. Those should remain deterministic.

Investigate available Nautilus adapters as well.

Check specifically whether MetaTrader 5 connectivity is official, community-maintained, or would require us to build an adapter.

If a direct FTMO/Nautilus integration does not exist, clearly explain the cleanest architecture.

Build a small proof of concept if practical:

historical/live-normalized data
        ↓
Nautilus
        ↓
H4 swing strategy candidate
        ↓
execution simulation
        ↓
FTMO rule engine
        ↓
trade/equity ledger

Do not yet remove the existing Backtrader implementation. Ideally create an engine abstraction so we can compare:

BacktraderEngine
NautilusEngine

using the SAME strategy definition and SAME dataset where possible.

Then run equivalence tests and explain any differences.

---

## 3. Connect the system to REAL / LIVE market data

Synthetic data is useful only for software testing.

It must NOT be used to evaluate whether the trading strategy is profitable.

I want a real market-data architecture.

Because the target is FTMO, investigate what gives us the closest possible representation of the actual prices and execution conditions we would experience on an FTMO account.

Investigate these options:

A. FTMO MetaTrader 5 feed through the MetaTrader5 Python integration

B. FTMO cTrader through cTrader Open API

C. NautilusTrader adapters where appropriate

D. External institutional-quality historical/live providers only where they add value

For EUR/USD especially, remember that FX is decentralized, so the FTMO broker/platform feed may be more useful for reproducing FTMO execution conditions than using an unrelated generic EUR/USD dataset.

I want TWO separate data modes:

LIVE MARKET MODE
- subscribe to current bid/ask
- build M15/H4/D1 bars from authoritative timestamps
- record spread
- record ticks where useful
- account for market sessions
- continuously persist received market data
- feed compact snapshots to TradingAgents

HISTORICAL REPLAY/BACKTEST MODE
- load stored real market data
- reproduce exactly the same timestamps and price basis
- run deterministic replay through Nautilus/Backtrader
- calculate realistic costs
- compare expected and actual execution behaviour

Create a common interface such as:

MarketDataProvider
    get_quote()
    get_ticks()
    get_bars()
    subscribe_quotes()
    subscribe_bars()
    get_instrument_metadata()

Possible implementations:

MT5MarketDataProvider
CTraderMarketDataProvider
CSVMarketDataProvider
NautilusCatalogProvider

The rest of TradingAgents should not need to know which provider is being used.

Also create a recorder/data catalog so that every live session gradually builds our own real historical dataset.

Store at minimum:

timestamp UTC
symbol
bid
ask
mid if needed
spread
OHLC bars
tick volume/volume where available
source/provider
account/server when relevant
timezone
instrument specifications

Avoid timezone leakage/look-ahead bias.

All agent analysis must use only information that existed at the decision timestamp.

---

## Safety / rollout architecture

Do NOT enable autonomous real-money execution yet.

Implement stages:

MODE 1 — historical backtest
MODE 2 — historical replay
MODE 3 — live-data shadow mode
MODE 4 — FTMO demo / Free Trial paper execution
MODE 5 — optional live execution only later

Shadow mode is particularly important.

In shadow mode:

1. receive real market data
2. run all TradingAgents reasoning
3. produce the proposed swing trade
4. run the FTMO risk gate
5. record exactly what would have been traded
6. DO NOT send the order
7. later compare the predicted entry/SL/TP and actual subsequent market behaviour

This gives us forward-test results without risking an account.

---

## Dashboard

Extend the dashboard so I can see the complete reasoning chain.

For each potential trade I want:

MARKET
EUR/USD
Current bid/ask
Spread
D1 trend
H4 trend
ATR / volatility
Session

AGENTS
Technical: Bullish / Neutral / Bearish + short reasoning
News/Macro: ...
Sentiment: ...
Bull researcher: ...
Bear researcher: ...
Trader: ...
Risk team: ...
Portfolio Manager: ...

FINAL
LONG / SHORT / NO TRADE
Confidence
Entry
SL
TP
Risk %
Expected R:R

FTMO
Equity
Daily loss used / remaining
Maximum loss used / remaining
Risk if SL occurs
Trade allowed: YES / NO

VALIDATION
Backtest result
Holdout result
Stressed-cost result
Shadow/live-forward result

I also want to be able to drill into an agent's reasoning without displaying huge raw prompt contents by default.

---

## Deliverables

Before coding heavily, give me:

1. A diagram of the CURRENT architecture.
2. A diagram of the PROPOSED architecture.
3. Where the FTMO module will connect to TradingAgents.
4. Nautilus vs Backtrader recommendation.
5. Recommended FTMO live data source: MT5 vs cTrader, with reasons.
6. Exact implementation phases.
7. New modules/files you propose adding.
8. Anything in the existing implementation that could cause look-ahead bias or unrealistic performance.

Then implement the architecture incrementally.

Do not optimize a strategy to make the backtest look profitable.

Do not tune parameters using the holdout period.

Keep development, validation, holdout, stressed-cost and live-forward results separate.

The goal is not to produce many trades.

The goal is to produce a small number of explainable, reproducible, risk-controlled swing decisions backed by the entire TradingAgents reasoning pipeline and validated using real market data.