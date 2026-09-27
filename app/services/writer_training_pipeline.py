from __future__ import annotations

from app.db import connect
from app.services.default_skills import BUILTIN_WRITER_TRAINING_SKILL_CONTENT
from app.services.workflow_service import (
    WorkflowStateError,
    _run_step,
    _task_context,
    get_task,
)


def _training_source(task: dict, explicit_source: str) -> str:
    if explicit_source.strip():
        return explicit_source.strip()
    draft = str(task.get("draft") or "").strip()
    if draft:
        return draft
    chapter_id = task.get("chapter_id")
    if chapter_id is None:
        raise WorkflowStateError(
            "writer training requires source text, a task draft, or a linked chapter"
        )
    with connect() as conn:
        row = conn.execute(
            "SELECT content FROM chapters WHERE id=? AND project_id=?",
            (chapter_id, task["project_id"]),
        ).fetchone()
    content = str(row["content"] or "").strip() if row else ""
    if not content:
        raise WorkflowStateError(
            "writer training requires non-empty source text"
        )
    return content


def _persist_writer_profile(
    *,
    project_id: int,
    task_id: int,
    content: str,
) -> None:
    source_ref = "writer-training:craft-profile"
    with connect() as conn:
        existing = conn.execute(
            """
            SELECT id
            FROM memories
            WHERE project_id=? AND source_ref=?
            ORDER BY id
            LIMIT 1
            """,
            (project_id, source_ref),
        ).fetchone()
        if existing:
            version = conn.execute(
                """
                SELECT COALESCE(MAX(version),0)+1 AS next_version
                FROM memory_versions
                WHERE memory_id=?
                """,
                (existing["id"],),
            ).fetchone()["next_version"]
            conn.execute(
                """
                UPDATE memories
                SET kind='writer-training',
                    title='Writer Craft Profile',
                    content=?,
                    confirmed=1,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (content, existing["id"]),
            )
            conn.execute(
                """
                INSERT INTO memory_versions(
                    memory_id,version,kind,title,content,confirmed,note
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    existing["id"],
                    version,
                    "writer-training",
                    "Writer Craft Profile",
                    content,
                    1,
                    f"Writer training task #{task_id}",
                ),
            )
            return

        cur = conn.execute(
            """
            INSERT INTO memories(
                project_id,kind,title,content,source_type,source_ref,confirmed
            ) VALUES(?,?,?,?,?,?,1)
            """,
            (
                project_id,
                "writer-training",
                "Writer Craft Profile",
                content,
                "agent",
                source_ref,
            ),
        )
        conn.execute(
            """
            INSERT INTO memory_versions(
                memory_id,version,kind,title,content,confirmed,note
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (
                cur.lastrowid,
                1,
                "writer-training",
                "Writer Craft Profile",
                content,
                1,
                f"Writer training task #{task_id}",
            ),
        )


async def _training_step(
    *,
    task_id: int,
    role: str,
    stage: str,
    mode: str,
    content: str,
    instruction: str,
):
    result = await _run_step(
        task_id=task_id,
        role=role,
        stage=stage,
        mode=mode,
        content=content,
        instruction=instruction,
    )
    if result.demo:
        raise WorkflowStateError(
            "writer training requires a real AI provider; demo/mock output is not a valid training result"
        )
    return result


async def run_writer_training(
    task_id: int,
    *,
    source: str = "",
    transfer_brief: str = "",
) -> dict:
    task = get_task(task_id)
    if not task:
        raise ValueError("task not found")

    project_id = int(task["project_id"])
    source_text = _training_source(task, source)
    context = _task_context(task_id, project_id)
    training_rules = BUILTIN_WRITER_TRAINING_SKILL_CONTENT

    diagnosis = await _training_step(
        task_id=task_id,
        role="writer-coach",
        stage="training-diagnosis",
        mode="check",
        content=source_text,
        instruction="\n\n".join(
            [
                context,
                training_rules,
                """执行阶段 A 基线诊断。只选最多 3 个会反复影响长篇质量的高杠杆能力问题，必须引用当前文本中的具体证据。
输出格式：
WRITER_TRAINING_DIAGNOSIS_V1
【高杠杆问题1】...
【证据】...
【影响】...
【训练目标】...
最多三项。
最后分别判断：场景导演 / 人物行为 / 语言节奏 当前为 NEEDS_WORK、EMERGING、STABLE 中哪一级。
禁止改写正文，禁止给范文。""",
            ]
        ),
    )

    scene_attempt = await _training_step(
        task_id=task_id,
        role="writer-trainee",
        stage="training-scene-direction-attempt",
        mode="continue",
        content=source_text,
        instruction="\n\n".join(
            [
                context,
                training_rules,
                diagnosis.content,
                """只做阶段 B：根据当前文本反推并重做一张 Scene Direction Card，不写正文。
必须包含：核心张力、POV过滤、3个以内主细节、主动忽略项、快写区、慢写区、人物距离变化、结束状态、近期套路禁用项。
重点不是补得更全，而是做取舍。""",
            ]
        ),
    )

    scene_feedback = await _training_step(
        task_id=task_id,
        role="scene-coach",
        stage="training-scene-direction-feedback",
        mode="check",
        content=scene_attempt.content,
        instruction="\n\n".join(
            [
                training_rules,
                diagnosis.content,
                """批改 Scene Direction Card。最多指出 3 个问题，每个问题必须说明：哪里没有做取舍、为什么会让正文平均用力/视角漂移/节奏失焦、下一次重写只需要改什么。
禁止替 Writer 直接写一张更好的卡。""",
            ]
        ),
    )

    scene_rewrite = await _training_step(
        task_id=task_id,
        role="writer-trainee",
        stage="training-scene-direction-rewrite",
        mode="continue",
        content=scene_attempt.content,
        instruction="\n\n".join(
            [
                training_rules,
                scene_feedback.content,
                """根据教练意见重写 Scene Direction Card。只解决指出的问题，不扩大设定，不新增关键线索。输出完整修订卡。""",
            ]
        ),
    )

    behavior_attempt = await _training_step(
        task_id=task_id,
        role="writer-trainee",
        stage="training-character-behavior-attempt",
        mode="continue",
        content=source_text,
        instruction="\n\n".join(
            [
                context,
                training_rules,
                scene_rewrite.content,
                """执行阶段 C。
第一部分先输出 Behavior Matrix：对当前核心在场人物分别写目标、恐惧/秘密、筹码、身份位置、第一反应、回避方式、承认阈值、最大让步。
第二部分写一个 500—900 字的训练片段，只重写当前文本里人物攻防最集中的一小场。禁止解释人物在试探或撒谎，必须让行为和对白自己成立；至少一人不合作；信息分层释放。""",
            ]
        ),
    )

    behavior_feedback = await _training_step(
        task_id=task_id,
        role="character-coach",
        stage="training-character-behavior-feedback",
        mode="check",
        content=behavior_attempt.content,
        instruction="\n\n".join(
            [
                context,
                training_rules,
                """只批改人物行为训练。最多 3 个高影响问题。
重点检查：人物是否按卡行动、是否因为剧情需要突然老实/变笨/变聪明、对白是否退化为问答表、不同人物声音是否可区分、信息是否有承认阈值。
每项给原文证据和明确重写目标，不提供范文。""",
            ]
        ),
    )

    behavior_rewrite = await _training_step(
        task_id=task_id,
        role="writer-trainee",
        stage="training-character-behavior-rewrite",
        mode="polish",
        content=behavior_attempt.content,
        instruction="\n\n".join(
            [
                training_rules,
                behavior_feedback.content,
                """重写训练片段与必要的 Behavior Matrix。必须保留原场景事实和结果，只修人物行为、信息释放和人物声音。输出 Behavior Matrix + 完整训练片段。""",
            ]
        ),
    )

    rhythm_attempt = await _training_step(
        task_id=task_id,
        role="writer-trainee",
        stage="training-rhythm-attempt",
        mode="polish",
        content=behavior_rewrite.content,
        instruction="\n\n".join(
            [
                training_rules,
                """执行阶段 D 语言节奏训练。不得改变事实、人物意图和信息顺序。
先标出 2—4 个句群的节奏目的（例如：进入/承接/加压/停顿/落点），再重写训练片段。
重点训练：3—5句句群起伏、句法变化、动作/对白/观察交替、关键处慢半拍、过渡处敢压缩、情绪少说半句、段尾不总结。
不要为了变化使用怪句式或堆比喻。""",
            ]
        ),
    )

    rhythm_feedback = await _training_step(
        task_id=task_id,
        role="rhythm-coach",
        stage="training-rhythm-feedback",
        mode="check",
        content=rhythm_attempt.content,
        instruction="\n\n".join(
            [
                training_rules,
                """只批改语言节奏。最多 3 个问题，必须按句群而不是孤立句判断。
检查：是否仍连续同句法、是否靠大量单句段制造假节奏、该快处拖、该慢处跳、情绪说满、人物口语被统一抛光。
给证据和重写目标，不提供整段范文。""",
            ]
        ),
    )

    rhythm_rewrite = await _training_step(
        task_id=task_id,
        role="writer-trainee",
        stage="training-rhythm-rewrite",
        mode="polish",
        content=rhythm_attempt.content,
        instruction="\n\n".join(
            [
                training_rules,
                rhythm_feedback.content,
                """按教练反馈做最后一次定向重写。只处理语言节奏和留白，不改变事实、因果、人物行为和信息顺序。输出完整训练片段。""",
            ]
        ),
    )

    integrated_scene = await _training_step(
        task_id=task_id,
        role="writer-trainee",
        stage="training-integrated-scene",
        mode="continue",
        content=source_text,
        instruction="\n\n".join(
            [
                context,
                training_rules,
                diagnosis.content,
                scene_rewrite.content,
                behavior_feedback.content,
                rhythm_feedback.content,
                """执行阶段 E 综合训练。基于同一作品事实，重新写一个 900—1600 字完整场景。
必须同时应用：场景取舍、POV过滤、人物行为阈值、潜台词、句群节奏。
不得复制前面训练片段句子，不得新增关键线索，不得用总结句证明自己“学会了”。只输出正文。""",
            ]
        ),
    )

    if transfer_brief.strip():
        transfer_case = transfer_brief.strip()
    else:
        examiner = await _training_step(
            task_id=task_id,
            role="training-examiner",
            stage="training-transfer-brief",
            mode="continue",
            content=source_text,
            instruction="\n\n".join(
                [
                    context,
                    training_rules,
                    """生成阶段 F 迁移测试题，不写答案。
要求：仍在同一作品世界，优先使用已存在人物；改变地点、即时目标或关系压力；不得复用当前训练文本的关键动作、证据、台词和章尾结构。
题目必须能同时测试：场景取舍、人物行为、语言节奏。
控制在 250 字以内。""",
                ]
            ),
        )
        transfer_case = examiner.content

    transfer_scene = await _training_step(
        task_id=task_id,
        role="writer-trainee",
        stage="training-transfer-attempt",
        mode="continue",
        content=transfer_case,
        instruction="\n\n".join(
            [
                context,
                training_rules,
                """这是迁移测试。不要查看或复述上一轮教练的具体改句，只使用你已经提炼出的写作原则。
写 800—1400 字完整场景，保持现有人物卡与作品事实，不新增关键世界规则。只输出正文。""",
            ]
        ),
    )

    transfer_review = await _training_step(
        task_id=task_id,
        role="training-examiner",
        stage="training-transfer-review",
        mode="check",
        content=transfer_scene.content,
        instruction="\n\n".join(
            [
                context,
                training_rules,
                diagnosis.content,
                """盲审迁移测试。分别判断：
- 场景导演：NEEDS_WORK / EMERGING / STABLE / TRANSFERABLE
- 人物行为：NEEDS_WORK / EMERGING / STABLE / TRANSFERABLE
- 语言节奏：NEEDS_WORK / EMERGING / STABLE / TRANSFERABLE
每项必须引用新场景证据。
重点检查基线问题是否在新场景复发。不要因为文字顺就判通过，不给总分。""",
            ]
        ),
    )

    profile = await _training_step(
        task_id=task_id,
        role="writer-coach",
        stage="training-profile",
        mode="check",
        content="\n\n".join(
            [
                diagnosis.content,
                scene_feedback.content,
                behavior_feedback.content,
                rhythm_feedback.content,
                transfer_review.content,
            ]
        ),
        instruction="\n\n".join(
            [
                training_rules,
                """蒸馏为 Writer Craft Profile。不要复述全部训练过程。
严格输出：
WRITER_CRAFT_PROFILE_V1
【稳定能力 STABLE】
- ...
【不稳定能力 EMERGING】
- ...
【待训练 NEEDS_WORK】
- ...
【可迁移 TRANSFERABLE】
- ...
【高频失败模式】
- ...
【下一轮训练】
- 最多2项
【正式写作激活规则】
- 最多6条，每条一句、可执行
不得记录作品剧情秘密，不得修改人物卡和世界设定。""",
            ]
        ),
    )

    _persist_writer_profile(
        project_id=project_id,
        task_id=task_id,
        content=profile.content,
    )

    return {
        "task_id": task_id,
        "project_id": project_id,
        "diagnosis": diagnosis.content,
        "scene_direction": {
            "attempt": scene_attempt.content,
            "feedback": scene_feedback.content,
            "rewrite": scene_rewrite.content,
        },
        "character_behavior": {
            "attempt": behavior_attempt.content,
            "feedback": behavior_feedback.content,
            "rewrite": behavior_rewrite.content,
        },
        "language_rhythm": {
            "attempt": rhythm_attempt.content,
            "feedback": rhythm_feedback.content,
            "rewrite": rhythm_rewrite.content,
        },
        "integrated_scene": integrated_scene.content,
        "transfer": {
            "brief": transfer_case,
            "scene": transfer_scene.content,
            "review": transfer_review.content,
        },
        "writer_craft_profile": profile.content,
    }
