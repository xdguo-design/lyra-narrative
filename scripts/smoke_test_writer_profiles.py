from __future__ import annotations

import asyncio
import json
import os
import time

from app.ai import ChatMessage, ChatRequest, ProviderConfig, build_provider
from app.ai.providers.base import ProviderError
from app.ai.providers.http import request_json
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


async def discover_dots3_models() -> dict:
    profile = _named_provider_profile("DOTS3")
    if profile is None:
        return {"profile": "DOTS3", "model_discovery": "missing_profile"}

    api_key_env = str(profile.get("api_key_env") or "").strip()
    api_key = os.getenv(api_key_env, "").strip() if api_key_env else ""
    base_url = str(profile.get("base_url") or "").rstrip("/")
    if not base_url or not api_key:
        return {"profile": "DOTS3", "model_discovery": "missing_config"}

    started = time.perf_counter()
    try:
        data = await request_json(
            provider="DOTS3",
            url=f"{base_url}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=20.0,
        )
    except Exception as exc:
        return {
            "profile": "DOTS3",
            "model_discovery": "failed",
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
        }

    raw_models = data.get("data") if isinstance(data, dict) else None
    ids = []
    if isinstance(raw_models, list):
        for item in raw_models:
            if isinstance(item, dict) and item.get("id"):
                ids.append(str(item["id"]))
    candidates = [
        model_id
        for model_id in ids
        if any(token in model_id.lower() for token in ("glm", "5.3", "flash"))
    ]
    return {
        "profile": "DOTS3",
        "model_discovery": "ok",
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "model_count": len(ids),
        "candidates": candidates[:100],
    }


async def probe_dots3_glm53(model_id: str) -> dict:
    profile = _named_provider_profile("DOTS3")
    if profile is None:
        return {"profile": "DOTS3-GLM53", "ok": False, "status": "missing_profile"}

    api_key_env = str(profile.get("api_key_env") or "").strip()
    provider = build_provider(
        ProviderConfig(
            name="DOTS3-GLM53",
            kind=str(profile["protocol"]),
            base_url=str(profile.get("base_url") or "") or None,
            api_key_env=api_key_env or None,
            default_model=model_id,
            timeout_seconds=30.0,
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
            "profile": "DOTS3-GLM53",
            "ok": False,
            "status": "request_failed",
            "model": model_id,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
        }

    return {
        "profile": "DOTS3-GLM53",
        "ok": bool(response.content.strip()),
        "status": "ok" if response.content.strip() else "empty",
        "model": response.model,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "finish_reason": response.finish_reason,
        "sample": response.content.strip()[:80],
    }


async def main() -> int:
    results = []
    for profile_name in PROFILES:
        result = await probe(profile_name)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)

    discovery = await discover_dots3_models()
    results.append(discovery)
    print(json.dumps(discovery, ensure_ascii=False), flush=True)

    if discovery.get("model_discovery") == "ok":
        candidates = list(discovery.get("candidates") or [])
        glm53_candidates = [
            item
            for item in candidates
            if "glm" in item.lower()
            and ("5.3" in item.lower() or "53" in item.lower())
            and "flash" in item.lower()
        ]
        if glm53_candidates:
            glm53_result = await probe_dots3_glm53(glm53_candidates[0])
            results.append(glm53_result)
            print(json.dumps(glm53_result, ensure_ascii=False), flush=True)

    os.makedirs("artifacts/writer-provider-smoke", exist_ok=True)
    with open(
        "artifacts/writer-provider-smoke/results.json",
        "w",
        encoding="utf-8",
    ) as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)

    probe_results = [item for item in results if "ok" in item]
    return 0 if all(item["ok"] for item in probe_results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
