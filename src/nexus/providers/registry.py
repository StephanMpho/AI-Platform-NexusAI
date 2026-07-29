"""Provider registry.

Only providers with credentials are loaded. `mock` is always present, which is
what lets the test suite and a fresh clone exercise the full path offline.
"""

from __future__ import annotations

from functools import lru_cache

from nexus.config import Settings, get_settings
from nexus.providers.base import LLMProvider
from nexus.providers.mock import MockProvider


class ProviderRegistry:
    def __init__(self, settings: Settings) -> None:
        self._providers: dict[str, LLMProvider] = {"mock": MockProvider()}
        self._load(settings)

    def _load(self, settings: Settings) -> None:
        creds = settings.providers

        if creds.openai_api_key:
            from nexus.providers.openai import OpenAIProvider

            self._providers["openai"] = OpenAIProvider(creds.openai_api_key.get_secret_value())

        if creds.anthropic_api_key:
            from nexus.providers.anthropic import AnthropicProvider

            self._providers["anthropic"] = AnthropicProvider(
                creds.anthropic_api_key.get_secret_value()
            )

        # TODO(GW-001): azure_openai, and self-hosted via an OpenAI-compatible URL

    def get(self, slug: str) -> LLMProvider:
        try:
            return self._providers[slug]
        except KeyError:
            raise KeyError(
                f"provider '{slug}' is not configured. Available: {sorted(self._providers)}"
            ) from None

    def available(self) -> list[str]:
        return sorted(self._providers)


@lru_cache
def get_registry() -> ProviderRegistry:
    return ProviderRegistry(get_settings())
