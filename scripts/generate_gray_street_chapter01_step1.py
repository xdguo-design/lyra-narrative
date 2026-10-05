from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.db import connect, init_db
from app.services.book_pipeline import _chapter_text_is_usable, _create_task
from app.services.default_skills import BUILTIN_WRITING_SKILL_NAME
from app.services.workflow_service import _run_step
from scripts.generate_gray_street_chapter01 import (
    CANON_PATH,
    GOAL,
    INSTRUCTION,
    configure_provider,
    create_project,
    keep_generation_skills_lean,
)

OUTPUT_DIR = Path("artifacts/gray-street-chapter01-step1")


def writer_skill_excerpt(task_id: int, limit: int = 12000) -> str:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT sv.content
            FROM writing_task_skills wts
            JOIN skills s ON s.id=wts.skill_id
            JOIN skill_versions sv
              ON sv.skill_id=wts.skill_id AND sv.version=wts.version
            WHERE wts.task_id=? AND s.name=?
            ORDER BY wts.version DESC
            LIMIT 1
            """,
            (task_id, BUILTIN_WRITING_SKILL_NAME),
        ).fetchone()
    return str(row["content"] or "")[-limit:] if row else ""


def selected_skills(task_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT s.name,wts.version
            FROM writing_task_skills wts
            JOIN skills s ON s.id=wts.skill_id
            WHERE wts.task_id=?
            ORDER BY s.name
            """,
            (task_id,),
        ).fetchall()
    return [dict(row) for row in rows]


async def main() -> None:
    provider = configure_provider()
    init_db()
    project_id, chapter_id = create_project()

    task_id = _create_task(
        project_id=project_id,
        chapter_id=chapter_id,
        goal=GOAL,
        instruction=INSTRUCTION,
    )
    keep_generation_skills_lean(task_id)

    canon = CANON_PATH.read_text(encoding="utf-8")
    skill = writer_skill_excerpt(task_id)

    result = await _run_step(
        task_id=task_id,
        role="writer",
        stage="gray-street-chapter01-step1-draft",
        mode="continue",
        content="这是第一节，没有前文。",
        instruction="\n\n".join(
            [
                GOAL,
                INSTRUCTION,
                "【冻结 Canon】\n" + canon,
                "【当前最新全局 Writer Skill】\n" + skill,
                """这是分步流水线第 1 步，只负责生成第一节完整初稿，不做审核、不做解释。
目标 3000—4300 个中文字符。
必须从零写，不复制旧聊天稿或旧平台失败稿。
正文优先使用完整段落和自然中长句群；不要连续裸对白，不要问卷式问答，不要大量一句一段，不要“不是A而是B”式作者总结。
人物的动作、手上任务、利益和空间应自然参与对白，但不要机械给每句台词补动作。
严格完成 Canon 的第一节十个冻结节点，第一节不解释神秘体系。
只输出小说正文。""",
            ]
        ),
    )

    text = result.content.strip()
    if not _chapter_text_is_usable(text):
        raise RuntimeError(f"step1 writer returned unusable chapter: chars={len(text)}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "chapter-01-step1-draft.md").write_text(
        "# 第一节 怀表\n\n" + text + "\n",
        encoding="utf-8",
    )
    manifest = {
        "step": 1,
        "task_id": task_id,
        "chars": len(text),
        "provider": provider,
        "skills": selected_skills(task_id),
        "status": "draft_ready",
        "next_step": "specialist_review",
    }
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
