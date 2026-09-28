"""Discover account model IDs and browse a public catalog without credentials.

Cloud provider URLs are fixed. Ollama discovery accepts only the API server's
standard loopback listener, so user config cannot turn this into a proxy.
"""
from __future__ import annotations

from functools import lru_cache
import time
from urllib.parse import urlsplit

import requests


_MODEL_URLS = {
    "openai": "https://api.openai.com/v1/models",
    "openrouter": "https://openrouter.ai/api/v1/models",
    "deepseek": "https://api.deepseek.com/v1/models",
    "mistral": "https://api.mistral.ai/v1/models",
    "nim": "https://integrate.api.nvidia.com/v1/models",
    "groq": "https://api.groq.com/openai/v1/models",
    "claude": "https://api.anthropic.com/v1/models",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models",
}

_CATALOG_PROVIDERS = {
    "openai": "openai", "claude": "anthropic", "gemini": "google",
    "deepseek": "deepseek", "mistral": "mistral", "nim": "nvidia",
    "groq": "groq", "cloudflare": "cloudflare-workers-ai", "openrouter": "openrouter",
}


@lru_cache(maxsize=1)
def _public_catalog(_time_bucket: int) -> dict:
    # This shared cache contains public metadata only. Never send user keys to
    # the catalog, and never cache an account-specific model list here.
    response = requests.get(
        "https://models.dev/api.json", headers={}, params={},
        timeout=10, allow_redirects=False,
    )
    response.raise_for_status()
    if response.status_code >= 300:
        raise ValueError("Public model catalog redirected the request")
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Public model catalog returned invalid data")
    return payload


def public_models(name: str) -> list[str]:
    """Native provider IDs for text models; account access still needs testing."""
    catalog = _public_catalog(int(time.monotonic() // 900))
    provider = catalog.get(_CATALOG_PROVIDERS[name])
    if not isinstance(provider, dict) or not isinstance(provider.get("models"), dict):
        raise ValueError("Public model catalog does not include this provider")
    models = set()
    for model in provider["models"].values():
        if not isinstance(model, dict):
            continue
        modalities = model.get("modalities") or {}
        if (not isinstance(modalities, dict) or not isinstance(modalities.get("input"), list)
                or "text" not in modalities["input"]
                or modalities.get("output") != ["text"]
                or model.get("status") == "deprecated"):
            continue
        model_id = model.get("id")
        if (isinstance(model_id, str) and 0 < len(model_id) <= 200
                and not any(ch.isspace() or ord(ch) < 32 for ch in model_id)):
            models.add(model_id)
    return sorted(models, key=str.casefold)


def discover_models(name: str, key: str, *, account_id: str = "", base_url: str = "") -> list[str]:
    """Return the model IDs a provider currently advertises for this key."""
    if name == "ollama":
        # Only the API server's standard local Ollama listener is reachable
        # here. Arbitrary config URLs must never become a server-side proxy.
        parsed = urlsplit(base_url or "http://localhost:11434")
        if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
                or parsed.port != 11434 or parsed.username or parsed.password
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
            raise ValueError("Ollama model discovery requires localhost:11434")
        url = f"{parsed.scheme}://{parsed.netloc}/api/tags"
    elif name == "cloudflare":
        if not account_id:
            raise ValueError("Cloudflare account ID is required to load models")
        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/models/search"
    else:
        url = _MODEL_URLS[name]

    headers = {} if name == "ollama" else {"Authorization": f"Bearer {key}"}
    if name == "claude":
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    elif name == "gemini":
        headers = {"x-goog-api-key": key}

    models: set[str] = set()
    params: dict[str, str | int] = {}
    if name == "cloudflare":
        params = {"per_page": 100}
    elif name == "claude":
        params = {"limit": 100}
    elif name == "gemini":
        params = {"pageSize": 1000}

    # Some catalogs paginate. Bound the walk so a bad response cannot keep a
    # request open indefinitely.
    deadline = time.monotonic() + 20
    for _ in range(10):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise requests.Timeout("Model discovery exceeded its time budget")
        response = requests.get(url, headers=headers, params=params, timeout=min(10, remaining), allow_redirects=False)
        response.raise_for_status()
        if response.status_code >= 300:
            raise ValueError("Provider redirected the model list request")
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Provider returned an invalid model list")
        entries = payload.get("models" if name in {"gemini", "ollama"} else
                              "result" if name == "cloudflare" else "data")
        if not isinstance(entries, list):
            raise ValueError("Provider returned an invalid model list")
        for item in entries:
            if not isinstance(item, dict):
                continue
            if name == "gemini":
                methods = item.get("supportedGenerationMethods")
                if not isinstance(methods, list) or "generateContent" not in methods:
                    continue
            model = item.get("name" if name in {"gemini", "cloudflare", "ollama"} else "id")
            if isinstance(model, str) and model.strip():
                if name == "gemini" and model.startswith("models/"):
                    model = model.removeprefix("models/")
                models.add(model)
        if name == "gemini" and payload.get("nextPageToken"):
            cursor = payload["nextPageToken"]
            if not isinstance(cursor, str) or cursor == params.get("pageToken"):
                raise ValueError("Provider returned an invalid pagination cursor")
            params["pageToken"] = cursor
        elif name == "claude" and payload.get("has_more"):
            cursor = payload.get("last_id")
            if not isinstance(cursor, str) or not cursor or cursor == params.get("after_id"):
                raise ValueError("Provider returned an invalid pagination cursor")
            params["after_id"] = cursor
        elif name == "cloudflare" and isinstance(payload.get("result_info"), dict):
            total_pages = payload["result_info"].get("total_pages", 1)
            if not isinstance(total_pages, int) or total_pages < 1:
                raise ValueError("Provider returned invalid pagination data")
            if total_pages <= params.get("page", 1):
                break
            params["page"] = params.get("page", 1) + 1
        else:
            break
    return sorted(models, key=str.casefold)
