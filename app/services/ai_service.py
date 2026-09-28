from __future__ import annotations

import os
import shlex
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


_NATURAL_READER_ROLES = {
    "blind-reader",
    "blind-dialogue-reader",
    "blind-natural-reader",
    "style-reviewer",
    "naturalness-reviewer",
    "aesthetic-reviewer",
}

_REASONING_READER_ROLES = {
    "blind-artifice-reader",
    "cadence-character-reader",
    "revision-integrity-reviewer",
    "continuity-reviewer",
    "plot-reviewer",
    "character-reviewer",
    "world-science-reviewer",
    "reader-gap-reviewer",
    "training-examiner",
}

_FINAL_REVIEW_ROLES = {
    "approval-reviewer",
    "final-reviewer",
}

_ROLE_PRIMARY_DEFAULTS = {
    "blind-reader": "GLM52",
    "blind-dialogue-reader": "GLM52",
    "blind-natural-reader": "SENSENOVA68",
    "style-reviewer": "SENSENOVA68",
    "naturalness-reviewer": "GLM52",
    "aesthetic-reviewer": "AGNES",
    "blind-artifice-reader": "DEEPSEEKV4PRO",
    "cadence-character-reader": "MODELSCOPE",
    "revision-integrity-reviewer": "DEEPSEEKV4PRO",
    "continuity-reviewer": "MODELSCOPE",
    "plot-reviewer": "DEEPSEEKV4PRO",
    "character-reviewer": "GLM52",
    "world-science-reviewer": "MODELSCOPE",
    "reader-gap-reviewer": "DEEPSEEKV4PRO",
    "training-examiner": "MODELSCOPE",
}


def _role_bucket(role: str) -> str:
    normalized = role.strip().lower()
    if normalized in _NATURAL_READER_ROLES:
        return "natural-reader"
    if normalized in _REASONING_READER_ROLES:
        return "reasoning-reader"
    if normalized in _FINAL_REVIEW_ROLES:
        return "final-review"
    if normalized.endswith("-reviewer"):
        return "reasoning-reader"
    return "writer"


def _role_profile_candidates(role: str) -> list[str]:
    normalized_role = role.strip().lower()
    bucket = _role_bucket(role)
    settings = {
        "writer": (
            "NARRATIVE_WRITER_PROFILE",
            "ATRIA",
            "NARRATIVE_WRITER_FALLBACK_PROFILES",
            "AGNES,KIMIK3",
        ),
        "natural-reader": (
            "NARRATIVE_NATURAL_READER_PROFILE",
            "GLM52",
            "NARRATIVE_NATURAL_READER_FALLBACK_PROFILES",
            "SENSENOVA68,AGNES",
        ),
        "reasoning-reader": (
            "NARRATIVE_REASONING_READER_PROFILE",
            "DEEPSEEKV4PRO",
            "NARRATIVE_REASONING_READER_FALLBACK_PROFILES",
            "MODELSCOPE,GLM52",
        ),
        "final-review": (
            "NARRATIVE_FINAL_REVIEW_PROFILE",
            "SENSENOVA",
            "NARRATIVE_FINAL_REVIEW_FALLBACK_PROFILES",
            "DEEPSEEKV4PRO,AGNES",
        ),
    }
    primary_env, bucket_default, fallback_env, fallback_default = settings[bucket]
    role_env = "NARRATIVE_ROLE_" + normalized_role.upper().replace("-", "_") + "_PROFILE"
    primary_default = _ROLE_PRIMARY_DEFAULTS.get(normalized_role, bucket_default)
    raw_names = [
        os.getenv(role_env, os.getenv(primary_env, primary_default)).strip(),
        *[
            item.strip()
            for item in os.getenv(fallback_env, fallback_default).split(",")
            if item.strip()
        ],
    ]

    result: list[str] = []
    for name in raw_names:
        normalized = name.upper()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _named_provider_profile(profile_name: str) -> dict | None:
    normalized = profile_name.strip().upper()
    raw = os.getenv(f"NARRATIVE_PROFILE_{normalized}", "").strip()
    if not raw:
        return None

    parsed: dict[str, str] = {}
    for token in shlex.split(raw.replace("\n", " ")):
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        parsed[key.strip()] = value.strip()

    kind = parsed.get("NOVEL_AI_KIND", "").strip().lower()
    model = parsed.get("NOVEL_AI_MODEL", "").strip()
    if not kind or not model:
        return None

    profile_secret_env = f"NARRATIVE_PROFILE_SECRET_{normalized}"
    api_key_env = ""
    if os.getenv(profile_secret_env, "").strip():
        api_key_env = profile_secret_env
    else:
        configured_env = parsed.get("NOVEL_AI_API_KEY_ENV", "").strip()
        shared_profile_secret_env = (
            f"NARRATIVE_PROFILE_SECRET_{configured_env.upper()}"
            if configured_env
            else ""
        )
        if (
            shared_profile_secret_env
            and os.getenv(shared_profile_secret_env, "").strip()
        ):
            api_key_env = shared_profile_secret_env
        elif configured_env and os.getenv(configured_env, "").strip():
            api_key_env = configured_env

    return {
        "name": parsed.get("NOVEL_AI_PROVIDER_NAME", normalized).strip() or normalized,
        "protocol": kind,
        "base_url": parsed.get("NOVEL_AI_BASE_URL", "").strip(),
        "api_key_env": api_key_env,
        "default_model": model,
    }


def _runtime_profiles(role: str) -> list[dict]:
    profiles: list[dict] = []
    for name in _role_profile_candidates(role):
        profile = _named_provider_profile(name)
        if profile is not None:
            profiles.append(profile)

    if profiles:
        return profiles

    default = _default_provider_profile()
    if default:
        return [default]

    return [
        {
            "name": os.getenv("NOVEL_AI_PROVIDER_NAME", "workbench").strip()
            or "workbench",
            "protocol": os.getenv("NOVEL_AI_KIND", "demo").strip().lower(),
            "base_url": os.getenv("NOVEL_AI_BASE_URL", "").strip(),
            "api_key_env": os.getenv("NOVEL_AI_API_KEY_ENV", "").strip(),
            "default_model": os.getenv("NOVEL_AI_MODEL", "").strip(),
        }
    ]


async def assist(
    *,
    mode: str,
    content: str,
    instruction: str = "",
    role: str = "",
) -> AssistResult:
    from app.ai import (
        ChatMessage,
        ChatRequest,
        ProviderConfig,
        ProviderError,
        build_provider,
    )

    user_prompt = f"当前正文：\n{content[-12000:]}"
    if instruction.strip():
        user_prompt += f"\n\n额外要求：\n{instruction.strip()}"

    configured_reasoning_effort = os.getenv(
        "NOVEL_AI_REASONING_EFFORT",
        "",
    ).strip()
    max_tokens = int(os.getenv("NOVEL_AI_MAX_TOKENS", "6000"))
    configured_temperature = os.getenv("NOVEL_AI_TEMPERATURE", "").strip()

    last_error: Exception | None = None
    for profile in _runtime_profiles(role):
        kind = str(profile["protocol"]).strip().lower()
        provider_name = str(profile["name"]).strip()
        model = str(profile["default_model"]).strip()
        base_url = str(profile.get("base_url") or "").strip() or None
        api_key_env = str(profile.get("api_key_env") or "").strip() or None

        if kind in {"", "demo", "mock"}:
            return _demo(mode, content, instruction)
        if not model:
            last_error = RuntimeError(
                f"provider profile '{provider_name}' requires a default model before use"
            )
            continue

        extra: dict[str, str] = {}
        if model.lower().startswith(("gpt-5", "gpt-6")):
            extra["reasoning_effort"] = configured_reasoning_effort or "medium"
        elif (
            configured_reasoning_effort
            and kind == "openai-compatible"
            and os.getenv("NOVEL_AI_FORWARD_REASONING_EFFORT", "0")
            .strip()
            .lower()
            in {"1", "true", "yes", "on"}
        ):
            extra["reasoning_effort"] = configured_reasoning_effort

        if configured_temperature:
            temperature = float(configured_temperature)
        elif model.lower().startswith("kimi-k3"):
            temperature = 1.0
        else:
            temperature = 0.72 if mode == "continue" else 0.35

        try:
            provider = build_provider(
                ProviderConfig(
                    name=provider_name,
                    kind=kind,
                    base_url=base_url,
                    api_key_env=api_key_env,
                    default_model=model,
                    timeout_seconds=float(
                        os.getenv("NOVEL_AI_TIMEOUT_SECONDS", "180")
                    ),
                )
            )
            response = await provider.chat(
                ChatRequest(
                    system=_system_prompt(mode),
                    messages=[ChatMessage(role="user", content=user_prompt)],
                    temperature=temperature,
                    max_tokens=max_tokens,
                    extra=extra,
                )
            )
            return AssistResult(
                content=response.content,
                provider=response.provider,
                model=response.model,
            )
        except ProviderError as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"no usable provider profile for role {role!r}")
