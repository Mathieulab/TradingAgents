# Contributing to Finance Lab / Astra

Start with the root [README](README.md) to install and run the project. Work
from the repository root using `.venv-astra`, not a different system Python.
The [Astra roadmap](docs/ASTRA_ROADMAP_SOURCE.md) is the main direction; compare
it with the [architecture assessment](docs/ASTRA_ARCHITECTURE.md) before
changing the integration. Older audit/test-plan documents are historical.

## Code Map

| Location | Responsibility |
| --- | --- |
| `cli/main.py`, `cli/utils.py` | Shared wizard and original market-research interface |
| `cli/ftmo.py`, `cli/local_models.py` | Guided FTMO session and inference-server model discovery |
| `cli/decision_summary.py`, `cli/finance_backtest.py` | Research decision summaries and Finance Lab replay display |
| `tradingagents/graph/`, `tradingagents/agents/` | Actual LangGraph agent workflow, prompts, and structured output |
| `tradingagents/integrations/astra_context.py` | Role-scoped recorded context bridge into the existing agents |
| `tradingagents/dataflows/`, `tradingagents/llm_clients/` | Research data sources and LLM provider clients |
| `finance_lab/astra/models.py`, `catalog.py` | Typed contracts, observation catalog, and decision/review persistence |
| `finance_lab/astra/providers.py`, `recorder.py` | CSV/read-only MT5 and independent recording process |
| `finance_lab/astra/context.py`, `evidence.py` | As-of feature context and dated central-bank publications |
| `finance_lab/astra/orchestrator.py`, `risk.py` | Full-agent event reasoning and deterministic FTMO gate |
| `finance_lab/astra/pipeline.py`, `engines.py` | Frozen-candidate execution review and Backtrader/Nautilus adapters |
| `finance_lab/astra/dashboard.py` | Textual market, proposal, risk, and reasoning views |
| `finance_lab/ftmo/` | Separate deterministic historical H4 swing study |
| `finance_lab/core/`, `finance_lab/storage/` | Earlier indicators, replay/style comparison, trade gates, and storage |
| `finance_lab/mcp/` | Portfolio-memory server and documentation for other planned servers |
| `tests/` | Regression tests; Astra and historical-study tests use fixtures |

## Verify a Change

No MT5 account, hosted LLM, or real trade is needed for the focused Astra
regressions. Install `.[dev,astra,ftmo]` first:

```powershell
.\.venv-astra\Scripts\python.exe -m pytest tests/test_astra.py tests/test_astra_providers.py tests/test_astra_engines.py tests/test_astra_pipeline.py tests/test_astra_dashboard.py tests/test_cli_ftmo.py tests/test_ftmo.py -q
.\.venv-astra\Scripts\python.exe -m pytest tests/test_source_resilience.py tests/test_structured_agents.py tests/test_vendor_routing.py tests/test_ollama_model_catalog.py -q
.\.venv-astra\Scripts\python.exe -m finance_lab.ftmo --demo --no-ui
```

Run adjacent tests when touching research, providers, memory, or CLI behavior.
`python -m pytest` runs the full suite in the selected environment; some tests
outside this focused set may require additional extras or services. Do not
describe a targeted run as a full-suite pass. A synthetic demo verifies
software behavior, never profitability.

Check only the files you changed for lint, then inspect the diff:

```powershell
.\.venv-astra\Scripts\python.exe -m ruff check finance_lab/astra/pipeline.py tests/test_astra_pipeline.py
git diff --check
git diff --stat
```

The Ruff command above is an example for a pipeline change. Whole-repository
lint has existing findings; avoid unrelated formatting or cleanup in a feature
PR. The existing `uv.lock` predates the Astra extras; these setup instructions
use `pip` and `pyproject.toml`, not a verified locked Astra environment.

## Development Rules

- Reuse the existing agent graph. Do not replace full-agent reasoning with an
  independent indicator bot or let an LLM simulate fills/loss-limit arithmetic.
- Keep `NO TRADE` explicit. Missing or stale evidence must not become invented
  prices, neutral sentiment, or a synthetic production-data fallback.
- Retain UTC event/receipt times, provenance, and as-of filtering. Future
  outcomes and rankings cannot influence the original signal or risk gate.
- Keep decisions immutable. New execution observations belong in a separate
  review, with bounded coverage and explicit limitations.
- Preserve original research and historical Backtrader behavior. Keep fixtures
  deterministic and mock network/LLM dependencies in unit tests.
- Do not optimize on the holdout or mix development, validation, holdout,
  stressed-cost, and forward-shadow results. The baseline currently has
  development/holdout/stress splits, not a separate validation set.
- Never add broker order submission as an incidental extension. Demo execution
  needs its own reviewed scope and safety criteria; live execution is later.

## Useful Next Work

Follow the roadmap incrementally, agreeing on a small change before coding:

1. Validate read-only recording against an actual intended MT5 terminal:
   identity, timestamps, history coverage, disconnects, and restart gaps.
2. Add a verifiable economic-event calendar with publication/receipt provenance
   and missing-data behavior; RSS headlines are not a calendar substitute.
3. Extend execution parity beyond the four-hour POC, with measured costs,
   financing, gaps, partial fills, and Prague daily-loss boundaries.
4. Add forward-shadow outcome evaluation without rewriting the original
   decision or using later outcomes to authorize earlier entries.
5. Specify reconciliation, restart recovery, kill switches, and acceptance
   tests before any explicitly authorized demo-order implementation.

## Collaborate on GitHub

The repository owner must invite your GitHub account for direct write access.
Without it, fork the repository and open a pull request from your fork.
With access, start from a clean working tree:

```powershell
git switch main
git pull --ff-only origin main
git switch -c feature/short-description
# Make a focused change and run its tests.
git add path/to/changed_file.py path/to/test_file.py
git diff --cached
git commit -m "feat(astra): describe the change"
git push -u origin feature/short-description
```

Open a PR into `main` with the behavior change, exact test commands/results,
data assumptions, and remaining limitations. Never force-push shared `main`.
Do not commit `.env`, `.astra.json`, account identifiers, private datasets,
databases, prompt traces, virtual environments, or generated reports. Use
redacted errors and small synthetic fixtures for bug reports.
