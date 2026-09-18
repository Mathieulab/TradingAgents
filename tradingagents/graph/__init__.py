"""Lazy public exports for graph helpers."""

from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "TradingAgentsGraph": ".trading_graph",
    "ConditionalLogic": ".conditional_logic",
    "GraphSetup": ".setup",
    "Propagator": ".propagation",
    "Reflector": ".reflection",
    "SignalProcessor": ".signal_processing",
}

__all__ = [
    "TradingAgentsGraph",
    "ConditionalLogic",
    "GraphSetup",
    "Propagator",
    "Reflector",
    "SignalProcessor",
]


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(_EXPORTS[name], __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
