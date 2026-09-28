from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from app.db import connect, init_db
from app.services.full_novel_pipeline import _run_review_round


PROJECT_TITLE = "rewrite-v3 chapter candidate heterogeneous review"
CHAPTER_ONE = Path(
    os.getenv(
        "NARRATIVE_REVIEW_PREVIOUS_CHAPTER",
        "books/yamen-proficiency/rewrite-v3/chapter-01/final-candidate.md",
    )
)
CHAPTER_TWO = Path(
    os.getenv(
        "NARRATIVE_REVIEW_CHAPTER",
        "books/yamen-proficiency/rewrite-v3/chapter-02/final-candidate.md",
    )
)
OUTPUT_DIR = Path(
    os.getenv(
        "NARRATIVE_REVIEW_OUTPUT_DIR",
        "artifacts/rewrite-v3-chapter-review",
    )
)


def create_review_task(previous: str, current: str) -> int:
    with connect() as conn:
        old = conn.execute(
            "SELECT id FROM projects WHERE title=?",
            (PROJECT_TITLE,),
        ).fetchone()
        if old:
            conn.execute("DELETE FROM projects WHERE id=?", (old["id"],))

        project = conn.execute(
            "INSERT INTO projects(title,description,genre) VALUES(?,?,?)",
            (
                PROJECT_TITLE,
                "Targeted heterogeneous reader verification for rewrite-v3.",
                "架空历史 / 公案 / 底层成长",
            ),
        )
        project_id = int(project.lastrowid)

        first = conn.execute(
            "INSERT INTO chapters(project_id,title,position,content,status) "
            "VALUES(?,?,?,?,?)",
            (project_id, "第一章", 1, previous, "draft"),
        )
        second = conn.execute(
            "INSERT INTO chapters(project_id,title,position,content,status) "
            "VALUES(?,?,?,?,?)",
            (project_id, "第二章", 2, current, "draft"),
        )
        del first

        task = conn.execute(
            "INSERT INTO writing_tasks(project_id,chapter_id,goal,instruction,status) "
            "VALUES(?,?,?,?,?)",
            (
                project_id,
                int(second.lastrowid),
                "仅审核 rewrite-v3 第二章候选稿，不改正文",
                "使用异构 Reader；商业读者最终首读仍由会话中的 ChatGPT 人工执行。",
                "running",
            ),
        )
        return int(task.lastrowid)


async def main() -> None:
    os.environ.setdefault("NOVEL_SEED_DEMO", "0")
    init_db()

    previous = CHAPTER_ONE.read_text(encoding="utf-8")
    current = CHAPTER_TWO.read_text(encoding="utf-8")
    task_id = create_review_task(previous, current)

    context = "【前一章正文，仅供连续性 Reviewer 使用】\n" + previous
    outputs, blocking = await _run_review_round(
        task_id=task_id,
        draft=current,
        context=context,
        round_no=1,
    )

    with connect() as conn:
        runs = [
            dict(row)
            for row in conn.execute(
                "SELECT id,role,stage,status,provider,model,error "
                "FROM agent_runs WHERE task_id=? ORDER BY id",
                (task_id,),
            ).fetchall()
        ]
        findings = [
            dict(row)
            for row in conn.execute(
                "SELECT reviewer,category,severity,summary,suggestion,status "
                "FROM review_findings WHERE task_id=? ORDER BY id",
                (task_id,),
            ).fetchall()
        ]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "review.md").write_text(
        "# Rewrite-v3 Chapter 02 Heterogeneous Machine Review\n\n"
        + "\n\n---\n\n".join(outputs)
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "task_id": task_id,
        "blocking": blocking,
        "chapter": str(CHAPTER_TWO),
        "previous_chapter": str(CHAPTER_ONE),
        "runs": runs,
        "findings": findings,
    }
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
