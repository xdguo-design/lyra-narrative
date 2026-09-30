from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path

from app.ai import ChatMessage, ChatRequest, ProviderConfig, build_provider
from app.services.ai_service import _named_provider_profile


PROFILES = (
    "AGNES",
    "DOTS3",
    "SENSENOVA68",
    "ATRIA",
    "GLM52",
    "GLM53FLASH",
)

PROMPT = """请写一章完整的历史悬疑小说正文，硬长度 2850—3250 个中文字符。

场景：县衙后院，陈安继续追查昨日赈粮中一只破口粮袋的异常。
只写正文，不要标题、提纲、解释、字符统计。

固定顺序与事实：
1. 刘旺先回避，只说泔水车谁都能推。
2. 只能从右轮磨损、车辙、刘旺左脚旧布鞋后跟缺一角等可见异常施压。
3. 刘旺先只承认昨夜推过一趟；另起一问后才说“孙成”。
4. 再经过独立压力节拍后，刘旺才说“五文”。
5. 刘旺交代袋子放在“后厨侧门”，后来不见了。
6. 沿既有窄车辙、木棚、蓝麻线复查，找到昨日破口粮袋；不得新增切痕、重新缝线、绳子等物证。
7. 上秤只能先得出一句：“重量对不上。”
8. 到这时才取昨夜入库记录；记录只写同口径官斗登记的斗数。
9. 再取昨夜同口径官斗复量，必须逐字出现一次：“短三斗一升。”
10. 只确认分量短了、袋子位置变了，不定性谁偷、怎么偷，不猜孙成动机。
11. 粮袋与记录分开收好留查。
12. 最后一句必须且只能是：“马二死了。”

硬限制：
- 正文少于 2700 个中文字符时不得结束，也不得提前写“马二死了。”
- 不新增精确时辰、请假、腿疼、封条、皮重、尸体地点、死因、伤口、新人物、新证据。
- 不出现“谁给的报酬/报酬多少/拿了多少钱”这类问卷式提示。
- 不出现英文夹杂。
- 对白短，人物有身体反应和现场任务；三阶段之间用动作与空间移动自然过渡。
"""

REQUIRED = (
    "孙成",
    "五文",
    "后厨侧门",
    "重量对不上",
    "官斗",
    "短三斗一升",
    "马二死了。",
)

FORBIDDEN = (
    "半夜",
    "子时",
    "卯时",
    "申时",
    "三更",
    "五更",
    "皮重",
    "封条",
    "谁给的报酬",
    "报酬多少",
    "拿了多少钱",
    "草绳",
    "尸体",
    "伤口",
    "tighter",
)


def _request_settings(model: str) -> tuple[int, float, dict]:
    normalized = model.lower()
    max_tokens = 7000
    timeout_seconds = 120.0
    extra: dict = {}
    if any(marker in normalized for marker in ("glm-5", "sensenova", "atria")):
        max_tokens = 10000
        timeout_seconds = 150.0
    if normalized in {"glm-5.3-flash", "glm-5.3-flashx"}:
        max_tokens = 12000
        timeout_seconds = 180.0
        extra = {
            "reasoning_effort": "low",
            "thinking": {"type": "enabled", "clear_thinking": True},
        }
    return max_tokens, timeout_seconds, extra


def _metrics(text: str) -> dict:
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    required_hits = {marker: marker in text for marker in REQUIRED}
    forbidden_hits = [marker for marker in FORBIDDEN if marker in text]
    exact_hook = text.endswith("马二死了。") and text.count("马二死了。") == 1
    length_ok = 2700 <= len(text) <= 3400
    quality_gate = (
        bool(text)
        and length_ok
        and all(required_hits.values())
        and exact_hook
        and not forbidden_hits
    )
    return {
        "chars": len(text),
        "chinese_chars": chinese_chars,
        "length_ok": length_ok,
        "required_hits": required_hits,
        "forbidden_hits": forbidden_hits,
        "exact_hook": exact_hook,
        "quality_gate": quality_gate,
    }


async def run_one(profile_name: str, out_dir: Path) -> dict:
    profile = _named_provider_profile(profile_name)
    if profile is None:
        return {"profile": profile_name, "ok": False, "status": "missing_profile"}

    api_key_env = str(profile.get("api_key_env") or "").strip()
    if not api_key_env or not os.getenv(api_key_env, "").strip():
        return {
            "profile": profile_name,
            "ok": False,
            "status": "missing_secret",
            "model": profile.get("default_model"),
        }

    model = str(profile["default_model"])
    max_tokens, timeout_seconds, extra = _request_settings(model)
    provider = build_provider(
        ProviderConfig(
            name=str(profile["name"]),
            kind=str(profile["protocol"]),
            base_url=str(profile.get("base_url") or "") or None,
            api_key_env=api_key_env,
            default_model=model,
            timeout_seconds=timeout_seconds,
        )
    )

    started = time.perf_counter()
    try:
        response = await provider.chat(
            ChatRequest(
                system="你是中文长篇小说作家。严格遵守事实边界和长度硬门槛，只输出完整正文。",
                messages=[ChatMessage(role="user", content=PROMPT)],
                temperature=0.30,
                max_tokens=max_tokens,
                extra=extra,
            )
        )
    except Exception as exc:
        return {
            "profile": profile_name,
            "ok": False,
            "status": "request_failed",
            "model": model,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "request_max_tokens": max_tokens,
            "timeout_seconds": timeout_seconds,
            "error_type": type(exc).__name__,
            "error": str(exc)[:800],
        }

    text = response.content.strip()
    result = {
        "profile": profile_name,
        "ok": bool(text),
        "status": "ok" if text else "empty",
        "provider": response.provider,
        "model": response.model,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "finish_reason": response.finish_reason,
        "request_max_tokens": max_tokens,
        "timeout_seconds": timeout_seconds,
        **_metrics(text),
    }
    if text:
        (out_dir / f"{profile_name.lower()}.md").write_text(text, encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


async def main() -> int:
    out_dir = Path("artifacts/writer-benchmark")
    out_dir.mkdir(parents=True, exist_ok=True)

    results = await asyncio.gather(
        *(run_one(profile_name, out_dir) for profile_name in PROFILES)
    )
    ranked = sorted(
        results,
        key=lambda item: (
            not bool(item.get("quality_gate")),
            abs(int(item.get("chars") or 0) - 3000),
            int(item.get("elapsed_ms") or 9999999),
        ),
    )
    payload = {
        "target_chars": [2850, 3250],
        "hard_gate_chars": [2700, 3400],
        "profiles": list(PROFILES),
        "results": results,
        "quality_candidates": [
            item["profile"] for item in ranked if item.get("quality_gate")
        ],
    }
    (out_dir / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "quality_candidates": payload["quality_candidates"],
                "ranked_profiles": [item["profile"] for item in ranked],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
