"""Local Ollama adapter. Talks to localhost:11434 over plain HTTP via urllib
(no extra dependency). Always BASIC tier."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from providers.base import Provider, ProviderError, ProviderInfo, estimate_tier

_BASE_URL = "http://localhost:11434"
_GENERATE_TIMEOUT = 300
_PROBE_TIMEOUT = 2


def _http_post(url: str, payload: dict, timeout: int) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _http_get(url: str, timeout: int) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read())


def list_local_models() -> list[str]:
    """Models the user has pulled. Empty list if Ollama is not running."""
    try:
        data = _http_get(f"{_BASE_URL}/api/tags", _PROBE_TIMEOUT)
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return []
    return [m["name"] for m in data.get("models", [])]


class OllamaProvider(Provider):
    def __init__(self, *, model: str | None, timeout: int = _GENERATE_TIMEOUT):
        self.model = model
        self.timeout = timeout
        tier, verified = estimate_tier(model, "local")
        self.info = ProviderInfo(
            name="ollama",
            display_name="Ollama (local model)",
            kind="local",
            available=True,
            detail=f"local model: {model}",
            tier=tier,
            model=model,
            tier_verified=verified,
        )

    def generate(self, prompt: str) -> str:
        payload = {"model": self.model, "prompt": prompt, "stream": False}
        try:
            data = _http_post(f"{_BASE_URL}/api/generate", payload, self.timeout)
        except (urllib.error.URLError, OSError) as exc:
            raise ProviderError(
                f"Ollama request failed ({exc}). Start Ollama, or `ollama pull {self.model}`."
            ) from exc
        text = (data.get("response") or "").strip()
        if not text:
            raise ProviderError("Ollama returned an empty response.")
        return text
