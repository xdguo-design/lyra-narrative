from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.db import connect, init_db
from app.services.book_pipeline import _create_task
from app.services.full_novel_pipeline import _run_review_round
from scripts.generate_gray_street_chapter01 import (
    CANON_PATH,
    configure_provider,
    create_project,
    keep_generation_skills_lean,
)

INPUT = Path("artifacts/step1-input/chapter-01-step1-draft.md")
OUTPUT_DIR = Path("artifacts/gray-street-chapter01-step2")


def _strip_title(text: str) -> str:
    text = text.strip()
    if text.startswith("# 第一节 怀表"):
        return text[len("# 第一节 怀表"):].strip()
    return text


def _findings(task_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT reviewer,category,severity,summary,suggestion,status
            FROM review_findings
            WHERE task_id=?
            ORDER BY
              CASE severity WHEN 'blocking' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
              id
            """,
            (task_id,),
        ).fetchall()
    return [dict(row) for row in rows]


async def main() -> None:
    configure_provider()
    init_db()
    project_id, chapter_id = create_project()
    task_id = _create_task(
        project_id=project_id,
        chapter_id=chapter_id,
        goal="只审核《灰街》第一节 Step 1 初稿，不改正文。",
        instruction=(
            "这是分步流水线第 2 步。只做专项审核；"
            "禁止 revision、禁止 polish、禁止改写正文。"
        ),
    )
    keep_generation_skills_lean(task_id)

    draft = _strip_title(INPUT.read_text(encoding="utf-8"))
    canon = CANON_PATH.read_text(encoding="utf-8")

    with connect() as conn:
        conn.execute(
            "UPDATE writing_tasks SET draft=?,revised_content=?,status='reviewing' WHERE id=?",
            (draft, draft, task_id),
        )
        conn.execute("DELETE FROM review_findings WHERE task_id=?", (task_id,))

    outputs, has_blocking = await _run_review_round(
        task_id=task_id,
        draft=draft,
        context=canon,
        round_no=1,
        auto_learn=False,
        retry_failed_reviewers=1,
    )

    findings = _findings(task_id)
    by_reviewer: dict[str, list[dict]] = {}
    for item in findings:
        by_reviewer.setdefault(str(item["reviewer"]), []).append(item)

    summary = {
        "step": 2,
        "task_id": task_id,
        "draft_chars": len(draft),
        "reviewer_count": len(outputs),
        "has_blocking": bool(has_blocking),
        "blocking_count": sum(1 for x in findings if x["severity"] == "blocking"),
        "warning_count": sum(1 for x in findings if x["severity"] == "warning"),
        "finding_count": len(findings),
        "status": "review_complete",
        "next_step": "multi_reader_review",
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "specialist-review.json").write_text(
        json.dumps(
            {
                "summary": summary,
                "review_outputs": outputs,
                "findings": findings,
                "findings_by_reviewer": by_reviewer,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
