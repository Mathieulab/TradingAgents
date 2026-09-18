# Mathieu TradingAgents Test Plan

This plan is for the current first-pass state: core TradingAgents plus a docs-only `finance_lab/` scaffold.

## Current Verification Result

Attempted on 2026-06-16:

```powershell
python -m cli.main
```

Initial result: the entrypoint was found, but the Python environment was missing installed dependencies:

```text
ModuleNotFoundError: No module named 'langchain_core'
```

Resolution: installed project requirements with:

```powershell
python -m pip install -r requirements.txt
```

Follow-up verification:

```powershell
python -m cli.main --help
```

Result: success. The bare interactive command no longer crashes on imports; it stays open waiting for user input.

## 1. Install Locally

From PowerShell:

```powershell
cd C:\Users\mathi\MyTradingAgents\TradingAgents
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .[dev]
```

For optional Bedrock support:

```powershell
python -m pip install -e .[dev,bedrock]
```

## 2. Run CLI

Interactive source entrypoint:

```powershell
python -m cli.main
```

Installed command after `pip install -e .`:

```powershell
tradingagents
```

Example local Ollama environment:

```powershell
$env:TRADINGAGENTS_LLM_PROVIDER = "ollama"
$env:TRADINGAGENTS_LLM_BACKEND_URL = "http://localhost:11434/v1"
$env:TRADINGAGENTS_DEEP_THINK_LLM = "qwen3-coder:30b-a3b-q4_K_M"
$env:TRADINGAGENTS_QUICK_THINK_LLM = "qwen3:8b"
$env:TRADINGAGENTS_TEMPERATURE = "0.0"
python -m cli.main
```

## 3. Run Tests

Full pytest suite:

```powershell
python -m pytest
```

Focused examples:

```powershell
python -m pytest tests\test_memory_log.py
python -m pytest tests\test_ollama_base_url.py
python -m pytest tests\test_openai_compatible_provider.py
```

Lint if ruff is installed:

```powershell
python -m ruff check .
```

## 4. Run Finance Lab Examples

The current `finance_lab/` content is a scaffold and configuration plan. It does not yet include runnable backtesting, reporting, or fake-trader code.

Inspect the example config:

```powershell
Get-Content .\finance_lab\config\finance_lab.example.yaml
```

Create a private local copy when needed:

```powershell
Copy-Item .\finance_lab\config\finance_lab.local.yaml.example .\finance_lab\config\finance_lab.local.yaml
```

Do not commit `finance_lab.local.yaml` if it later contains secrets or private paths.

## 5. Generate A Report

Current core project report path:

1. Run `python -m cli.main`.
2. Complete the interactive analysis.
3. Choose `Y` when prompted to save the report.

Future finance-lab report command target:

```powershell
python -m finance_lab.reports.report_generator --input <analysis-json> --output .\finance_lab\reports\out
```

That command is not implemented yet.

## 6. Run A Fake Trader Simulation

Future target command:

```powershell
python -m finance_lab.fake_trading.fake_trader --config .\finance_lab\config\finance_lab.local.yaml
```

That command is not implemented yet. The schema and docs are prepared so the next task can add code and tests without touching core TradingAgents behavior.
