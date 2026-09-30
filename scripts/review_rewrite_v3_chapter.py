from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from app.db import connect, init_db
from app.services.full_novel_pipeline import _persist_memory, _run_review_round


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


CONTROL_SOURCES = [
    (
        Path("books/yamen-proficiency/rewrite-v3/control/story-bible-v1.md"),
        "story-bible",
        "rewrite-v3 Story Bible",
    ),
    (
        Path("books/yamen-proficiency/rewrite-v3/control/volume-01-outline-v1.md"),
        "volume-outline",
        "第一卷 1—30 总纲",
    ),
    (
        Path("books/yamen-proficiency/rewrite-v3/control/foreshadow-registry-v1.md"),
        "foreshadow",
        "伏笔总表",
    ),
    (
        Path("books/yamen-proficiency/rewrite-v3/control/proficiency-skill-tree-v1.md"),
        "proficiency-tree",
        "熟练度技能树",
    ),
    (
        Path("books/yamen-proficiency/rewrite-v3/control/conflict-opponent-ladder-v1.md"),
        "opponent-ladder",
        "矛盾与对立面升级图",
    ),
]


CHARACTER_CARDS = [
    (
        "陈安",
        "县衙白役 / 主角",
        "谨慎、克制，先观察再下判断；刚进入这套身份与规则，不越权。说话偏短，不抢着解释自己聪明；不确定时会明确保留。",
        '["谨慎","克制","不越权"]',
    ),
    (
        "赵六",
        "老白役 / 陈安同伴",
        "在县衙混久了，怕惹事、会躲责任，嘴上贫但不真莽；熟人之间会损两句，遇到班头立刻收着。说话更口语、更短。",
        '["老油条","怕事","嘴贫"]',
    ),
    (
        "周虎",
        "班头",
        "有权威、重程序、办事直接。问话短，命令清楚，不喜欢解释大道理；可以谨慎区分事实与推断，但不会临场说成工整格言。",
        '["班头","程序意识","短句命令"]',
    ),
    (
        "刘旺",
        "后厨跑腿 / 厨役",
        "干杂活，怕被牵连，遇到追问会先自保、半答、解释自己为什么没错；说话粗直，有火气，不会主动替调查者整理逻辑。",
        '["后厨","自保","粗直"]',
    ),
]


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

        for name, role, profile, tags in CHARACTER_CARDS:
            conn.execute(
                """
                INSERT INTO characters(project_id,name,role,profile,tags)
                VALUES(?,?,?,?,?)
                """,
                (project_id, name, role, profile, tags),
            )

    for control_path, kind, title in CONTROL_SOURCES:
        _persist_memory(
            project_id=project_id,
            task_id=0,
            kind=kind,
            title=title,
            content=control_path.read_text(encoding="utf-8"),
        )

    with connect() as conn:
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

    with connect() as conn:
        controls = conn.execute(
            """
            SELECT kind,title,content
            FROM memories
            WHERE project_id=(SELECT project_id FROM writing_tasks WHERE id=?)
              AND confirmed=1
            ORDER BY id
            """,
            (task_id,),
        ).fetchall()
    control_context = "\n\n".join(
        f"【{row['title']}】\n{row['content']}" for row in controls
    )
    context = "\n\n".join(
        item
        for item in [
            "【前一章正文，仅供连续性 Reviewer 使用】\n" + previous,
            control_context,
        ]
        if item
    )
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
