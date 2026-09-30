import json
import unittest
from unittest.mock import patch

from app.ai.providers.http import request_sse_json


class _FakeStreamResponse:
    def __init__(self, lines):
        self._lines = lines
        self.headers = {"Content-Type": "text/event-stream; charset=utf-8"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def __iter__(self):
        return iter(self._lines)


class StreamingHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_aggregates_openai_sse_chunks(self):
        chunks = [
            {
                "id": "chat-1",
                "model": "glm-5.3-flash",
                "choices": [{"delta": {"content": "正"}, "finish_reason": None}],
            },
            {
                "id": "chat-1",
                "model": "glm-5.3-flash",
                "choices": [{"delta": {"content": "常"}, "finish_reason": None}],
            },
            {
                "id": "chat-1",
                "model": "glm-5.3-flash",
                "choices": [{"delta": {}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 123},
            },
        ]
        lines = [
            f"data: {json.dumps(item, ensure_ascii=False)}\n".encode()
            for item in chunks
        ]
        lines.append(b"data: [DONE]\n")

        with patch(
            "app.ai.providers.http.urllib.request.urlopen",
            return_value=_FakeStreamResponse(lines),
        ):
            result = await request_sse_json(
                provider="GLM53FLASH",
                url="https://example.invalid/v1/chat/completions",
                payload={"stream": True},
                timeout=30,
            )

        self.assertEqual(result["model"], "glm-5.3-flash")
        self.assertEqual(result["choices"][0]["message"]["content"], "正常")
        self.assertEqual(result["choices"][0]["finish_reason"], "stop")
        self.assertEqual(result["usage"]["total_tokens"], 123)
        self.assertEqual(result["_stream"]["chunks"], 3)


if __name__ == "__main__":
    unittest.main()
