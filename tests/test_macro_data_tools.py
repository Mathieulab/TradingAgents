import importlib
import importlib.util
import sys
import types
from pathlib import Path


def _load_macro_tools_without_optional_deps(monkeypatch, route_to_vendor):
    fake_langchain_core = types.ModuleType("langchain_core")
    fake_tools = types.ModuleType("langchain_core.tools")
    fake_errors = types.ModuleType("tradingagents.dataflows.errors")
    fake_interface = types.ModuleType("tradingagents.dataflows.interface")

    class VendorNotConfiguredError(ValueError):
        pass

    def tool(func=None, *args, **kwargs):
        if func is None:
            return lambda wrapped: wrapped
        return func

    fake_tools.tool = tool
    fake_errors.VendorNotConfiguredError = VendorNotConfiguredError
    fake_interface.route_to_vendor = route_to_vendor
    monkeypatch.setitem(sys.modules, "langchain_core", fake_langchain_core)
    monkeypatch.setitem(sys.modules, "langchain_core.tools", fake_tools)
    monkeypatch.setitem(sys.modules, "tradingagents.dataflows.errors", fake_errors)
    monkeypatch.setitem(sys.modules, "tradingagents.dataflows.interface", fake_interface)

    module_path = (
        Path(__file__).resolve().parents[1]
        / "tradingagents"
        / "agents"
        / "utils"
        / "macro_data_tools.py"
    )
    spec = importlib.util.spec_from_file_location("_macro_data_tools_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_macro_tool_returns_unavailable_message_when_fred_key_missing(monkeypatch):
    module = None

    def route_to_vendor(*args, **kwargs):
        raise module.VendorNotConfiguredError("FRED_API_KEY environment variable is not set.")

    module = _load_macro_tools_without_optional_deps(monkeypatch, route_to_vendor)

    result = module.get_macro_indicators("cpi", "2026-06-01", 365)

    assert result.startswith("MACRO_DATA_UNAVAILABLE:")
    assert "FRED_API_KEY" in result
    assert "do not fabricate" in result


def test_macro_tool_still_returns_vendor_payload(monkeypatch):
    module = _load_macro_tools_without_optional_deps(
        monkeypatch,
        lambda *args, **kwargs: "MACRO_OK",
    )

    assert module.get_macro_indicators("cpi", "2026-06-01", 365) == "MACRO_OK"
