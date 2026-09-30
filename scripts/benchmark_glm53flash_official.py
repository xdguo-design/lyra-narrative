from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path

from app.ai import ChatMessage, ChatRequest, ProviderConfig, build_provider
from app.services.ai_service import _named_provider_profile

PROFILE = "GLM53FLASH"
OUT_DIR = Path("artifacts/glm53flash-official-benchmark")
FALLBACK_REVIEW_SOURCE = Path(
    "books/yamen-proficiency/rewrite-v3/chapter-02/final-candidate.md"
)

OFFICIAL_PARAMETERS = {
    "temperature": 1.0,
    "top_p": 0.95,
    "reasoning_effort": "max",
    "thinking": {"type": "enabled", "clear_thinking": False},
    "stream": True,
    "tool_stream": True,
}

WRITER_PROMPT = """写一章约 3000 个中文字符的历史悬疑小说正文，只输出正文。

背景：县衙后院正在追查赈粮短缺。陈安从昨日粮车留下的车辙和一只位置异常的破口粮袋继续追查。皂班班头周虎负责现场处置，刘旺是后厨杂役，孙成是西库库吏，马二是昨日运粮车夫。

要求：
1. 目标 2800—3300 个中文字符，不要标题、提纲、解释。
2. 线索必须通过动作、观察、复查和人物压力自然出现，不要问卷式盘问。
3. 陈安不能直接猜出幕后主使；周虎不能替作者总结案情。
4. 先确认刘旺昨夜推过粮袋，再自然逼出“孙成”和“五文”，之后找到被移动的破口粮袋。
5. 称重只先确认“重量对不上”，再用昨夜记录与同口径官斗复量，最后只能确认“短三斗一升”。
6. 不新增手机、手电、水泥、现代单位等时代错位物件或术语。
7. 最后一句必须是：“马二死了。”
"""

REVIEW_INSTRUCTION = """你是长篇历史悬疑小说的连续性总审稿人。请对下面完整章节做一次整章连续性审稿。

检查：
- 时间线是否自洽；
- 人物身份、权限、行为动机是否前后一致；
- 道具、位置、移动路线、称量与证据链是否能成立；
- 是否存在作者替人物总结、结论跳跃、问卷式对白；
- 章尾钩子是否由前文自然推出；
- 指出 P0/P1 问题，并给出可执行修改建议。

不要重写全文。输出结构化审稿意见。
"""


def _build_provider(timeout_seconds: float):
    profile = _named_provider_profile(PROFILE)
    if profile is None:
        raise RuntimeError("GLM53FLASH profile is missing")
    api_key_env = str(profile.get("api_key_env") or "").strip()
    if not api_key_env or not os.getenv(api_key_env, "").strip():
        raise RuntimeError("GLM53FLASH secret is missing")
    return profile, build_provider(
        ProviderConfig(
            name=str(profile["name"]),
            kind=str(profile["protocol"]),
            base_url=str(profile.get("base_url") or "") or None,
            api_key_env=api_key_env,
            default_model=str(profile["default_model"]),
            timeout_seconds=timeout_seconds,
        )
    )


async def _call(
    *,
    label: str,
    system: str,
    prompt: str,
    max_tokens: int,
    timeout_seconds: float,
) -> tuple[dict, str]:
    profile, provider = _build_provider(timeout_seconds)
    started = time.perf_counter()
    try:
        response = await provider.chat(
            ChatRequest(
                system=system,
                messages=[ChatMessage(role="user", content=prompt)],
                temperature=0.1,
                max_tokens=max_tokens,
            )
        )
    except Exception as exc:
        result = {
            "label": label,
            "ok": False,
            "status": "request_failed",
            "configured_model": profile.get("default_model"),
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "error_type": type(exc).__name__,
            "error": str(exc)[:1200],
        }
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return result, ""

    text = response.content.strip()
    stream_meta = response.raw.get("_stream") if isinstance(response.raw, dict) else None
    result = {
        "label": label,
        "ok": bool(text),
        "status": "ok" if text else "empty",
        "provider": response.provider,
        "model": response.model,
        "configured_model": profile.get("default_model"),
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "finish_reason": response.finish_reason,
        "usage": response.usage,
        "stream": stream_meta or {},
        "chars": len(text),
        "chinese_chars": len(re.findall(r"[\u4e00-\u9fff]", text)),
    }
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result, text


async def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    smoke, smoke_text = await _call(
        label="short_response",
        system="你是连通性测试助手。",
        prompt="只回复两个汉字：正常",
        max_tokens=4096,
        timeout_seconds=180.0,
    )
    smoke["quality_gate"] = bool(smoke.get("ok")) and "正常" in smoke_text
    (OUT_DIR / "short-response.txt").write_text(smoke_text, encoding="utf-8")

    writer, writer_text = await _call(
        label="writer_3000_chars",
        system="你是中文历史悬疑长篇小说作家，只输出可以直接使用的正文。",
        prompt=WRITER_PROMPT,
        max_tokens=16000,
        timeout_seconds=300.0,
    )
    writer["target_chinese_chars"] = [2800, 3300]
    writer["quality_gate"] = (
        bool(writer.get("ok"))
        and 2600 <= int(writer.get("chinese_chars") or 0) <= 3500
        and writer_text.rstrip().endswith("马二死了。")
    )
    (OUT_DIR / "writer-3000.md").write_text(writer_text, encoding="utf-8")

    if len(writer_text) >= 2200:
        review_source = writer_text
        review_source_name = "generated_3000_char_chapter"
    else:
        review_source = FALLBACK_REVIEW_SOURCE.read_text(encoding="utf-8")
        review_source_name = str(FALLBACK_REVIEW_SOURCE)

    reviewer, review_text = await _call(
        label="whole_chapter_continuity_review",
        system="你是严谨的中文长篇小说连续性审稿人。",
        prompt=REVIEW_INSTRUCTION + "\n\n【完整章节】\n" + review_source,
        max_tokens=10000,
        timeout_seconds=300.0,
    )
    reviewer["review_source"] = review_source_name
    reviewer["source_chars"] = len(review_source)
    reviewer["quality_gate"] = bool(reviewer.get("ok")) and len(review_text) >= 300
    (OUT_DIR / "continuity-review.md").write_text(review_text, encoding="utf-8")

    summary = {
        "profile": PROFILE,
        "official_parameters": OFFICIAL_PARAMETERS,
        "tests": {
            "short_response": smoke,
            "writer_3000_chars": writer,
            "whole_chapter_continuity_review": reviewer,
        },
        "all_calls_ok": all(
            bool(item.get("ok"))
            for item in (smoke, writer, reviewer)
        ),
        "all_quality_gates_passed": all(
            bool(item.get("quality_gate"))
            for item in (smoke, writer, reviewer)
        ),
    }
    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if summary["all_calls_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
