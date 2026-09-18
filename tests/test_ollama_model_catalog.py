from tradingagents.llm_clients.model_catalog import get_model_options


def test_ollama_qwen_defaults_use_explicit_pulled_tags():
    """Avoid qwen3:latest because `ollama pull qwen3:8b` does not create that tag."""
    quick_values = [value for _, value in get_model_options("ollama", "quick")]
    deep_values = [value for _, value in get_model_options("ollama", "deep")]

    assert "qwen3:8b" in quick_values
    assert "qwen3-coder:30b-a3b-q4_K_M" in deep_values
    assert "qwen3:latest" not in quick_values
    assert "qwen3:latest" not in deep_values
