"""Discover exact model IDs from the selected local inference server."""

import os
from urllib.parse import urlsplit, urlunsplit

import requests


def validate_endpoint(value):
    value = value.strip()
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or "\\" in value
        or any(c.isspace() for c in value)
    ):
        raise ValueError("Use a server URL, e.g. http://localhost:11434/v1, not a model folder")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Use a base URL without credentials, query parameters or fragments")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("The server URL contains an invalid port") from exc
    if port == 0:
        raise ValueError("The server URL contains an invalid port")
    return value.rstrip("/")


def local_endpoint(provider, value):
    value = validate_endpoint(value)
    parsed = urlsplit(value)
    if provider in {"ollama", "openai_compatible"} and parsed.path in {"", "/"}:
        return urlunsplit((parsed.scheme, parsed.netloc, "/v1", "", ""))
    return value


def prompt_local_endpoint(provider, default):
    import questionary

    def valid(value):
        try:
            validate_endpoint(value)
            return True
        except ValueError as exc:
            return str(exc)

    value = questionary.text(
        "Model server URL (HTTP address, not the model folder):",
        default=default,
        validate=valid,
    ).ask()
    if value is None:
        raise KeyboardInterrupt
    return local_endpoint(provider, value)


def discover_models(provider, endpoint):
    """Return installed/served IDs, annotating currently loaded Ollama models."""
    endpoint = local_endpoint(provider, endpoint)
    headers = {}
    if provider == "ollama":
        root = endpoint.removesuffix("/v1")
        response = requests.get(root + "/api/tags", timeout=4, allow_redirects=False)
        response.raise_for_status()
        payload = response.json()
        models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(models, list):
            raise ValueError("Ollama did not return a model list")
        loaded = set()
        try:
            running = requests.get(root + "/api/ps", timeout=2, allow_redirects=False)
            running.raise_for_status()
            running_payload = running.json()
            running_models = (
                running_payload.get("models", []) if isinstance(running_payload, dict) else []
            )
            loaded = {
                m["name"]
                for m in running_models
                if isinstance(m, dict) and isinstance(m.get("name"), str)
            }
        except (requests.RequestException, ValueError, TypeError):
            pass
        ids = sorted(
            {
                m["name"]
                for m in models
                if isinstance(m, dict) and isinstance(m.get("name"), str) and m["name"]
            }
        )
        return [(name + (" [running]" if name in loaded else " [installed]"), name) for name in ids]
    if provider == "openai_compatible":
        key = os.environ.get("OPENAI_COMPATIBLE_API_KEY")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        response = requests.get(
            endpoint + "/models", headers=headers, timeout=4, allow_redirects=False
        )
        response.raise_for_status()
        payload = response.json()
        models = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(models, list):
            raise ValueError("The endpoint did not return an OpenAI-compatible model list")
        ids = sorted(
            {
                m["id"]
                for m in models
                if isinstance(m, dict) and isinstance(m.get("id"), str) and m["id"]
            }
        )
        return [(name + " [served]", name) for name in ids]
    return []
