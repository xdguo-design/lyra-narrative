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
CHAPTER = Path("books/yamen-proficiency/rewrite-v3/chapter-02/final-candidate.md")
PREVIOUS = Path("books/yamen-proficiency/rewrite-v3/chapter-01/final-candidate.md")
CONTROL_FILES = [
    Path("books/yamen-proficiency/rewrite-v3/control/story-bible-v1.md"),
    Path("books/yamen-proficiency/rewrite-v3/control/volume-01-outline-v1.md"),
    Path("books/yamen-proficiency/rewrite-v3/control/foreshadow-registry-v1.md"),
]
OUT_DIR = Path("artifacts/chapter-02-glm53-deep-review")

INSTRUCTION = """你是第二章的深度审稿人，只审核【连续性、剧情逻辑、证据链】。不要润色文风，不要重写全文。

必须逐项检查：
1. 第一章到第二章的时间、地点、人物身份、权限、伤势、道具和已知信息是否连续；
2. 第二章内部每条线索的信息来源是否成立，人物是否知道了自己不可能知道的事；
3. 刘旺—孙成—五文—破口粮袋—称量—官斗—短三斗一升—马二之间的因果链是否逐步成立；
4. 物证链：粮袋原位置、发现位置、移动、称重、记录、官斗复量、短缺结论，是否有缺失环节或结论跳跃；
5. 县衙人员的权限和办案程序是否自洽，是否有人越权、记录凭空出现、量具口径不明；
6. 是否提前泄漏后续章信息，或把尚未证实的推断写成事实；
7. 章末马二死亡是否与本章线索形成合理升级，而不是机械钩子。

严重性：
- P0：事实矛盾、证据链断裂、因果无法成立，会破坏剧情；
- P1：明显逻辑/权限/信息来源问题，需要本章修；
- P2：可改善但不阻断。

严格输出：
GLM53_DEEP_REVIEW_V1
VERDICT: PASS 或 RETURN

每个问题单独一块：
ISSUE: G53-001
SEVERITY: P0/P1/P2
CATEGORY: CONTINUITY/PLOT/EVIDENCE
LOCATION: 精确到场景或原句
EVIDENCE: 引用最短必要原文
PROBLEM: 问题是什么
IMPACT: 为什么影响剧情成立
FIX: 最小修复动作
---
最后输出：
P0_COUNT: n
P1_COUNT: n
P2_COUNT: n
SUMMARY: 一段总评
"""

async def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    profile = _named_provider_profile(PROFILE)
    if profile is None:
        raise RuntimeError("GLM53FLASH profile is missing")
    api_key_env = str(profile.get("api_key_env") or "").strip()
    if not api_key_env or not os.getenv(api_key_env, "").strip():
        raise RuntimeError("GLM53FLASH secret is missing")

    chapter = CHAPTER.read_text(encoding="utf-8")
    previous = PREVIOUS.read_text(encoding="utf-8")
    controls = []
    for path in CONTROL_FILES:
        if path.exists():
            controls.append(f"【{path.name}】\n" + path.read_text(encoding="utf-8"))

    prompt = "\n\n".join([
        INSTRUCTION,
        "【第一章，仅供连续性核对】\n" + previous,
        *controls,
        "【第二章待审正文】\n" + chapter,
    ])

    provider = build_provider(
        ProviderConfig(
            name=str(profile["name"]),
            kind=str(profile["protocol"]),
            base_url=str(profile.get("base_url") or "") or None,
            api_key_env=api_key_env,
            default_model=str(profile["default_model"]),
            timeout_seconds=900.0,
        )
    )
    started = time.perf_counter()
    response = await provider.chat(
        ChatRequest(
            system="你是严谨的历史悬疑长篇小说深度连续性与证据链审稿人。",
            messages=[ChatMessage(role="user", content=prompt)],
            temperature=1.0,
            max_tokens=48000,
            extra={"reasoning_effort": "high"},
        )
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    text = response.content.strip()

    counts = {}
    for level in ("P0", "P1", "P2"):
        matches = re.findall(rf"SEVERITY:\s*{level}\b", text, flags=re.I)
        counts[level] = len(matches)

    summary = {
        "chapter": str(CHAPTER),
        "profile": PROFILE,
        "provider": response.provider,
        "model": response.model,
        "elapsed_ms": elapsed_ms,
        "finish_reason": response.finish_reason,
        "usage": response.usage,
        "output_chars": len(text),
        "issue_counts": counts,
        "usable": bool(text),
        "official_parameters": {
            "temperature": 1.0,
            "top_p": 0.95,
            "thinking": {"type": "enabled", "clear_thinking": True},
            "stream": True,
            "reasoning_effort": "high",
            "max_tokens": 48000,
            "timeout_seconds": 900,
        },
    }
    (OUT_DIR / "review.md").write_text(text + "\n", encoding="utf-8")
    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False), flush=True)

if __name__ == "__main__":
    asyncio.run(main())
