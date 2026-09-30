import unittest
from unittest.mock import AsyncMock, patch

from app.ai.providers.base import (
    ChatMessage,
    ChatRequest,
    ProviderConfig,
    ProviderError,
)
from app.ai.providers.openai_compatible import OpenAICompatibleProvider


class OpenAICompatibleProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_accepts_standard_openai_response(self):
        provider = OpenAICompatibleProvider(
            ProviderConfig(
                name="writer",
                kind="openai-compatible",
                base_url="https://example.invalid/v1",
                default_model="writer-model",
            )
        )
        response_json = {
            "model": "writer-model",
            "choices": [
                {
                    "message": {"role": "assistant", "content": "标准响应"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"total_tokens": 10},
        }
        with patch(
            "app.ai.providers.openai_compatible.request_json",
            new=AsyncMock(return_value=response_json),
        ):
            result = await provider.chat(
                ChatRequest(messages=[ChatMessage(role="user", content="test")])
            )

        self.assertEqual(result.content, "标准响应")
        self.assertEqual(result.model, "writer-model")
        self.assertEqual(result.provider, "writer")

    async def test_accepts_wrapped_sensenova_style_response(self):
        provider = OpenAICompatibleProvider(
            ProviderConfig(
                name="主写作-SenseNova",
                kind="openai-compatible",
                base_url="https://example.invalid/v1",
                default_model="sensenova-model",
            )
        )
        response_json = {
            "data": {
                "id": "test-id",
                "choices": [
                    {
                        "index": 0,
                        "message": "包装响应",
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"total_tokens": 12},
            },
            "status": {"code": 0, "message": "ok"},
        }
        with patch(
            "app.ai.providers.openai_compatible.request_json",
            new=AsyncMock(return_value=response_json),
        ):
            result = await provider.chat(
                ChatRequest(messages=[ChatMessage(role="user", content="test")])
            )

        self.assertEqual(result.content, "包装响应")
        self.assertEqual(result.model, "sensenova-model")
        self.assertEqual(result.provider, "主写作-SenseNova")
        self.assertEqual(result.usage["total_tokens"], 12)

    async def test_rejects_empty_content_response(self):
        provider = OpenAICompatibleProvider(
            ProviderConfig(
                name="writer",
                kind="openai-compatible",
                base_url="https://example.invalid/v1",
                default_model="writer-model",
            )
        )
        response_json = {
            "model": "writer-model",
            "choices": [
                {
                    "message": {"role": "assistant", "content": ""},
                    "finish_reason": "length",
                }
            ],
            "usage": {"total_tokens": 3000},
        }
        with patch(
            "app.ai.providers.openai_compatible.request_json",
            new=AsyncMock(return_value=response_json),
        ), self.assertRaisesRegex(ProviderError, "empty content"):
            await provider.chat(
                ChatRequest(messages=[ChatMessage(role="user", content="test")])
            )

    async def test_glm53flash_uses_official_streaming_defaults(self):
        provider = OpenAICompatibleProvider(
            ProviderConfig(
                name="GLM53FLASH",
                kind="openai-compatible",
                base_url="https://open.bigmodel.cn/api/paas/v4",
                default_model="glm-5.3-flash",
            )
        )
        response_json = {
            "model": "glm-5.3-flash",
            "choices": [
                {
                    "message": {"role": "assistant", "content": "正常"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"total_tokens": 20},
        }
        stream = AsyncMock(return_value=response_json)
        normal = AsyncMock(return_value=response_json)
        with patch(
            "app.ai.providers.openai_compatible.request_sse_json",
            new=stream,
        ), patch(
            "app.ai.providers.openai_compatible.request_json",
            new=normal,
        ):
            result = await provider.chat(
                ChatRequest(
                    messages=[ChatMessage(role="user", content="test")],
                    temperature=0.2,
                    max_tokens=4096,
                )
            )

        self.assertEqual(result.content, "正常")
        self.assertEqual(stream.await_count, 1)
        self.assertEqual(normal.await_count, 0)
        payload = stream.await_args.kwargs["payload"]
        self.assertEqual(payload["temperature"], 1.0)
        self.assertEqual(payload["top_p"], 0.95)
        self.assertEqual(payload["reasoning_effort"], "max")
        self.assertEqual(
            payload["thinking"],
            {"type": "enabled", "clear_thinking": True},
        )
        self.assertIs(payload["stream"], True)
        self.assertIs(payload["tool_stream"], True)
        self.assertEqual(payload["max_tokens"], 4096)

    async def test_glm53flash_allows_explicit_overrides(self):
        provider = OpenAICompatibleProvider(
            ProviderConfig(
                name="GLM53FLASH",
                kind="openai-compatible",
                base_url="https://open.bigmodel.cn/api/paas/v4",
                default_model="glm-5.3-flash",
            )
        )
        response_json = {
            "model": "glm-5.3-flash",
            "choices": [
                {
                    "message": {"role": "assistant", "content": "正常"},
                    "finish_reason": "stop",
                }
            ],
        }
        stream = AsyncMock(return_value=response_json)
        with patch(
            "app.ai.providers.openai_compatible.request_sse_json",
            new=stream,
        ):
            await provider.chat(
                ChatRequest(
                    messages=[ChatMessage(role="user", content="test")],
                    extra={"reasoning_effort": "high", "top_p": 0.9},
                )
            )

        payload = stream.await_args.kwargs["payload"]
        self.assertEqual(payload["reasoning_effort"], "high")
        self.assertEqual(payload["top_p"], 0.9)


if __name__ == "__main__":
    unittest.main()
