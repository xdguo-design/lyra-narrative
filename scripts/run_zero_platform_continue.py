from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

from app.db import connect, init_db
from app.services.book_pipeline import _create_task, _run_frozen_chapter
from app.services.continuity_service import (
    _json_object,
    normalize_story_state,
    persist_story_state,
)
from app.services.full_novel_pipeline import _persist_memory
from app.services.workflow_service import _run_step
from scripts.run_zero_platform_rewrite import (
    configure_provider,
    register_provider_profile,
)


PROJECT_TITLE = "零点站台（公众号当前版续写）"
PROJECT_GENRE = "科幻 / 悬疑"
SOURCE_PATH = Path("books/zero-platform/published-v1/chapters-04-06.md")
OUTPUT_DIR = "artifacts/zero-platform-platform-continue"
SOURCE_CHAPTERS = (4, 5, 6)
TARGET_CHAPTERS = (7, 8)

CHAPTER_RE = re.compile(
    r"^#\s*第\s*(\d+)\s*章\s+(.+?)\s*$",
    re.MULTILINE,
)
OUTLINE_RE = re.compile(
    r"^\s*\[?CHAPTER\s*0*(7|8)\]?\s*[:：\-]?\s*(?:标题[:：]\s*)?(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def parse_source_chapters(text: str) -> dict[int, dict[str, str]]:
    matches = list(CHAPTER_RE.finditer(text))
    chapters: dict[int, dict[str, str]] = {}
    for index, match in enumerate(matches):
        number = int(match.group(1))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        chapters[number] = {
            "title": match.group(2).strip(),
            "content": text[start:end].strip(),
        }
    missing = [number for number in SOURCE_CHAPTERS if number not in chapters]
    if missing:
        raise ValueError(f"missing source chapters: {missing}")
    return chapters


def extract_continuation_titles(outline: str) -> dict[int, str]:
    titles = {
        int(match.group(1)): match.group(2).strip(" #*-")
        for match in OUTLINE_RE.finditer(outline)
    }
    missing = [number for number in TARGET_CHAPTERS if not titles.get(number)]
    if missing:
        raise ValueError(f"continuation outline missing titles: {missing}")
    return titles


def create_project() -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO projects(title,description,genre) VALUES(?,?,?)",
            (
                PROJECT_TITLE,
                "从微信公众号当前版本第4-6章继续生成第7-8章；现有正文冻结，不重写。",
                PROJECT_GENRE,
            ),
        )
        return int(cur.lastrowid)


def import_source_chapters(
    project_id: int,
    chapters: dict[int, dict[str, str]],
) -> dict[int, int]:
    ids: dict[int, int] = {}
    with connect() as conn:
        for number in SOURCE_CHAPTERS:
            item = chapters[number]
            cur = conn.execute(
                """
                INSERT INTO chapters(project_id,title,position,content,status)
                VALUES(?,?,?,?,?)
                """,
                (
                    project_id,
                    item["title"],
                    number,
                    item["content"],
                    "approved",
                ),
            )
            chapter_id = int(cur.lastrowid)
            ids[number] = chapter_id
            conn.execute(
                """
                INSERT INTO chapter_versions(chapter_id,content,note)
                VALUES(?,?,?)
                """,
                (chapter_id, item["content"], "公众号当前版本冻结正文"),
            )
    return ids


async def seed_chapter_six_state(
    *,
    project_id: int,
    chapter_id: int,
    source_text: str,
) -> int:
    task_id = _create_task(
        project_id=project_id,
        chapter_id=chapter_id,
        goal="读取现有第4-6章，建立第6章结束时的权威 Story State",
        instruction="只能抽取既有事实，不续写、不改写、不新增世界规则。",
    )
    with connect() as conn:
        conn.execute(
            """
            UPDATE writing_tasks
            SET status='running',draft=?,revised_content=?,updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (source_text, source_text, task_id),
        )

    result = await _run_step(
        task_id=task_id,
        role="continuity-state-updater",
        stage="import-chapter-06-story-state",
        mode="check",
        content=source_text,
        instruction="""下面是《零点站台》当前发布版第4、5、6章。你只负责提取第6章结束时的客观连续性状态，不能续写、不能重写、不能替作者补设定。

必须特别保留：林远的真实罪责与意识状态、艾拉与小杰的关系及其负罪感、K的身份/立场变化、零点站台、共识场、记忆编辑、铁锈色稳态、金属纽扣中的林远残留意识，以及第6章最后“纽扣裂纹内灰色代码跳动，K表现出恐惧”的章末钩子。

只输出 JSON，严格使用结构：
{
  "chapter_number": 6,
  "chapter_summary": "100字以内",
  "characters": [{"name":"","location":"","physical_state":"","knowledge":[],"relationship_changes":[],"active_goal":""}],
  "items": [{"name":"","holder":"","location":"","state":"","uses_remaining":"unknown"}],
  "locations": [{"name":"","state":"","access":""}],
  "world_counters": [{"name":"","value":"","rule":""}],
  "revealed_facts": [],
  "open_threads": [],
  "closed_threads": [],
  "last_scene": {"time":"","location":"","present_characters":[],"hook":""},
  "do_not_reset": []
}""",
    )
    state = normalize_story_state(
        _json_object(result.content),
        chapter_number=6,
    )
    persist_story_state(
        project_id=project_id,
        task_id=task_id,
        chapter_id=chapter_id,
        chapter_number=6,
        state=state,
    )
    with connect() as conn:
        conn.execute(
            """
            UPDATE writing_tasks
            SET status='awaiting_approval',updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (task_id,),
        )
    return task_id


async def plan_continuation(
    *,
    project_id: int,
    source_text: str,
) -> tuple[int, str]:
    task_id = _create_task(
        project_id=project_id,
        chapter_id=None,
        goal="基于现有第4-6章，为第7-8章设计终局续写方案",
        instruction=(
            "第4-6章是已发布冻结正文，绝不重写。只规划第7、8章，"
            "第8章必须完成主要矛盾和核心伏笔回收。"
        ),
    )
    with connect() as conn:
        conn.execute(
            "UPDATE writing_tasks SET status='running',updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (task_id,),
        )

    architecture = await _run_step(
        task_id=task_id,
        role="story-architect",
        stage="continuation-architecture",
        mode="continue",
        content=source_text,
        instruction="""从现有第4-6章中提取续写必须遵守的冻结故事架构，不写正文。
区分：已经发生的事实、人物主动犯下的错误、尚未完成的冲突、必须回收的伏笔、不能靠重置/失忆/突然新增规则解决的问题。
不要把林远洗白；不要把艾拉写成单纯救赎工具；K必须继续承担“秩序与真实”之间的主动选择。""",
    )
    _persist_memory(
        project_id=project_id,
        task_id=task_id,
        kind="architecture",
        title="公众号当前版续写冻结架构",
        content=architecture.content,
    )

    world = await _run_step(
        task_id=task_id,
        role="world-builder",
        stage="continuation-world-lock",
        mode="continue",
        content=source_text + "\n\n" + architecture.content,
        instruction="""只整理现有第4-6章已经建立或强烈约束的世界规则，不新增能力。
重点锁定：零点站台、意识上传、共识场、记忆编辑/清理、底层日志、权限代码、频率与现实渲染之间的关系，以及这些机制的代价和边界。
输出“允许做什么 / 不允许做什么 / 终局必须满足什么条件”。不写正文。""",
    )
    _persist_memory(
        project_id=project_id,
        task_id=task_id,
        kind="world",
        title="公众号当前版世界规则锁",
        content=world.content,
    )

    characters = await _run_step(
        task_id=task_id,
        role="character-designer",
        stage="continuation-character-lock",
        mode="continue",
        content=source_text + "\n\n" + architecture.content + "\n\n" + world.content,
        instruction="""只提取并冻结续写时林远、艾拉、K三人的人物状态、秘密、罪责、欲望、恐惧、关系冲突和不能被轻易抹平的矛盾。
必须保留林远对小杰死亡与自我删改记忆的责任；保留艾拉用小杰痛苦撕开系统封锁造成的伦理负担；保留K从绝对秩序维护者走向局部秩序重建者的变化。不要替他们和解。""",
    )
    _persist_memory(
        project_id=project_id,
        task_id=task_id,
        kind="character",
        title="公众号当前版人物状态锁",
        content=characters.content,
    )

    outline = await _run_step(
        task_id=task_id,
        role="plot-planner",
        stage="continuation-outline",
        mode="continue",
        content=(
            architecture.content
            + "\n\n"
            + world.content
            + "\n\n"
            + characters.content
            + "\n\n第6章末尾原文：\n"
            + source_text[-5000:]
        ),
        instruction="""只规划第7、8章，不得生成第1-6章替代稿。

必须恰好输出两个章节标题，格式严格为：
[CHAPTER 07] 标题：xxxx
[CHAPTER 08] 标题：xxxx

每章标题后分别写：开场状态、人物目标、阻碍、冲突升级、揭示信息、主动错误选择或代价、转折、章末状态。
第7章必须直接承接第6章最后的纽扣灰色代码与K的恐惧，把林远残留意识、K的局部共识场计划、艾拉的责任冲突真正撞在一起。
第8章必须完成终局：解决“林远是否/如何继续存在”“城市应由谁决定何为真实”“艾拉和K分别承担什么代价”。禁止突然出现万能开关、陌生组织或新物理规则；禁止靠所有人互相理解收尾；允许保留余味，但主要矛盾必须有结果。""",
    )
    _persist_memory(
        project_id=project_id,
        task_id=task_id,
        kind="outline",
        title="第7-8章冻结终局大纲",
        content=outline.content,
    )

    combined = (
        "# 续写架构\n\n"
        + architecture.content
        + "\n\n# 世界规则\n\n"
        + world.content
        + "\n\n# 人物状态\n\n"
        + characters.content
        + "\n\n# 第7-8章大纲\n\n"
        + outline.content
    )
    with connect() as conn:
        conn.execute(
            """
            UPDATE writing_tasks
            SET draft=?,revised_content=?,status='reviewed',updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (combined, combined, task_id),
        )
    return task_id, outline.content


def create_target_chapter(
    *,
    project_id: int,
    number: int,
    title: str,
) -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO chapters(project_id,title,position,content,status)
            VALUES(?,?,?,?,?)
            """,
            (project_id, title, number, "", "draft"),
        )
        return int(cur.lastrowid)


def export_snapshot(
    *,
    output: Path,
    project_id: int,
    provider_id: int,
    provider_config: dict[str, str],
    source_text: str,
    planning_task_id: int,
    task_ids: list[int],
    result: dict,
) -> None:
    output.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        planning = conn.execute(
            "SELECT revised_content FROM writing_tasks WHERE id=?",
            (planning_task_id,),
        ).fetchone()
        tasks = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM writing_tasks WHERE project_id=? ORDER BY id",
                (project_id,),
            ).fetchall()
        ]
        findings = [
            dict(row)
            for row in conn.execute(
                """
                SELECT rf.*
                FROM review_findings rf
                JOIN writing_tasks wt ON wt.id=rf.task_id
                WHERE wt.project_id=?
                ORDER BY rf.id
                """,
                (project_id,),
            ).fetchall()
        ]
        states = [
            dict(row)
            for row in conn.execute(
                """
                SELECT * FROM story_state_snapshots
                WHERE project_id=?
                ORDER BY chapter_number,id
                """,
                (project_id,),
            ).fetchall()
        ]
        runs = [
            dict(row)
            for row in conn.execute(
                """
                SELECT ar.*
                FROM agent_runs ar
                JOIN writing_tasks wt ON wt.id=ar.task_id
                WHERE wt.project_id=?
                ORDER BY ar.id
                """,
                (project_id,),
            ).fetchall()
        ]
        generated = []
        for task_id in task_ids:
            row = conn.execute(
                """
                SELECT wt.*,c.title,c.position
                FROM writing_tasks wt
                JOIN chapters c ON c.id=wt.chapter_id
                WHERE wt.id=?
                """,
                (task_id,),
            ).fetchone()
            if row:
                generated.append(dict(row))

    continuation_parts = []
    for row in sorted(generated, key=lambda item: int(item["position"])):
        content = str(row.get("revised_content") or row.get("draft") or "").strip()
        if content:
            continuation_parts.append(
                f"# 第 {row['position']} 章 {row['title']}\n\n{content}"
            )
    continuation = "\n\n".join(continuation_parts)

    manifest = {
        "provider": {
            "id": provider_id,
            "name": provider_config["name"],
            "protocol": provider_config["protocol"],
            "model": provider_config["model"],
        },
        "project_id": project_id,
        "source_chapters": list(SOURCE_CHAPTERS),
        "target_chapters": list(TARGET_CHAPTERS),
        "result": result,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output / "source-chapters-04-06.md").write_text(source_text, encoding="utf-8")
    (output / "planning.md").write_text(
        str(planning["revised_content"] if planning else ""),
        encoding="utf-8",
    )
    (output / "continuation-07-08.md").write_text(continuation, encoding="utf-8")
    (output / "manuscript-04-08.md").write_text(
        source_text.rstrip() + "\n\n" + continuation,
        encoding="utf-8",
    )
    for filename, payload in [
        ("tasks.json", tasks),
        ("review-findings.json", findings),
        ("story-state.json", states),
        ("agent-runs.json", runs),
    ]:
        (output / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


async def main() -> None:
    provider_config = configure_provider()
    init_db()
    provider_id = register_provider_profile(provider_config)

    source_text = SOURCE_PATH.read_text(encoding="utf-8").strip()
    source_chapters = parse_source_chapters(source_text)

    project_id = create_project()
    source_ids = import_source_chapters(project_id, source_chapters)
    await seed_chapter_six_state(
        project_id=project_id,
        chapter_id=source_ids[6],
        source_text=source_text,
    )
    planning_task_id, outline = await plan_continuation(
        project_id=project_id,
        source_text=source_text,
    )
    titles = extract_continuation_titles(outline)

    task_ids: list[int] = []
    prior_manuscript = source_text
    stopped_on_blocking = False

    for number in TARGET_CHAPTERS:
        chapter_id = create_target_chapter(
            project_id=project_id,
            number=number,
            title=titles[number],
        )
        task_id = _create_task(
            project_id=project_id,
            chapter_id=chapter_id,
            goal=f"续写公众号当前版本第 {number} 章《{titles[number]}》",
            instruction=(
                "第4-6章是已发布冻结正文，绝不重写。"
                f"这是终局续写的第 {number} 章，必须严格执行冻结架构、世界规则、人物状态和第7-8章大纲。"
                "不得把另一套沈砚/姜岚/青屿站版本混入本书。"
                "不得通过失忆、梦境、重启世界或突然新增规则回避已有罪责和冲突。"
                + (
                    "本章必须直接承接第6章最后纽扣内灰色代码跳动、K第一次表现恐惧的现场。"
                    if number == 7
                    else "本章是最终章，必须完成主要矛盾和核心伏笔回收，并给林远、艾拉、K各自明确不可逆的代价或选择。"
                )
            ),
        )
        task_ids.append(task_id)
        chapter_result = await _run_frozen_chapter(
            task_id=task_id,
            chapter_number=number,
            prior_manuscript=prior_manuscript,
        )
        candidate = str(
            chapter_result.get("revised_content")
            or chapter_result.get("draft")
            or ""
        ).strip()
        if candidate:
            prior_manuscript += (
                f"\n\n# 第 {number} 章 {titles[number]}\n\n{candidate}"
            )
        if chapter_result.get("status") == "reviewed":
            stopped_on_blocking = True
            break

    result = {
        "project_id": project_id,
        "planning_task_id": planning_task_id,
        "chapter_task_ids": task_ids,
        "source_chapters": list(SOURCE_CHAPTERS),
        "target_chapters": list(TARGET_CHAPTERS),
        "generated_chapters": len(task_ids),
        "stopped_on_blocking": stopped_on_blocking,
        "status": "needs_revision" if stopped_on_blocking else "awaiting_human_approval",
    }

    export_snapshot(
        output=Path(os.getenv("NARRATIVE_OUTPUT_DIR", OUTPUT_DIR)),
        project_id=project_id,
        provider_id=provider_id,
        provider_config=provider_config,
        source_text=source_text,
        planning_task_id=planning_task_id,
        task_ids=task_ids,
        result=result,
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
