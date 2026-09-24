from __future__ import annotations

from .base import BaseProvider, ChatRequest, ChatResponse, ProviderError
from .http import request_json


class OllamaProvider(BaseProvider):
    """Local Ollama adapter."""

    def _base_url(self) -> str:
        return (self.config.base_url or "http://127.0.0.1:11434").rstrip("/")

    async def chat(self, request: ChatRequest) -> ChatResponse:
        model = request.model or self.config.default_model
        if not model:
            raise ProviderError("model is required", provider=self.name)

        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.extend({"role": item.role, "content": item.content} for item in request.messages)

        options = {"temperature": request.temperature}
        if request.max_tokens is not None:
            options["num_predict"] = request.max_tokens

        data = await request_json(
            provider=self.name,
            url=f"{self._base_url()}/api/chat",
            method="POST",
            headers=self.config.headers,
            payload={
                "model": model,
                "messages": messages,
                "stream": False,
                "options": options,
                **request.extra,
            },
            timeout=self.config.timeout_seconds,
        )
        message = data.get("message") or {}
        if "content" not in message:
            raise ProviderError("invalid Ollama response", provider=self.name)

        return ChatResponse(
            content=message.get("content") or "",
            model=data.get("model", model),
            provider=self.name,
            finish_reason=data.get("done_reason"),
            raw=data,
        )

    async def health_check(self) -> bool:
        try:
            await request_json(
                provider=self.name,
                url=f"{self._base_url()}/api/tags",
                timeout=min(self.config.timeout_seconds, 10.0),
            )
            return True
        except ProviderError:
            return False
