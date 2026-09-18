# Finance Lab

`finance_lab/` is the separated workspace for finance-specific extensions around this TradingAgents fork. It is intentionally additive so upstream TradingAgents code can stay compatible.

Safety rule: this lab is for research, backtesting, and paper trading only. Real-money order execution is not implemented here and must remain disabled by default if a placeholder is ever added.

## FTMO Test Desk

The standalone [FTMO Test Desk](ftmo/README.md) provides a deterministic EUR/USD
H4 swing strategy with M15 execution, overnight financing, two-step account objectives,
CSV/MT5 import, chronological holdout,
cost stress test, and an interactive terminal dashboard. Start it without an LLM
or environment variables:

```powershell
.\.venv-ftmo\Scripts\python.exe -m finance_lab.ftmo
```

Use `--demo` for the labelled synthetic example. Broker history is required to
evaluate real market performance. This module does not place external orders.

## Using Codex For This Repo

Use Codex as the coding and review agent from the repository root:

```powershell
cd C:\Users\mathi\MyTradingAgents\TradingAgents
```

Recommended workflow:

1. Keep core TradingAgents changes small and tested.
2. Put finance-specific tools, prompts, MCP servers, notebooks, fake trades, and dashboards under `finance_lab/`.
3. Use `docs/MATHIEU_PROJECT_AUDIT.md` as the architecture baseline before changing core behavior.
4. Use `docs/MATHIEU_TEST_PLAN.md` before and after changes.

## Using A Local LLM Through Ollama

Start Ollama outside this repo, then pull models:

```powershell
ollama pull qwen3:8b
ollama pull qwen3-coder:30b-a3b-q4_K_M
```

TradingAgents expects an OpenAI-compatible Ollama endpoint:

```powershell
$env:TRADINGAGENTS_LLM_PROVIDER = "ollama"
$env:TRADINGAGENTS_LLM_BACKEND_URL = "http://localhost:11434/v1"
$env:TRADINGAGENTS_DEEP_THINK_LLM = "qwen3-coder:30b-a3b-q4_K_M"
$env:TRADINGAGENTS_QUICK_THINK_LLM = "qwen3:8b"
$env:TRADINGAGENTS_TEMPERATURE = "0.0"
python -m cli.main
```

You can also set Ollama's own endpoint variable:

```powershell
$env:OLLAMA_BASE_URL = "http://localhost:11434/v1"
```

## Using OpenAI-Compatible Local Servers

For vLLM, LM Studio, llama.cpp server, or a custom relay:

```powershell
$env:TRADINGAGENTS_LLM_PROVIDER = "openai_compatible"
$env:TRADINGAGENTS_LLM_BACKEND_URL = "http://localhost:8000/v1"
$env:TRADINGAGENTS_DEEP_THINK_LLM = "your-served-model"
$env:TRADINGAGENTS_QUICK_THINK_LLM = "your-served-model"
$env:TRADINGAGENTS_TEMPERATURE = "0.0"
python -m cli.main
```

If the endpoint requires a key:

```powershell
$env:OPENAI_COMPATIBLE_API_KEY = "replace-with-your-key"
```

Do not store real keys in this repository.

## Isolating Finance Tools

Keep finance-specific extensions in these folders:

- `config/`: example finance-lab config files.
- `mcp/`: local MCP server plans and future implementations.
- `skills/`: finance-specific prompts and review checklists.
- `lsp/`: finance-project coding and analysis tooling notes.
- `notebooks/`: exploratory research notebooks.
- `reports/`: generated research reports and future report code.
- `fake_trading/`: fake trade schema, paper-trading memory, and future SQLite store.
- `strategies/`: future strategies and backtest inputs.
- `dashboards/`: future dashboards.

## Recommended Local LLM Roles

- Coding model: use the strongest coding model available locally, for example `qwen3-coder:30b-a3b-q4_K_M`.
- Finance analysis model: use a stronger reasoning model with low temperature.
- Fast summarizer model: use a smaller model such as `qwen3:8b`.
- Strategy critic model: use a separate model or prompt role focused on downside, drawdown, and invalid assumptions.

## Recommended Configuration Values

For Ollama:

```yaml
llm:
  provider: ollama
  base_url: http://localhost:11434/v1
  deep_think_model: qwen3-coder:30b-a3b-q4_K_M
  quick_think_model: qwen3:8b
  temperature: 0.0
```

For a generic OpenAI-compatible endpoint:

```yaml
llm:
  provider: openai_compatible
  base_url: http://localhost:8000/v1
  deep_think_model: your-served-model
  quick_think_model: your-served-model
  temperature: 0.0
```

TradingAgents field mapping:

- `llm.provider` -> `TRADINGAGENTS_LLM_PROVIDER`
- `llm.base_url` -> `TRADINGAGENTS_LLM_BACKEND_URL`
- `llm.deep_think_model` -> `TRADINGAGENTS_DEEP_THINK_LLM`
- `llm.quick_think_model` -> `TRADINGAGENTS_QUICK_THINK_LLM`
- `llm.temperature` -> `TRADINGAGENTS_TEMPERATURE`

Use `finance_lab/config/finance_lab.example.yaml` as the starting point.

## Optional NautilusTrader Backtesting

Finance Lab keeps the simple vectorized backtester as the default. NautilusTrader
is reserved for the advanced event-driven backend because it adds heavier engine,
instrument, venue, and strategy wiring.

Install the optional dependency only when working on that backend:

```powershell
pip install "tradingagents[nautilus]"
```

NautilusTrader currently requires Python 3.12 or newer. The Finance Lab backend
selector accepts `backend="nautilus"` and returns a structured missing-dependency
or not-implemented response until the full engine adapter is wired.

## Running Decision Replay After TradingAgents Analysis

The normal CLI does not run a backtest unless enabled. The default Finance Lab
mode is `decision_replay`, which scores the actual final TradingAgents decision
over future market bars and compares it with buy-and-hold plus a benchmark:

```powershell
cd C:\Users\mathi\MyTradingAgents\TradingAgents
$env:TRADINGAGENTS_FINANCE_BACKTEST_ENABLED = "true"
$env:TRADINGAGENTS_FINANCE_BACKTEST_MODE = "decision_replay"
$env:TRADINGAGENTS_FINANCE_BACKTEST_BENCHMARK = "SPY"
$env:TRADINGAGENTS_FINANCE_BACKTEST_HORIZONS = "5,20,60,120"
python -m cli.main
```

The CLI panel reports the final action/rating, post-decision exposure, stop-loss
detection, decision return, buy-and-hold return, benchmark return, alpha, max
drawdown, stop-loss hits, and deterministic outcome lessons for each evaluable
horizon.

To let future Portfolio Manager decisions learn from these replay outcomes,
enable Finance Lab memory at the same time:

```powershell
$env:TRADINGAGENTS_FINANCE_MEMORY_ENABLED = "true"
$env:TRADINGAGENTS_FINANCE_MEMORY_PATH = "$PWD\finance_lab\storage\dev_finance_memory.db"
$env:TRADINGAGENTS_FINANCE_BACKTEST_ENABLED = "true"
$env:TRADINGAGENTS_FINANCE_BACKTEST_MODE = "decision_replay"
python -m cli.main
```

After a replay is evaluated, Finance Lab stores the horizon rows and an outcome
lesson on the saved decision. On future analyses for the same symbol, the CLI
and programmatic graph inject those lessons into the Portfolio Manager's
`past_context`. This learning is time-aware: an analysis for a historical date
only receives replay lessons whose evaluated exit dates were already known by
that date, while today's analysis can use all completed past outcomes.

Interpretation note: for `Buy` and `Overweight`, decision return is intentionally
the same as buy-and-hold at 100% exposure, so alpha vs hold is normally `0.00%`.
The useful checks are benchmark alpha, drawdown, stop-loss behavior, and whether
the stated time horizon matched the realized result.

Same-day analyses usually show `pending` because there are no future bars yet.
Run the analysis with a past analysis date to score immediately, or keep the
decision in Finance Lab memory and evaluate it later when forward data exists.

For historical runs, TradingAgents now sets `analysis_as_of_date` to the selected
analysis date and keeps `strict_as_of_date=true` by default. Data tools that
accept dates are clamped to that date, future-only windows are rejected, and
live-only tools such as prediction markets are blocked for past analysis dates.
This keeps decision replay from becoming a hindsight test where the agents saw
information from after the date being scored.

To run the older historical strategy backtest instead of decision replay:

```powershell
$env:TRADINGAGENTS_FINANCE_BACKTEST_ENABLED = "true"
$env:TRADINGAGENTS_FINANCE_BACKTEST_MODE = "strategy"
$env:TRADINGAGENTS_FINANCE_BACKTEST_BACKEND = "simple"
$env:TRADINGAGENTS_FINANCE_BACKTEST_STRATEGY = "buy_and_hold"
$env:TRADINGAGENTS_FINANCE_BACKTEST_LOOKBACK_DAYS = "365"
python -m cli.main
```

For the EMA crossover strategy:

```powershell
$env:TRADINGAGENTS_FINANCE_BACKTEST_STRATEGY = "ema_cross"
$env:TRADINGAGENTS_FINANCE_BACKTEST_FAST_PERIOD = "12"
$env:TRADINGAGENTS_FINANCE_BACKTEST_SLOW_PERIOD = "26"
python -m cli.main
```

To exercise the Nautilus path:

```powershell
$env:TRADINGAGENTS_FINANCE_BACKTEST_BACKEND = "nautilus"
python -m cli.main
```

Until the full Nautilus engine adapter is implemented, this path should display
a clear missing-dependency or not-implemented message rather than silently using
the simple backend.

## Trade Style Fit

Decision replay also computes a Trade Style Fit panel. It reuses the evaluated
forward horizons to compare which trading style best fit the same final
TradingAgents decision.

Daily styles are scored immediately from yfinance daily bars:

- `short_term`: 1d, 2d, 5d
- `swing`: 5d, 10d, 20d
- `position`: 60d, 120d

Intraday styles are included in the panel but marked `Needs dataset` until an
intraday provider is configured:

- `scalping`: 1m/5m bars
- `intraday`: 5m/15m bars

This avoids pretending daily candles can validate scalping. The intended next
data sources are local CSV minute bars first, then optional Alpaca or
Polygon/Massive adapters behind the same provider interface.

The default decision replay horizons are now:

```powershell
$env:TRADINGAGENTS_FINANCE_BACKTEST_HORIZONS = "1,2,5,10,20,60,120"
```

You can still override this list, but styles whose horizons are missing will be
shown as pending or evaluated from the subset available.

## Paper Trade Gate

Decision replay now also emits a Paper Trade Gate. This is the deterministic
pre-execution filter that should sit before NautilusTrader or any broker
adapter.

The gate returns:

- `candidate`: `yes`, `watchlist`, or `no`
- `execution_intent`: `paper_long`, `hold_existing_or_watch`, `reduce_or_exit_existing`, or `skip`
- `position_size`: conservative paper size, currently up to 50%
- `best_style`: the daily style selected by Trade Style Fit
- `failed_rules`, `warnings`, and human-readable `reasons`

The gate is intentionally strict:

- `Buy` requires a detected stop-loss.
- `Hold` is not treated as a new-entry order.
- `Sell` requires current-position context before it can become an exit or reduce order.
- weak style fit, non-positive expectancy, missing relative edge, or high drawdown blocks the trade.

This makes Finance Lab suitable as a decision/filter layer. NautilusTrader should
remain the future execution engine for event-driven backtesting, paper/live
order state, broker integration, reconciliation, and recovery.
