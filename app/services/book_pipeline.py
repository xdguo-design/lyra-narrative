from __future__ import annotations

import re

from app.db import connect
from app.services.continuity_service import (
    ContinuityStateError,
    capture_story_state,
    latest_story_state,
    record_repetition_blocking,
    render_story_state,
    repair_repetition,
    repetition_report,
)
from app.services.full_novel_pipeline import (
    _persist_memory,
    _require_real_provider,
    _run_review_round,
)
from app.services.workflow_service import _run_step, _task_context, get_task


def _create_task(
    *,
    project_id: int,
    chapter_id: int | None,
    goal: str,
    instruction: str,
) -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO writing_tasks(project_id,chapter_id,goal,instruction,status)
            VALUES(?,?,?,?,?)
            """,
            (project_id, chapter_id, goal, instruction, "pending"),
        )
        task_id = int(cur.lastrowid)
        conn.execute(
            """
            INSERT INTO writing_task_skill_policy(task_id,mode)
            VALUES(?,?)
            """,
            (task_id, "default"),
        )
        skills = conn.execute(
            """
            SELECT id,current_version
            FROM skills
            WHERE enabled=1 AND (project_id IS NULL OR project_id=?)
            ORDER BY project_id IS NOT NULL DESC,id
            """,
            (project_id,),
        ).fetchall()
        for skill in skills:
            conn.execute(
                """
                INSERT INTO writing_task_skills(task_id,skill_id,version)
                VALUES(?,?,?)
                """,
                (task_id, skill["id"], skill["current_version"]),
            )
    return task_id


def _chapter_titles(outline: str, count: int) -> list[str]:
    titles: dict[int, str] = {}
    pattern = re.compile(
        r"^\s*\[?CHAPTER\s*0*(\d+)\]?\s*[:：\-]?\s*(?:标题[:：]\s*)?(.+?)\s*$",
        re.IGNORECASE,
    )
    for line in outline.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        number = int(match.group(1))
        title = match.group(2).strip(" #*-")
        if 1 <= number <= count and title:
            titles[number] = title
    return [titles.get(index, f"第{index}章") for index in range(1, count + 1)]


def _ensure_chapters(project_id: int, titles: list[str]) -> list[int]:
    with connect() as conn:
        existing = conn.execute(
            "SELECT * FROM chapters WHERE project_id=? ORDER BY position,id",
            (project_id,),
        ).fetchall()
        ids: list[int] = []
        for index, title in enumerate(titles, start=1):
            if index <= len(existing):
                chapter_id = int(existing[index - 1]["id"])
                conn.execute(
                    """
                    UPDATE chapters
                    SET title=?,content='',status='draft',updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (title, chapter_id),
                )
            else:
                cur = conn.execute(
                    """
                    INSERT INTO chapters(project_id,title,position,content,status)
                    VALUES(?,?,?,?,?)
                    """,
                    (project_id, title, index, "", "draft"),
                )
                chapter_id = int(cur.lastrowid)
            ids.append(chapter_id)
        return ids


async def _plan_book(
    *,
    project_id: int,
    project_title: str,
    genre: str,
    goal: str,
    instruction: str,
    chapter_count: int,
) -> int:
    task_id = _create_task(
        project_id=project_id,
        chapter_id=None,
        goal=f"为《{project_title}》完成整本创作规划",
        instruction=instruction,
    )
    with connect() as conn:
        conn.execute(
            "UPDATE writing_tasks SET status='running',updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (task_id,),
        )

    context = _task_context(task_id, project_id)
    architect = await _run_step(
        task_id=task_id,
        role="story-architect",
        stage="book-architecture",
        mode="continue",
        content="",
        instruction="\n\n".join(
            item
            for item in [
                f"作品：{project_title}",
                f"类型：{genre}",
                f"整书目标：{goal}",
                instruction,
                context,
                """你只负责整本小说的故事架构，不写正文。必须输出：核心命题、主角欲望、对抗力量、主要人物之间不可调和的利益/亲情/责任冲突、关键秘密、主动犯错、三幕推进、高潮选择、结局、伏笔与回收表。禁止全员好人，至少两名核心人物必须因为自己的主动选择制造严重后果。""",
            ]
            if item
        ),
    )
    _persist_memory(
        project_id=project_id,
        task_id=task_id,
        kind="architecture",
        title="冻结故事架构",
        content=architect.content,
    )

    context = _task_context(task_id, project_id)
    world = await _run_step(
        task_id=task_id,
        role="world-builder",
        stage="book-world-design",
        mode="continue",
        content=architect.content,
        instruction="\n\n".join(
            item
            for item in [
                context,
                """建立可被后续正文严格遵守的世界设定，不写正文。科幻题材必须按：科学假设 → 装置原理 → 事故机制 → 可观测现象 → 跨界规则 → 极限条件 → 结局成立条件。只允许极少数核心虚构假设，其余现象从假设推导。明确列出绝对禁止违反的规则。""",
            ]
            if item
        ),
    )
    _persist_memory(
        project_id=project_id,
        task_id=task_id,
        kind="world",
        title="冻结世界观与硬规则",
        content=world.content,
    )

    context = _task_context(task_id, project_id)
    characters = await _run_step(
        task_id=task_id,
        role="character-designer",
        stage="book-character-design",
        mode="continue",
        content=f"{architect.content}\n\n{world.content}",
        instruction="\n\n".join(
            item
            for item in [
                context,
                """设计核心人物，不写正文。每个人必须给出：表层目标、真正欲望、恐惧、秘密、历史错误、当前谎言、底线、会做出的错误选择、能伤害谁、会被谁伤害、与其他核心人物的直接矛盾、最终变化。禁止把反派写成纯误会，禁止所有人最后靠互相理解解决冲突。""",
            ]
            if item
        ),
    )
    _persist_memory(
        project_id=project_id,
        task_id=task_id,
        kind="character",
        title="冻结核心人物与矛盾",
        content=characters.content,
    )

    context = _task_context(task_id, project_id)
    outline = await _run_step(
        task_id=task_id,
        role="plot-planner",
        stage="book-outline",
        mode="continue",
        content=f"{architect.content}\n\n{world.content}\n\n{characters.content}",
        instruction="\n\n".join(
            item
            for item in [
                context,
                f"""把整本故事规划为恰好 {chapter_count} 章。每章必须使用一行标题格式：
[CHAPTER 01] 标题：xxxx
随后写：开场状态、人物目标、阻碍、冲突升级、揭示信息、错误选择或代价、转折、章末钩子。
每一章都必须改变人物关系或风险等级；世界设定必须通过事件与后果揭示，禁止人物集中讲课。第 {chapter_count} 章必须完成主要矛盾与核心伏笔回收。""",
            ]
            if item
        ),
    )
    _persist_memory(
        project_id=project_id,
        task_id=task_id,
        kind="outline",
        title=f"冻结 {chapter_count} 章整卷大纲",
        content=outline.content,
    )

    combined = (
        "# 故事架构\n\n"
        + architect.content
        + "\n\n# 世界观\n\n"
        + world.content
        + "\n\n# 人物\n\n"
        + characters.content
        + "\n\n# 章节大纲\n\n"
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
    return task_id


async def _run_frozen_chapter(
    *,
    task_id: int,
    chapter_number: int,
    prior_manuscript: str,
) -> dict:
    with connect() as conn:
        task = conn.execute(
            "SELECT * FROM writing_tasks WHERE id=?",
            (task_id,),
        ).fetchone()
        chapter = conn.execute(
            "SELECT * FROM chapters WHERE id=?",
            (task["chapter_id"],),
        ).fetchone()
        conn.execute(
            "UPDATE writing_tasks SET status='running',updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (task_id,),
        )
        conn.execute("DELETE FROM review_findings WHERE task_id=?", (task_id,))

    project_id = int(task["project_id"])
    context = _task_context(task_id, project_id)
    story_state = latest_story_state(
        project_id,
        before_chapter_number=chapter_number,
    )
    story_state_context = render_story_state(story_state)
    review_context = context + "\n\n" + story_state_context
    prior = prior_manuscript[-6000:] if prior_manuscript else "这是第一章，没有前文。"
    writer = await _run_step(
        task_id=task_id,
        role="writer",
        stage=f"chapter-{chapter_number:02d}-draft",
        mode="continue",
        content="",
        instruction="\n\n".join(
            [
                f"当前章节：第 {chapter_number} 章《{chapter['title']}》",
                task["goal"],
                task["instruction"],
                context,
                story_state_context,
                "最近前文片段（只负责语气、场景和章末承接；事实状态以 Story State 为准，不得复制前文）：\n" + prior,
                """严格从冻结章节大纲中定位当前章节节点，写出完整章节正文，并执行本次冻结的写作 Skill。Story State 中已经发生的伤势、知识、关系、道具消耗、地点损坏和伏笔状态都是不可逆历史，除非本章明确发生新的事件改变它。不得重复已经发生过的“第一次”、揭密、交接或跨界场景；不得提前消耗后续章节核心反转，不得新造世界规则。设定只能通过行动、环境、证据、冲突与后果出现。人物必须带着自己的秘密和利益行动。普通叙事不要默认切成碎短句；让动作、感觉、观察和人物关系形成完整语流。陌生术语首次出现必须落到读者能立即理解的语境中；对白必须有情绪目的和人物关系，禁止资料问答式推进。只输出当前章节正文，严禁复制前文章节。""",
            ]
        ),
    )

    enriched = await _run_step(
        task_id=task_id,
        role="scene-enricher",
        stage=f"chapter-{chapter_number:02d}-enrichment",
        mode="polish",
        content=writer.content,
        instruction=f"""{review_context}

不改变事件、规则、人物选择和伏笔，仅增强场景承载力：空间、声音、气味、光线、动作、停顿、潜台词、危险逼近和人物之间的压迫感。删掉可以被现场表现替代的解释性段落。只输出完整正文。""",
    )

    prose = await _run_step(
        task_id=task_id,
        role="prose-editor",
        stage=f"chapter-{chapter_number:02d}-prose",
        mode="polish",
        content=enriched.content,
        instruction=f"""{review_context}

只做语言层编辑，并严格执行本次冻结写作 Skill：改善长短句组合、节奏、意象、对白质感、信息密度和重复。重点清理连续碎短句/单句段落、只靠“不像A、也不像B”成立的空洞描写、第一次出现却没有落地解释的陌生术语、缺乏人物意图的功能性对白，以及高频“不是A，是B”等模型腔结构。优先使用具体、正向、可感知的形象，让情绪通过动作和关系发生。禁止新增/删除关键事件，禁止修改世界规则、人物动机、伏笔位置和结局方向。只输出完整正文。""",
    )
    draft, _ = await repair_repetition(
        task_id=task_id,
        chapter_number=chapter_number,
        draft=prose.content,
        prior_manuscript=prior_manuscript,
        story_state_context=story_state_context,
    )
    with connect() as conn:
        conn.execute(
            "UPDATE writing_tasks SET draft=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (draft, task_id),
        )

    first_reviews, _ = await _run_review_round(
        task_id=task_id,
        draft=draft,
        context=review_context,
        round_no=1,
    )
    context = _task_context(task_id, project_id)
    review_context = context + "\n\n" + story_state_context
    revision = await _run_step(
        task_id=task_id,
        role="revision-agent",
        stage=f"chapter-{chapter_number:02d}-revision-r1",
        mode="polish",
        content=draft,
        instruction="\n\n".join(
            [
                """根据五个独立 Reviewer 的结构化审核结果修订，并严格执行冻结的“小说精修流程” Skill。REWRITE_BLOCK 必须重建 Reviewer 指定范围；LOCAL_REWRITE 只修改最小必要范围；DELETE 直接删除无效内容；POLISH 只处理语言层。blocking 必须修复，禁止新增规则绕过问题，禁止越过 Reviewer 的修改边界，也不能把冲突改成所有人互相理解。保留事实锚点和未被指出问题的有效部分。只输出完整章节。""",
                "Reviewer 意见：\n" + "\n\n".join(first_reviews),
                review_context,
            ]
        ),
    )
    with connect() as conn:
        conn.execute(
            "UPDATE review_findings SET status='addressed' WHERE task_id=? AND status='open'",
            (task_id,),
        )

    second_reviews, second_blocking = await _run_review_round(
        task_id=task_id,
        draft=revision.content,
        context=review_context,
        round_no=2,
        prior_outputs=first_reviews,
    )
    context = _task_context(task_id, project_id)
    review_context = context + "\n\n" + story_state_context
    final_content = revision.content
    final_blocking = second_blocking
    if second_blocking:
        second_revision = await _run_step(
            task_id=task_id,
            role="revision-agent",
            stage=f"chapter-{chapter_number:02d}-revision-r2",
            mode="polish",
            content=revision.content,
            instruction="\n\n".join(
                [
                    """第二轮复审仍有 blocking。只处理复审结果为 FAIL 的原问题，沿用原问题的处置级别和修改边界；不得改动已经 PASS 的范围，不得破坏已经通过的世界规则、人物冲突和章节功能。只输出完整章节。""",
                    "第二轮 Reviewer 意见：\n" + "\n\n".join(second_reviews),
                    review_context,
                ]
            ),
        )
        final_content = second_revision.content
        with connect() as conn:
            conn.execute(
                "UPDATE review_findings SET status='addressed' WHERE task_id=? AND status='open'",
                (task_id,),
            )
        _, final_blocking = await _run_review_round(
            task_id=task_id,
            draft=final_content,
            context=review_context,
            round_no=3,
            prior_outputs=second_reviews,
        )

    final_repetition = repetition_report(final_content, prior_manuscript)
    if final_repetition["blocking"]:
        record_repetition_blocking(
            task_id=task_id,
            report=final_repetition,
        )
        from app.services.rejection_learning import learn_from_open_blocking_findings

        learn_from_open_blocking_findings(
            task_id=task_id,
            source="final-repetition-gate",
        )
        final_blocking = True

    if not final_blocking:
        try:
            await capture_story_state(
                task_id=task_id,
                project_id=project_id,
                chapter_id=int(chapter["id"]),
                chapter_number=chapter_number,
                chapter_content=final_content,
            )
        except ContinuityStateError as exc:
            final_blocking = True
            with connect() as conn:
                conn.execute(
                    """
                    INSERT INTO review_findings(
                        task_id,reviewer,category,severity,summary,suggestion,status
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        task_id,
                        "continuity-state-updater",
                        "continuity",
                        "blocking",
                        f"Story State 更新失败：{exc}",
                        "修复状态提取后才能继续生成下一章。",
                        "open",
                    ),
                )
        learn_from_open_blocking_findings(
            task_id=task_id,
            source="continuity-state-updater",
        )

    with connect() as conn:
        conn.execute(
            """
            UPDATE writing_tasks
            SET revised_content=?,status=?,updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (
                final_content,
                "reviewed" if final_blocking else "awaiting_approval",
                task_id,
            ),
        )
    return get_task(task_id) or {}


async def run_book_pipeline(
    *,
    project_id: int,
    goal: str,
    instruction: str,
    chapter_count: int,
) -> dict:
    _require_real_provider()
    if chapter_count < 1 or chapter_count > 30:
        raise ValueError("chapter_count must be between 1 and 30")

    with connect() as conn:
        project = conn.execute(
            "SELECT * FROM projects WHERE id=?",
            (project_id,),
        ).fetchone()
        if not project:
            raise ValueError("project not found")

    planning_task_id = await _plan_book(
        project_id=project_id,
        project_title=project["title"],
        genre=project["genre"],
        goal=goal,
        instruction=instruction,
        chapter_count=chapter_count,
    )
    with connect() as conn:
        outline = conn.execute(
            """
            SELECT content FROM memories
            WHERE project_id=? AND kind='outline' AND confirmed=1
            ORDER BY updated_at DESC,id DESC LIMIT 1
            """,
            (project_id,),
        ).fetchone()["content"]

    titles = _chapter_titles(outline, chapter_count)
    chapter_ids = _ensure_chapters(project_id, titles)

    task_ids: list[int] = []
    prior_manuscript = ""
    stopped_on_blocking = False
    for index, chapter_id in enumerate(chapter_ids, start=1):
        task_id = _create_task(
            project_id=project_id,
            chapter_id=chapter_id,
            goal=f"依据冻结整卷规划完成第 {index} 章候选稿",
            instruction=(
                f"这是第 {index}/{chapter_count} 章。必须遵守冻结架构、世界观、人物矛盾"
                "和整卷大纲；本轮不自动人工批准。"
            ),
        )
        task_ids.append(task_id)
        result = await _run_frozen_chapter(
            task_id=task_id,
            chapter_number=index,
            prior_manuscript=prior_manuscript,
        )
        candidate = str(result.get("revised_content") or result.get("draft") or "")
        prior_manuscript += (
            f"\n\n# 第 {index} 章 {titles[index - 1]}\n\n{candidate}"
        )
        if result.get("status") == "reviewed":
            stopped_on_blocking = True
            break

    return {
        "project_id": project_id,
        "planning_task_id": planning_task_id,
        "chapter_task_ids": task_ids,
        "planned_chapters": chapter_count,
        "generated_chapters": len(task_ids),
        "stopped_on_blocking": stopped_on_blocking,
        "status": "needs_revision" if stopped_on_blocking else "awaiting_human_approval",
    }
