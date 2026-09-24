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

GOAL = """从零重写《零点站台》为一部 8 章完整中篇科幻悬疑小说。必须形成完整开端、升级、高潮和收束，不写成设定展示稿。"""

INSTRUCTION = """创作要求：
1. 科幻规则必须自洽，设定由规则推导，不临时加规则。
2. 先架构、世界观、人物、大纲，再写正文。
3. 人物必须有秘密、利益冲突和错误选择，不能全员好人。
4. 场景承担信息表达，避免说明书式对白。
5. 每章必须推动风险或人物关系变化。
6. 全流程必须经过 Reviewer 和 Revision。
"""


def configure_provider() -> None:
    # Values come from GitHub Actions variables or local environment.
    defaults = {
        "NOVEL_AI_KIND": "openai",
        "NOVEL_AI_MODEL": "gpt-5.6-sol",
        "NOVEL_AI_BASE_URL": "https://api.openai.com/v1",
        "NOVEL_AI_API_KEY_ENV": "OPENAI_API_KEY",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)
    os.environ.setdefault("NOVEL_AI_REASONING_EFFORT", "high")
    os.environ.setdefault("NOVEL_AI_MAX_TOKENS", "8000")
    os.environ.setdefault("NOVEL_SEED_DEMO", "0")

    key_name = os.environ["NOVEL_AI_API_KEY_ENV"]
    if not os.getenv(key_name, "").strip():
        raise RuntimeError(f"Missing API key secret: {key_name}")


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
    configure_provider()
    init_db()
    project_id = create_project()
    result = await run_book_pipeline(
        project_id=project_id,
        goal=GOAL,
        instruction=INSTRUCTION,
        chapter_count=8,
    )

    output = Path(os.getenv("NARRATIVE_OUTPUT_DIR", "artifacts/zero-platform-platform-rewrite"))
    output.mkdir(parents=True, exist_ok=True)
    task = get_task(int(result["planning_task_id"])) or {}
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "provider": os.getenv("NOVEL_AI_KIND"),
                "model": os.getenv("NOVEL_AI_MODEL"),
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
