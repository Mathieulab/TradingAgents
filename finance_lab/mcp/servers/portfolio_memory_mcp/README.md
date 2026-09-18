# portfolio_memory_mcp

Local MCP server for Finance Lab paper-trading memory.

Implemented tools:

- `health_check`: confirm the SQLite path and paper-only mode,
- `save_strategy`: save or update a strategy definition,
- `save_trade_decision`: save a BUY/HOLD/SELL paper decision,
- `save_trade_result`: save a deterministic result from known entry/exit prices,
- `evaluate_trade_result`: evaluate a decision through the market-data provider,
- `get_strategy_memory`: read recent decisions and saved results,
- `summarize_strategy_memory`: summarize decision counts, win rate, and recurring mistakes.

Run from the repository root:

```powershell
$env:TRADINGAGENTS_FINANCE_MEMORY_PATH = "$PWD\finance_lab\storage\dev_finance_memory.db"
python -m finance_lab.mcp.servers.portfolio_memory_mcp
```

All records are paper-trading records only. The server does not connect to a broker
and never places real-money orders.
