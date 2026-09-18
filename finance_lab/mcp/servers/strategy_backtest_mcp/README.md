# strategy_backtest_mcp

Planned MCP server for strategy backtesting.

Initial scope:

- run local strategy simulations,
- select `simple` or optional `nautilus` backtest backends,
- calculate return and risk metrics,
- compare strategies,
- export JSON summaries.

Required metrics should include total return, win rate, average win, average loss, expectancy, max drawdown, trade count, profit factor, fees impact, and slippage impact.

Backend plan:

- `simple`: current deterministic vectorized Finance Lab backtester.
- `nautilus`: optional advanced backend, installed with `tradingagents[nautilus]` on Python 3.12+.

The Nautilus path should stay explicit and fail closed until the engine adapter
maps Finance Lab OHLCV data into Nautilus instruments, venues, bar types, and a
paper-only strategy class.
