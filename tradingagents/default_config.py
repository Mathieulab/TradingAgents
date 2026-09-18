import os

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".tradingagents")

# Single source of truth for env-var â†’ config-key overrides. To expose
# a new config key for environment-based override, add a row here â€” no
# entry-point script changes required. Coercion is driven by the type
# of the existing default, so users can keep writing plain strings in
# their .env file.
_ENV_OVERRIDES = {
    "TRADINGAGENTS_LLM_PROVIDER":         "llm_provider",
    "TRADINGAGENTS_DEEP_THINK_LLM":       "deep_think_llm",
    "TRADINGAGENTS_QUICK_THINK_LLM":      "quick_think_llm",
    "TRADINGAGENTS_LLM_BACKEND_URL":      "backend_url",
    "TRADINGAGENTS_OUTPUT_LANGUAGE":      "output_language",
    "TRADINGAGENTS_MAX_DEBATE_ROUNDS":    "max_debate_rounds",
    "TRADINGAGENTS_MAX_RISK_ROUNDS":      "max_risk_discuss_rounds",
    "TRADINGAGENTS_CHECKPOINT_ENABLED":   "checkpoint_enabled",
    "TRADINGAGENTS_BENCHMARK_TICKER":     "benchmark_ticker",
    "TRADINGAGENTS_TEMPERATURE":          "temperature",
    "TRADINGAGENTS_FINANCE_MCP_ENABLED":  "finance_mcp_enabled",
    "TRADINGAGENTS_FINANCE_MCP_URL":      "finance_mcp_url",
    "TRADINGAGENTS_FINANCE_MEMORY_ENABLED": "finance_memory_enabled",
    "TRADINGAGENTS_FINANCE_MEMORY_PATH":  "finance_memory_path",
    "TRADINGAGENTS_FINANCE_BACKTEST_ENABLED": "finance_backtest_enabled",
    "TRADINGAGENTS_FINANCE_BACKTEST_MODE": "finance_backtest_mode",
    "TRADINGAGENTS_FINANCE_BACKTEST_BACKEND": "finance_backtest_backend",
    "TRADINGAGENTS_FINANCE_BACKTEST_STRATEGY": "finance_backtest_strategy",
    "TRADINGAGENTS_FINANCE_BACKTEST_BENCHMARK": "finance_backtest_benchmark",
    "TRADINGAGENTS_FINANCE_BACKTEST_HORIZONS": "finance_backtest_horizons",
    "TRADINGAGENTS_FINANCE_BACKTEST_LOOKBACK_DAYS": "finance_backtest_lookback_days",
    "TRADINGAGENTS_FINANCE_BACKTEST_INITIAL_CASH": "finance_backtest_initial_cash",
    "TRADINGAGENTS_FINANCE_BACKTEST_FAST_PERIOD": "finance_backtest_fast_period",
    "TRADINGAGENTS_FINANCE_BACKTEST_SLOW_PERIOD": "finance_backtest_slow_period",
    "TRADINGAGENTS_FINANCE_BACKTEST_FEE_BPS": "finance_backtest_fee_bps",
    "TRADINGAGENTS_FINANCE_BACKTEST_SLIPPAGE_BPS": "finance_backtest_slippage_bps",
    "TRADINGAGENTS_CHART_OUTPUT_DIR":     "chart_output_dir",
    "TRADINGAGENTS_STRICT_AS_OF_DATE":     "strict_as_of_date",
}


def _coerce(value: str, reference):
    """Coerce env-var string to the type of the existing default value."""
    if isinstance(reference, bool):
        return value.strip().lower() in ("true", "1", "yes", "on")
    if isinstance(reference, int) and not isinstance(reference, bool):
        return int(value)
    if isinstance(reference, float):
        return float(value)
    return value


def _apply_env_overrides(config: dict) -> dict:
    """Apply TRADINGAGENTS_* env vars to the config dict in-place."""
    for env_var, key in _ENV_OVERRIDES.items():
        raw = os.environ.get(env_var)
        if raw is None or raw == "":
            continue
        config[key] = _coerce(raw, config.get(key))
    return config


DEFAULT_CONFIG = _apply_env_overrides({
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", os.path.join(_TRADINGAGENTS_HOME, "logs")),
    "data_cache_dir": os.getenv("TRADINGAGENTS_CACHE_DIR", os.path.join(_TRADINGAGENTS_HOME, "cache")),
    "memory_log_path": os.getenv("TRADINGAGENTS_MEMORY_LOG_PATH", os.path.join(_TRADINGAGENTS_HOME, "memory", "trading_memory.md")),
    "finance_memory_path": os.path.join(_TRADINGAGENTS_HOME, "finance", "finance_memory.db"),
    "chart_output_dir": os.path.join(_TRADINGAGENTS_HOME, "charts"),
    # Optional cap on the number of resolved memory log entries. When set,
    # the oldest resolved entries are pruned once this limit is exceeded.
    # Pending entries are never pruned. None disables rotation entirely.
    "memory_log_max_entries": None,
    # LLM settings
    "llm_provider": "openai",
    "deep_think_llm": "gpt-5.5",
    "quick_think_llm": "gpt-5.4-mini",
    # When None, each provider's client falls back to its own default endpoint
    # (api.openai.com for OpenAI, generativelanguage.googleapis.com for Gemini, ...).
    # The CLI overrides this per provider when the user picks one. Keeping a
    # provider-specific URL here would leak (e.g. OpenAI's /v1 was previously
    # being forwarded to Gemini, producing malformed request URLs).
    "backend_url": None,
    # Provider-specific thinking configuration
    "google_thinking_level": None,      # "high", "minimal", etc.
    "openai_reasoning_effort": None,    # "medium", "high", "low"
    "anthropic_effort": None,           # "high", "medium", "low"
    # Sampling temperature, forwarded to every provider when set. None leaves
    # each provider at its own default. Lower values reduce run-to-run
    # variation on models that honor it; reasoning models largely ignore it
    # and no setting makes LLM output bit-identical across runs (see README).
    "temperature": None,
    # Checkpoint/resume: when True, LangGraph saves state after each node
    # so a crashed run can resume from the last successful step.
    "checkpoint_enabled": False,
    # Finance Lab research memory and replay are on by default; MCP is opt-in.
    "finance_mcp_enabled": False,
    "finance_mcp_url": "http://localhost:8765",
    "finance_memory_enabled": True,
    "finance_backtest_enabled": True,
    "finance_backtest_mode": "decision_replay",
    "finance_backtest_backend": "simple",
    "finance_backtest_strategy": "buy_and_hold",
    "finance_backtest_benchmark": "QQQ",
    "finance_backtest_horizons": "1,2,5,10,20,60,120",
    "finance_backtest_lookback_days": 365,
    "finance_backtest_initial_cash": 10000.0,
    "finance_backtest_fast_period": 12,
    "finance_backtest_slow_period": 26,
    "finance_backtest_fee_bps": 0.0,
    "finance_backtest_slippage_bps": 0.0,
    "analysis_as_of_date": None,
    "strict_as_of_date": True,
    # Output language for analyst reports and final decision
    # Internal agent debate stays in English for reasoning quality
    "output_language": "English",
    # Debate and discussion settings
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    "analyst_concurrency_limit": 1,
    # News / data fetching parameters
    # Increase for longer lookback strategies or to broaden macro coverage;
    # decrease to reduce token usage in agent prompts.
    "news_article_limit": 20,             # max articles per ticker (ticker-news)
    "global_news_article_limit": 10,      # max articles for global/macro news
    "global_news_lookback_days": 7,       # macro news lookback window
    # Search queries used by get_global_news for macro headlines. Extend or
    # replace to broaden geographic / sector coverage.
    "global_news_queries": [
        "Federal Reserve interest rates inflation",
        "S&P 500 earnings GDP economic outlook",
        "geopolitical risk trade war sanctions",
        "ECB Bank of England BOJ central bank policy",
        "oil commodities supply chain energy",
    ],
    # Data vendor configuration
    # Category-level configuration (default for all tools in category).
    # The configured value is the exact vendor chain â€” requests are NOT silently
    # routed to vendors you didn't choose. For ordered fallback, list several,
    # e.g. "yfinance,alpha_vantage". "default" uses all available vendors.
    "data_vendors": {
        "core_stock_apis": "yfinance",       # Options: alpha_vantage, yfinance
        "technical_indicators": "yfinance",  # Options: alpha_vantage, yfinance
        "fundamental_data": "yfinance",      # Options: alpha_vantage, yfinance
        "news_data": "yfinance",             # Options: alpha_vantage, yfinance
        "macro_data": "fred",                # Options: fred (needs FRED_API_KEY)
        "prediction_markets": "polymarket",  # Options: polymarket (keyless)
    },
    # Tool-level configuration (takes precedence over category-level)
    "tool_vendors": {
        # Example: "get_stock_data": "alpha_vantage",  # Override category default
    },
    # Benchmark for alpha calculation in the reflection layer.
    # ``benchmark_ticker`` (when set) overrides the suffix map for all
    # tickers; leave it None to use ``benchmark_map`` for auto-detection
    # based on the ticker's exchange suffix. SPY remains the US default
    # so the reflection label keeps reading "Alpha vs SPY" for US tickers
    # while non-US tickers get their regional index automatically.
    "benchmark_ticker": None,
    "benchmark_map": {
        ".NS":  "^NSEI",       # NSE India (Nifty 50)
        ".BO":  "^BSESN",      # BSE India (Sensex)
        ".T":   "^N225",       # Tokyo (Nikkei 225)
        ".HK":  "^HSI",        # Hong Kong (Hang Seng)
        ".L":   "^FTSE",       # London (FTSE 100)
        ".TO":  "^GSPTSE",     # Toronto (TSX Composite)
        ".AX":  "^AXJO",       # Australia (ASX 200)
        ".SS":  "000001.SS",   # Shanghai (SSE Composite)
        ".SZ":  "399001.SZ",   # Shenzhen (SZSE Component)
        "":     "SPY",         # default for US-listed tickers (no suffix)
    },
})
