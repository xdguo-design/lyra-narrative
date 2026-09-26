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
    prompts = {
        "continue": "你是长篇小说续写编辑。延续人物、视角、时态和叙事风格，只输出可直接接在正文后的新正文。",
        "polish": "你是小说文字编辑。保留事实、人物关系和情节含义，改善节奏、句式、画面与可读性，只输出润色后的正文。",
        "check": "你是小说一致性审稿人。检查人物行为、时间线、称谓、地点、道具和因果是否冲突，输出精炼的问题清单与修改建议。",
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
        )
    )
    user_prompt = f"当前正文：\n{content[-12000:]}"
    if instruction.strip():
        user_prompt += f"\n\n额外要求：\n{instruction.strip()}"
    extra: dict[str, str] = {}
    if model.lower().startswith(("gpt-5", "gpt-6")):
        extra["reasoning_effort"] = os.getenv(
            "NOVEL_AI_REASONING_EFFORT", "medium"
        ).strip() or "medium"

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
