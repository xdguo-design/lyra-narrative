from __future__ import annotations

from collections.abc import Callable

from .anthropic import AnthropicProvider
from .base import BaseProvider, ProviderConfig, ProviderError
from .gemini import GeminiProvider
from .ollama import OllamaProvider
from .openai_compatible import OpenAICompatibleProvider

ProviderFactory = Callable[[ProviderConfig], BaseProvider]


class ProviderRegistry:
    """Registry keeps agents independent from vendor SDKs and endpoints."""

    def __init__(self) -> None:
        self._factories: dict[str, ProviderFactory] = {}

    def register(self, kind: str, factory: ProviderFactory) -> None:
        self._factories[kind.strip().lower()] = factory

    def create(self, config: ProviderConfig) -> BaseProvider:
        kind = config.kind.strip().lower()
        try:
            factory = self._factories[kind]
        except KeyError as exc:
            raise ProviderError(
                f"unknown provider kind: {config.kind}",
                provider=config.name,
            ) from exc
        return factory(config)

    @property
    def kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))


DEFAULT_REGISTRY = ProviderRegistry()

# Native/direct adapters.
DEFAULT_REGISTRY.register("gemini", GeminiProvider)
DEFAULT_REGISTRY.register("anthropic", AnthropicProvider)
DEFAULT_REGISTRY.register("ollama", OllamaProvider)

# OpenAI protocol family. Gateway is deliberately just one optional entry.
DEFAULT_REGISTRY.register("openai", OpenAICompatibleProvider)
DEFAULT_REGISTRY.register("openai-compatible", OpenAICompatibleProvider)
DEFAULT_REGISTRY.register("deepseek", OpenAICompatibleProvider)
DEFAULT_REGISTRY.register("vllm", OpenAICompatibleProvider)
DEFAULT_REGISTRY.register("freellm-gateway", OpenAICompatibleProvider)


def build_provider(config: ProviderConfig) -> BaseProvider:
    return DEFAULT_REGISTRY.create(config)
