from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from app.db import connect, init_db
from app.services.book_pipeline import (
    _chapter_titles,
    _create_task,
    _ensure_chapters,
    _run_frozen_chapter,
)
from app.services.full_novel_pipeline import _persist_memory
from app.services.workflow_service import _run_step, _task_context, get_task


PROJECT_TITLE = "穿成县衙白役，我把熟练度肝满了（正式流水线前十章）"
PROJECT_GENRE = "架空历史 / 穿越 / 底层成长 / 熟练度"
CHAPTER_COUNT = 10

FREEZE_SOURCES = [
    (
        "books/yamen-proficiency/manual-v6-run-001/architecture.md",
        "source-architecture",
        "既有冻结故事架构",
    ),
    (
        "books/yamen-proficiency/manual-v6-run-001/characters.md",
        "source-characters",
        "既有冻结人物卡",
    ),
    (
        "books/yamen-proficiency/manual-v6-run-001/proficiency-rules.md",
        "source-proficiency",
        "熟练度硬规则",
    ),
    (
        "books/yamen-proficiency/manual-v6-run-001/genre-promise-matrix.md",
        "source-promise",
        "类型 Promise Matrix",
    ),
    (
        "books/yamen-proficiency/manual-v6-run-001/rewrite-freeze-pack-v1.md",
        "source-freeze-pack",
        "正式重写 Freeze Pack",
    ),
]

GOAL = """从冻结设定重新生成《穿成县衙白役，我把熟练度肝满了》的前 10 章正式流水线候选稿。
这是长篇开篇段，不是 10 章完结短篇。第 10 章不得强行解决第一卷全部冲突，也不得提前查清马二之死全部真相。
核心阅读承诺：底层县衙生存、家庭与债务、熟练度真实成长、身份职业推进、县城生活、案件与危险必须交叉推进。"""

SEGMENT_INSTRUCTION = """这是一次正式流水线验证，不允许使用 books/yamen-proficiency/rewrite-v3/ 下的任何正文、章节标题、人工修订句子或人工十章规划作为答案来源。

必须遵守已经写入当前 Writer / Refinement / Reader Skill 的规则，尤其：
1. 少解释不等于少质感。关键声音、气味、触感、动作阻力和空间必须有可感知表面；不得写成只有事实骨架的分镜稿。
2. 连续动作组成自然句群，不机械切成多个短句。
3. 对白必须有人在说：身体、视线、手上任务、关系和利益要进入关键话轮；极短回应必须通过 ORALITY_GAP 检查。
4. 穿越后的现代记忆与原身记忆不能像资料加载一样顺滑，必须用认知错位/迟滞体现，但不得增加解释性独白。
5. 默认每 3 章至少形成 1 个小高潮。高潮不是只丢一个新线索，必须同时推动压力、选择、后果中的至少两项。
6. 每个三章单元结束时，至少两名核心人物的关系、权限、责任、目标或资源状态要真实变化，并被下一章继承。
7. 人物推进要快但不能跳级：陈安仍从白役起步；周虎的信任必须逐步获得；赵六不能长期只做笑料和陪衬；小满不能只做被保护对象；孙成不能轻易招供。
8. 系统只能记录真实行动与学习，不认线索、不鉴真伪、不生成资源、不按章弹窗。
9. 连续三章不得全部使用同一种调查发动机；降速章必须推进家庭、钱、职业或关系。
10. 前 10 章只完成长篇第一阶段的明显起跑和人物位置变化，不关闭第一卷主矛盾。
"""


def configure_provider() -> dict[str, str]:
    name = os.getenv(
        "NARRATIVE_PROVIDER_NAME",
        os.getenv("NOVEL_AI_PROVIDER_NAME", "默认写作"),
    ).strip()
    protocol = os.getenv(
        "NARRATIVE_PROVIDER_PROTOCOL",
        os.getenv("NOVEL_AI_KIND", "openai-compatible"),
    ).strip().lower()
    model = os.getenv(
        "NARRATIVE_PROVIDER_MODEL",
        os.getenv("NOVEL_AI_MODEL", "gpt-5.6-sol"),
    ).strip()
    base_url = os.getenv(
        "NARRATIVE_PROVIDER_BASE_URL",
        os.getenv("NOVEL_AI_BASE_URL", "https://api.openai.com/v1"),
    ).strip()
    secret_name = os.getenv(
        "NARRATIVE_PROVIDER_SECRET_NAME",
        os.getenv("NOVEL_AI_API_KEY_ENV", "OPENAI_API_KEY"),
    ).strip()
    api_key = (
        os.getenv("NARRATIVE_PROVIDER_API_KEY", "").strip()
        or os.getenv("NOVEL_AI_API_KEY", "").strip()
        or os.getenv(secret_name, "").strip()
    )

    if not name:
        raise RuntimeError("NARRATIVE_PROVIDER_NAME must not be empty")
    if protocol not in {"openai-compatible", "openai", "anthropic", "gemini", "ollama"}:
        raise RuntimeError(f"unsupported provider protocol: {protocol}")
    if not model:
        raise RuntimeError("NARRATIVE_PROVIDER_MODEL must not be empty")
    if protocol != "ollama" and not api_key:
        raise RuntimeError(
            f"provider secret is empty; configure GitHub Actions secret {secret_name}"
        )

    os.environ["NOVEL_AI_KIND"] = protocol
    os.environ["NOVEL_AI_MODEL"] = model
    os.environ["NOVEL_AI_BASE_URL"] = base_url
    os.environ["NARRATIVE_PROVIDER_API_KEY"] = api_key
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
    }


def create_clean_project() -> int:
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
                "仅用于验证升级后 NarrativeOS 正式流水线；不读取 rewrite-v3 人工正文。",
                PROJECT_GENRE,
            ),
        )
        return int(cur.lastrowid)


def seed_frozen_sources(project_id: int) -> None:
    with connect() as conn:
        for source_path, kind, title in FREEZE_SOURCES:
            path = Path(source_path)
            if not path.exists():
                raise RuntimeError(f"missing frozen source: {source_path}")
            content = path.read_text(encoding="utf-8")
            conn.execute(
                """
                INSERT INTO memories(
                    project_id,kind,title,content,source_type,source_ref,confirmed
                ) VALUES(?,?,?,?,?,?,1)
                """,
                (
                    project_id,
                    kind,
                    title,
                    content,
                    "repo",
                    source_path,
                ),
            )


async def plan_first_ten(project_id: int) -> tuple[int, str]:
    task_id = _create_task(
        project_id=project_id,
        chapter_id=None,
        goal="依据冻结设定规划长篇前十章，不关闭第一卷",
        instruction=SEGMENT_INSTRUCTION,
    )
    with connect() as conn:
        conn.execute(
            "UPDATE writing_tasks SET status='running',updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (task_id,),
        )

    context = _task_context(task_id, project_id)
    outline = await _run_step(
        task_id=task_id,
        role="plot-planner",
        stage="first-ten-outline",
        mode="continue",
        content="",
        instruction="\n\n".join(
            [
                GOAL,
                SEGMENT_INSTRUCTION,
                context,
                f"""只规划长篇的前 {CHAPTER_COUNT} 章，不写正文，不重写已经冻结的世界规则和人物卡。
必须输出恰好 {CHAPTER_COUNT} 个章节节点，每章标题严格使用：
[CHAPTER 01] 标题：xxxx

每章随后写：开场状态、人物目标、阻碍、主要动作、人物摩擦、错误选择/代价、状态变化、章末牵引。
三章节拍必须显式成立：第 1—3、4—6、7—9 各形成一轮压力曲线，其中每轮至少一章构成小高潮；小高潮后的人物状态不得复位。
第 10 章只作为下一阶段起跑，不解决马二死亡全部真相，不把陈安直接升级为正式差役。""",
            ]
        ),
    )

    _persist_memory(
        project_id=project_id,
        task_id=task_id,
        kind="outline",
        title="冻结前十章流水线规划",
        content=outline.content,
    )
    with connect() as conn:
        conn.execute(
            """
            UPDATE writing_tasks
            SET draft=?,revised_content=?,status='reviewed',updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (outline.content, outline.content, task_id),
        )
    return task_id, outline.content


def export_run(
    project_id: int,
    planning_task_id: int,
    provider: dict[str, str],
    chapter_task_ids: list[int],
    stopped_on_blocking: bool,
) -> Path:
    output_dir = Path(
        os.getenv(
            "NARRATIVE_OUTPUT_DIR",
            "artifacts/yamen-proficiency-first-ten-pipeline",
        )
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    planning_task = get_task(planning_task_id) or {}
    (output_dir / "planning.md").write_text(
        str(planning_task.get("revised_content") or planning_task.get("draft") or ""),
        encoding="utf-8",
    )
    (output_dir / "planning-task.json").write_text(
        json.dumps(planning_task, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with connect() as conn:
        chapters = conn.execute(
            """
            SELECT id,title,position,content FROM chapters
            WHERE project_id=? ORDER BY position,id
            """,
            (project_id,),
        ).fetchall()
        skills = conn.execute(
            """
            SELECT name,current_version FROM skills
            WHERE enabled=1 AND project_id IS NULL
            ORDER BY name
            """
        ).fetchall()

    manifest: dict = {
        "project_id": project_id,
        "project_title": PROJECT_TITLE,
        "provider": provider,
        "planned_chapters": CHAPTER_COUNT,
        "generated_chapters": len(chapter_task_ids),
        "stopped_on_blocking": stopped_on_blocking,
        "skills": [
            {"name": row["name"], "version": int(row["current_version"])}
            for row in skills
        ],
        "provenance": {
            "rewrite_v3_used_as_input": False,
            "freeze_sources": [source[0] for source in FREEZE_SOURCES],
        },
        "chapters": [],
    }

    manuscript = [
        "# 《穿成县衙白役，我把熟练度肝满了》",
        "",
        "> NarrativeOS 正式流水线前十章候选稿",
    ]

    for index, task_id in enumerate(chapter_task_ids, start=1):
        task = get_task(task_id) or {}
        chapter = chapters[index - 1]
        content = str(task.get("revised_content") or task.get("draft") or "")
        filename = f"chapter-{index:02d}.md"
        (output_dir / filename).write_text(
            f"# {chapter['title']}\n\n{content.strip()}\n",
            encoding="utf-8",
        )
        (output_dir / f"task-{task_id}.json").write_text(
            json.dumps(task, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        manuscript.extend(["", "---", "", f"# {chapter['title']}", "", content.strip()])

        runs = task.get("runs") or []
        findings = task.get("findings") or []
        manifest["chapters"].append(
            {
                "position": index,
                "chapter_id": int(chapter["id"]),
                "title": chapter["title"],
                "task_id": task_id,
                "status": task.get("status"),
                "agent_runs": len(runs),
                "review_findings": len(findings),
                "provider_models": sorted(
                    {
                        f"{run.get('provider')}:{run.get('model')}"
                        for run in runs
                        if run.get("provider") or run.get("model")
                    }
                ),
            }
        )

    (output_dir / "manuscript-candidate.md").write_text(
        "\n".join(manuscript) + "\n",
        encoding="utf-8",
    )
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_dir


async def main() -> None:
    provider = configure_provider()
    init_db()
    project_id = create_clean_project()
    seed_frozen_sources(project_id)

    planning_task_id, outline = await plan_first_ten(project_id)
    titles = _chapter_titles(outline, CHAPTER_COUNT)
    chapter_ids = _ensure_chapters(project_id, titles)

    prior_manuscript = ""
    chapter_task_ids: list[int] = []
    stopped_on_blocking = False

    output_dir = export_run(
        project_id,
        planning_task_id,
        provider,
        chapter_task_ids,
        stopped_on_blocking,
    )
    print(
        json.dumps(
            {
                "checkpoint": "planning",
                "output_dir": str(output_dir),
                "planned_chapters": CHAPTER_COUNT,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    try:
        for index, chapter_id in enumerate(chapter_ids, start=1):
            task_id = _create_task(
                project_id=project_id,
                chapter_id=chapter_id,
                goal=f"生成正式流水线前十章中的第 {index} 章候选稿",
                instruction=(
                    SEGMENT_INSTRUCTION
                    + f"\n当前为第 {index}/{CHAPTER_COUNT} 章。"
                    + "\n只允许引用冻结 source memories、当前 Skill、Story State 和流水线自动生成的前文。"
                ),
            )
            chapter_task_ids.append(task_id)
            print(
                json.dumps(
                    {
                        "checkpoint": "chapter-start",
                        "chapter": index,
                        "task_id": task_id,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            result = await _run_frozen_chapter(
                task_id=task_id,
                chapter_number=index,
                prior_manuscript=prior_manuscript,
            )
            candidate = str(
                result.get("revised_content") or result.get("draft") or ""
            )
            with connect() as conn:
                conn.execute(
                    "UPDATE chapters SET content=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (candidate, chapter_id),
                )
            prior_manuscript += (
                f"\n\n# 第 {index} 章 {titles[index - 1]}\n\n{candidate}"
            )
            if result.get("status") == "reviewed":
                stopped_on_blocking = True

            output_dir = export_run(
                project_id,
                planning_task_id,
                provider,
                chapter_task_ids,
                stopped_on_blocking,
            )
            print(
                json.dumps(
                    {
                        "checkpoint": "chapter-complete",
                        "chapter": index,
                        "task_id": task_id,
                        "status": result.get("status"),
                        "output_dir": str(output_dir),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            if stopped_on_blocking:
                break
    except Exception as exc:
        output_dir = export_run(
            project_id,
            planning_task_id,
            provider,
            chapter_task_ids,
            stopped_on_blocking,
        )
        print(
            json.dumps(
                {
                    "checkpoint": "failure",
                    "generated_chapters": len(chapter_task_ids),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "output_dir": str(output_dir),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        raise

    output_dir = export_run(
        project_id,
        planning_task_id,
        provider,
        chapter_task_ids,
        stopped_on_blocking,
    )
    print(
        json.dumps(
            {
                "ok": not stopped_on_blocking,
                "output_dir": str(output_dir),
                "project_id": project_id,
                "planning_task_id": planning_task_id,
                "chapter_task_ids": chapter_task_ids,
                "generated_chapters": len(chapter_task_ids),
                "stopped_on_blocking": stopped_on_blocking,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
