from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(slots=True)
class AssistResult:
    content: str
    provider: str
    model: str
    demo: bool = False


def _system_prompt(mode: str) -> str:
    prompts = {
        "continue": "你是长篇小说续写编辑。延续人物、视角、时态和叙事风格，只输出可直接接在正文后的新正文。",
        "architect": "你是小说故事架构师。设计主题、核心命题、主线矛盾、升级路径、高潮、结局和伏笔回收，只输出结构化故事架构。",
        "world": "你是小说世界观与科学设定设计师。建立底层假设、规则、边界、因果链和限制条件，保证后续情节能从规则推出。",
        "characters": "你是人物与冲突设计师。为主要人物建立欲望、秘密、错误、利益冲突、关系张力、底线和人物弧，避免全员好人。",
        "outline": "你是剧情规划师。把已批准架构、世界观和人物冲突转化为章节级剧情工程，每章明确目标、阻碍、变化、代价和钩子。",
        "draft": "你是小说正文 Writer。严格依据已批准的架构、世界规则、人物设计和章节大纲写完整场景，不擅自改设定。",
        "enrich": "你是场景深化编辑。加强环境、动作、气氛、情绪递进和信息承载，不改变剧情事实、人物动机和世界规则。",
        "revise": "你是 Revision Agent。根据审核意见重写被打回内容，逐项修复 blocking 问题，并保持已经批准的创作约束。",
        "polish": "你是小说文字编辑。保留事实、人物关系和情节含义，改善节奏、句式、画面与可读性，只输出润色后的正文。",
        "check": "你是独立小说审稿人。根据给定审核维度检查冲突与缺陷，严格服从调用方要求的审核输出格式。",
    }
    return prompts.get(mode, prompts["continue"])


def _demo(mode: str, content: str, instruction: str = "") -> AssistResult:
    tail = (content or "").strip().splitlines()[-1:] or [""]
    if mode == "polish":
        text = content or "演示模式未连接真实模型；当前没有可润色正文。"
    elif mode == "check":
        if "NARRATIVEOS_REVIEW_V1" in instruction:
            text = "NO_ISSUE"
        else:
            text = "演示检查：未发现结构化设定冲突。连接真实模型后会结合当前章节、人物卡和世界观做完整一致性检查。"
    else:
        lead = tail[0].strip()[:80]
        text = f"演示续写：从“{lead}”继续——走廊尽头传来一声很轻的金属碰撞，像有人刚刚收起钥匙。"
    return AssistResult(content=text, provider="demo", model="local-demo", demo=True)


async def assist(*, mode: str, content: str, instruction: str = "") -> AssistResult:
    kind = os.getenv("NOVEL_AI_KIND", "demo").strip().lower()
    if kind in {"", "demo", "mock"}:
        return _demo(mode, content, instruction)

    from app.ai import ChatMessage, ChatRequest, ProviderConfig, build_provider

    model = os.getenv("NOVEL_AI_MODEL", "").strip()
    if not model:
        raise RuntimeError("NOVEL_AI_MODEL is required when NOVEL_AI_KIND is configured")

    timeout_seconds = float(os.getenv("NOVEL_AI_TIMEOUT_SECONDS", "90"))
    provider = build_provider(
        ProviderConfig(
            name="workbench",
            kind=kind,
            base_url=os.getenv("NOVEL_AI_BASE_URL") or None,
            api_key_env=os.getenv("NOVEL_AI_API_KEY_ENV") or None,
            default_model=model,
            timeout_seconds=timeout_seconds,
        )
    )
    user_prompt = f"当前正文：\n{content[-12000:]}"
    if instruction.strip():
        user_prompt += f"\n\n额外要求：\n{instruction.strip()}"

    creative_modes = {"continue", "architect", "characters", "outline", "draft", "enrich"}
    standard_token_budget = {
        "check": 700,
        "architect": 1600,
        "world": 1800,
        "characters": 1800,
        "outline": 1800,
        "draft": 2400,
        "enrich": 2400,
        "polish": 2400,
        "revise": 2400,
    }
    local_acceptance_budget = {
        "check": 280,
        "architect": 560,
        "world": 640,
        "characters": 640,
        "outline": 720,
        "draft": 900,
        "enrich": 900,
        "polish": 900,
        "revise": 900,
    }
    budget_profile = os.getenv("NOVEL_AI_BUDGET_PROFILE", "standard").strip().lower()
    max_tokens_by_mode = (
        local_acceptance_budget
        if budget_profile == "ci-local"
        else standard_token_budget
    )
    extra: dict[str, object] = {}
    if kind == "ollama":
        think_enabled = os.getenv("NOVEL_AI_OLLAMA_THINK", "false").strip().lower()
        extra["think"] = think_enabled in {"1", "true", "yes", "on"}

    response = await provider.chat(
        ChatRequest(
            system=_system_prompt(mode),
            messages=[ChatMessage(role="user", content=user_prompt)],
            temperature=0.68 if mode in creative_modes else 0.25,
            max_tokens=max_tokens_by_mode.get(mode, 1800),
            extra=extra,
        )
    )
    return AssistResult(content=response.content, provider=response.provider, model=response.model)
