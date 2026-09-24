from __future__ import annotations

import os
import urllib.parse

from .base import BaseProvider, ChatRequest, ChatResponse, ProviderError
from .http import request_json


class GeminiProvider(BaseProvider):
    """Google Gemini native REST adapter."""

    def _base_url(self) -> str:
        return (self.config.base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")

    def _api_key(self) -> str:
        if not self.config.api_key_env:
            raise ProviderError("api_key_env is required for Gemini", provider=self.name)
        value = os.getenv(self.config.api_key_env)
        if not value:
            raise ProviderError(
                f"environment variable {self.config.api_key_env} is not set",
                provider=self.name,
            )
        return value

    async def chat(self, request: ChatRequest) -> ChatResponse:
        model = request.model or self.config.default_model
        if not model:
            raise ProviderError("model is required", provider=self.name)

        contents = []
        for message in request.messages:
            if message.role == "system":
                continue
            role = "model" if message.role == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": message.content}]})

        payload = {
            "contents": contents,
            "generationConfig": {"temperature": request.temperature},
            **request.extra,
        }
        system_text = request.system or "\n".join(
            item.content for item in request.messages if item.role == "system"
        )
        if system_text:
            payload["systemInstruction"] = {"parts": [{"text": system_text}]}
        if request.max_tokens is not None:
            payload["generationConfig"]["maxOutputTokens"] = request.max_tokens

        key = urllib.parse.quote(self._api_key(), safe="")
        data = await request_json(
            provider=self.name,
            url=f"{self._base_url()}/models/{urllib.parse.quote(model, safe='')}:generateContent?key={key}",
            method="POST",
            headers=self.config.headers,
            payload=payload,
            timeout=self.config.timeout_seconds,
        )
        try:
            candidate = data["candidates"][0]
            parts = candidate["content"]["parts"]
            content = "".join(part.get("text", "") for part in parts)
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("invalid Gemini response", provider=self.name) from exc

        usage = data.get("usageMetadata") or {}
        return ChatResponse(
            content=content,
            model=model,
            provider=self.name,
            finish_reason=candidate.get("finishReason"),
            usage=usage,
            raw=data,
        )

    async def health_check(self) -> bool:
        try:
            key = urllib.parse.quote(self._api_key(), safe="")
            await request_json(
                provider=self.name,
                url=f"{self._base_url()}/models?key={key}",
                headers=self.config.headers,
                timeout=min(self.config.timeout_seconds, 10.0),
            )
            return True
        except ProviderError:
            return False
