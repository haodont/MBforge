"""Provider model-list probing.

``fetch_provider_models`` queries the provider model-list API (OpenAI
``/models``, Anthropic ``/v1/models``, Ollama ``/api/tags``) so the Settings
UI can offer the real available models instead of hard-coded presets.
"""

from __future__ import annotations

import httpx

from .provider_config import provider_kind

# Probe defaults (bare endpoints, no /v1 — the probe appends its own path).
# anthropic uses the official host; ollama serves its native API on the raw
# port. openai-compatible providers are covered by provider_config's chat
# defaults but the probe strips the trailing /v1 to reuse them.
_PROBE_DEFAULT_BASE_URLS: dict[str, str] = {
    "anthropic": "https://api.anthropic.com",
    "ollama": "http://localhost:11434",
}


def _probe_url(base_url: str, path: str) -> str:
    """Join a base URL and an absolute path without double slashes."""
    return base_url.rstrip("/") + path


def fetch_provider_models(
    provider: str,
    base_url: str = "",
    api_key: str = "",
    timeout: float = 10.0,
    transport: httpx.BaseTransport | None = None,
) -> list[dict[str, str]]:
    """Query the provider model-list API and return [{value, label}, ...].

    Supported providers (case-insensitive):

    - openai_compatible / openai / deepseek: GET {base}/models with
      Authorization: Bearer.
    - anthropic: GET {base}/v1/models with x-api-key and anthropic-version
      headers.
    - ollama: GET {base}/api/tags (no auth); a trailing /v1 on the base URL
      is stripped because the OpenAI-compatible path differs.

    Raises ValueError with a user-facing message on unsupported providers,
    network failures, non-200 responses, or malformed payloads. transport
    exists only for tests (httpx.MockTransport).
    """
    kind = provider_kind(provider)  # raises ValueError for unknown providers
    headers: dict[str, str] = {}
    url: str
    model_key: str
    label_key: str | None

    if kind == "openai_compatible":
        base = base_url.strip() or "https://api.openai.com/v1"
        url = _probe_url(base, "/models")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        model_key, label_key = "id", None
    elif kind == "anthropic":
        base = base_url.strip() or _PROBE_DEFAULT_BASE_URLS["anthropic"]
        if base.rstrip("/").endswith("/v1"):
            url = _probe_url(base, "/models")
        else:
            url = _probe_url(base, "/v1/models")
        if api_key:
            headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
        model_key, label_key = "id", "display_name"
    else:  # ollama
        base = base_url.strip() or _PROBE_DEFAULT_BASE_URLS["ollama"]
        if base.rstrip("/").endswith("/v1"):
            base = base.rstrip("/")[:-3]
        url = _probe_url(base, "/api/tags")
        model_key, label_key = "name", None

    try:
        with httpx.Client(timeout=timeout, transport=transport) as client:
            resp = client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise ValueError(
            f"cannot reach model service {url}: {type(exc).__name__}"
        ) from exc

    if resp.status_code == 401 or resp.status_code == 403:
        raise ValueError(
            f"authentication failed (HTTP {resp.status_code}) - check the API key"
        )
    if resp.status_code != 200:
        raise ValueError(
            f"model service returned HTTP {resp.status_code} - check the base URL"
        )

    try:
        payload = resp.json()
    except ValueError as exc:
        raise ValueError("model service returned an invalid response") from exc

    rows: list[dict[str, str]] = []
    if kind == "openai_compatible":
        entries = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            raise ValueError("model service returned no model list")
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get(model_key), str):
                rows.append({"value": entry[model_key], "label": entry[model_key]})
    elif kind == "anthropic":
        entries = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            raise ValueError("model service returned no model list")
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get(model_key), str):
                label = entry.get(label_key) if label_key else None
                rows.append(
                    {
                        "value": entry[model_key],
                        "label": str(label) if label else entry[model_key],
                    }
                )
    else:  # ollama
        entries = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            raise ValueError("model service returned no model list")
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get(model_key), str):
                rows.append({"value": entry[model_key], "label": entry[model_key]})

    # Deduplicate (some gateways repeat ids) and sort for a stable dropdown.
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for row in rows:
        if row["value"] in seen:
            continue
        seen.add(row["value"])
        unique.append(row)
    unique.sort(key=lambda row: row["value"].lower())
    return unique
