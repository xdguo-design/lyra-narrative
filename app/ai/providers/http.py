from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from .base import ProviderError


def _retry_settings() -> tuple[int, float]:
    retries = max(0, int(os.getenv("NOVEL_AI_HTTP_RETRIES", "4")))
    base_delay = max(1.0, float(os.getenv("NOVEL_AI_RETRY_BASE_SECONDS", "12")))
    return retries, base_delay


def _retry_delay(exc: urllib.error.HTTPError, base_delay: float, attempt: int) -> float:
    retry_after = exc.headers.get("Retry-After") if exc.headers else None
    try:
        delay = float(retry_after) if retry_after else base_delay * (attempt + 1)
    except (TypeError, ValueError):
        delay = base_delay * (attempt + 1)
    return min(delay, 90.0)


async def request_json(
    *,
    provider: str,
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    timeout: float = 90.0,
) -> dict[str, Any]:
    """Small stdlib HTTP helper so the provider layer has no SDK hard dependency."""

    def _send() -> dict[str, Any]:
        body = None
        merged_headers = {"Accept": "application/json", **(headers or {})}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            merged_headers.setdefault("Content-Type", "application/json")

        retries, base_delay = _retry_settings()
        attempt = 0

        while True:
            req = urllib.request.Request(
                url=url,
                data=body,
                headers=merged_headers,
                method=method,
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    raw = response.read().decode("utf-8")
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                retryable = exc.code in {408, 409, 425, 429, 500, 502, 503, 504}
                if retryable and attempt < retries:
                    time.sleep(_retry_delay(exc, base_delay, attempt))
                    attempt += 1
                    continue
                raise ProviderError(
                    f"{provider} request failed ({exc.code}): {detail[:1000]}",
                    provider=provider,
                    status_code=exc.code,
                ) from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt < retries:
                    time.sleep(min(base_delay * (attempt + 1), 90.0))
                    attempt += 1
                    continue
                raise ProviderError(
                    f"{provider} request failed: {exc}",
                    provider=provider,
                ) from exc
            except json.JSONDecodeError as exc:
                raise ProviderError(
                    f"{provider} returned invalid JSON: {exc}",
                    provider=provider,
                ) from exc

    return await asyncio.to_thread(_send)


def _append_delta_content(parts: list[str], value: Any) -> None:
    if isinstance(value, str):
        parts.append(value)
        return
    if not isinstance(value, list):
        return
    for item in value:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str):
            parts.append(text)


async def request_sse_json(
    *,
    provider: str,
    url: str,
    method: str = "POST",
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    timeout: float = 180.0,
) -> dict[str, Any]:
    """Read an OpenAI-compatible SSE stream and normalize it to one response dict.

    The socket timeout applies while waiting for each streamed chunk instead of
    forcing a long reasoning response to arrive as one complete JSON body.
    """

    def _send() -> dict[str, Any]:
        body = None
        merged_headers = {"Accept": "text/event-stream", **(headers or {})}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            merged_headers.setdefault("Content-Type", "application/json")

        retries, base_delay = _retry_settings()
        attempt = 0

        while True:
            req = urllib.request.Request(
                url=url,
                data=body,
                headers=merged_headers,
                method=method,
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    content_type = str(response.headers.get("Content-Type", "")).lower()
                    if "text/event-stream" not in content_type:
                        raw = response.read().decode("utf-8")
                        return json.loads(raw) if raw else {}

                    content_parts: list[str] = []
                    finish_reason: str | None = None
                    usage: dict[str, Any] = {}
                    model = ""
                    response_id = ""
                    chunk_count = 0

                    for raw_line in response:
                        line = raw_line.decode("utf-8", errors="replace").strip()
                        if not line or line.startswith(":") or not line.startswith("data:"):
                            continue
                        item = line[5:].strip()
                        if item == "[DONE]":
                            break
                        if not item:
                            continue

                        chunk = json.loads(item)
                        if isinstance(chunk.get("error"), dict):
                            message = str(
                                chunk["error"].get("message") or "provider stream error"
                            )
                            raise ProviderError(message, provider=provider)

                        chunk_count += 1
                        response_id = str(chunk.get("id") or response_id)
                        model = str(chunk.get("model") or model)
                        chunk_usage = chunk.get("usage")
                        if isinstance(chunk_usage, dict):
                            usage = chunk_usage

                        choices = chunk.get("choices")
                        if not isinstance(choices, list):
                            continue
                        for choice in choices:
                            if not isinstance(choice, dict):
                                continue
                            delta = choice.get("delta")
                            if isinstance(delta, dict):
                                _append_delta_content(
                                    content_parts,
                                    delta.get("content"),
                                )
                            message = choice.get("message")
                            if isinstance(message, dict):
                                _append_delta_content(
                                    content_parts,
                                    message.get("content"),
                                )
                            if choice.get("finish_reason") is not None:
                                finish_reason = str(choice.get("finish_reason"))

                    return {
                        "id": response_id,
                        "model": model,
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": "".join(content_parts),
                                },
                                "finish_reason": finish_reason,
                            }
                        ],
                        "usage": usage,
                        "_stream": {"chunks": chunk_count},
                    }
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                retryable = exc.code in {408, 409, 425, 429, 500, 502, 503, 504}
                if retryable and attempt < retries:
                    time.sleep(_retry_delay(exc, base_delay, attempt))
                    attempt += 1
                    continue
                raise ProviderError(
                    f"{provider} request failed ({exc.code}): {detail[:1000]}",
                    provider=provider,
                    status_code=exc.code,
                ) from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt < retries:
                    time.sleep(min(base_delay * (attempt + 1), 90.0))
                    attempt += 1
                    continue
                raise ProviderError(
                    f"{provider} request failed: {exc}",
                    provider=provider,
                ) from exc
            except json.JSONDecodeError as exc:
                raise ProviderError(
                    f"{provider} returned invalid SSE JSON: {exc}",
                    provider=provider,
                ) from exc

    return await asyncio.to_thread(_send)
