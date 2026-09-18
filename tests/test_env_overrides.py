"""Tests for TRADINGAGENTS_* env-var overlay onto DEFAULT_CONFIG."""

from __future__ import annotations

import importlib

import pytest

import tradingagents.default_config as default_config_module


def _reload_with_env(monkeypatch, **overrides):
    """Set/clear env vars then reload default_config to re-evaluate DEFAULT_CONFIG."""
    for key in list(default_config_module._ENV_OVERRIDES):
        monkeypatch.delenv(key, raising=False)
    for key, val in overrides.items():
        monkeypatch.setenv(key, val)
    return importlib.reload(default_config_module)


def test_no_env_uses_built_in_defaults(monkeypatch):
    dc = _reload_with_env(monkeypatch)
    assert dc.DEFAULT_CONFIG["llm_provider"] == "openai"
    assert dc.DEFAULT_CONFIG["deep_think_llm"] == "gpt-5.5"
    assert dc.DEFAULT_CONFIG["quick_think_llm"] == "gpt-5.4-mini"
    assert dc.DEFAULT_CONFIG["backend_url"] is None
    assert dc.DEFAULT_CONFIG["max_debate_rounds"] == 1
    assert dc.DEFAULT_CONFIG["checkpoint_enabled"] is False


def test_string_overrides(monkeypatch):
    dc = _reload_with_env(
        monkeypatch,
        TRADINGAGENTS_LLM_PROVIDER="google",
        TRADINGAGENTS_DEEP_THINK_LLM="gemini-3-pro-preview",
        TRADINGAGENTS_QUICK_THINK_LLM="gemini-3-flash-preview",
        TRADINGAGENTS_LLM_BACKEND_URL="https://example.invalid/v1",
        TRADINGAGENTS_OUTPUT_LANGUAGE="Chinese",
    )
    assert dc.DEFAULT_CONFIG["llm_provider"] == "google"
    assert dc.DEFAULT_CONFIG["deep_think_llm"] == "gemini-3-pro-preview"
    assert dc.DEFAULT_CONFIG["quick_think_llm"] == "gemini-3-flash-preview"
    assert dc.DEFAULT_CONFIG["backend_url"] == "https://example.invalid/v1"
    assert dc.DEFAULT_CONFIG["output_language"] == "Chinese"


def test_int_coercion(monkeypatch):
    dc = _reload_with_env(
        monkeypatch,
        TRADINGAGENTS_MAX_DEBATE_ROUNDS="3",
        TRADINGAGENTS_MAX_RISK_ROUNDS="2",
    )
    assert dc.DEFAULT_CONFIG["max_debate_rounds"] == 3
    assert isinstance(dc.DEFAULT_CONFIG["max_debate_rounds"], int)
    assert dc.DEFAULT_CONFIG["max_risk_discuss_rounds"] == 2
    assert isinstance(dc.DEFAULT_CONFIG["max_risk_discuss_rounds"], int)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("true", True), ("True", True), ("1", True), ("yes", True), ("on", True),
        ("false", False), ("False", False), ("0", False), ("no", False), ("off", False),
    ],
)
def test_bool_coercion(monkeypatch, raw, expected):
    dc = _reload_with_env(monkeypatch, TRADINGAGENTS_CHECKPOINT_ENABLED=raw)
    assert dc.DEFAULT_CONFIG["checkpoint_enabled"] is expected


def test_empty_env_value_is_passthrough(monkeypatch):
    """Empty TRADINGAGENTS_* values must not clobber the built-in default."""
    dc = _reload_with_env(
        monkeypatch,
        TRADINGAGENTS_LLM_PROVIDER="",
        TRADINGAGENTS_MAX_DEBATE_ROUNDS="",
    )
    assert dc.DEFAULT_CONFIG["llm_provider"] == "openai"
    assert dc.DEFAULT_CONFIG["max_debate_rounds"] == 1


def test_invalid_int_raises(monkeypatch):
    """Garbage int values should surface a ValueError at import, not silently misconfigure."""
    monkeypatch.setenv("TRADINGAGENTS_MAX_DEBATE_ROUNDS", "not-a-number")
    with pytest.raises(ValueError):
        importlib.reload(default_config_module)
    # Restore module state for subsequent tests in this process
    monkeypatch.delenv("TRADINGAGENTS_MAX_DEBATE_ROUNDS", raising=False)
    importlib.reload(default_config_module)


def test_unknown_env_var_is_ignored(monkeypatch):
    """Env vars outside _ENV_OVERRIDES must not bleed into DEFAULT_CONFIG."""
    dc = _reload_with_env(
        monkeypatch,
        TRADINGAGENTS_NONEXISTENT_KEY="oops",
    )
    assert "nonexistent_key" not in dc.DEFAULT_CONFIG


def test_finance_backtest_env_overrides(monkeypatch):
    dc = _reload_with_env(
        monkeypatch,
        TRADINGAGENTS_FINANCE_BACKTEST_ENABLED="true",
        TRADINGAGENTS_FINANCE_BACKTEST_MODE="decision_replay",
        TRADINGAGENTS_FINANCE_BACKTEST_BACKEND="nautilus",
        TRADINGAGENTS_FINANCE_BACKTEST_STRATEGY="ema_cross",
        TRADINGAGENTS_FINANCE_BACKTEST_BENCHMARK="QQQ",
        TRADINGAGENTS_FINANCE_BACKTEST_HORIZONS="5,20",
        TRADINGAGENTS_FINANCE_BACKTEST_LOOKBACK_DAYS="90",
        TRADINGAGENTS_FINANCE_BACKTEST_INITIAL_CASH="25000.5",
        TRADINGAGENTS_FINANCE_BACKTEST_FAST_PERIOD="5",
        TRADINGAGENTS_FINANCE_BACKTEST_SLOW_PERIOD="20",
        TRADINGAGENTS_FINANCE_BACKTEST_FEE_BPS="1.5",
        TRADINGAGENTS_FINANCE_BACKTEST_SLIPPAGE_BPS="2.5",
    )

    assert dc.DEFAULT_CONFIG["finance_backtest_enabled"] is True
    assert dc.DEFAULT_CONFIG["finance_backtest_mode"] == "decision_replay"
    assert dc.DEFAULT_CONFIG["finance_backtest_backend"] == "nautilus"
    assert dc.DEFAULT_CONFIG["finance_backtest_strategy"] == "ema_cross"
    assert dc.DEFAULT_CONFIG["finance_backtest_benchmark"] == "QQQ"
    assert dc.DEFAULT_CONFIG["finance_backtest_horizons"] == "5,20"
    assert dc.DEFAULT_CONFIG["finance_backtest_lookback_days"] == 90
    assert dc.DEFAULT_CONFIG["finance_backtest_initial_cash"] == 25000.5
    assert dc.DEFAULT_CONFIG["finance_backtest_fast_period"] == 5
    assert dc.DEFAULT_CONFIG["finance_backtest_slow_period"] == 20
    assert dc.DEFAULT_CONFIG["finance_backtest_fee_bps"] == 1.5
    assert dc.DEFAULT_CONFIG["finance_backtest_slippage_bps"] == 2.5
