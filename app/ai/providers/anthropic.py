from __future__ import annotations

import os

from .base import BaseProvider, ChatRequest, ChatResponse, ProviderError
from .http import request_json


class AnthropicProvider(BaseProvider):
    """Anthropic Messages API adapter."""

    def _base_url(self) -> str:
        return (self.config.base_url or "https://api.anthropic.com/v1").rstrip("/")

    def _api_key(self) -> str:
        if not self.config.api_key_env:
            raise ProviderError("api_key_env is required for Anthropic", provider=self.name)
        value = os.getenv(self.config.api_key_env)
        if not value:
            raise ProviderError(
                f"environment variable {self.config.api_key_env} is not set",
                provider=self.name,
            )
        return value

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key(),
            "anthropic-version": str(self.config.options.get("anthropic_version", "2023-06-01")),
            **self.config.headers,
        }

    async def chat(self, request: ChatRequest) -> ChatResponse:
        model = request.model or self.config.default_model
        if not model:
            raise ProviderError("model is required", provider=self.name)

        system_parts = []
        if request.system:
            system_parts.append(request.system)

        messages = []
        for message in request.messages:
            if message.role == "system":
                system_parts.append(message.content)
                continue
            role = "assistant" if message.role == "assistant" else "user"
            messages.append({"role": role, "content": message.content})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens or int(self.config.options.get("max_tokens", 4096)),
            **request.extra,
        }
        if system_parts:
            payload["system"] = "\n".join(system_parts)

        data = await request_json(
            provider=self.name,
            url=f"{self._base_url()}/messages",
            method="POST",
            headers=self._headers(),
            payload=payload,
            timeout=self.config.timeout_seconds,
        )
        try:
            blocks = data["content"]
            content = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
        except (KeyError, TypeError) as exc:
            raise ProviderError("invalid Anthropic response", provider=self.name) from exc

        return ChatResponse(
            content=content,
            model=data.get("model", model),
            provider=self.name,
            finish_reason=data.get("stop_reason"),
            usage=data.get("usage") or {},
            raw=data,
        )

    async def health_check(self) -> bool:
        # Anthropic does not expose a cheap universal models endpoint for every account.
        # Validate configuration locally; the first real request remains authoritative.
        try:
            self._api_key()
            return True
        except ProviderError:
            return False
