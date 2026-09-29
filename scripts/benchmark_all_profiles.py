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
    "ATRIA",
    "DEEPSEEKV4PRO",
    "DOTS3",
    "GLM52",
    "KIMIK3",
    "MODELSCOPE",
    "SENSENOVA",
    "SENSENOVA68",
)

WRITER_PROMPT = """请写一段 900—1400 个中文字符的历史悬疑小说正文。
场景：县衙后院，陈安从一条车辙和一只粮袋的异常位置继续追查赈粮短缺。
要求：
1. 只写正文，不要标题、提纲、解释。
2. 对话像现场的人会说的话，禁止问卷式盘问。
3. 线索必须通过动作、观察、等待、复查自然出现。
4. 主角不能立刻得出总幕后结论。
5. 严禁现代物件、现代词汇和英文夹杂。
6. 结尾是完整句子，并留下一个具体的新麻烦。
"""

REVIEW_TEXT = """陈安举起手电筒照向县衙后院的水泥地，发现一串新鲜脚印。他立即断定整个州府都参与了赈粮贪腐，于是对门房说：‘你昨日几点看见粮车？车上几个人？每个人叫什么？他们分别去了哪里？’门房连续回答了十几个问题。陈安点头：‘所以幕后主使已经很清楚了。’随后他打开手机记下线索。"""

REVIEW_PROMPT = f"""你是中文小说审稿人。请审下面这段正文，找出最重要的 5 个问题，并说明为什么会影响成稿质量。优先检查：时代错位、人物像工具、结论跳跃、问卷式对白、作者总结。不要重写全文。

正文：
{REVIEW_TEXT}"""

BAD_WRITER_MARKERS = ("手电筒", "手机", "水泥地", "tighter", "APP", "微信")


def _provider(profile_name: str, timeout_seconds: float):
    profile = _named_provider_profile(profile_name)
    if profile is None:
        return None, None
    api_key_env = str(profile.get("api_key_env") or "").strip()
    if not api_key_env or not os.getenv(api_key_env, "").strip():
        return profile, None
    provider = build_provider(
        ProviderConfig(
            name=str(profile["name"]),
            kind=str(profile["protocol"]),
            base_url=str(profile.get("base_url") or "") or None,
            api_key_env=api_key_env,
            default_model=str(profile["default_model"]),
            timeout_seconds=timeout_seconds,
        )
    )
    return profile, provider


async def _call(profile_name: str, *, system: str, prompt: str, max_tokens: int, timeout_seconds: float) -> dict:
    profile, provider = _provider(profile_name, timeout_seconds)
    if profile is None:
        return {"ok": False, "status": "missing_profile"}
    if provider is None:
        return {"ok": False, "status": "missing_secret", "model": profile.get("default_model")}

    started = time.perf_counter()
    try:
        response = await provider.chat(
            ChatRequest(
                system=system,
                messages=[ChatMessage(role="user", content=prompt)],
                temperature=0.55,
                max_tokens=max_tokens,
            )
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": "request_failed",
            "model": profile.get("default_model"),
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "error_type": type(exc).__name__,
            "error": str(exc)[:800],
        }

    text = response.content.strip()
    return {
        "ok": bool(text),
        "status": "ok" if text else "empty",
        "provider": response.provider,
        "model": response.model,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "finish_reason": response.finish_reason,
        "text": text,
    }


def _writer_metrics(text: str) -> dict:
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin_tokens = re.findall(r"\b[A-Za-z]{3,}\b", text)
    bad_markers = [item for item in BAD_WRITER_MARKERS if item.lower() in text.lower()]
    complete_tail = bool(text) and text[-1] in "。！？…」』”）】"
    return {
        "chars": len(text),
        "chinese_chars": chinese_chars,
        "complete_tail": complete_tail,
        "latin_token_count": len(latin_tokens),
        "bad_markers": bad_markers,
        "length_ok": 700 <= len(text) <= 1900,
    }


async def run_profile(profile_name: str, out_dir: Path) -> dict:
    smoke = await _call(
        profile_name,
        system="你是连通性测试助手。",
        prompt="只回复两个汉字：正常",
        max_tokens=32,
        timeout_seconds=25.0,
    )
    smoke_text = smoke.pop("text", "")
    if smoke_text:
        smoke["sample"] = smoke_text[:80]

    writer = await _call(
        profile_name,
        system="你是中文长篇小说作家，只输出正文。",
        prompt=WRITER_PROMPT,
        max_tokens=2400,
        timeout_seconds=80.0,
    )
    writer_text = writer.pop("text", "")
    writer_metrics = _writer_metrics(writer_text) if writer_text else {}
    if writer_text:
        (out_dir / f"{profile_name.lower()}-writer.md").write_text(writer_text, encoding="utf-8")

    reviewer = await _call(
        profile_name,
        system="你是严谨的中文小说审稿人，只输出审稿意见。",
        prompt=REVIEW_PROMPT,
        max_tokens=900,
        timeout_seconds=55.0,
    )
    review_text = reviewer.pop("text", "")
    if review_text:
        (out_dir / f"{profile_name.lower()}-review.md").write_text(review_text, encoding="utf-8")

    writer_ok = bool(writer.get("ok")) and bool(writer_metrics.get("length_ok")) and bool(writer_metrics.get("complete_tail")) and not writer_metrics.get("bad_markers")
    review_ok = bool(reviewer.get("ok")) and len(review_text) >= 120
    result = {
        "profile": profile_name,
        "smoke": smoke,
        "writer": {**writer, **writer_metrics, "quality_gate": writer_ok},
        "review": {**reviewer, "chars": len(review_text), "quality_gate": review_ok},
    }
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


async def main() -> int:
    out_dir = Path("artifacts/model-pool-benchmark")
    out_dir.mkdir(parents=True, exist_ok=True)
    results = await asyncio.gather(
        *(run_profile(profile_name, out_dir) for profile_name in PROFILES)
    )

    (out_dir / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
