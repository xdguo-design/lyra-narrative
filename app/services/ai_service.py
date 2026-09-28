from __future__ import annotations

import os
from dataclasses import dataclass

from app.db import connect


@dataclass(slots=True)
class AssistResult:
    content: str
    provider: str
    model: str
    demo: bool = False


def _system_prompt(mode: str) -> str:
    prose_rules = (
        "中文小说默认使用自然完整的语流，不把短句和单句段落当成高级感；"
        "短句只用于确有需要的冲击、停顿或情绪断裂。"
        "描写优先给出可感知的正向形象和身体经验，少用‘不像A、也不像B’式排除法。"
        "陌生术语首次出现必须让普通读者从语境、用途或自然解释中立即理解。"
        "对白必须体现人物关系、情绪和当下意图，避免纯资料问答。"
    )
    prompts = {
        "continue": (
            "你是长篇小说续写编辑。延续人物、视角、时态和叙事风格，只输出可直接接在正文后的新正文。"
            + prose_rules
        ),
        "polish": (
            "你是小说文字编辑。保留事实、人物关系和情节含义，改善节奏、句式、画面与可读性，只输出润色后的正文。"
            + prose_rules
        ),
        "check": (
            "你是小说一致性审稿人。检查人物行为、时间线、称谓、地点、道具和因果是否冲突；"
            "同时识别碎句堆叠、空洞否定式描写、未落地术语和缺少人物意图的功能性对白，输出精炼的问题清单与修改建议。"
        ),
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


def _default_provider_profile() -> dict | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM provider_profiles
            WHERE enabled=1 AND is_default=1 AND protocol<>''
            ORDER BY id
            LIMIT 1
            """
        ).fetchone()
        return dict(row) if row else None


async def assist(*, mode: str, content: str, instruction: str = "") -> AssistResult:
    profile = _default_provider_profile()
    if profile:
        kind = str(profile["protocol"]).strip().lower()
        provider_name = str(profile["name"]).strip()
        model = str(profile["default_model"]).strip()
        base_url = str(profile["base_url"]).strip() or None
        api_key_env = str(profile["api_key_env"]).strip() or None
        if not model:
            raise RuntimeError(
                f"provider profile '{provider_name}' requires a default model before use"
            )
    else:
        kind = os.getenv("NOVEL_AI_KIND", "demo").strip().lower()
        provider_name = os.getenv("NOVEL_AI_PROVIDER_NAME", "workbench").strip() or "workbench"
        model = os.getenv("NOVEL_AI_MODEL", "").strip()
        base_url = os.getenv("NOVEL_AI_BASE_URL") or None
        api_key_env = os.getenv("NOVEL_AI_API_KEY_ENV") or None

    if kind in {"", "demo", "mock"}:
        return _demo(mode, content, instruction)

    from app.ai import ChatMessage, ChatRequest, ProviderConfig, build_provider

    if not model:
        raise RuntimeError("NOVEL_AI_MODEL is required when a real provider is configured")

    provider = build_provider(
        ProviderConfig(
            name=provider_name,
            kind=kind,
            base_url=base_url,
            api_key_env=api_key_env,
            default_model=model,
            timeout_seconds=float(os.getenv("NOVEL_AI_TIMEOUT_SECONDS", "180")),
        )
    )
    user_prompt = f"当前正文：\n{content[-12000:]}"
    if instruction.strip():
        user_prompt += f"\n\n额外要求：\n{instruction.strip()}"
    extra: dict[str, str] = {}
    configured_reasoning_effort = os.getenv(
        "NOVEL_AI_REASONING_EFFORT", ""
    ).strip()
    if model.lower().startswith(("gpt-5", "gpt-6")):
        extra["reasoning_effort"] = configured_reasoning_effort or "medium"
    elif (
        configured_reasoning_effort
        and kind == "openai-compatible"
        and os.getenv("NOVEL_AI_FORWARD_REASONING_EFFORT", "0").strip().lower()
        in {"1", "true", "yes", "on"}
    ):
        extra["reasoning_effort"] = configured_reasoning_effort

    max_tokens = int(os.getenv("NOVEL_AI_MAX_TOKENS", "6000"))
    response = await provider.chat(
        ChatRequest(
            system=_system_prompt(mode),
            messages=[ChatMessage(role="user", content=user_prompt)],
            temperature=0.72 if mode == "continue" else 0.35,
            max_tokens=max_tokens,
            extra=extra,
        )
    )
    return AssistResult(content=response.content, provider=response.provider, model=response.model)