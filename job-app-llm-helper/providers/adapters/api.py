"""BYO-key API adapters: send the prompt as a single user message via the
official SDK. SDKs are optional deps — imports are loaded lazily so the app
runs without them installed; selecting an API provider without its SDK fails
cleanly with an install hint. Keys are redacted from all error messages.
"""

from __future__ import annotations

from providers.base import Provider, ProviderError, ProviderInfo, estimate_tier

_MAX_TOKENS = 4096


def _load_anthropic():
    from anthropic import Anthropic

    return Anthropic


def _load_openai():
    from openai import OpenAI

    return OpenAI


def _load_google():
    from google import genai

    return genai


def _redact(text: str, secret: str | None) -> str:
    if secret and secret in text:
        return text.replace(secret, "***REDACTED***")
    return text


class _ApiProvider(Provider):
    name: str = ""
    display_name: str = ""
    sdk_pkg: str = ""

    def __init__(self, *, api_key: str | None, model: str | None):
        self.api_key = api_key
        self.model = model
        tier, verified = estimate_tier(model, "api")
        self.info = ProviderInfo(
            name=self.name,
            display_name=self.display_name,
            kind="api",
            available=api_key is not None,
            detail="key present" if api_key else "no API key configured",
            tier=tier,
            model=model,
            tier_verified=verified,
        )

    def _require_key(self) -> str:
        if not self.api_key:
            raise ProviderError(
                f"{self.display_name}: no API key. Enter a key or pick another provider."
            )
        return self.api_key

    def generate(self, prompt: str) -> str:
        self._require_key()
        try:
            return self._call(prompt)
        except ProviderError:
            raise
        except ImportError:
            raise ProviderError(
                f"{self.display_name} needs its SDK. Run: pip install {self.sdk_pkg}"
            ) from None
        except Exception as exc:
            raise ProviderError(
                f"{self.display_name} request failed: {_redact(str(exc), self.api_key)}"
            ) from exc

    def _call(self, prompt: str) -> str:  # pragma: no cover - overridden
        raise NotImplementedError


class AnthropicApi(_ApiProvider):
    name = "anthropic_api"
    display_name = "Anthropic (API key)"
    sdk_pkg = "anthropic"

    def _call(self, prompt: str) -> str:
        Anthropic = _load_anthropic()
        client = Anthropic(api_key=self.api_key)
        resp = client.messages.create(
            model=self.model,
            max_tokens=_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()


class OpenAiApi(_ApiProvider):
    name = "openai_api"
    display_name = "OpenAI (API key)"
    sdk_pkg = "openai"

    def _call(self, prompt: str) -> str:
        OpenAI = _load_openai()
        client = OpenAI(api_key=self.api_key)
        resp = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content.strip()


class GoogleApi(_ApiProvider):
    name = "google_api"
    display_name = "Google Gemini (API key)"
    sdk_pkg = "google-genai"

    def _call(self, prompt: str) -> str:
        genai = _load_google()
        client = genai.Client(api_key=self.api_key)
        resp = client.models.generate_content(model=self.model, contents=prompt)
        return resp.text.strip()
