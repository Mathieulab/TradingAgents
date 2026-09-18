# TradingAgents / Finance Lab / Astra

This is [Mathieulab's fork](https://github.com/Mathieulab/TradingAgents) of
[TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents).
It brings the existing multi-agent research workflow together with a finance
research lab and an **EUR/USD FTMO swing shadow-testing workspace** named Astra.

**Current status: research and shadow testing only. Broker orders are disabled.**
An approved proposal is not an executed trade, a profitable strategy, or proof
that an account will pass an FTMO evaluation.

## Start Here

New contributor? Install the project below, run the no-account smoke test, then
read [CONTRIBUTING.md](CONTRIBUTING.md) for the code map, tests, and development
priorities. The main project direction is the
[Astra roadmap](docs/ASTRA_ROADMAP_SOURCE.md); the
[architecture assessment](docs/ASTRA_ARCHITECTURE.md) describes what exists and
what still needs work. Older planning notes and the upstream reference below
are background, not evidence that every planned feature is implemented.

### What You Can Run Today

| Workspace | Purpose | Inputs and limitations |
| --- | --- | --- |
| Market research | Original analyst team, bull/bear debate, trader, risk team, and portfolio manager for stocks, ETFs, and crypto | Local/cloud LLM plus supported data providers; external sources can be unavailable |
| Finance Lab replay | Store decisions, compare forward horizons, trade styles, and risk gates | Historical bars and optional minute data; hindsight comparisons are not live entry signals |
| Astra FTMO swing | Full agent reasoning on recorded EUR/USD context, deterministic FTMO gate, shadow ledger, terminal charts | Read-only MT5 or imported observations; no broker orders |
| Historical swing study | Fixed H4 EMA/Donchian/ATR baseline using M15 execution, costs, development/holdout/stress runs | Real CSVs for market evaluation; labelled synthetic demo for software checks only |
| Engine comparison | Backtrader and Nautilus replay of the same frozen bracket candidate | Bounded execution proof of concept, not a complete multi-day swing backtest |

The historical baseline is a separate deterministic experiment. It does not
replace the agents in Astra. Research on SPY is never relabelled as an EUR/USD
trade.

## Install

For the complete Astra environment, use **64-bit Python 3.12-3.14** and Git.
The current local environment was tested with Python 3.14. Live MT5 recording
requires Windows and an installed MetaTrader 5 terminal logged into your
intended account. Other platforms can use research/import/replay where the
dependencies are available; live MT5 support is Windows-only.

From PowerShell:

```powershell
git clone https://github.com/Mathieulab/TradingAgents.git
cd TradingAgents
py -3.14 -m venv .venv-astra
.\.venv-astra\Scripts\python.exe -m pip install --upgrade pip
.\.venv-astra\Scripts\python.exe -m pip install -e ".[dev,astra,ftmo]"
```

Use `py -3.12` or `py -3.13` if that is your installed version. The Astra extra
pins NautilusTrader and MetaTrader5; a Python 3.10/3.11 core install does not
provide the complete Astra stack. The optional portfolio-memory MCP server
additionally needs `pip install -e ".[mcp]"` in the same environment.

Virtual-environment activation and manual `$env:` flags are **not required**
for the guided workflow. These commands invoke the intended Python directly.
The upstream Docker setup below is not an MT5/Astra deployment recipe.

### First Check: No Account or LLM Required

```powershell
.\.venv-astra\Scripts\python.exe -m cli.main --help
.\.venv-astra\Scripts\python.exe -m finance_lab.ftmo --demo --no-ui
```

The second command runs the standalone swing study on **synthetic test data**
and writes local reports under `reports/ftmo/`. Its returns measure no real
market edge. Omit `--no-ui` to open the historical terminal dashboard. For real
CSV formats, timezones, costs, and strategy rules, see the
[historical study guide](finance_lab/ftmo/README.md).

## Use the Application

```powershell
.\.venv-astra\Scripts\python.exe -m cli.main
```

Choose the ordinary market-research workspace or **FTMO swing** with the arrow
keys and Enter. `tradingagents.ps1` is a shortcut; the Python command also works
when PowerShell policy blocks scripts. To go directly to FTMO:

```powershell
.\.venv-astra\Scripts\python.exe -m cli.main ftmo
```

### Models

The guided setup asks for provider, analysis model, reasoning model, language,
and research depth. Start your inference server before model selection.

| Provider | Endpoint | Model selection |
| --- | --- | --- |
| Ollama | `http://localhost:11434/v1` | Discovers installed models and marks loaded ones as running |
| vLLM / other OpenAI-compatible server | Usually `http://localhost:8000/v1` | Choose OpenAI-compatible and a model ID served by that endpoint |
| Cloud provider | Provider default | Choose a supported model; supply your own API key when prompted |

An endpoint is an HTTP URL, **not a local model folder**. For example, install
an Ollama model with `ollama pull qwen3:8b`, then choose its discovered ID. This
is a setup example, not a validated trading-model recommendation. The quick
model handles analysts, researchers, trader, and risk debaters; the deep model
handles the research manager and portfolio manager. Greater debate depth adds
latency and, with hosted providers, cost.

### First FTMO Shadow Session

1. Open MT5 and log into the intended account yourself. Verify the account,
   server, original balance, and EUR/USD symbol. Astra never asks for a broker
   password.
2. Choose **Start full pipeline: Live MT5 shadow analysis** in the FTMO menu.
3. Complete model setup and confirm the detected MT5 identity. Use the exact
   broker symbol, such as `EURUSD` or its supported suffix, not `USD`. Original
   account balance and account login are different fields.
4. Choose a single H4 analysis or the H4-close watcher. The workflow starts a
   separate read-only recorder, checks data readiness, records available
   Fed/ECB publications, and runs the complete agent team.
5. Read the proposal and deterministic gate result. Accept **Open decision
   dashboard?** or select **Dashboard** from the workspace to inspect charts,
   risk headroom, agent reasoning, and execution-review status.

The recorder stays active while models think and stops when the session ends.
Insufficient history, missing news evidence, stale quotes, an unknown daily
baseline, or an unsupported account state can block a candidate. This is
expected fail-closed behavior, not permission to bypass the gate.

If you do not have MT5, use the synthetic software check or import real data
through the workspace. Recorded agent replay needs timestamped bars, quotes,
account observations, and evidence; an OHLC CSV alone is not a full replay
dataset. See the [Astra guide](finance_lab/astra/README.md) for schemas and
advanced commands.

## How the Pieces Work Together

```text
MT5 read-only feed / historical imports
    -> SQLite catalog: quotes, bars, account observations, evidence
    -> compact as-of M15 / H4 / D1 context
    -> existing TradingAgents LangGraph
       analysts -> bull/bear -> research manager -> trader
       -> risk debate -> portfolio manager
    -> structured LONG / SHORT / NO TRADE proposal
    -> deterministic FTMO risk gate
    -> immutable shadow decision and reasoning ledger
    -> later recorded quotes -> bounded Nautilus / Backtrader review
    -> terminal dashboard
```

Agents explain **whether and why** to propose a trade. Deterministic code
calculates admissibility and simulates execution; the LLM does not calculate
fills or decide whether an FTMO loss limit was technically breached.
Historical snapshot agents cannot fetch current vendor data. Publication,
event, and receipt timestamps support as-of filtering. Forward observations
never alter the original proposal or gate result.

### Read Results Correctly

- `NO TRADE` and rejected candidates are valid outcomes; they are not executed.
- `APPROVE` means an admissible **shadow candidate**, not broker authorization.
- A pending execution review means sufficient real subsequent quotes are not
  yet available. Keep recording; a one-shot run may finish before they arrive.
- The integrated engine review needs at least three post-decision quotes,
  rejects gaps over 30 seconds, and is bounded to four hours within one Prague
  day. Commissions, swaps, and latency are not calibrated in this POC.
- Completed POC results are stored separately and frozen. They are not
  multi-day swing validation, holdout results, or profitability evidence.
- Finance Lab's retrospective best-style ranking is descriptive, not proof of
  an optimal strategy. Daily bars cannot establish a scalping edge.

## Local Data and Safety

| Location | Contents |
| --- | --- |
| `.astra.json` | Local model/MT5 settings; no API keys or broker passwords |
| `.env` | Optional local provider credentials, including keys saved by the wizard |
| `results/astra/market.sqlite` | Recorded observations, decisions, prompts, reasoning, and execution reviews |
| `results/astra/recorder.log` | Recorder diagnostics |
| `reports/` | Generated research and historical-study output |

These files are private runtime state and excluded from Git. Never attach an
unredacted database, account screenshot, `.env`, or prompt log to a public
issue. Using a hosted LLM sends its supplied analysis context to that provider;
review that choice before running on account data.

The gate currently targets flat EUR/USD accounts denominated in USD with FTMO
two-step assumptions. Verify current account rules independently. A complete
economic calendar, missed-tick recovery, account/order reconciliation,
calibrated multi-day execution, and demo-order execution remain future work.
Fed/ECB RSS publications are partial macro evidence, not a verified calendar.
There is no cTrader implementation and no autonomous real-money path.

## Troubleshooting and Development

| Symptom | Next step |
| --- | --- |
| Empty dashboard or zero records | Run a shadow session or import a complete replay dataset first |
| No approved candidate to compare | Inspect the proposal/gate; do not weaken risk checks to force a trade |
| Saved symbol/endpoint needs correction | Re-save model or MT5 setup with an exact symbol and HTTP endpoint |
| Local models are missing | Check the inference server, endpoint, and installed/served model IDs |
| News site unavailable | Treat it as missing evidence, not neutral sentiment; inspect source diagnostics |
| PowerShell blocks `.ps1` | Use the direct virtual-environment Python commands above |

Development instructions and targeted verification:
[CONTRIBUTING.md](CONTRIBUTING.md). Detailed references:
[Astra](finance_lab/astra/README.md),
[historical swing study](finance_lab/ftmo/README.md),
[Finance Lab](finance_lab/README.md), and
[architecture/rollout](docs/ASTRA_ARCHITECTURE.md).

## Upstream Attribution

The underlying TradingAgents framework is by TauricResearch and its
contributors. This fork retains the [Apache-2.0 license](LICENSE). The paper,
original framework documentation, and citation are preserved below; upstream
release notes and examples do not describe the current status of every fork
extension.

---

## Upstream Framework Reference

<p align="center">
  <img src="assets/TauricResearch.png" style="width: 60%; height: auto;">
</p>

<div align="center" style="line-height: 1;">
  <a href="https://arxiv.org/abs/2412.20138" target="_blank"><img alt="arXiv" src="https://img.shields.io/badge/arXiv-2412.20138-B31B1B?logo=arxiv"/></a>
  <a href="https://discord.com/invite/hk9PGKShPK" target="_blank"><img alt="Discord" src="https://img.shields.io/badge/Discord-TradingResearch-7289da?logo=discord&logoColor=white&color=7289da"/></a>
  <a href="./assets/wechat.png" target="_blank"><img alt="WeChat" src="https://img.shields.io/badge/WeChat-TauricResearch-brightgreen?logo=wechat&logoColor=white"/></a>
  <a href="https://x.com/TauricResearch" target="_blank"><img alt="X Follow" src="https://img.shields.io/badge/X-TauricResearch-white?logo=x&logoColor=white"/></a>
  <br>
  <a href="https://github.com/TauricResearch/" target="_blank"><img alt="Community" src="https://img.shields.io/badge/Join_GitHub_Community-TauricResearch-14C290?logo=discourse"/></a>
</div>

<div align="center">
  <!-- Keep these links. Translations will automatically update with the README. -->
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=de">Deutsch</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=es">Español</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=fr">français</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ja">日本語</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ko">한국어</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=pt">Português</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ru">Русский</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=zh">中文</a>
</div>

---

# TradingAgents: Multi-Agents LLM Financial Trading Framework

## News
- [2026-05] **TradingAgents v0.2.5** released with the grounded Sentiment Analyst, GPT-5.5 etc. model coverage, Qwen/GLM/MiniMax dual-region support, `TRADINGAGENTS_*` env-var configurability with API-key auto-detection, remote Ollama support, non-US alpha benchmarks, and ticker path-traversal hardening. See [CHANGELOG.md](CHANGELOG.md) for the full list.
- [2026-04] **TradingAgents v0.2.4** released with structured-output agents (Research Manager, Trader, Portfolio Manager), LangGraph checkpoint resume, persistent decision log, DeepSeek/Qwen/GLM/Azure provider support, Docker, and a Windows UTF-8 encoding fix.
- [2026-03] **TradingAgents v0.2.3** released with multi-language support, GPT-5.4 family models, unified model catalog, backtesting date fidelity, and proxy support.
- [2026-03] **TradingAgents v0.2.2** released with GPT-5.4/Gemini 3.1/Claude 4.6 model coverage, five-tier rating scale, OpenAI Responses API, Anthropic effort control, and cross-platform stability.
- [2026-02] **TradingAgents v0.2.0** released with multi-provider LLM support (GPT-5.x, Gemini 3.x, Claude 4.x, Grok 4.x) and improved system architecture.
- [2026-01] **Trading-R1** [Technical Report](https://arxiv.org/abs/2509.11420) released, with [Terminal](https://github.com/TauricResearch/Trading-R1) expected to land soon.

<div align="center">
<a href="https://www.star-history.com/#TauricResearch/TradingAgents&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=TauricResearch/TradingAgents&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=TauricResearch/TradingAgents&type=Date" />
   <img alt="TradingAgents Star History" src="https://api.star-history.com/svg?repos=TauricResearch/TradingAgents&type=Date" style="width: 80%; height: auto;" />
 </picture>
</a>
</div>

> 🎉 **TradingAgents** officially released! We have received numerous inquiries about the work, and we would like to express our thanks for the enthusiasm in our community.
>
> So we decided to fully open-source the framework. Looking forward to building impactful projects with you!

<div align="center">

🚀 [TradingAgents](#tradingagents-framework) | ⚡ [Installation & CLI](#installation-and-cli) | 🎬 [Demo](https://www.youtube.com/watch?v=90gr5lwjIho) | 📦 [Package Usage](#tradingagents-package) | 🤝 [Contributing](#contributing) | 📄 [Citation](#citation)

</div>

## TradingAgents Framework

TradingAgents is a multi-agent trading framework that mirrors the dynamics of real-world trading firms. By deploying specialized LLM-powered agents: from fundamental analysts, sentiment experts, and technical analysts, to trader, risk management team, the platform collaboratively evaluates market conditions and informs trading decisions. Moreover, these agents engage in dynamic discussions to pinpoint the optimal strategy.

<p align="center">
  <img src="assets/schema.png" style="width: 100%; height: auto;">
</p>

> TradingAgents framework is designed for research purposes. Trading performance may vary based on many factors, including the chosen backbone language models, model temperature, trading periods, the quality of data, and other non-deterministic factors. [It is not intended as financial, investment, or trading advice.](https://tauric.ai/disclaimer/)

Our framework decomposes complex trading tasks into specialized roles.

### Analyst Team
- Fundamentals Analyst: Evaluates company financials and performance metrics, identifying intrinsic values and potential red flags.
- Sentiment Analyst: Aggregates news headlines, StockTwits, and Reddit chatter into a single sentiment read to gauge short-term market mood.
- News Analyst: Monitors global news and macroeconomic indicators, interpreting the impact of events on market conditions.
- Technical Analyst: Utilizes technical indicators (like MACD and RSI) to detect trading patterns and forecast price movements.

<p align="center">
  <img src="assets/analyst.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

### Researcher Team
- Comprises both bullish and bearish researchers who critically assess the insights provided by the Analyst Team. Through structured debates, they balance potential gains against inherent risks.

<p align="center">
  <img src="assets/researcher.png" width="70%" style="display: inline-block; margin: 0 2%;">
</p>

### Trader Agent
- Composes reports from the analysts and researchers to make informed trading decisions, determining the timing and magnitude of trades.

<p align="center">
  <img src="assets/trader.png" width="70%" style="display: inline-block; margin: 0 2%;">
</p>

### Risk Management and Portfolio Manager
- Continuously evaluates portfolio risk by assessing market volatility, liquidity, and other risk factors. The risk management team evaluates and adjusts trading strategies, providing assessment reports to the Portfolio Manager for final decision.
- The Portfolio Manager approves/rejects the transaction proposal. If approved, the order will be sent to the simulated exchange and executed.

<p align="center">
  <img src="assets/risk.png" width="70%" style="display: inline-block; margin: 0 2%;">
</p>

## Installation and CLI

### Installation

Clone TradingAgents:
```bash
git clone https://github.com/TauricResearch/TradingAgents.git
cd TradingAgents
```

Create a virtual environment in any of your favorite environment managers:
```bash
conda create -n tradingagents python=3.12
conda activate tradingagents
```

Install the package and its dependencies:
```bash
pip install .
```

### Docker

Alternatively, run with Docker:
```bash
cp .env.example .env  # add your API keys
docker compose run --rm tradingagents
```

For local models with Ollama:
```bash
docker compose --profile ollama run --rm tradingagents-ollama
```

### Required APIs

TradingAgents supports multiple LLM providers. Set the API key for your chosen provider:

```bash
export OPENAI_API_KEY=...          # OpenAI (GPT)
export GOOGLE_API_KEY=...          # Google (Gemini)
export ANTHROPIC_API_KEY=...       # Anthropic (Claude)
export XAI_API_KEY=...             # xAI (Grok)
export DEEPSEEK_API_KEY=...        # DeepSeek
export DASHSCOPE_API_KEY=...       # Qwen — International (dashscope-intl.aliyuncs.com)
export DASHSCOPE_CN_API_KEY=...    # Qwen — China (dashscope.aliyuncs.com)
export ZHIPU_API_KEY=...           # GLM via Z.AI (international)
export ZHIPU_CN_API_KEY=...        # GLM via BigModel (China, open.bigmodel.cn)
export MINIMAX_API_KEY=...         # MiniMax — Global (api.minimax.io)
export MINIMAX_CN_API_KEY=...      # MiniMax — China (api.minimaxi.com)
export OPENROUTER_API_KEY=...      # OpenRouter
export ALPHA_VANTAGE_API_KEY=...   # Alpha Vantage
```

For Azure OpenAI, copy `.env.enterprise.example` to `.env.enterprise` and fill in your credentials.

For AWS Bedrock, install the extra with `pip install ".[bedrock]"`, set `llm_provider: "bedrock"`, configure AWS credentials (environment variables, `~/.aws/credentials`, or an IAM role) and `AWS_DEFAULT_REGION`, and use a Bedrock model ID, e.g. `us.anthropic.claude-opus-4-8-v1:0`.

For local models, configure Ollama with `llm_provider: "ollama"`. The default endpoint is `http://localhost:11434/v1`; set `OLLAMA_BASE_URL` to point at a remote `ollama-serve`. Pull models with `ollama pull <name>`, and pick "Custom model ID" in the CLI for any model not listed by default.

For any other OpenAI-compatible server (vLLM, LM Studio, llama.cpp, or a custom relay), use `llm_provider: "openai_compatible"` and set the endpoint via `backend_url` (or `TRADINGAGENTS_LLM_BACKEND_URL`), e.g. `http://localhost:8000/v1` for vLLM or `http://localhost:1234/v1` for LM Studio. The model is whatever your server serves. No key is needed for local servers; set `OPENAI_COMPATIBLE_API_KEY` when the endpoint requires one.

Alternatively, copy `.env.example` to `.env` and fill in your keys:
```bash
cp .env.example .env
```

### CLI Usage

This Finance Lab fork also includes an integrated **FTMO swing** workspace:

```powershell
.\tradingagents.ps1
```

Choose normal market research or FTMO swing. FTMO uses the same provider/model
wizard, discovers Ollama/vLLM models, records MT5 data read-only, and runs the
complete agent team before the deterministic risk gate. No broker orders are
enabled. See the [FTMO setup and safety guide](finance_lab/astra/README.md).
`astra.ps1` without arguments opens the same FTMO workspace directly.

Launch the interactive CLI:
```bash
tradingagents          # installed command
python -m cli.main     # alternative: run directly from source
```
You will see a screen where you can select your desired tickers, analysis date, LLM provider, research depth, and more.

### Markets and tickers

TradingAgents works with any market Yahoo Finance covers, using the exchange-suffixed ticker. Company identity and the alpha benchmark resolve automatically per market.

- US: `AAPL`, `SPY`
- Hong Kong: `0700.HK` · Tokyo: `7203.T` · London: `AZN.L`
- India: `RELIANCE.NS`, `.BO` · Canada: `.TO` · Australia: `.AX`
- China A-shares: Shanghai `.SS`, Shenzhen `.SZ` (e.g. `600519.SS` for Kweichow Moutai)
- Crypto: `BTC-USD`, `ETH-USD`

<p align="center">
  <img src="assets/cli/cli_init.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

An interface will appear showing results as they load, letting you track the agent's progress as it runs.

<p align="center">
  <img src="assets/cli/cli_news.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

<p align="center">
  <img src="assets/cli/cli_transaction.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

## TradingAgents Package

### Implementation Details

We built TradingAgents with LangGraph to ensure flexibility and modularity. The framework supports multiple LLM providers: OpenAI, Google, Anthropic, xAI, DeepSeek, Qwen (Alibaba DashScope, international and China endpoints), GLM (Zhipu), MiniMax (global + China), OpenRouter, Ollama for local models, and Azure OpenAI for enterprise.

### Python Usage

To use TradingAgents inside your code, you can import the `tradingagents` module and initialize a `TradingAgentsGraph()` object. The `.propagate()` function will return a decision. You can run `main.py`, here's also a quick example:

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

ta = TradingAgentsGraph(debug=True, config=DEFAULT_CONFIG.copy())

# forward propagate
_, decision = ta.propagate("NVDA", "2026-01-15")
print(decision)
```

You can also adjust the default configuration to set your own choice of LLMs, debate rounds, etc.

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "openai"        # e.g. openai, google, anthropic, deepseek, groq, ollama; openai_compatible covers any OpenAI-compatible endpoint (vLLM, LM Studio, llama.cpp, ...)
config["deep_think_llm"] = "gpt-5.5"     # Model for complex reasoning
config["quick_think_llm"] = "gpt-5.4-mini" # Model for quick tasks
config["max_debate_rounds"] = 2

ta = TradingAgentsGraph(debug=True, config=config)
_, decision = ta.propagate("NVDA", "2026-01-15")
print(decision)
```

See `tradingagents/default_config.py` for all configuration options.

## Persistence and Recovery

TradingAgents persists two kinds of state across runs.

### Decision log

The decision log is always on. Each completed run appends its decision to `~/.tradingagents/memory/trading_memory.md`. On the next run for the same ticker, TradingAgents fetches the realised return (raw and alpha vs SPY), generates a one-paragraph reflection, and injects the most recent same-ticker decisions plus recent cross-ticker lessons into the Portfolio Manager prompt, so each analysis carries forward what worked and what didn't.

Override the path with `TRADINGAGENTS_MEMORY_LOG_PATH`.

### Checkpoint resume

Checkpoint resume is opt-in via `--checkpoint`. When enabled, LangGraph saves state after each node so a crashed or interrupted run resumes from the last successful step instead of starting over. On a resume run you will see `Resuming from step N for <TICKER> on <date>` in the logs; on a new run you will see `Starting fresh`. Checkpoints are cleared automatically on successful completion.

Per-ticker SQLite databases live at `~/.tradingagents/cache/checkpoints/<TICKER>.db` (override the base with `TRADINGAGENTS_CACHE_DIR`). Use `--clear-checkpoints` to reset all of them before a run.

```bash
tradingagents analyze --checkpoint           # enable for this run
tradingagents analyze --clear-checkpoints    # reset before running
```

```python
config = DEFAULT_CONFIG.copy()
config["checkpoint_enabled"] = True
ta = TradingAgentsGraph(config=config)
_, decision = ta.propagate("NVDA", "2026-01-15")
```

## Reproducibility

TradingAgents is LLM-driven, so two runs of the same ticker and date can differ. This is expected for a research tool built on language models, not a defect. The variation comes from a few distinct sources, and it helps to separate them.

Language model sampling is non-deterministic. Even at a fixed temperature, providers do not guarantee byte-identical output across calls, and reasoning models (the default GPT-5.x family, and any thinking-mode model) vary the most because their internal reasoning is itself sampled.

Live data moves. News, StockTwits, and Reddit return different content as time passes, so a run today sees different inputs than a run last week even for the same historical trade date. Pin the analysis date to hold the price and indicator window fixed, but the social and news sources still reflect "now".

To reduce variation you can lower the sampling temperature. Set `temperature` in your config (or `TRADINGAGENTS_TEMPERATURE` in `.env`); lower values make models that honor it more repeatable. Reasoning models largely ignore temperature, so for tighter reproducibility pair a low temperature with a non-reasoning model such as `gpt-4.1`.

```python
config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "openai"
config["deep_think_llm"] = "gpt-4.1"      # non-reasoning model honors temperature
config["quick_think_llm"] = "gpt-4.1"
config["temperature"] = 0.0
```

What does not vary anymore: the analyzed company identity is resolved deterministically from the ticker before any agent runs, and the market analyst grounds exact price and indicator claims in a verified data snapshot. Earlier reports of "different companies" or fabricated price levels across runs are addressed by these two mechanisms.

Backtest results are not guaranteed to match any published figure. Returns depend on the model, the temperature, the date range, data quality, and the sampling above. Treat the framework as a research scaffold for studying multi-agent analysis, not as a strategy with a fixed, replicable return.

## Contributing

Contributions are welcome: bug fixes, documentation, and feature ideas; past contributions are credited per release in [`CHANGELOG.md`](CHANGELOG.md).

## Citation

Please reference our work if you find *TradingAgents* provides you with some help :)

```
@misc{xiao2025tradingagentsmultiagentsllmfinancial,
      title={TradingAgents: Multi-Agents LLM Financial Trading Framework}, 
      author={Yijia Xiao and Edward Sun and Di Luo and Wei Wang},
      year={2025},
      eprint={2412.20138},
      archivePrefix={arXiv},
      primaryClass={q-fin.TR},
      url={https://arxiv.org/abs/2412.20138}, 
}
```
