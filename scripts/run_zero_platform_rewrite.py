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

GOAL = """从零重写《零点站台》为一部 8 章完整中篇科幻悬疑小说。
只保留核心前提：2036 年临江市，停运七年的青屿站每天 00:07 会出现一列不在运营图中的银灰色列车；34 岁供电巡检工程师林桥在列车里看见了 2029 年青屿站事故中失踪的妹妹林夏。
必须形成完整开端、升级、高潮和收束，不写成设定展示稿。"""

INSTRUCTION = """创作要求：
1. 科幻规则必须能解释得通。只允许少量核心虚构假设，其余现象从装置、事故、边界条件和可观测后果推导；禁止临近高潮临时添加规则。
2. 先由 Story Architect 做整本架构，再做世界观、人物矛盾、8 章冻结大纲；正文不得反向篡改冻结设定。
3. 人物不能全是好人。至少两名主要人物必须主动隐瞒、利用、越线或做出造成严重后果的错误选择；冲突不能靠误会和最后互相理解自动解决。
4. 林桥不能天然正确；林夏不能只是懂事妹妹；主要对抗角色必须拥有可理解但不可被轻易原谅的行为。
5. 氛围必须由场景承担。青屿站、列车、电气异常、声音、灯光、空间变化必须逐章形成压力；减少人物坐下来解释世界观。
6. 语言要能托住情节：避免流水账、连续短句和说明书式对白；保持克制、冷感、有画面，但不堆砌修辞。
7. 每章都必须改变风险等级或人物关系，并留下自然的下一章牵引。
8. 第 8 章必须完成主要矛盾和核心伏笔回收；允许留下余味，不允许用开放结局逃避解释。
9. 旧版 8 章正文不作为输入答案，不复写旧稿；这是一次平台从架构开始的全新生产。
10. 全部 Agent 使用同一个 OpenAI GPT-5.6 Sol Provider。"""


def _configure_openai() -> None:
    os.environ["NOVEL_AI_KIND"] = "openai"
    os.environ["NOVEL_AI_MODEL"] = "gpt-5.6-sol"
    os.environ["NOVEL_AI_BASE_URL"] = "https://api.openai.com/v1"
    os.environ["NOVEL_AI_API_KEY_ENV"] = "OPENAI_API_KEY"
    os.environ.setdefault("NOVEL_AI_REASONING_EFFORT", "high")
    os.environ.setdefault("NOVEL_AI_MAX_TOKENS", "8000")
    os.environ.setdefault("NOVEL_SEED_DEMO", "0")
    if not os.getenv("OPENAI_API_KEY", "").strip():
        raise RuntimeError(
            "OPENAI_API_KEY is required. Put it in the runtime environment or "
            "GitHub Actions secret; never commit it to the repository."
        )


def _create_clean_project() -> int:
    with connect() as conn:
        old = conn.execute(
            "SELECT id FROM projects WHERE title=?",
            (PROJECT_TITLE,),
        ).fetchone()
        if old:
            conn.execute("DELETE FROM projects WHERE id=?", (old["id"],))
        cur = conn.execute(
            "INSERT INTO projects(title,description,genre) VALUES(?,?,?)",
            (
                PROJECT_TITLE,
                "由 NarrativeOS Full Book Pipeline 从架构开始重新生产。",
                PROJECT_GENRE,
            ),
        )
        project_id = int(cur.lastrowid)
        conn.execute(
            """
            INSERT INTO chapters(project_id,title,position,content,status)
            VALUES(?,?,?,?,?)
            """,
            (project_id, "第一章", 1, "", "draft"),
        )
        return project_id


def _export_run(project_id: int, result: dict) -> Path:
    output_dir = Path(
        os.getenv("NARRATIVE_OUTPUT_DIR", "artifacts/zero-platform-platform-rewrite")
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    planning_task = get_task(int(result["planning_task_id"])) or {}
    (output_dir / "planning-task.json").write_text(
        json.dumps(planning_task, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "planning.md").write_text(
        str(planning_task.get("revised_content") or planning_task.get("draft") or ""),
        encoding="utf-8",
    )

    manifest = {
        "project_id": project_id,
        "project_title": PROJECT_TITLE,
        "provider": "openai",
        "model": "gpt-5.6-sol",
        "reasoning_effort": os.getenv("NOVEL_AI_REASONING_EFFORT", "high"),
        **result,
        "chapters": [],
    }

    manuscript_parts = [f"# 《零点站台》\n\n> NarrativeOS 平台候选稿"]
    with connect() as conn:
        chapters = conn.execute(
            """
            SELECT id,title,position FROM chapters
            WHERE project_id=? ORDER BY position,id
            """,
            (project_id,),
        ).fetchall()

    for index, task_id in enumerate(result["chapter_task_ids"], start=1):
        task = get_task(int(task_id)) or {}
        content = str(task.get("revised_content") or task.get("draft") or "")
        chapter = chapters[index - 1]
        filename = f"chapter-{index:04d}.md"
        (output_dir / filename).write_text(
            f"# {chapter['title']}\n\n{content.strip()}\n",
            encoding="utf-8",
        )
        (output_dir / f"task-{task_id}.json").write_text(
            json.dumps(task, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        manuscript_parts.append(
            f"# {chapter['title']}\n\n{content.strip()}"
        )
        manifest["chapters"].append(
            {
                "position": index,
                "chapter_id": int(chapter["id"]),
                "title": chapter["title"],
                "task_id": int(task_id),
                "status": task.get("status"),
                "agent_runs": len(task.get("runs") or []),
                "review_findings": len(task.get("findings") or []),
                "provider_models": sorted(
                    {
                        f"{run.get('provider')}:{run.get('model')}"
                        for run in (task.get("runs") or [])
                        if run.get("provider") or run.get("model")
                    }
                ),
            }
        )

    (output_dir / "manuscript-candidate.md").write_text(
        "\n\n---\n\n".join(manuscript_parts) + "\n",
        encoding="utf-8",
    )
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_dir


async def main() -> None:
    _configure_openai()
    init_db()
    project_id = _create_clean_project()
    result = await run_book_pipeline(
        project_id=project_id,
        goal=GOAL,
        instruction=INSTRUCTION,
        chapter_count=8,
    )
    output_dir = _export_run(project_id, result)
    print(
        json.dumps(
            {
                "ok": True,
                "output_dir": str(output_dir),
                **result,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
