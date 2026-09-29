from __future__ import annotations

import asyncio
import json
import os
import shlex
import time

from app.ai import ChatMessage, ChatRequest, ProviderConfig, build_provider

CANDIDATES = ("glm-5.3-flash", "glm-5.3", "GLM-5.3-Flash")


def parse_profile(raw: str) -> dict[str, str]:
    parsed = {}
    for token in shlex.split(raw.replace("\n", " ")):
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        parsed[key.strip()] = value.strip()
    return parsed


async def probe(model: str) -> dict:
    parsed = parse_profile(os.environ["NARRATIVE_PROFILE_DOTS3"])
    base_url = parsed.get("NOVEL_AI_BASE_URL", "").strip()
    kind = parsed.get("NOVEL_AI_KIND", "openai-compatible").strip()
    provider = build_provider(
        ProviderConfig(
            name="GLM53FLASH",
            kind=kind,
            base_url=base_url or None,
            api_key_env="NARRATIVE_PROFILE_SECRET_DOTS3",
            default_model=model,
            timeout_seconds=35,
        )
    )
    started = time.perf_counter()
    try:
        response = await provider.chat(
            ChatRequest(
                system="你是连通性测试助手。",
                messages=[ChatMessage(role="user", content="只回复两个汉字：正常")],
                temperature=0.1,
                max_tokens=32,
            )
        )
    except Exception as exc:
        return {
            "model": model,
            "ok": False,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "error_type": type(exc).__name__,
            "error": str(exc)[:600],
        }
    return {
        "model": model,
        "ok": bool(response.content.strip()),
        "resolved_model": response.model,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "sample": response.content.strip()[:40],
    }


async def main() -> int:
    for model in CANDIDATES:
        result = await probe(model)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if result.get("ok"):
            return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
