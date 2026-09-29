from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.db import connect, init_db
from app.services.book_pipeline import _chapter_text_is_usable, _create_task
from app.services.workflow_service import _run_step, _task_context
from scripts.generate_rewrite_v3_chapter import (
    CHAPTER_NUMBER,
    CHAPTER_ONE,
    GOAL,
    INSTRUCTION,
    create_project,
    keep_generation_skills_lean,
)

OUTPUT_DIR = Path("artifacts/rewrite-v3-chapter-fast-draft")


async def main() -> int:
    init_db()
    project_id, chapter_id = create_project()
    task_id = _create_task(
        project_id=project_id,
        chapter_id=chapter_id,
        goal=GOAL,
        instruction=INSTRUCTION,
    )
    keep_generation_skills_lean(task_id)

    prior = CHAPTER_ONE.read_text(encoding="utf-8")
    context = _task_context(task_id, project_id)

    instruction = "\n\n".join(
        [
            GOAL,
            INSTRUCTION,
            context,
            """这是快速草稿通道。你只负责先交付一版可验收的完整第二章正文。
不得输出提纲、解释、审稿意见或写作说明。
正文目标 2500—3800 个中文字符。
必须从第一章刘旺“问你件事”自然接上。
优先保证人物像人在现场说话：刘旺先回避再逐层松口；陈安不连续盘问；赵六看风险；周虎掌握处置权。
调查必须靠动作、复核、搬动、等待和现场噪声推进，不得写成证据问答表。
粮袋最终确认短三斗一升；章末只引出马二死亡，不解释死因。
结尾必须完整，不得半句截断。只输出正文。""",
        ]
    )

    writer = await _run_step(
        task_id=task_id,
        role="writer",
        stage="chapter-02-fast-draft",
        mode="continue",
        content=prior[-3500:],
        instruction=instruction,
    )

    text = writer.content.strip()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "chapter-02-fast-candidate.md").write_text(
        "# 第二章 谁让你推的车\n\n" + text + "\n",
        encoding="utf-8",
    )

    with connect() as conn:
        conn.execute(
            "UPDATE writing_tasks SET draft=?,revised_content=?,status='awaiting_approval' WHERE id=?",
            (text, text, task_id),
        )
        rows = conn.execute(
            "SELECT role,stage,status,provider,model,error FROM agent_runs WHERE task_id=? ORDER BY id",
            (task_id,),
        ).fetchall()

    manifest = {
        "task_id": task_id,
        "usable": _chapter_text_is_usable(text),
        "chars": len(text),
        "runs": [dict(row) for row in rows],
    }
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False), flush=True)
    return 0 if manifest["usable"] else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
