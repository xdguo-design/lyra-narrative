import unittest
from unittest.mock import AsyncMock, patch

from app.ai.providers.base import ChatMessage, ChatRequest, ProviderConfig
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


if __name__ == "__main__":
    unittest.main()
