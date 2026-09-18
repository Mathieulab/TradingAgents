# Finance Lab MCP

This folder is reserved for finance-specific MCP servers. Keep them separated from core TradingAgents until their APIs are stable.

Servers:

- `portfolio_memory_mcp`: implemented local paper-trading memory server.
- `market_data_mcp`: planned normalized market data access.
- `strategy_backtest_mcp`: planned strategy simulation and metrics.
- `news_sentiment_mcp`: planned news and sentiment retrieval summaries.

Rules:

- no secrets in server code or examples,
- no real broker order execution,
- explicit paper/backtest mode by default,
- deterministic outputs where possible,
- tests before wiring into core TradingAgents.
