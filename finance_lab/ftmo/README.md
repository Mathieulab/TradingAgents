# FTMO Swing Test Desk

A standalone terminal workspace for testing a fixed EUR/USD **H4 swing strategy** against
FTMO **two-step** evaluation loss objectives. No LLM, API key, or `$env` settings
are needed. This is a historical simulation; it does not connect to a trading account.

## Start

From the repository root, the environment prepared for this project can be used directly:

```powershell
.\.venv-ftmo\Scripts\python.exe -m finance_lab.ftmo
```

The setup asks for demo/CSV data, account balance, phase, risk per trade, costs and
overnight swap rates. Signals use completed four-hour candles, with positions
held across days and weekends. Default: EUR/USD, USD 10,000, two-step Challenge,
0.25% risk. `ftmo.ps1` is a shortcut
to the same command when local PowerShell script execution is allowed.

To open the synthetic example without setup prompts:

```powershell
.\ftmo.ps1 --demo
```

To run and save results without opening the terminal app:

```powershell
.\.venv-ftmo\Scripts\python.exe -m finance_lab.ftmo --demo --no-ui
```

The synthetic dataset uses fixed seed 731. Its returns measure **no real market edge**.

## Install On Another Machine

Python 3.10+ (verified here on Python 3.14):

```powershell
python -m venv .venv-ftmo
.\.venv-ftmo\Scripts\python.exe -m pip install -r finance_lab/ftmo/requirements.txt
```

For an existing full TradingAgents installation, `pip install -e ".[ftmo]"` also
installs the dashboard dependencies and adds the `finance-ftmo` command. The old
LLM virtual environment is independent of `.venv-ftmo`.

## Real Historical Data

Export **EUR/USD 15-minute candles** from MT5 or a broker. Prefer at least 6-12
months spanning several market conditions. Complete H4 candles are constructed
from these bars for swing signals; M15 bars monitor fills, floating equity and
midnight loss resets. Partial H4 candles never generate signals. At least 3,328
M15 candles are required with the default indicators. This version models EUR/USD in a USD
account only; gold, indices and other quote currencies need different contract specs.

Accepted files: comma/semicolon/tab-separated OHLC, with `timestamp` or `datetime`,
or MetaTrader `<DATE>` / `<TIME>` columns. `volume` or `<TICKVOL>` is optional.
Timestamps are **bar opening times**, ordered, unique, and aligned to M15. Supply
the broker export timezone explicitly when timestamps have no UTC offset. Ambiguous
DST timestamps, invalid prices and daily/hourly bars are rejected. Missing bars
are reported and never silently filled.

Example for a broker export whose timestamps really use fixed UTC+2:

```powershell
.\.venv-ftmo\Scripts\python.exe -m finance_lab.ftmo `
  --csv C:\data\EURUSD_M15.csv `
  --timezone Etc/GMT-2 --price-basis bid `
  --balance 10000 --phase challenge --risk 0.25 `
  --spread-pips 1.0 --slippage-pips 0.2 --commission 3.5 `
  --swap-long -8 --swap-short -4
```

`Etc/GMT-2` means UTC+2 in IANA notation. It is only an example: broker server
time may change with DST and may differ from your local or FTMO reset timezone.
For offset-aware timestamps, `--timezone` can be omitted. Confirm the actual
broker clock before importing. Use `--price-basis mid` for midpoint candles.
Bid candles are converted to midpoint using half the assumed fixed spread.
Charts and stop levels use these simulated midpoint prices.
Swap values above are illustrative assumptions, not current FTMO rates. Replace
them with the selected broker/account's USD-per-lot rates; negative means a debit.

## Fixed Strategy

```text
Completed H4 candle (assembled from M15 data)
        |
EMA 20 > EMA 50 and close > prior 20 highs  -> LONG
EMA 20 < EMA 50 and close < prior 20 lows   -> SHORT
        |
07:00-15:45 UTC entries / one position / max 1 entry per Prague day
        |
Risk 0.25% of equity / internal daily stop 1% / leverage cap 10:1
        |
Next M15 candle open + adverse slippage
        |
Stop: 2 x H4 Wilder ATR(14) / target: 2 x stop distance
        |
Multi-day hold / OCO stop or target / maximum 10 calendar days
```

Backtrader handles positions, fills and OCO orders. A small broker subclass activates
bracket protection on the entry candle; when both stop and target are touched
inside one candle, the stop is processed first. A target already marketable at
the opening price is executed before later intrabar extremes. Gaps through stops fill at the adverse
opening price. Position sizing includes estimated round-trip costs, uses 0.01-lot
increments and caps leverage. Time-limit and risk-cutoff liquidations use the next
available open (the final bar open for the dataset end). Orders use the first M15
opening after the completed signal, without reading future candles. With UTC-aligned
H4 bars and the entry-session filter, new entries normally occur at 08:00 or 12:00 UTC.

Spread is charged as a cash cost on each side, alongside USD commission per 100k
lot; slippage moves execution prices. These are fixed assumptions, not a live
bid/ask execution model. Overnight financing is estimated at 17:00 New York on
weekdays, with triple Wednesday rollover. US DST is respected. The ledger deducts
financing at rollover and reconciles it with the broker's final equity. Actual
swap rates and holiday adjustments vary by broker; verify them before importing
market history. There is no routine daily liquidation. ATR uses Backtrader's Wilder smoothing.

## Evaluation

Each run has three independent simulated accounts:

- First 70%: development period, with indicator warmup.
- Last 30%: chronological holdout using the same frozen parameters. Pre-split
  candles warm indicators only; positions and account balance start fresh.
- Last 30%: another fresh holdout account with spread, slippage, commission and
  swap debits doubled; swap credits are halved.

There is no parameter search or automatic fitting. Repeatedly changing parameters
after viewing holdout results turns the holdout into development data. Reserve
another untouched period before drawing a conclusion.

Results include net returns, closed trades, win rate, profit factor, dollar
expectancy, cost and financing totals, adverse-bar drawdown, and rule breaches. Undefined
statistics appear as `n/a`. Fewer than 30 holdout trades is flagged as insufficient
evidence; reaching 30 alone is not statistical proof. `FORWARD DEMO CANDIDATE`
means a real CSV passed these preliminary historical filters, not that it is ready
for an FTMO purchase or live execution.

## Account Objectives

Source: [FTMO Trading Objectives](https://ftmo.com/en/trading-objectives/),
checked 2026-09-05. The two-step preset is:

| Objective | Challenge | Verification |
|---|---:|---:|
| Profit target, closed balance | 10% | 5% |
| Maximum daily loss | 5% of initial balance | 5% of initial balance |
| Maximum overall loss | 10%, static | 10%, static |
| Minimum days opening a position | 4 | 4 |

Daily equity floor = balance at 00:00 **Europe/Prague** minus 5% of initial capital.
Overall equity floor = 90% of initial capital. Floating loss estimates and
transaction costs are included. A breach remains recorded even if equity later
recovers. No subsequent entries are allowed; an existing position is liquidated
at the next available open. Gaps can exceed both stops and risk limits.

The strategy's tighter 1% daily cutoff uses the day's worst estimated equity,
halts new entries and schedules liquidation at the next open. Bar-level risk
observations are conservative estimates, not continuous tick-level enforcement.
Drawdown compares adverse bar equity to the prior sampled closing-equity peak.
`OBJECTIVE MET` requires a flat account, target balance, at least four entry days
and no recorded loss breach. It describes this simulated phase only. Challenge
and Verification are separate runs; this is not certification of an FTMO pass.

The one-step product, funded-account restrictions, economic-news windows,
execution outages and forbidden-practice reviews are outside this preset.

## Dashboard And Artifacts

The terminal has Market, Trade journal, Validation and Account rules tabs.
Market shows candles, EMAs, breakout channel, fill markers, open stop/target,
ATR, equity, current rule headroom and the strategy flow. Full-period validation
statistics remain visible independently of the chart replay cursor.

Select development/holdout/cost stress and H4 swing/M15 execution from the menus.
H4 is the default chart. Only completed H4 bars are shown; marker positions on that
view group M15 fills next to their preceding H4 close. Inspect exact fill times in
the journal or M15 view. Use Space to play/pause,
Left/Right to step, Home/End to jump, +/- to zoom, S for a terminal SVG snapshot,
Q to quit. Compact terminals stack the technical panel below the charts; scroll
to view the full workspace. A 120-column by 40-row terminal is recommended.

Each run is saved under `reports/ftmo/<timestamp>_<id>/`:

- `result.json`: frozen parameters per run, source, normalized M15/H4 candles, curves,
  ledger, account rules, split timestamp and assessment.
- `development_trades.csv`, `holdout_trades.csv`, `stress_trades.csv`.
- Terminal snapshots when requested.

## Next Test Stage

Import actual broker history, inspect data gaps and match costs to the account.
Evaluate the unchanged strategy on an untouched date range, then observe it on an
FTMO Free Trial/demo account. A streaming broker adapter, order reconciliation,
news scheduling and recovery tests are required before automating that forward
stage. This module currently places no external orders.

## Verification

```powershell
.\.venv-ftmo\Scripts\python.exe -m pip install pytest ruff
.\.venv-ftmo\Scripts\python.exe -m pytest tests/test_ftmo.py
.\.venv-ftmo\Scripts\python.exe -m ruff check finance_lab/ftmo tests/test_ftmo.py
```
