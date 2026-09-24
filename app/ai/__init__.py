"""AI provider abstraction for Novel Workbench."""

from .providers.base import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ProviderConfig,
    ProviderError,
)
from .providers.registry import ProviderRegistry, build_provider

__all__ = [
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "ProviderConfig",
    "ProviderError",
    "ProviderRegistry",
    "build_provider",
]
