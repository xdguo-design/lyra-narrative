from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from app.db import connect, init_db
from app.services.book_pipeline import run_book_pipeline
from app.services.workflow_service import get_task


PROJECT_TITLE = "零点站台（NarrativeOS 平台重写）"
PROJECT_GENRE = "都市悬疑 / 科幻"
SUPPORTED_PROTOCOLS = {"openai-compatible", "anthropic", "gemini", "ollama"}

GOAL = """从零重写《零点站台》为一部 8 章完整中篇科幻悬疑小说。必须形成完整开端、升级、高潮和收束，不写成设定展示稿。"""

INSTRUCTION = """创作要求：
1. 科幻规则必须自洽，设定由规则推导，不临时加规则。
2. 先架构、世界观、人物、大纲，再写正文。
3. 人物必须有秘密、利益冲突和错误选择，不能全员好人。
4. 场景承担信息表达，避免说明书式对白。
5. 每章必须推动风险或人物关系变化。
6. 全流程必须经过 Reviewer 和 Revision。
"""


def configure_provider() -> dict[str, str]:
    name = os.getenv("NARRATIVE_PROVIDER_NAME", "默认写作").strip()
    protocol = os.getenv(
        "NARRATIVE_PROVIDER_PROTOCOL", "openai-compatible"
    ).strip().lower()
    model = os.getenv("NARRATIVE_PROVIDER_MODEL", "gpt-5.6-sol").strip()
    base_url = os.getenv(
        "NARRATIVE_PROVIDER_BASE_URL", "https://api.openai.com/v1"
    ).strip()
    secret_name = os.getenv(
        "NARRATIVE_PROVIDER_SECRET_NAME", "OPENAI_API_KEY"
    ).strip()

    if not name:
        raise RuntimeError("NARRATIVE_PROVIDER_NAME must not be empty")
    if protocol not in SUPPORTED_PROTOCOLS:
        raise RuntimeError(f"unsupported provider protocol: {protocol}")
    if not model:
        raise RuntimeError("NARRATIVE_PROVIDER_MODEL must not be empty")

    # Keep legacy runtime environment available for pipeline guards and fallback.
    os.environ["NOVEL_AI_KIND"] = protocol
    os.environ["NOVEL_AI_MODEL"] = model
    os.environ["NOVEL_AI_BASE_URL"] = base_url
    os.environ["NOVEL_AI_API_KEY_ENV"] = "NARRATIVE_PROVIDER_API_KEY"
    os.environ["NOVEL_AI_PROVIDER_NAME"] = name
    os.environ.setdefault("NOVEL_AI_REASONING_EFFORT", "high")
    os.environ.setdefault("NOVEL_AI_MAX_TOKENS", "8000")
    os.environ.setdefault("NOVEL_SEED_DEMO", "0")

    return {
        "name": name,
        "protocol": protocol,
        "model": model,
        "base_url": base_url,
        "secret_name": secret_name,
        "api_key_env": "NARRATIVE_PROVIDER_API_KEY",
    }


def register_provider_profile(config: dict[str, str]) -> int:
    with connect() as conn:
        conn.execute("UPDATE provider_profiles SET is_default=0")
        existing = conn.execute(
            "SELECT id FROM provider_profiles WHERE name=?",
            (config["name"],),
        ).fetchone()
        if existing:
            provider_id = int(existing["id"])
            conn.execute(
                """
                UPDATE provider_profiles
                SET protocol=?,base_url=?,api_key_env=?,default_model=?,
                    enabled=1,is_default=1,updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    config["protocol"],
                    config["base_url"],
                    config["api_key_env"],
                    config["model"],
                    provider_id,
                ),
            )
            return provider_id

        cur = conn.execute(
            """
            INSERT INTO provider_profiles(
                name,protocol,base_url,api_key_env,default_model,enabled,is_default
            ) VALUES(?,?,?,?,?,1,1)
            """,
            (
                config["name"],
                config["protocol"],
                config["base_url"],
                config["api_key_env"],
                config["model"],
            ),
        )
        return int(cur.lastrowid)


def create_project() -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO projects(title,description,genre) VALUES(?,?,?)",
            (
                PROJECT_TITLE,
                "由 Lyra Narrative Full Book Pipeline 生成。",
                PROJECT_GENRE,
            ),
        )
        return int(cur.lastrowid)


async def main() -> None:
    provider_config = configure_provider()
    init_db()
    provider_id = register_provider_profile(provider_config)
    project_id = create_project()

    result = await run_book_pipeline(
        project_id=project_id,
        goal=GOAL,
        instruction=INSTRUCTION,
        chapter_count=8,
    )

    output = Path(
        os.getenv(
            "NARRATIVE_OUTPUT_DIR",
            "artifacts/zero-platform-platform-rewrite",
        )
    )
    output.mkdir(parents=True, exist_ok=True)
    task = get_task(int(result["planning_task_id"])) or {}
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "provider": {
                    "id": provider_id,
                    "name": provider_config["name"],
                    "protocol": provider_config["protocol"],
                    "model": provider_config["model"],
                    "base_url": provider_config["base_url"],
                    "secret_name": provider_config["secret_name"],
                },
                "result": result,
                "planning": task,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
