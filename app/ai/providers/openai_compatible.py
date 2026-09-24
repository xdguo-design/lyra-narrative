from __future__ import annotations

import os

from .base import BaseProvider, ChatRequest, ChatResponse, ProviderError
from .http import request_json


class OpenAICompatibleProvider(BaseProvider):
    """OpenAI-compatible chat provider.

    Works with OpenAI-compatible endpoints such as DeepSeek, Qwen-compatible
    services, self-hosted vLLM, and freellm-gateway when it exposes the standard
    /v1/chat/completions contract.
    """

    def _base_url(self) -> str:
        return (self.config.base_url or "https://api.openai.com/v1").rstrip("/")

    def _api_key(self) -> str | None:
        if not self.config.api_key_env:
            return None
        return os.getenv(self.config.api_key_env)

    def _headers(self) -> dict[str, str]:
        headers = dict(self.config.headers)
        api_key = self._api_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    async def chat(self, request: ChatRequest) -> ChatResponse:
        model = request.model or self.config.default_model
        if not model:
            raise ProviderError("model is required", provider=self.name)

        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.extend({"role": item.role, "content": item.content} for item in request.messages)

        payload = {
            "model": model,
            "messages": messages,
            "temperature": request.temperature,
            **request.extra,
        }
        if request.max_tokens is not None:
            is_openai_reasoning_model = (
                self.config.kind.strip().lower() == "openai"
                and model.lower().startswith(("gpt-5", "gpt-6", "o1", "o3", "o4"))
            )
            token_key = (
                "max_completion_tokens" if is_openai_reasoning_model else "max_tokens"
            )
            payload[token_key] = request.max_tokens

        data = await request_json(
            provider=self.name,
            url=f"{self._base_url()}/chat/completions",
            method="POST",
            headers=self._headers(),
            payload=payload,
            timeout=self.config.timeout_seconds,
        )
        try:
            choice = data["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("invalid OpenAI-compatible response", provider=self.name) from exc

        return ChatResponse(
            content=content or "",
            model=data.get("model", model),
            provider=self.name,
            finish_reason=choice.get("finish_reason"),
            usage=data.get("usage") or {},
            raw=data,
        )

    async def health_check(self) -> bool:
        try:
            await request_json(
                provider=self.name,
                url=f"{self._base_url()}/models",
                headers=self._headers(),
                timeout=min(self.config.timeout_seconds, 10.0),
            )
            return True
        except ProviderError:
            return False
