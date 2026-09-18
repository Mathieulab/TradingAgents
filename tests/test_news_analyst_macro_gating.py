import importlib.util
import sys
import types
from pathlib import Path


def _load_news_analyst(monkeypatch, *, macro_available: bool):
    fake_prompts = types.ModuleType("langchain_core.prompts")
    fake_agent_utils = types.ModuleType("tradingagents.agents.utils.agent_utils")
    fake_macro_tools = types.ModuleType("tradingagents.agents.utils.macro_data_tools")

    class ChatPromptTemplate:
        @classmethod
        def from_messages(cls, messages):
            return cls()

    class MessagesPlaceholder:
        def __init__(self, variable_name):
            self.variable_name = variable_name

    def make_tool(name):
        return types.SimpleNamespace(name=name)

    fake_prompts.ChatPromptTemplate = ChatPromptTemplate
    fake_prompts.MessagesPlaceholder = MessagesPlaceholder
    fake_agent_utils.get_news = make_tool("get_news")
    fake_agent_utils.get_global_news = make_tool("get_global_news")
    fake_agent_utils.get_macro_indicators = make_tool("get_macro_indicators")
    fake_agent_utils.get_prediction_markets = make_tool("get_prediction_markets")
    fake_agent_utils.get_instrument_context_from_state = lambda state: "Instrument context"
    fake_agent_utils.get_language_instruction = lambda: ""
    fake_macro_tools.macro_indicators_available = lambda: macro_available

    monkeypatch.setitem(sys.modules, "langchain_core.prompts", fake_prompts)
    monkeypatch.setitem(sys.modules, "tradingagents.agents.utils.agent_utils", fake_agent_utils)
    monkeypatch.setitem(
        sys.modules,
        "tradingagents.agents.utils.macro_data_tools",
        fake_macro_tools,
    )

    module_path = (
        Path(__file__).resolve().parents[1]
        / "tradingagents"
        / "agents"
        / "analysts"
        / "news_analyst.py"
    )
    spec = importlib.util.spec_from_file_location("_news_analyst_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_news_analyst_omits_macro_tool_when_fred_key_missing(monkeypatch):
    module = _load_news_analyst(monkeypatch, macro_available=False)

    tools = module.get_news_analyst_tools()
    instruction = module.get_news_tool_instruction("company")

    assert [tool.name for tool in tools] == [
        "get_news",
        "get_global_news",
        "get_prediction_markets",
    ]
    assert "do not call get_macro_indicators" in instruction


def test_news_analyst_includes_macro_tool_when_fred_key_exists(monkeypatch):
    module = _load_news_analyst(monkeypatch, macro_available=True)

    tools = module.get_news_analyst_tools()
    instruction = module.get_news_tool_instruction("company")

    assert [tool.name for tool in tools] == [
        "get_news",
        "get_global_news",
        "get_macro_indicators",
        "get_prediction_markets",
    ]
    assert "actual data from FRED" in instruction
