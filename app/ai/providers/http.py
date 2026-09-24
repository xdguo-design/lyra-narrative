from __future__ import annotations

import asyncio
import json
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

        req = urllib.request.Request(url=url, data=body, headers=merged_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ProviderError(
                f"{provider} request failed ({exc.code}): {detail[:1000]}",
                provider=provider,
                status_code=exc.code,
            ) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ProviderError(f"{provider} request failed: {exc}", provider=provider) from exc

    return await asyncio.to_thread(_send)
