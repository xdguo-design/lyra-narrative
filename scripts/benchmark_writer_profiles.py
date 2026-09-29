from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from app.ai import ChatMessage, ChatRequest, ProviderConfig, build_provider
from app.services.ai_service import _named_provider_profile

PROFILES = ("AGNES", "DOTS3")
PROMPT = """请写一段 1200—1800 个中文字符的历史悬疑小说正文。

场景：县衙后院，陈安从一条车辙和一只粮袋的异常位置继续追查赈粮短缺。
要求：
1. 只写正文，不要标题、提纲、解释。
2. 对话必须像人在现场会说的话，禁止连续问卷式盘问。
3. 线索通过动作、等待、观察、搬动、复查自然出现。
4. 不要让主角一下子说出结论。
5. 结尾必须是完整句子，并留下一个新的麻烦。
"""


async def run_one(profile_name: str) -> dict:
    profile = _named_provider_profile(profile_name)
    if profile is None:
        return {"profile": profile_name, "ok": False, "status": "missing_profile"}

    api_key_env = str(profile.get("api_key_env") or "").strip()
    if not api_key_env or not os.getenv(api_key_env, "").strip():
        return {"profile": profile_name, "ok": False, "status": "missing_secret"}

    provider = build_provider(
        ProviderConfig(
            name=str(profile["name"]),
            kind=str(profile["protocol"]),
            base_url=str(profile.get("base_url") or "") or None,
            api_key_env=api_key_env,
            default_model=str(profile["default_model"]),
            timeout_seconds=60.0,
        )
    )

    started = time.perf_counter()
    try:
        response = await provider.chat(
            ChatRequest(
                system="你是中文长篇小说作家，只输出正文。",
                messages=[ChatMessage(role="user", content=PROMPT)],
                temperature=0.72,
                max_tokens=2800,
            )
        )
    except Exception as exc:
        return {
            "profile": profile_name,
            "ok": False,
            "status": "request_failed",
            "model": profile.get("default_model"),
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
        }

    text = response.content.strip()
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    complete_tail = bool(text) and text[-1] in "。！？…」』”）】"
    return {
        "profile": profile_name,
        "ok": bool(text) and len(text) >= 800 and complete_tail,
        "status": "ok" if bool(text) and len(text) >= 800 and complete_tail else "weak_output",
        "provider": response.provider,
        "model": response.model,
        "elapsed_ms": elapsed_ms,
        "chars": len(text),
        "finish_reason": response.finish_reason,
        "complete_tail": complete_tail,
        "text": text,
    }


async def main() -> int:
    out_dir = Path("artifacts/writer-benchmark")
    out_dir.mkdir(parents=True, exist_ok=True)

    summaries = []
    failed = False
    for profile_name in PROFILES:
        result = await run_one(profile_name)
        text = result.pop("text", "")
        if text:
            (out_dir / f"{profile_name.lower()}.md").write_text(text, encoding="utf-8")
        summaries.append(result)
        failed = failed or not result.get("ok", False)
        print(json.dumps(result, ensure_ascii=False), flush=True)

    (out_dir / "results.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
