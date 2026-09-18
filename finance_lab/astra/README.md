# Astra Swing Integration

Authoritative direction: [original roadmap](../../docs/ASTRA_ROADMAP_SOURCE.md).
Architecture, comparison and rollout: [architecture](../../docs/ASTRA_ARCHITECTURE.md).

## Current Scope

This is the first guarded integration, **not a profitable strategy certification
or a live execution system**. The existing FTMO Backtrader study and historical
dashboard remain available through `ftmo.ps1`.

- Real bid/ask CSV import and a read-only MT5 terminal provider.
- SQLite recording with UTC event/receipt times, provenance, deduplication and
  a persistent observed-breach latch. No synthetic production-data fallback.
- Complete M15 source candles feed UTC H4/D1 context. Existing Backtrader EMA,
  Donchian and Wilder ATR calculations supply evidence, not trade authorization.
- The **existing LangGraph** runs Market, News/Macro, Sentiment, Bull, Bear,
  Research Manager, Trader, all three risk debaters and Portfolio Manager.
  Fundamentals remain supported when relevant; corporate statements are not used
  for spot EUR/USD. No agent is replaced by an automatic breakout rule.
- Trader and PM preserve typed LONG/SHORT/NO TRADE outputs. Malformed proposals
  become NO TRADE. Snapshot agents cannot fetch current vendor data or daily memory.
- Idempotent H4-close shadow decisions; explicit news/regime/volatility/risk events
  can also be submitted. Only H4-close detection has a polling watcher today.
- Deterministic, conservative **flat EUR/USD, USD-account, FTMO two-step** gate.
  Existing positions/pending orders, stale quotes/accounts, unknown daily baseline,
  missing D1 history/news evidence or exhausted loss budgets block approval.
- Reasoning, actual LangChain prompt callbacks, snapshot/model/code fingerprints,
  risk policy and gate-time quotes/accounts are retained in the decision ledger.
- A narrow Backtrader/Nautilus bracket comparison and terminal reasoning dashboard.

No broker `order_send` implementation exists. APPROVE means an admissible **shadow
candidate**, not an instruction to place a real order. All performance evidence
starts as unavailable and is kept separate from software fixture tests.

## Launch

Start from the normal TradingAgents launcher, using the installed `.venv-astra`:

```powershell
cd C:\Users\mathi\MyTradingAgents\TradingAgents
.\tradingagents.ps1
```

Choose **FTMO swing**, then **Start full pipeline: Live MT5 shadow analysis**. Use the arrow keys and
Enter, not the old numeric menu. Normal stocks/ETF/crypto research is the other
workspace; its existing agent selection and environment overrides are preserved.

The FTMO workflow uses the same TradingAgents language, depth, provider and model
wizard. Ollama offers installed models and marks loaded ones as `running`.
OpenAI-compatible services such as vLLM list their served model IDs. If discovery
fails, suggested/manual IDs remain available with a warning; this does not prove
the service is ready. Start your inference server before running analysis.

- **Analysis model (quick):** analysts, bull/bear researchers, trader and risk debaters.
- **Reasoning model (deep):** research manager and portfolio manager.
- **Ollama URL:** normally `http://localhost:11434/v1`, not a model-directory path.
- **vLLM URL:** normally `http://localhost:8000/v1`; choose OpenAI-compatible.
- **Instrument:** EUR/USD, normally `EURUSD` or its broker suffix, not `USD`.
- **MT5 login/server:** detected from your open terminal, then explicitly confirmed.
- **Original balance:** the starting balance in your FTMO account details, not the login.

The first live run guides you through model selection, confirms your terminal,
starts an independent read-only recorder, waits for fresh account data and runs
the existing full agent graph. Market-data readiness is checked before invoking
the models. Dated Federal Reserve/ECB publications are recorded automatically
before the live decision; unavailable feeds remain explicitly unavailable.
These publications are partial macro evidence, **not a verified economic calendar**.
Progress names each completed agent. Choose a
single H4 analysis or a four-hour H4-close watcher. The owned recorder stops when
the session ends or you press Ctrl+C. Recorder errors are in
`results/astra/recorder.log` (or beside your custom catalog).

The integrated path is:

```text
FTMO MT5 -> recorded bid/ask + closed M15/H4/D1 context
        -> full TradingAgents research and risk debate
        -> typed LONG / SHORT / NO TRADE swing contract
        -> deterministic FTMO gate
        -> bounded Nautilus + Backtrader execution review
        -> shadow ledger and decision dashboard
```

The execution review runs only for an approved candidate with actual subsequent
quotes. Otherwise it shows `not_run`, `pending`, or a concrete blocking reason.
The H4 watcher revisits a pending review as quotes arrive. The first evaluated
POC is frozen and saved separately from the decision; it never changes the
original gate or turns hindsight into an entry signal. Gaps over 30 seconds are
rejected instead of assuming what happened while recording was stopped.
Automatic reviews are bounded to four hours and the original Prague day, and
exclude commissions/swaps/latency. They test execution mechanics, not multi-day
swing outcomes or profitability. A one-shot run can end with a pending review;
use continuous recording/watch when forward observations are needed.

SPY stock/ETF research is not converted into an EUR/USD trade. Choose FTMO swing
at launch to have the same agent team reason about the correct broker instrument.
No CSV import is needed for the live MT5 path. Cancellation of an import/setup
step returns to the workspace, and repaired-setting warnings appear once per
workspace session, rather than on every menu action.

At completion, accept **Open the decision dashboard?**, or choose **Dashboard**
after a decision is recorded to see the chart, proposal,
risk gate and individual agent reasoning. An empty dashboard now explains the
next step. The same workspace includes recorded replay, real-data/evidence
imports, the historical Backtrader baseline and the bounded engine comparison.
The baseline is a separate deterministic study, not an agent-driven replay.

There are no extra `$env:` flags to enable results. Setup saves non-secret settings
to ignored `.astra.json`. Invalid fields from older setup attempts are reported
and reset in memory; the file is rewritten only when you save a setup step.
Existing LLM API keys are read from the root `.env` or process environment;
the existing key prompt can save missing provider keys to `.env`, never to
`.astra.json`. No broker password is requested or stored.

Direct entry points are also available:

```powershell
.\tradingagents.ps1 ftmo
.\astra.ps1
.\.venv-astra\Scripts\python.exe -m cli.main ftmo
```

`astra.ps1` with no arguments now opens this integrated workspace. Explicit
commands such as `astra.ps1 status` still use the advanced scripting interface.
The Python command is also available when PowerShell script policy blocks `.ps1`
files; no machine-wide execution-policy change is required.

Environment recreation (Windows Python 3.12-3.14; tested with 3.14):

```powershell
C:\Python314\python.exe -m venv .venv-astra
.\.venv-astra\Scripts\python.exe -m pip install -e '.[dev,astra,ftmo]'
```

Pinned POC packages: NautilusTrader 1.231.0 and MetaTrader5 5.0.6180.
The separate `.venv-ftmo` environment is left unchanged.

## Advanced Separate-Process Session

The guided live workflow above manages recording for you. The commands below
are for running the recorder and reasoning separately; do not start a second
recorder alongside the guided live workflow.

1. Log into the intended FTMO MT5 terminal yourself. No terminal login or order
   submission is performed by Astra. Verify account type, USD denomination,
   original balance, exact symbol name, server and login number.
2. Run configuration, then start the recorder in its own terminal:

```powershell
.\astra.ps1 configure
.\astra.ps1 record-mt5 --seconds 3600 --history-days 180
```

The bridge checks both expected server and account login, hashes the identity in
the market catalog, imports available closed M15 broker history, polls overlapping
tick ranges and records account observations. Disconnection or identity changes
stop it explicitly. Restarting does not automatically recover missed tick history.
MT5 history depth depends on the terminal/server; 180 requested days is not a
guarantee of 180 available days. Bars fetched now have a receipt timestamp of now.

3. In another terminal, run reasoning once or watch for new H4 closes:

```powershell
.\astra.ps1 analyze
.\astra.ps1 analyze --watch-seconds 3600
```

Only run one of those for a given session. Slow reasoning never pauses the
recorder. When reasoning finishes, shadow mode reloads quotes/accounts and runs
the gate at **completion time**, not at the older prompt timestamp. News/macro
evidence must be imported before an approval can pass; absence is not neutrality.

4. Inspect the ledger:

```powershell
.\astra.ps1 dashboard
.\astra.ps1 status
```

The dashboard includes recorded price/support/resistance/proposed SL/TP, an agent
overview with individual reasoning details, proposal, account/loss headroom and
separate evidence stages.
Press `a` from the existing FTMO chart desk to open this same reasoning screen
when running in the Astra environment; Escape returns to the historical desk.
This view shows **decision-time recordings**, not an unlabelled live price chart.

## Historical Data

Use your actual broker export. `import-quotes` requires an explicit instrument
specification JSON, validated against `Instrument` in `models.py`. Required fields
are `symbol`, `feed_id`, `provider`; review currency, contract size, increments
and min/step/max units instead of relying blindly on the EUR/USD defaults.

```powershell
.\astra.ps1 import-quotes C:\data\quotes.csv --instrument C:\data\instrument.json
.\astra.ps1 import-records bar C:\data\m15.jsonl
.\astra.ps1 import-records account C:\data\accounts.jsonl
.\astra.ps1 import-records evidence C:\data\evidence.jsonl
.\astra.ps1 analyze --mode replay --as-of '2026-09-10T12:00:30Z'
```

Quote CSV columns: `timestamp,bid,ask`, optionally `received_at,volume`.
Every timestamp requires an offset or `Z`; naive timestamps are rejected.

JSONL files contain one contract from `models.py` per line:

- **Bar:** symbol/feed, M15 timeframe, bid/ask/mid basis, open_time, close_time,
  OHLC and optional volume/receipt time. Set `complete: true` only for verified
  complete source candles. M15 open/close times must be 15 minutes apart on the
  UTC grid. H4 requires 16 such candles; D1 requires 96. Partial trading days are
  conservatively omitted rather than fabricated.
- **AccountSnapshot:** explicit timestamp/feed/currency, original balance,
  balance/equity, Prague date, day-start balance, positions/pending orders and
  origin (`recorded` for imported history). Never invent a historical account
  state just to obtain approval.
- **Evidence:** kind (`news`, `macro`, `sentiment`, `fundamentals`), publication
  and optional receipt timestamp, source and a bounded summary. Evidence currently
  shares the catalog's universe; import only relevant sources for that universe.
  The live workflow also records dated Fed/ECB RSS publications. A complete,
  verified economic-calendar integration remains future work; replay never
  fetches current publications to fill historical gaps.

Missing receipt times mean *assumed historical availability at event time*, not
proof of when information was really received. Do not mix these backfill
assumptions with actual live-forward evidence. Closed bars reconstructed from
isolated CSV quote samples are not automatically declared complete.

Pass `--catalog` **before** the subcommand to separate datasets or experiments:
`astra.ps1 --catalog C:\data\replay.sqlite status`. Multiple instrument versions
or conflicting bar revisions fail closed; select a separate reviewed catalog
rather than silently overwriting observations.

## Execution Comparison

After a completed approved candidate and recorded subsequent quotes exist:

```powershell
.\astra.ps1 compare-engines DECISION_KEY --until '2026-09-10T13:00:00Z'
```

This deliberately bounded POC replays a frozen bracket on both engines. It does
not ask an LLM to simulate fills. Entry is at the second quote (a common explicit
scheduling convention); prices must still fit the frozen entry zone. It uses the
first target, full fills and no financing/commission/latency. Unclosed positions
remain marked to market. Quotes must have strictly increasing distinct timestamps,
cover at most four hours and stay in the account's Prague day. Reports persist
fills, marked equity, FTMO headroom and a shared scenario hash.

Measured differences, covered by tests:

- At zero spread, ordinary target fills and stop gaps agree in the tested cases.
- Backtrader gives opening-price improvement on a gap through a take-profit limit;
  this Nautilus configuration fills its resting limit at the specified limit.
- Nautilus uses actual bid/ask sides; Backtrader's point-bars use midpoint. Spreads
  therefore change entry prices, target triggering and PnL. This is not a defect
  to hide by adjusting inputs.

These are software execution fixtures, **not evidence of an edge**. The original
multi-day FTMO Backtrader study is not migrated to Nautilus yet. Broker-specific
swaps, calibrated latency/fees, partial liquidity, continuous FTMO liquidation and
multi-instrument risk must be verified before that migration or demo orders.

## Safety And Remaining Work

- Current risk defaults: 0.25% maximum per trade, 1% internal daily cutoff, 5%
  two-step daily floor, 10% static total floor. Size rounds down to broker units.
  Net R:R and risk include assumed slippage, round-trip commission and a
  conservative per-calendar-day financing reserve. These are **uncalibrated
  assumptions**, not guarantees against gaps or broker execution costs.
- Polling only sees sampled account state. The breach latch cannot prove that
  an unobserved intrapoll or pre-recording breach never happened. Full account
  history, reset/transfer reconciliation and rule-version verification remain
  prerequisites for demo/live execution.
- Quote aggregation uses UTC boundaries, not broker-local H4 candles. Exchange
  sessions/holidays and broker-specific DST schedules are not fully integrated.
- NO TRADE is a normal result. A rejected proposal has zero authorized size.
- A crash leaves a visible `running` claim; it is not automatically retried and
  cannot submit an order. Review the incomplete audit before creating a new event.
- cTrader and Nautilus catalog/live adapters are not implemented. MT5 adapters
  listed by Nautilus are community integrations, not a verified FTMO adapter.
- Live market connectivity and actual model-provider reasoning have not been
  exercised against the user's account in this development run. Tests use fake
  providers/models and clearly labelled execution fixtures.
- Development, validation, holdout, stress and live-forward metrics remain
  separate and unavailable until actually computed. No parameter optimization or
  holdout tuning was performed. Long-horizon shadow outcome scoring is next work.

## Verification

```powershell
.\.venv-astra\Scripts\python.exe -m pytest tests/test_astra.py tests/test_astra_providers.py tests/test_astra_engines.py tests/test_astra_dashboard.py -q
.\.venv-astra\Scripts\python.exe -m pytest tests/test_cli_ftmo.py tests/test_cli_env_skip.py tests/test_ollama_base_url.py tests/test_openai_compatible_provider.py -q
.\.venv-astra\Scripts\python.exe -m pytest tests/test_astra_pipeline.py tests/test_source_resilience.py -q
```

The focused suite covers as-of/receipt filtering, incomplete candles, feed identity,
loss limits, pending exposure, malformed proposals, the full existing agent graph,
idempotency, persistent breaches, execution differences and terminal layouts.
The larger regression report is written to `results/astra-regressions.xml`.
Latest focused results are in `results/astra/final-checks.xml`. The default Astra
catalog, prompts and generated reports are excluded from Git; custom catalog
locations require the same care before committing or sharing files.
