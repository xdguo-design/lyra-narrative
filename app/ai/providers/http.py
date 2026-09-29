from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from .base import ProviderError


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

        retries = max(0, int(os.getenv("NOVEL_AI_HTTP_RETRIES", "4")))
        base_delay = max(1.0, float(os.getenv("NOVEL_AI_RETRY_BASE_SECONDS", "12")))
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
                    retry_after = exc.headers.get("Retry-After") if exc.headers else None
                    try:
                        delay = float(retry_after) if retry_after else base_delay * (attempt + 1)
                    except (TypeError, ValueError):
                        delay = base_delay * (attempt + 1)
                    time.sleep(min(delay, 90.0))
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
