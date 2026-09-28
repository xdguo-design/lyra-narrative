from __future__ import annotations

import re
from types import SimpleNamespace

from app.db import connect
from app.services.default_skills import BUILTIN_WRITER_TRAINING_SKILL_CONTENT
from app.services.workflow_service import (
    WorkflowStateError,
    _run_step,
    _task_context,
    get_task,
)

_LEVELS = {"NEEDS_WORK", "EMERGING", "STABLE", "TRANSFERABLE"}


def _diagnosed_level(text: str, label: str) -> str:
    match = re.search(
        rf"【{re.escape(label)}】\s*(NEEDS_WORK|EMERGING|STABLE|TRANSFERABLE)",
        text,
    )
    return match.group(1) if match else "NEEDS_WORK"


def _needs_coaching(level: str) -> bool:
    return level not in {"STABLE", "TRANSFERABLE"}


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
最后严格输出三行能力状态：
【场景导演】NEEDS_WORK / EMERGING / STABLE / TRANSFERABLE
【人物行为】NEEDS_WORK / EMERGING / STABLE / TRANSFERABLE
【语言节奏】NEEDS_WORK / EMERGING / STABLE / TRANSFERABLE
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

    scene_level = _diagnosed_level(diagnosis.content, "场景导演")
    if _needs_coaching(scene_level):
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
    else:
        scene_feedback = SimpleNamespace(
            content=f"SKIPPED_COACHING: 场景导演当前为 {scene_level}，保留练习卡并在综合/迁移阶段验证。"
        )
        scene_rewrite = scene_attempt

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

    behavior_level = _diagnosed_level(diagnosis.content, "人物行为")
    if _needs_coaching(behavior_level):
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
    else:
        behavior_feedback = SimpleNamespace(
            content=f"SKIPPED_COACHING: 人物行为当前为 {behavior_level}，保留练习并在综合/迁移阶段验证。"
        )
        behavior_rewrite = behavior_attempt

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

    rhythm_level = _diagnosed_level(diagnosis.content, "语言节奏")
    if _needs_coaching(rhythm_level):
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
    else:
        rhythm_feedback = SimpleNamespace(
            content=f"SKIPPED_COACHING: 语言节奏当前为 {rhythm_level}，保留练习并在综合/迁移阶段验证。"
        )
        rhythm_rewrite = rhythm_attempt

    reader_trace = await _training_step(
        task_id=task_id,
        role="blind-reader",
        stage="training-reader-trace",
        mode="check",
        content=rhythm_rewrite.content,
        instruction="""你是第一次读到这段文字的普通小说读者。你看不到人物卡、场景卡、作者意图、教练反馈和后续剧情，也不负责修改文本。
只根据眼前正文，严格输出：
READER_TRACE_V1
【我理解发生了什么】
【我理解人物各自想要什么】
【我理解关系发生了什么变化】
【我记住的最多3个细节】
【我不确定/需要回读的地方】
每一项必须标记为 INTENTIONAL_UNKNOWN / READER_GAP / AMBIGUOUS_GAP。
INTENTIONAL_UNKNOWN：我知道问题是什么，只是不知道答案。
READER_GAP：我连句子或动作在指什么都不能确定。
AMBIGUOUS_GAP：存在两个以上同样合理的解释。
【我认为正文故意留下的问题】
【我现在期待下一步发生什么】
如果某句话只有靠猜作者意图才能懂，必须放进“不确定/需要回读”，不要替作者补全。不要提供改写建议。""",
    )

    reader_gap = await _training_step(
        task_id=task_id,
        role="reader-gap-coach",
        stage="training-reader-gap",
        mode="check",
        content=rhythm_rewrite.content,
        instruction="\n\n".join(
            [
                training_rules,
                "作者侧 Scene Direction：\n" + scene_rewrite.content,
                "作者侧人物训练：\n" + behavior_attempt.content,
                "盲读者报告：\n" + reader_trace.content,
                """对照作者预期与读者实际理解，只判断 Reader Gap，不做一般润色。
重点分类 semantic-gap / causal-gap / motivation-gap / relationship-gap / salience-gap / suspense-gap / emotion-gap。
有意悬念可以保留，但读者必须清楚自己“不知道什么”；若读者连句子在说什么、人物为什么这样做、关系为何变化都需要作者材料才能理解，则必须打回。严格执行 Reader Gate v3：只有 INTENTIONAL_UNKNOWN 可直接 PASS；READER_GAP 必须修改；AMBIGUOUS_GAP 只有当多个解释均为作者有意设计且不影响当前理解时才可 PASS，否则修改。
若完全没有需要改正文的 Reader Gap，只输出 NO_READER_GAP。
若有问题，最多输出3项，每项必须含：类型、逐字片段、读者实际理解、作者预期、为什么属于信息缺失而非有效留白、重写边界。""",
            ]
        ),
    )

    if reader_gap.content.strip() == "NO_READER_GAP":
        reader_rewrite = rhythm_rewrite
    else:
        reader_rewrite = await _training_step(
            task_id=task_id,
            role="writer-trainee",
            stage="training-reader-rewrite",
            mode="polish",
            content=rhythm_rewrite.content,
            instruction="\n\n".join(
                [
                    reader_gap.content,
                    """只修 Reader Gap。不得改变事实、人物动机、信息顺序和节奏训练已经成立的部分。
目标不是多解释，而是补足一次阅读必需的语义支点、对象、因果或关系动作。有效悬念继续保留。
只输出完整训练片段。""",
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
                reader_gap.content,
                """执行阶段 F 综合训练。基于同一作品事实，重新写一个 900—1600 字完整场景。
必须同时应用：场景取舍、POV过滤、人物行为阈值、潜台词、句群节奏。
不得复制前面训练片段句子，不得新增关键线索，不得用总结句证明自己“学会了”。只输出正文。""",
            ]
        ),
    )

    integrated_reader_trace = await _training_step(
        task_id=task_id,
        role="blind-reader",
        stage="training-integrated-reader-trace",
        mode="check",
        content=integrated_scene.content,
        instruction="""你是第一次读到这段完整场景的普通小说读者。你不知道作者计划和训练目标。
严格输出 READER_TRACE_V1：
【我理解发生了什么】
【我理解人物各自想要什么】
【我理解关系发生了什么变化】
【我记住的最多3个细节】
【我不确定/需要回读的地方】
每一项必须标记为 INTENTIONAL_UNKNOWN / READER_GAP / AMBIGUOUS_GAP。
INTENTIONAL_UNKNOWN：我知道问题是什么，只是不知道答案。
READER_GAP：我连句子或动作在指什么都不能确定。
AMBIGUOUS_GAP：存在两个以上同样合理的解释。
【我认为正文故意留下的问题】
【我现在期待下一步发生什么】
不要给改写建议，不要替作者脑补。""",
    )

    integrated_reader_gap = await _training_step(
        task_id=task_id,
        role="reader-gap-coach",
        stage="training-integrated-reader-gap",
        mode="check",
        content=integrated_scene.content,
        instruction="\n\n".join(
            [
                training_rules,
                "Scene Direction：\n" + scene_rewrite.content,
                "Blind Reader：\n" + integrated_reader_trace.content,
                """只判断作者预期与盲读结果之间是否存在必须修改的 Reader Gap。
若没有，只输出 NO_READER_GAP；若有，最多3项，按 semantic / causal / motivation / relationship / salience / suspense / emotion 分类，并给逐字片段和修改边界。""",
            ]
        ),
    )

    if integrated_reader_gap.content.strip() == "NO_READER_GAP":
        integrated_final = integrated_scene
    else:
        integrated_final = await _training_step(
            task_id=task_id,
            role="writer-trainee",
            stage="training-integrated-reader-rewrite",
            mode="polish",
            content=integrated_scene.content,
            instruction="\n\n".join(
                [
                    integrated_reader_gap.content,
                    """只修 Reader Gap，不做额外润色，不增加剧情、线索或解释性总结。保留已经成立的人物行为、场景结构和节奏。只输出完整正文。""",
                ]
            ),
        )

    integrated_reader_recheck = await _training_step(
        task_id=task_id,
        role="blind-reader",
        stage="training-integrated-reader-recheck",
        mode="check",
        content=integrated_final.content,
        instruction="""再次作为不知道任何作者意图的首次读者阅读。输出 READER_TRACE_V1，并明确列出仍需要回读或无法确定语义的地方。不要给修改建议。""",
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
                    """生成阶段 G 迁移测试题，不写答案。
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

    transfer_reader_trace = await _training_step(
        task_id=task_id,
        role="blind-reader",
        stage="training-transfer-reader-trace",
        mode="check",
        content=transfer_scene.content,
        instruction="""你是第一次读到迁移测试场景的普通小说读者，不知道训练目标、人物卡或作者计划。
输出 READER_TRACE_V1：
【我理解发生了什么】
【我理解人物各自想要什么】
【我理解关系发生了什么变化】
【我记住的最多3个细节】
【我不确定/需要回读的地方】
每一项必须标记为 INTENTIONAL_UNKNOWN / READER_GAP / AMBIGUOUS_GAP。
INTENTIONAL_UNKNOWN：我知道问题是什么，只是不知道答案。
READER_GAP：我连句子或动作在指什么都不能确定。
AMBIGUOUS_GAP：存在两个以上同样合理的解释。
【我认为正文故意留下的问题】
【我现在期待下一步发生什么】
不要提出修改方案。""",
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
                "迁移测试盲读者报告：\n" + transfer_reader_trace.content,
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
                reader_trace.content,
                reader_gap.content,
                integrated_reader_trace.content,
                integrated_reader_gap.content,
                integrated_reader_recheck.content,
                transfer_reader_trace.content,
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
        "reader_gate": {
            "trace": reader_trace.content,
            "gap": reader_gap.content,
            "rewrite": reader_rewrite.content,
        },
        "integrated_scene": {
            "draft": integrated_scene.content,
            "reader_trace": integrated_reader_trace.content,
            "reader_gap": integrated_reader_gap.content,
            "final": integrated_final.content,
            "reader_recheck": integrated_reader_recheck.content,
        },
        "transfer": {
            "brief": transfer_case,
            "scene": transfer_scene.content,
            "reader_trace": transfer_reader_trace.content,
            "review": transfer_review.content,
        },
        "writer_craft_profile": profile.content,
    }
