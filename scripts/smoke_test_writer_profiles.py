from __future__ import annotations

import asyncio
import json
import os
import time

from app.ai import ChatMessage, ChatRequest, ProviderConfig, build_provider
from app.ai.providers.base import ProviderError
from app.services.ai_service import _named_provider_profile

PROFILES = ("AGNES", "DOTS3")


async def probe(profile_name: str) -> dict:
    profile = _named_provider_profile(profile_name)
    if profile is None:
        return {
            "profile": profile_name,
            "ok": False,
            "status": "missing_profile",
            "elapsed_ms": 0,
        }

    api_key_env = str(profile.get("api_key_env") or "").strip()
    if not api_key_env or not os.getenv(api_key_env, "").strip():
        return {
            "profile": profile_name,
            "ok": False,
            "status": "missing_secret",
            "provider": profile.get("name"),
            "model": profile.get("default_model"),
            "elapsed_ms": 0,
        }

    provider = build_provider(
        ProviderConfig(
            name=str(profile["name"]),
            kind=str(profile["protocol"]),
            base_url=str(profile.get("base_url") or "") or None,
            api_key_env=api_key_env,
            default_model=str(profile["default_model"]),
            timeout_seconds=30.0,
        )
    )

    started = time.perf_counter()
    try:
        response = await provider.chat(
            ChatRequest(
                system="你是连通性测试助手。",
                messages=[
                    ChatMessage(
                        role="user",
                        content="只回复两个汉字：正常",
                    )
                ],
                temperature=0.1,
                max_tokens=32,
            )
        )
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return {
            "profile": profile_name,
            "ok": False,
            "status": "request_failed",
            "provider": profile.get("name"),
            "model": profile.get("default_model"),
            "elapsed_ms": elapsed_ms,
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
        }

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "profile": profile_name,
        "ok": bool(response.content.strip()),
        "status": "ok" if response.content.strip() else "empty",
        "provider": response.provider,
        "model": response.model,
        "elapsed_ms": elapsed_ms,
        "finish_reason": response.finish_reason,
        "sample": response.content.strip()[:80],
    }


async def main() -> int:
    results = []
    for profile_name in PROFILES:
        result = await probe(profile_name)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)

    os.makedirs("artifacts/writer-provider-smoke", exist_ok=True)
    with open(
        "artifacts/writer-provider-smoke/results.json",
        "w",
        encoding="utf-8",
    ) as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)

    return 0 if all(item["ok"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
