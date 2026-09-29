from __future__ import annotations

import asyncio
import os

from app.db import connect
from app.services.default_skills import (
    BUILTIN_READER_REVIEW_SKILL_CONTENT,
    BUILTIN_READER_REVIEW_SKILL_NAME,
)
from app.services.rejection_learning import learn_from_open_blocking_findings
from app.services.workflow_service import (
    WorkflowStateError,
    _parse_review_output,
    _run_step,
    _task_context,
    get_task,
)


def _require_real_provider() -> None:
    kind = os.getenv("NOVEL_AI_KIND", "demo").strip().lower()
    if kind in {"", "demo", "mock"}:
        raise WorkflowStateError(
            "full novel pipeline requires a real AI provider; demo/mock is not allowed"
        )


def _recent_chapter_window(project_id: int, current_position: int | None) -> str:
    if current_position is None:
        return ""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT position,title,content
            FROM chapters
            WHERE project_id=? AND position<?
            ORDER BY position DESC
            LIMIT 2
            """,
            (project_id, current_position),
        ).fetchall()
    if not rows:
        return ""
    rows = list(reversed(rows))
    return "\n\n".join(
        f"【前章 {row['position']}｜{row['title']}】\n{row['content']}"
        for row in rows
    )


def _task_reader_skill_content(task_id: int) -> str:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT sv.content
            FROM writing_task_skills wts
            JOIN skills s ON s.id=wts.skill_id
            JOIN skill_versions sv
              ON sv.skill_id=wts.skill_id AND sv.version=wts.version
            WHERE wts.task_id=? AND s.name=?
            ORDER BY s.project_id IS NOT NULL DESC,s.id
            LIMIT 1
            """,
            (task_id, BUILTIN_READER_REVIEW_SKILL_NAME),
        ).fetchone()
        if row:
            return str(row["content"])

        latest = conn.execute(
            """
            SELECT content
            FROM skills
            WHERE project_id IS NULL AND name=? AND enabled=1
            ORDER BY current_version DESC,id
            LIMIT 1
            """,
            (BUILTIN_READER_REVIEW_SKILL_NAME,),
        ).fetchone()
    return (
        str(latest["content"])
        if latest
        else BUILTIN_READER_REVIEW_SKILL_CONTENT
    )


def _active_character_cards(
    project_id: int,
    draft: str,
    limit: int = 8,
) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id,name,role,profile,tags
            FROM characters
            WHERE project_id=?
            ORDER BY id
            """,
            (project_id,),
        ).fetchall()

    active = [
        dict(row)
        for row in rows
        if str(row["name"] or "").strip()
        and str(row["name"]).strip() in draft
    ]
    active.sort(
        key=lambda item: (
            -draft.count(str(item["name"])),
            int(item["id"]),
        )
    )
    return active[:limit]


def _character_voice_instruction(
    character: dict,
    recent_chapter_window: str,
) -> str:
    name = str(character["name"])
    role = str(character.get("role") or "").strip()
    profile = str(character.get("profile") or "").strip()
    tags = str(character.get("tags") or "").strip()
    card = "\n".join(
        item
        for item in [
            f"姓名：{name}",
            f"身份/角色：{role}" if role else "",
            f"角色卡：{profile}" if profile else "",
            f"标签：{tags}" if tags and tags != "[]" else "",
        ]
        if item
    )
    return "\n\n".join(
        item
        for item in [
            f"""你现在不是通用 Reviewer，而是【{name}】的 Character Voice Reviewer。
你只能审核【{name}】在当前正文里说出的台词，以及紧邻这些台词、会改变说话方式的动作/关系压力。
你的判断标准不是“这句话意思对不对”，而是“以我的身份、脾气、关系、利益和此刻压力，我真的会这么说吗”。

角色卡：
{card}

硬规则：
1. 当前正文中属于【{name}】的每一句对白都必须逐句列出，PASS 也要列；不得只挑明显问题。
2. 做“说出口测试”：逻辑正确、证据边界正确、人物显得聪明，都不能替代口语自然。
3. 若一句话过度工整、对称、像作者总结、像规章、像金句、像为了证明人物聪明/专业而写，必须 FAIL。
4. 若角色卡较薄，只能依据正文已经建立的身份、关系、行为和前章表现判断；不得凭空发明方言、口头禅或背景。
5. 不得修改剧情、事实、证据边界、人物权限和行动结果。更自然说法只能改台词表达。
6. 熟人关系必须带关系记忆；上下级、同级、陌生人说话方式不能互换。
7. 任何一条关键对白 FAIL，则总 VERDICT 必须 FAIL。

严格输出：
CHARACTER_VOICE_REVIEW_V1
CHARACTER: {name}
VERDICT: PASS 或 VERDICT: FAIL

对每一句属于【{name}】的对白依次输出：
【原句】逐字原句
【角色判断】PASS / FAIL
【标签】ORALITY_GAP / VOICE_OVERPERFORMANCE_GAP / DIALOGUE_VOICE_GAP / RELATIONSHIP_VOICE_GAP / OVER_RATIONAL_DIALOGUE_GAP / NONE
【为什么像/不像我】一句到三句
【更自然说法】FAIL 时给一版；PASS 时写 KEEP
【必须保留】这句承担的事实、关系、权限或情绪功能

最后输出：
【整体声音】一句话概括当前章节里【{name}】的声音是否稳定。
【不得触碰】列出修订时不能破坏的角色边界。""",
            (
                "【前章窗口，仅用于关系记忆和既有说话方式】\n"
                + recent_chapter_window
                if recent_chapter_window
                else ""
            ),
        ]
        if item
    )


def _persist_memory(
    *,
    project_id: int,
    task_id: int,
    kind: str,
    title: str,
    content: str,
) -> None:
    source_ref = f"full-pipeline:{task_id}:{kind}"
    with connect() as conn:
        existing = conn.execute(
            "SELECT * FROM memories WHERE project_id=? AND source_ref=?",
            (project_id, source_ref),
        ).fetchone()
        if existing:
            version = conn.execute(
                "SELECT COALESCE(MAX(version),0)+1 AS next_version FROM memory_versions WHERE memory_id=?",
                (existing["id"],),
            ).fetchone()["next_version"]
            conn.execute(
                """
                UPDATE memories
                SET kind=?,title=?,content=?,confirmed=1,updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (kind, title, content, existing["id"]),
            )
            conn.execute(
                """
                INSERT INTO memory_versions(memory_id,version,kind,title,content,confirmed,note)
                VALUES(?,?,?,?,?,?,?)
                """,
                (
                    existing["id"],
                    version,
                    kind,
                    title,
                    content,
                    1,
                    f"Full novel pipeline task #{task_id}",
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
                kind,
                title,
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
                kind,
                title,
                content,
                1,
                f"Full novel pipeline task #{task_id}",
            ),
        )


def _review_contract(round_no: int) -> str:
    if round_no <= 1:
        return """NARRATIVEOS_REVIEW_V3
审核轮次：INITIAL。请严格按“小说精修流程 v9”的 Reviewer 统一审核输出格式执行。
每个问题一块，多个问题用单独一行 --- 分隔；没有问题只输出 NO_ISSUE。
必须包含：问题标识、严重性、处置级别、问题类型、问题定位、逐字片段、问题说明、判级理由、修改边界、必须保留事实、禁止新增内容、执行目标、建议动作、复审要求、复审结果=PENDING。
处置级别只能是 REWRITE_BLOCK / LOCAL_REWRITE / DELETE / POLISH / PASS。
REWRITE_BLOCK 必须解释为什么 LOCAL_REWRITE 不足；影响事实、因果或人物意图的问题不得降级为 POLISH。"""
    return """NARRATIVEOS_REVIEW_V3
审核轮次：RECHECK。你正在复审上一轮由同一 Reviewer 提出的问题。
必须沿用原问题标识，逐条检查原问题是否消失，不得用新问题替代原 blocking。
输出必须包含：原问题标识、原处置级别、问题类型、原问题定位、本次复审范围、复审检查、复审发现、复审结果 PASS/FAIL、后续处置、再次打回原因。
复审检查至少覆盖：事实锚点、因果链、人物动机、修改边界、禁止新增内容、原问题是否消失、是否产生新的 blocking。
若原问题全部解决且无新 blocking，可以输出 NO_ISSUE。"""


async def _run_revision_integrity_gate(
    *,
    task_id: int,
    before: str,
    after: str,
    context: str,
    round_no: int,
) -> tuple[str, bool]:
    result = await _run_step(
        task_id=task_id,
        role="revision-integrity-reviewer",
        stage=f"revision-integrity-r{round_no}",
        mode="check",
        content="\n\n".join(
            [
                "=== BEFORE REVISION ===",
                before,
                "=== AFTER REVISION ===",
                after,
            ]
        ),
        instruction="\n\n".join(
            [
                """你是 Revision Integrity Reviewer。你同时看到修改前与修改后正文。不要评价哪版更漂亮，只检查局部/整段修订是否破坏原场景功能与前后接口。

先从 BEFORE 提取 Narrative Function Contract：
1. 读者在这一段/场景结束前必须新知道什么；
2. 必须在这里确认的身份、关系、规则、时空或世界状态；
3. 必须发生的决定、关系变化或行动结果；
4. AFTER 后文继续依赖哪些已建立前提。

再比较 AFTER。

强制检查两类失败：
A. SCENE_FUNCTION_DRIFT
- 原本必须落地的认知、身份、关系、规则、决定或接口被删掉；
- 后文继续使用一个 AFTER 已没有建立的前提；
- 为了改善人物/语言/节奏而牺牲场景入口功能。

B. LOCAL_REWRITE_SEAM_GAP
- 同一个问题在修改块后又重新问一次；
- 同一事实被再次当作首次介绍；
- 同一决定/关系变化重复发生；
- 手中物、站位、伤势、情绪、空间状态被重置；
- 新修改提前了信息，但旧后文没有同步去重；
- 两段各自成立，拼接后出现“刚才不是已经说过/做过了吗”的阅读感。

严格输出：
REVISION_INTEGRITY_V1
VERDICT: PASS 或 VERDICT: FAIL
【Narrative Function Contract】
- 必须完成的读者认知：
- 必须确认的身份/关系/规则：
- 必须发生的状态变化：
- 后文依赖接口：
【Scene Function】PASS / FAIL
【Seam】PASS / FAIL
【失败标签】SCENE_FUNCTION_DRIFT / LOCAL_REWRITE_SEAM_GAP / NONE
【逐字证据】
【最小修复范围】
【不得触碰范围】

只要 Scene Function 或 Seam 任一 FAIL，VERDICT 必须 FAIL。
不得因为“事实在项目设定里仍然存在”而放过正文功能丢失。""",
                context,
            ]
        ),
    )
    failed = "VERDICT: PASS" not in result.content.upper()
    if failed:
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO review_findings(
                    task_id,reviewer,category,severity,summary,suggestion,status
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    task_id,
                    "revision-integrity-reviewer",
                    "revision-integrity",
                    "blocking",
                    result.content,
                    "恢复 Narrative Function Contract，并执行前后 Seam 去重/连续性修复；不得以继续扩大改写代替接口修复。",
                    "open",
                ),
            )
        learn_from_open_blocking_findings(
            task_id=task_id,
            source=f"revision-integrity-r{round_no}",
        )
    return result.content, failed


async def _safe_review_task(coro, label: str):
    try:
        result = await coro
        return {"ok": True, "label": label, "result": result, "error": ""}
    except Exception as exc:
        return {
            "ok": False,
            "label": label,
            "result": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


async def _run_review_round(
    *,
    task_id: int,
    draft: str,
    context: str,
    round_no: int,
    prior_outputs: list[str] | None = None,
    auto_learn: bool = True,
) -> tuple[list[str], bool]:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT wt.project_id,c.position
            FROM writing_tasks wt
            LEFT JOIN chapters c ON c.id=wt.chapter_id
            WHERE wt.id=?
            """,
            (task_id,),
        ).fetchone()
    recent_chapter_window = (
        _recent_chapter_window(
            int(row["project_id"]),
            int(row["position"]) if row and row["position"] is not None else None,
        )
        if row
        else ""
    )
    reader_skill_content = _task_reader_skill_content(task_id)

    character_cards = (
        _active_character_cards(int(row["project_id"]), draft)
        if row
        else []
    )
    character_voice_tasks = [
        asyncio.create_task(
            _run_step(
                task_id=task_id,
                role="character-voice-reviewer",
                stage=f"character-voice-r{round_no}-{int(character['id'])}",
                mode="check",
                content=draft,
                instruction=_character_voice_instruction(
                    character,
                    recent_chapter_window,
                ),
            )
        )
        for character in character_cards
    ]

    reader_trace_task = asyncio.create_task(_run_step(
        task_id=task_id,
        role="blind-reader",
        stage=f"reader-trace-r{round_no}",
        mode="check",
        content=draft,
        instruction="""你是第一次阅读这一章的普通小说读者。你看不到人物卡、世界设定、场景设计、作者意图、Reviewer意见或后续剧情。
不要修改正文，也不要替作者补全。
严格输出：
READER_TRACE_V1
【我理解发生了什么】
【我理解主要人物各自想要什么】
【我理解关系发生了什么变化】
【我记住的最多3个细节】
【我不确定/需要回读的地方】
每一项必须标记为 INTENTIONAL_UNKNOWN / READER_GAP / AMBIGUOUS_GAP。
INTENTIONAL_UNKNOWN：知道问题是什么，只是不知道答案。
READER_GAP：不知道句子或动作在指什么。
AMBIGUOUS_GAP：存在两个以上同样合理解释。
【我认为正文故意留下的问题】
【我现在期待下一步发生什么】
任何需要依靠作者背景材料才能解释的句子，都必须记录在“不确定/需要回读”。""",
    ))

    dialogue_reader_task = asyncio.create_task(_run_step(
        task_id=task_id,
        role="blind-dialogue-reader",
        stage=f"reader-dialogue-r{round_no}",
        mode="check",
        content=draft,
        instruction="\n\n".join(
            [
                reader_skill_content,
                """你现在只执行 Reader B 的“人物 / 关系 / 对话真实性”检查。你只看正文，不看人物卡、作者意图、Scene Card、Reviewer 意见和后续剧情，也不要替作者润色。

必须覆盖 B01—B27，重点不是对白长短，而是“这是不是两个具体的人在说话，而且他们有身体、有关系记忆、有面子、有情绪余波，也不会像机器人一样轮流准确回答”。

新增硬门槛：逻辑正确 ≠ 口语自然。对每条关键台词做“说出口测试”：这个人物在当前身份、关系、压力和场景里，真的会这么说吗？若台词过度工整、对称、像作者总结、像金句、像规章，或需要先在脑中翻译成自然说法，必须标 ORALITY_GAP；若人物声音明显在表演“聪明/克制/专业”，并检查 VOICE_OVERPERFORMANCE_GAP。不能因为信息准确或证据边界正确而 PASS。

严格输出：
DIALOGUE_AUTHENTICITY_V1
VERDICT: PASS 或 VERDICT: FAIL
【场景目标A】
【场景目标B】
【去名字测试】PASS / FAIL
【换人测试】PASS / FAIL
【声音指纹】
【关系痕迹】
【信息所有权】
【非合作/回避方式】
【对话后状态变化】
【身体/表情/并行任务】
【非语言指纹】
【空间关系】
【自我形象/面子】
【关系记忆】
【话轮是否过度对称】
【情绪余波】
【感知指纹】
【失败标签】DIALOGUE_VOICE_GAP / DIALOGUE_FUNCTIONAL_GAP / RELATIONSHIP_VOICE_GAP / DIALOGUE_PRESSURE_GAP / DIALOGUE_STATELESS_GAP / EMBODIED_DIALOGUE_GAP / GENERIC_ACTION_GAP / OVER_RATIONAL_DIALOGUE_GAP / SELF_PRESENTATION_GAP / RELATIONSHIP_MEMORY_GAP / TURN_TAKING_SYMMETRY_GAP / EMOTIONAL_RESIDUE_GAP / PERCEPTION_SIGNATURE_GAP / ORALITY_GAP / VOICE_OVERPERFORMANCE_GAP / NONE
【逐字问题片段】
【最小修改边界】

规则：
- “对白很短”不是失败理由；“对白很长”也不是通过理由。
- 若连续四轮以上问答主要只是问什么答什么、人物目标相同、换人后仍基本成立，VERDICT 必须 FAIL。
- 若关键人物首次长对话后仍无法形成稳定声音指纹，VERDICT 必须 FAIL。
- 熟人、上下级、债权人与债务人等关系必须改变说话方式。
- 不得为了显得真实机械添加打断、反问、沉默；所有非合作行为都必须服务人物目标。
- 对话不能只靠增加“皱眉/看了看/沉默”来伪造真实感。
- 连续纯对白并非自动失败；紧急行动、命令、快速确认可以很短。
- 若人物在说话时完全失去身体、手上任务、伤势和空间位置，且动作可以换给任何角色，判 EMBODIED_DIALOGUE_GAP / GENERIC_ACTION_GAP。
- 若人物总能准确解释自己的真实动机、情绪和局势，判 OVER_RATIONAL_DIALOGUE_GAP。
- 若熟人对话看不出共同历史、旧账、预判和禁区，判 RELATIONSHIP_MEMORY_GAP。
- 若连续话轮过度整齐、严格轮流、长度接近，判 TURN_TAKING_SYMMETRY_GAP。
- 若上一句造成的羞耻、冒犯、威胁、被看穿在后文完全不留痕迹，判 EMOTIONAL_RESIDUE_GAP。
- 若不同人物进入同一场景时总注意同一组东西，判 PERCEPTION_SIGNATURE_GAP。
- 不得修改正文。""",
            ]
        ),
    ))

    natural_reader_task = asyncio.create_task(_run_step(
        task_id=task_id,
        role="blind-natural-reader",
        stage=f"reader-natural-r{round_no}",
        mode="check",
        content=draft,
        instruction="\n\n".join(
            [
                reader_skill_content,
                """你现在只执行 Reader D：自然首读 / 气质。你看不到人物卡、作者意图、Scene Card、Reviewer 意见和后续剧情，也不要替作者脑补或润色。

必须逐段、逐关键句首读，覆盖 D01—D20。不要只盯开篇和章尾。

严格输出：
NATURAL_FIRST_READ_V2
VERDICT: PASS 或 VERDICT: FAIL

若 FAIL，每个问题必须输出：
【问题ID】D001 起递增
【逐字原句】
【标签】从 NATURALNESS_GAP / TONE_GAP / AUTHOR_JOKE_GAP / MICRO_CONTINUITY_GAP / COLLOCATION_GAP / QUANTITY_GAP / REFERENCE_GAP / AUTHOR_EFFECT_GAP / SCENE_TEXTURE_GAP / ACTION_FRAGMENTATION_GAP / EMBODIED_DIALOGUE_GAP / MEMORY_INTEGRATION_TOO_SMOOTH / ORALITY_GAP 中选择
【第一次为什么会停】
【是否只是人物毛刺】YES / NO
【最小修改边界】
【是否阻断交付】YES

若 PASS：
【问题】NONE
【为什么可以直接读过去】简述
【是否阻断交付】NO

规则：
- “能理解”不是通过理由。
- 只要有一个明确自然度问题，VERDICT 必须 FAIL。
- CHARACTER_ROUGHNESS 只有能明确归属于人物说话方式时才可保留。
- 不能把作者叙述的别扭句保护成“人物毛刺”。
- 若关键场景只剩“发生了什么”，声音、气味、触感、空间、动作阻力全被写成功能标签，判 SCENE_TEXTURE_GAP。
- 若同一连续观察/移动动作被机械切成多个短句，读起来像分镜脚本，判 ACTION_FRAGMENTATION_GAP。
- 若关键对白连续只剩台词信息、附近完全看不到说话人的身体/视线/手上任务，判 EMBODIED_DIALOGUE_GAP。
- “少解释”不能成为“少描写、少质感”的通过理由。
- 穿越/原身记忆/失忆恢复若像读取资料卡一样无摩擦，判 MEMORY_INTEGRATION_TOO_SMOOTH；不得靠解释性独白修。
- 极短对白若语法正确但真人不这么说，像作者为了节奏砸字，判 ORALITY_GAP。
- 所有关键对白都必须做“说出口测试”，不只检查极短句。逻辑正确但过度工整、像作者总结/金句/规章，或需要读者脑内翻译后才自然，同样判 ORALITY_GAP；不得因“意思对”放行。
- 不得修改正文。""",
            ]
        ),
    ))

    artifice_reader_task = asyncio.create_task(_run_step(
        task_id=task_id,
        role="blind-artifice-reader",
        stage=f"reader-artifice-r{round_no}",
        mode="check",
        content=draft,
        instruction="\n\n".join(
            [
                reader_skill_content,
                """你现在只执行 Reader C 的“阅读推进 / 作者痕迹”检查。你是第一次阅读的普通读者，不看人物卡、作者意图、Scene Card、Reviewer 意见或后续剧情，也不要替作者润色。

必须覆盖 C01—C15。重点不是“逻辑对不对”，而是正文有没有暴露作者施工痕迹：解释回声、设定清单、对话循环、人物声音过演、指纹打卡、身体状态播报、线索阶梯/密度、便利记忆、系统认证泄漏、巧合集群、证据展示摆台、调查是否被主角主持成解题板、显著异常是否成为孤儿信号，以及主角是否整章退化成摄像机。

严格输出：
STORY_FLOW_ARTIFICE_V1
VERDICT: PASS 或 VERDICT: FAIL
【解释回声】
【设定清单】
【对话循环】
【人物声音是否过演】
【指纹/身体状态是否打卡】
【线索阶梯】
【线索密度】
【记忆是否过于便利】
【系统是否间接认证判断】
【巧合集群】
【证据展示摆台】
【推理解题板感】
【显著异常是否被角色接收】
【主角本章是否有独占观察/选择/代价】
【失败标签】
【逐字证据】
【最小修改边界】

允许标签：
INTERPRETATION_ECHO_GAP
PREMISE_CHECKLIST_GAP
DIALOGUE_LOOP_GAP
VOICE_OVERPERFORMANCE_GAP
FINGERPRINT_OVERUSE_GAP
BODY_STATE_TICKER_GAP
CLUE_LADDER_GAP
CLUE_DENSITY_GAP
CONVENIENT_MEMORY_RECALL_GAP
SYSTEM_CONFIRMATION_LEAK
COINCIDENCE_CLUSTER_GAP
EVIDENCE_DISPLAY_STAGING
INVESTIGATION_WORKSHEET_GAP
SALIENT_SIGNAL_ORPHAN_GAP
PROTAGONIST_AGENCY_GAP
NONE

规则：
- 单个轻微痕迹可标 WATCH，不必强行 FAIL。
- 同一场景出现两类以上明确作者痕迹，或调查链整体像教程关，VERDICT 必须 FAIL。
- 不能把“有意悬念”误判为线索不足。
- 不能为了降低线索密度要求作者机械塞假线索。
- 人物标志动作出现一次不算打卡；短距离反复证明“这个人是谁”才算。
- 身体状态持续影响选择是好事；只有旁白不断重复播报才算 BODY_STATE_TICKER_GAP。
- 系统只要通过触发时机让读者等价理解成“刚才推理正确”，就算 SYSTEM_CONFIRMATION_LEAK。
- 嫌疑人物正常工作不算 EVIDENCE_DISPLAY_STAGING；只有其动作/位置连续配合关键证据展示才算。
- 两条相关线索连续出现不自动算 INVESTIGATION_WORKSHEET_GAP；只有主角连续三步以上都把“发现→解释→验证→兑现”当场主持完，读者明显感觉在看解题板时才判。
- 显著异常不要求立即解释答案；只要人物真实接收并形成疑问/记忆/待核查项即可通过 C14。
- 主角不需要包办破案；一个有后果的观察、选择、代价或策略即可避免 C15，禁止为过 Gate 强行越权。
- 对白若为了显得聪明、专业、克制而反复写成工整金句/原则句，优先检查 VOICE_OVERPERFORMANCE_GAP；“有道理”不能作为豁免。
- 不得修改正文。""",
            ]
        ),
    ))

    cadence_source = "\n\n".join(
        item
        for item in [
            recent_chapter_window,
            "【当前章节草稿】\n" + draft,
        ]
        if item
    )
    cadence_reader_task = asyncio.create_task(_run_step(
        task_id=task_id,
        role="cadence-character-reader",
        stage=f"reader-cadence-r{round_no}",
        mode="check",
        content=cadence_source,
        instruction="""你执行“三章节拍与人物状态推进”检查。若提供了前两章，则把前两章 + 当前章作为连续窗口；若不足三章，只检查人物状态是否继承、当前章是否为后续波峰积累真实压力，不因样本不足强行 FAIL。

严格输出：
THREE_CHAPTER_CADENCE_V1
VERDICT: PASS / WATCH / FAIL
【窗口章节】
【压力曲线】
【本窗口波峰】
【波峰是否只是新线索】YES / NO
【人物状态变化1】
【人物状态变化2】
【下一章必须继承】
【失败标签】PLATEAU_CADENCE_GAP / CHARACTER_STATE_STASIS_GAP / NONE
【证据】

判定：
- 有完整三章窗口且三章强度近似、都只是均匀推进，没有明确波峰，判 PLATEAU_CADENCE_GAP + FAIL。
- 有完整三章窗口，但所谓高潮只是再丢一个名字/物证，人物权限、关系、责任、目标完全不变，也应 FAIL。
- 连续窗口显示核心人物只重复既有人设、关系和权限不变化，判 CHARACTER_STATE_STASIS_GAP；若已有连续六章证据则 FAIL，否则可 WATCH。
- 小高潮不要求打斗；现实债务、关系破裂、职业权限变化同样成立。
- 不得为了制造高潮要求作者机械添加暴力、反转或巧合。
- 不得修改正文。""",
    ))

    reader_packets = await asyncio.gather(
        _safe_review_task(reader_trace_task, "reader-trace"),
        _safe_review_task(dialogue_reader_task, "reader-dialogue"),
        _safe_review_task(natural_reader_task, "reader-naturalness"),
        _safe_review_task(artifice_reader_task, "reader-artifice"),
        _safe_review_task(cadence_reader_task, "reader-cadence"),
    )

    review_execution_failures: list[dict[str, str]] = []

    def _packet_content(packet: dict) -> str:
        if packet["ok"]:
            return str(packet["result"].content)
        review_execution_failures.append(
            {"label": str(packet["label"]), "error": str(packet["error"])}
        )
        return (
            "VERDICT: FAIL\n"
            "【执行失败】" + str(packet["error"]) + "\n"
            "【说明】该 Reviewer 未完成，整轮审核不得通过。"
        )

    reader_trace_content = _packet_content(reader_packets[0])
    dialogue_reader_content = _packet_content(reader_packets[1])
    natural_reader_content = _packet_content(reader_packets[2])
    artifice_reader_content = _packet_content(reader_packets[3])
    cadence_reader_content = _packet_content(reader_packets[4])

    class _ReviewResultProxy:
        def __init__(self, content: str):
            self.content = content

    reader_trace_result = _ReviewResultProxy(reader_trace_content)
    dialogue_reader_result = _ReviewResultProxy(dialogue_reader_content)
    natural_reader_result = _ReviewResultProxy(natural_reader_content)
    artifice_reader_result = _ReviewResultProxy(artifice_reader_content)
    cadence_reader_result = _ReviewResultProxy(cadence_reader_content)

    dialogue_reader_failed = (
        "VERDICT: PASS" not in dialogue_reader_content.upper()
    )
    natural_reader_failed = (
        "VERDICT: PASS" not in natural_reader_content.upper()
    )
    artifice_reader_failed = (
        "VERDICT: PASS" not in artifice_reader_content.upper()
    )
    cadence_reader_failed = (
        "VERDICT: FAIL" in cadence_reader_content.upper()
        or not reader_packets[4]["ok"]
    )

    character_voice_packets = (
        await asyncio.gather(
            *[
                _safe_review_task(task, f"character-voice-{index}")
                for index, task in enumerate(character_voice_tasks)
            ]
        )
        if character_voice_tasks
        else []
    )
    character_voice_results = []
    for packet in character_voice_packets:
        character_voice_results.append(
            _ReviewResultProxy(_packet_content(packet))
        )
    character_voice_failures = [
        (character, result)
        for character, result in zip(
            character_cards,
            character_voice_results,
            strict=True,
        )
        if "VERDICT: PASS" not in result.content.upper()
    ]


    specs = [
        (
            "continuity-reviewer",
            "continuity",
            "检查人物状态、称谓、时间线、地点、道具、伏笔和已确认世界规则是否连续。特别检查跨章回调：正文说‘昨儿那个/又是/还记得’时，前文是否真的播种；未播种却当成既有前情，标 UNSEEDED_CALLBACK_GAP 并按影响判 blocking。发现硬冲突必须标 blocking。",
        ),
        (
            "plot-reviewer",
            "plot",
            "检查因果、人物动机、冲突升级、信息揭示、场景目标、代价和章末钩子。额外检查主角本章是否有独占观察、选择、代价或策略；若关键推进几乎全由配角完成而主角只在场，标 PROTAGONIST_AGENCY_GAP。剧情靠解释推进或冲突不足时明确指出。",
        ),
        (
            "character-reviewer",
            "character",
            "检查人物欲望、秘密、错误选择、关系冲突与行为一致性。必须逐个对照已冻结人物卡：性格、利益、恐惧、秘密、底线、说话习惯、当前处境是否真正约束了行为和对白。特别检查：谨慎/怕事的人是否过早坦白，强势的人是否无理由配合，嘴硬的人是否被一问就答，掌握信息的人是否不会试探或撒谎。重点识别全员好人、人物工具化、动机不足，以及“为了让剧情顺利推进而让人物突然变老实”的问题。",
        ),
        (
            "world-science-reviewer",
            "world-science",
            "检查世界规则与科学设定能否由既定假设推导，术语是否前后一致，是否出现为了剧情临时新增规则。硬逻辑矛盾标 blocking。",
        ),
        (
            "long-arc-reviewer",
            "long-arc",
            """你是 Long Arc Reviewer。结合当前任务上下文中的 Story Bible、第一卷总纲、Foreshadow Registry、Proficiency Skill Tree、Conflict & Opponent Ladder 检查长篇漂移。

必须检查：
1. VOLUME_OUTLINE_DRIFT：本章是否改变了冻结的阶段功能、人物状态目标或阶段结局；
2. FORESHADOW_EARLY_REVEAL：是否在计划节点前泄露作者端真相；
3. FORESHADOW_DROPPED：本章应推进的已登记伏笔是否无故消失，或使用“回调”却从未播种；
4. PROFICIENCY_TIER_LEAP：技能是否无真实练习就出现/升级，或系统越权给答案、知识、身份；
5. CONFLICT_ENGINE_DRIFT：钱、身份、家庭、职业与案件是否被单一调查线长期吞掉；
6. OPPONENT_FLATTENING：已冻结对手是否突然变蠢、全盘自白、失去程序/经济/关系优势；
7. LONG_TERM_STATE_DRIFT：人物得到的权限、信用、债务、关系后果是否与前章和阶段目标连续。

输出必须使用 NARRATIVEOS_REVIEW_V1；仅当偏离会破坏卷级结构、伏笔回收或技能边界时判 blocking。不要因为标题、具体场景写法与总纲不同就机械 FAIL；只要功能等价且不破坏冻结接口可以 PASS。""",
        ),
        (
            "style-reviewer",
            "style",
            "检查叙述视角、节奏、句式、对白、氛围、人物外貌/神态塑造、幽默来源、重复表达和说明性语言。重点抓连续碎短句、空洞排除式描写、陌生术语未落地、功能性对白、模型腔，以及前文已表达后又用总结句点题的 AI 式收束。重要人物首次出场只有姓名/职业而没有可记忆特征时也要指出。成片问题按 Skill 判级，不要把结构问题当成 POLISH。",
        ),
        (
            "naturalness-reviewer",
            "readability",
            "执行自然叙事硬门槛：逐段检查现实锚点、首次出现顺序、空间关系、普通读者一次阅读可理解性、朗读顺滑度、人物可记忆性和段尾/章尾自然度。对白额外执行“说出口测试”：逻辑正确但真人不会这么说、过度工整、像作者总结/规章/金句，必须指出 ORALITY_GAP，不能因为信息准确放行。重点抓作者脑内成立但正文没有说明的设施/器物、报告腔、百科腔、过密信息、需要回读的句子，以及“总得、至少、这一次、他知道、才刚刚开始”一类替读者总结的 AI 式收束。重要人物首次正式出场至少应由外貌/神态/动作/衣着/声音中的两项形成记忆点；幽默只能来自人物与处境。关键空间关系不清或成片拗口必须判 blocking + REWRITE_BLOCK；孤立名词或单句才允许 LOCAL_REWRITE。",
        ),
        (
            "aesthetic-reviewer",
            "aesthetic",
            "做审美复审，不按“华丽程度”评分。先对关键对白做“说出口测试”：若一句话主要让人感觉作者在写金句、总结原则或展示人物聪明，而不是人物当场会自然开口，必须指出，不能被“这句话很有道理”掩盖。检查：细节是否有主次、描写是否经过当前人物视角、关键处是否舍得慢写而流程是否敢压缩、是否存在人物声音被编辑同质化、情绪是否说得过满、是否存在正确但无味的标准句群、比喻/金句是否抢戏、连续章节是否复用同一种动作形态/笑点/金手指展示/章尾钩子。审美问题必须给可定位证据；单句可 POLISH/DELETE，成片模板化或视角平均化可 REWRITE_BLOCK。不得把个人偏好冒充 blocking。",
        ),
        (
            "reader-gap-reviewer",
            "reader",
            "这是独立盲读者的首次阅读报告：\n"
            + reader_trace_result.content
            + "\n\n你不是模拟读者，而是 Reader Gap Reviewer。结合正文与已确认上下文，检查作者意图是否真正落在正文里。重点区分：semantic-gap、causal-gap、motivation-gap、relationship-gap、salience-gap、suspense-gap、emotion-gap。强制审计关键人物知识来源：每个关键行动前，正文是否给出亲见、转述、记录、调查或既有前情；只能靠读者脑补来源时标 KNOWLEDGE_PROVENANCE_GAP。有意悬念可以保留，但读者必须清楚自己不知道什么；如果读者连句子对象、人物目的、关系变化或必要因果都要靠作者资料才能补全，必须指出。不能用‘读者多读两遍就懂’作为通过理由。严格按 Reader Gate v3 判定：INTENTIONAL_UNKNOWN 可 PASS；READER_GAP 必须修；AMBIGUOUS_GAP 只有多个解释均为作者有意且不损害当前场景理解时才可 PASS。关键理解缺失可判 blocking；孤立语义支点缺失可 LOCAL_REWRITE。",
        ),
    ]

    outputs: list[str] = []
    has_blocking = (
        bool(character_voice_failures)
        or natural_reader_failed
        or dialogue_reader_failed
        or artifice_reader_failed
        or cadence_reader_failed
        or bool(review_execution_failures)
    )

    if review_execution_failures:
        with connect() as conn:
            for failure in review_execution_failures:
                conn.execute(
                    """
                    INSERT INTO review_findings(
                        task_id,reviewer,category,severity,summary,suggestion,status
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        task_id,
                        str(failure["label"]),
                        "review-execution",
                        "blocking",
                        "Reviewer 执行失败：" + str(failure["error"]),
                        "修复该 Reviewer 调用后，重新完成所有 Reviewer 的全量审核；不得用其他 Reviewer 结果替代。",
                        "open",
                    ),
                )

    async def _run_specialist(index: int, spec: tuple[str, str, str]):
        role, category, instruction = spec
        prior = ""
        if prior_outputs and index < len(prior_outputs):
            prior = (
                "上一轮同一 Reviewer 的审核结果如下。RECHECK 时必须沿用其中的问题标识逐条复审：\n"
                + prior_outputs[index]
            )
        result = await _run_step(
            task_id=task_id,
            role=role,
            stage=f"review-r{round_no}",
            mode="check",
            content=draft,
            instruction="\n\n".join(
                item
                for item in [
                    instruction,
                    _review_contract(round_no),
                    prior,
                    context,
                ]
                if item
            ),
        )
        return role, category, result

    specialist_packets = await asyncio.gather(
        *(
            _safe_review_task(
                _run_specialist(index, spec),
                f"specialist-{spec[0]}",
            )
            for index, spec in enumerate(specs)
        )
    )

    specialist_results = []
    for packet, spec in zip(specialist_packets, specs, strict=True):
        if packet["ok"]:
            specialist_results.append(packet["result"])
            continue
        role, category, _instruction = spec
        review_execution_failures.append(
            {"label": str(packet["label"]), "error": str(packet["error"])}
        )
        specialist_results.append(
            (
                role,
                category,
                _ReviewResultProxy(
                    "NARRATIVEOS_REVIEW_V3\n"
                    "【严重性】blocking\n"
                    "【问题说明】Reviewer 执行失败，整轮审核不完整。\n"
                    "【建议动作】修复 Reviewer 执行后重新完成全量审核。\n"
                    "【执行错误】" + str(packet["error"])
                ),
            )
        )

    for role, category, result in specialist_results:
        outputs.append(f"[{category}] {result.content}")
        findings = _parse_review_output(result.content, draft)
        with connect() as conn:
            for finding in findings:
                severity = finding["severity"]
                if severity == "blocking":
                    has_blocking = True
                cur = conn.execute(
                    """
                    INSERT INTO review_findings(
                        task_id,reviewer,category,severity,summary,suggestion,status
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        task_id,
                        role,
                        category,
                        severity,
                        finding["summary"],
                        finding["suggestion"],
                        "open",
                    ),
                )
                if finding["excerpt"]:
                    conn.execute(
                        """
                        INSERT INTO review_finding_refs(
                            finding_id,excerpt,start_offset,end_offset
                        ) VALUES(?,?,?,?)
                        """,
                        (
                            cur.lastrowid,
                            finding["excerpt"],
                            finding["start_offset"],
                            finding["end_offset"],
                        ),
                    )

    for character, result in zip(
        character_cards,
        character_voice_results,
        strict=True,
    ):
        name = str(character["name"])
        outputs.append(f"[character-voice:{name}] {result.content}")
        if "VERDICT: PASS" in result.content.upper():
            continue
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO review_findings(
                    task_id,reviewer,category,severity,summary,suggestion,status
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    task_id,
                    "character-voice-reviewer",
                    f"character-voice:{name}",
                    "blocking",
                    result.content,
                    "只按角色自审给出的 FAIL 台词做最小口语修订；保留事实、证据边界、人物权限、关系和行动结果。",
                    "open",
                ),
            )

    outputs.append(f"[reader-dialogue] {dialogue_reader_result.content}")
    if dialogue_reader_failed:
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO review_findings(
                    task_id,reviewer,category,severity,summary,suggestion,status
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    task_id,
                    "blind-dialogue-reader",
                    "reader-dialogue",
                    "blocking",
                    dialogue_reader_result.content,
                    "按 Reader B 给出的最小修改边界重写功能性对白；不得仅增加字数，必须增强人物目标、声音和关系痕迹。",
                    "open",
                ),
            )

    outputs.append(f"[reader-artifice] {artifice_reader_result.content}")
    if artifice_reader_failed:
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO review_findings(
                    task_id,reviewer,category,severity,summary,suggestion,status
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    task_id,
                    "blind-artifice-reader",
                    "reader-artifice",
                    "blocking",
                    artifice_reader_result.content,
                    "按 Reader C 给出的最小修改边界降低作者痕迹；优先删解释回声、压缩重复对话、降低线索密度与巧合展示，不得机械添加假线索。",
                    "open",
                ),
            )

    outputs.append(f"[reader-cadence] {cadence_reader_result.content}")
    if cadence_reader_failed:
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO review_findings(
                    task_id,reviewer,category,severity,summary,suggestion,status
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    task_id,
                    "cadence-character-reader",
                    "reader-cadence",
                    "blocking",
                    cadence_reader_result.content,
                    "按三章节拍与人物状态推进门槛重构相关章节窗口；不得只在章尾补钩子，必须让压力波峰与人物关系/权限/责任变化同时落地。",
                    "open",
                ),
            )

    outputs.append(f"[reader-naturalness] {natural_reader_result.content}")
    if natural_reader_failed:
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO review_findings(
                    task_id,reviewer,category,severity,summary,suggestion,status
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    task_id,
                    "blind-natural-reader",
                    "reader-naturalness",
                    "blocking",
                    natural_reader_result.content,
                    "按 Reader D 给出的最小修改边界修复；不得顺手改写已通过内容。",
                    "open",
                ),
            )
    if has_blocking and auto_learn:
        learn_from_open_blocking_findings(
            task_id=task_id,
            source=f"review-round-{round_no}",
        )
    return outputs, has_blocking


async def run_full_novel_pipeline(task_id: int) -> dict:
    _require_real_provider()

    with connect() as conn:
        task = conn.execute(
            "SELECT * FROM writing_tasks WHERE id=?",
            (task_id,),
        ).fetchone()
        if not task:
            raise ValueError("task not found")
        if task["status"] in {"running", "awaiting_approval", "approved"}:
            raise WorkflowStateError(
                f"task cannot run while status is {task['status']}"
            )
        project = conn.execute(
            "SELECT * FROM projects WHERE id=?",
            (task["project_id"],),
        ).fetchone()
        if not project:
            raise ValueError("project not found")
        chapter = None
        if task["chapter_id"] is not None:
            chapter = conn.execute(
                "SELECT * FROM chapters WHERE id=? AND project_id=?",
                (task["chapter_id"], task["project_id"]),
            ).fetchone()
            if not chapter:
                raise ValueError("chapter not found")
        conn.execute(
            "UPDATE writing_tasks SET status='running',updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (task_id,),
        )
        conn.execute("DELETE FROM review_findings WHERE task_id=?", (task_id,))

    project_id = int(task["project_id"])
    goal = str(task["goal"])
    extra = str(task["instruction"] or "").strip()
    seed = chapter["content"] if chapter else ""
    initial_context = _task_context(task_id, project_id)

    try:
        architect = await _run_step(
            task_id=task_id,
            role="story-architect",
            stage="architecture",
            mode="continue",
            content=seed,
            instruction="\n\n".join(
                item
                for item in [
                    f"项目：{project['title']} / 类型：{project['genre']}",
                    f"创作目标：{goal}",
                    extra,
                    initial_context,
                    """你负责小说总架构，不写正文。输出：核心命题、主角欲望、主冲突、反派/对抗力量、关键秘密、三幕或卷级推进、高潮选择、结局、必须回收的伏笔。冲突必须来自人物选择而非偶然。""",
                ]
                if item
            ),
        )
        _persist_memory(
            project_id=project_id,
            task_id=task_id,
            kind="architecture",
            title="故事架构",
            content=architect.content,
        )

        context = _task_context(task_id, project_id)
        world = await _run_step(
            task_id=task_id,
            role="world-builder",
            stage="world-design",
            mode="continue",
            content=architect.content,
            instruction="\n\n".join(
                item
                for item in [
                    context,
                    """基于已批准的故事架构设计世界观，不写正文。对于科幻题材按：科学假设 → 装置原理 → 事故机制 → 可观测现象 → 跨界/能力规则 → 极限条件 → 高潮成立条件。只允许少量核心虚构假设，其余现象必须可推导；列出明确禁区，禁止后文临时改规则。""",
                ]
                if item
            ),
        )
        _persist_memory(
            project_id=project_id,
            task_id=task_id,
            kind="world",
            title="世界观与硬规则",
            content=world.content,
        )

        context = _task_context(task_id, project_id)
        characters = await _run_step(
            task_id=task_id,
            role="character-designer",
            stage="character-design",
            mode="continue",
            content=architect.content + "\n\n" + world.content,
            instruction="\n\n".join(
                item
                for item in [
                    context,
                    """设计核心人物，不写正文。每人必须给出：表层目标、深层欲望、恐惧、秘密、历史错误、底线、会做出的错误选择、与其他核心人物的不可调和矛盾、最终变化；并新增行为约束字段：正常状态下的说话方式、受压时第一反应、常用撒谎/回避方式、面对上级/同级/弱者时的不同态度、什么证据出现前绝不会承认、什么情况下才会改口、被逼到角落时会攻击/示弱/沉默/逃跑中的哪一种；每个核心人物还必须给出：
- “语言指纹”：常用词汇、句长、攻击/回避方式、幽默方式；
- “非语言指纹”：紧张、隐瞒、占上风、示弱时最自然的动作、表情、姿态和空间习惯；
- “自我形象”：他希望别人把自己看成什么人，最怕被看成什么人；
- “关系记忆”：与每个核心人物至少一条共同历史、旧账、禁区或双方默认不用说透的前提；
- “感知指纹”：进入陌生/危险/交易/家庭场景时最先注意什么、最容易忽略什么。
禁止把这些指纹写成每场都要打卡的固定动作或口头禅。禁止全员好人；主要冲突必须至少有一部分来自人物主动隐瞒、利用、越线或错误选择。人物卡必须能直接约束对白与行动，不得只写形容词。""",
                ]
                if item
            ),
        )
        _persist_memory(
            project_id=project_id,
            task_id=task_id,
            kind="character",
            title="核心人物与矛盾",
            content=characters.content,
        )

        context = _task_context(task_id, project_id)
        outline = await _run_step(
            task_id=task_id,
            role="plot-planner",
            stage="plot-outline",
            mode="continue",
            content=f"{architect.content}\n\n{world.content}\n\n{characters.content}",
            instruction="\n\n".join(
                item
                for item in [
                    context,
                    """把架构、世界规则和人物矛盾编排为可执行章节大纲，不写正文。每章必须列：开场状态、人物目标、阻碍、冲突升级、新信息、错误选择/代价、转折、章末钩子。世界规则的揭示必须通过事件和选择完成，禁止连续说明设定。
额外执行三章节拍：默认每 3 章至少形成一次小高潮，小高潮不能只等于“发现更大线索”，必须同时推动压力、人物选择和状态改变中的至少两项。每个 3 章单元结束时，至少两名核心人物的关系、权限、责任、目标或资源状态要发生可追踪变化。降速章也必须推进家庭、钱、职业或关系，不能原地踏步。""",
                ]
                if item
            ),
        )
        _persist_memory(
            project_id=project_id,
            task_id=task_id,
            kind="outline",
            title="章节大纲",
            content=outline.content,
        )

        context = _task_context(task_id, project_id)
        scene_blueprint = await _run_step(
            task_id=task_id,
            role="scene-director",
            stage="scene-blueprint",
            mode="continue",
            content=outline.content,
            instruction="\n\n".join(
                item
                for item in [
                    context,
                    """在写正文前做“场景导演卡”，不写正文。目标是帮助 Writer 做取舍，而不是增加说明文字。必须给出：
1. 本章真正的核心张力与读者应记住的一件事；
2. 视角过滤：当前 POV 最可能先注意什么、会忽略什么，禁止上帝视角平均描写；
3. 细节层级：最多 2—3 个主细节，哪些背景只能轻写；
4. 节奏地图：哪些流程一句压缩，哪些决定/关系变化必须慢写；
5. 在场人物的表层话语目的、真实目的、绝不愿交出的信息；
6. 对话身体线：每个主要人物在说话时手上正在做什么、身体状态如何、站位/距离怎样变化；至少指出一个能体现人物策略的非语言动作，同时标出禁止使用的通用填充动作；
7. 关系记忆触发点：这一场有哪些旧账、共同经历、默认前提、禁区可以自然影响说法；没有就写 NONE，禁止硬造回忆；
8. 自我形象与面子：每个人在这场最想保住什么形象，什么话即使是真的也不会直说；
9. 话轮与余波：哪一句可能打断正常轮流，哪一句之后情绪会持续影响后续回答；禁止把对话写成均匀轮询；
10. 感知差异：同一场景里每个人最先注意什么，不得全由作者统一分配注意力；
11. 潜台词与沉默点：哪些意思不要说透；
12. 本章幽默来源；若不需要幽默就明确写 NONE，禁止硬塞；
13. 与最近章节相比必须避免复用的动作形态、笑点、金手指展示和章尾钩子；
14. 章尾类型：优先从行动后果、关系变化、未完成选择、现实麻烦中选择，禁止模板化姓名/物证/系统弹窗打卡。
场景导演卡是约束和取舍，不是正文提纲扩写；不得新增世界规则、关键线索和人物秘密。""",
                ]
                if item
            ),
        )
        _persist_memory(
            project_id=project_id,
            task_id=task_id,
            kind="scene-blueprint",
            title="场景导演卡",
            content=scene_blueprint.content,
        )

        context = _task_context(task_id, project_id)
        writer = await _run_step(
            task_id=task_id,
            role="writer",
            stage="draft",
            mode="continue",
            content=seed,
            instruction="\n\n".join(
                item
                for item in [
                    f"写作任务：{goal}",
                    extra,
                    context,
                    """严格依据已确认的故事架构、世界规则、人物矛盾、章节大纲和本次冻结写作 Skill 生成当前目标章节的完整正文。不得擅自新增世界规则；设定信息优先通过行动、环境、冲突和后果呈现，不让人物充当说明书。不要默认使用碎短句；普通叙事让动作、感受与关系进入完整语流。陌生术语第一次出现必须让普通读者当场理解。任何地点、设施、器物第一次出现时，先让读者看懂它在哪里、是什么、做什么用，再使用专业名；禁止用“海堤上的门”这类缺少现实空间锚点的诗性概括要求读者自行脑补。对白必须带人物意图和关系温度，不能只承担问答式信息传递。写每场对白前必须先读取在场人物卡，明确每个人“想得到什么、怕暴露什么、愿意承认到什么程度、会如何拖延/反问/撒谎/试探”，并同时读取其语言指纹与非语言指纹。人物说话时不能变成悬空聊天框：身体状态、手上任务、表情、姿态和空间位置要在需要时承担情绪与策略，但禁止每句对白后机械补“皱眉/看了看/沉默/笑了笑”。同时避免“过度理性对白”：人物不应总能准确解释自己；熟人要带关系记忆，自我形象要影响说法，上一句的情绪要有余波，话轮不能长期严格一问一答。人物回答必须由性格与利益共同决定，不能因为作者需要信息就突然老实。写前必须读取“场景导演卡”，把它当作取舍约束而不是待勾选清单：主细节要突出，次要流程敢于压缩，关键决定与关系变化敢于慢写；描写经过当前人物视角过滤，不平均用力。对白允许不合作和留白，人物不必把真实目的说出来。先完成准确、有性格的正文，再考虑漂亮；不得为了金句、比喻或所谓文学感抢走人物和事件。正文完成后按正常语速自读，凡需回读才能理解的句子先改顺。额外执行 Natural First-Read：逐句找“意思能懂但第一眼发怪”的表达；检查对比/转折两端是否同一语义层级、是否依赖读者自动补词、幽默是否来自人物而非作者抖机灵。开篇前三段必须做类型第一印象检查，若气质与作品定位不符先重写。重要人物首次正式出场必须有可记忆的外貌、神态或动作特征；允许轻微幽默，但必须来自人物和处境。段尾、场景尾、章尾执行去 AI 收束检查：若只是总结、点题、重复情绪或用“总得、至少、这一次、他知道、才刚刚开始”等句式制造力度，删除或改成具体动作、发现、麻烦、关系变化或画面。只输出正文。""",
                ]
                if item
            ),
        )

        enriched = await _run_step(
            task_id=task_id,
            role="scene-enricher",
            stage="scene-enrichment",
            mode="polish",
            content=writer.content,
            instruction="\n\n".join(
                item
                for item in [
                    context,
                    """丰富场景承载力：补足空间、感官、动作、停顿、潜台词、气氛和冲突压力，但不得改变事件顺序、事实、世界规则和人物选择。对第一次出现的地点、设施和器物补足最少且准确的现实锚点，让普通读者无需专业知识也能看懂空间和用途；不得为了气氛发明含糊设施。删除纯说明式设定段落，让信息从场景中长出来。只输出完整正文。""",
                ]
                if item
            ),
        )

        prose = await _run_step(
            task_id=task_id,
            role="prose-editor",
            stage="prose-edit",
            mode="polish",
            content=enriched.content,
            instruction="\n\n".join(
                item
                for item in [
                    context,
                    """只做语言编辑，并严格执行本次冻结写作 Skill：改善节奏、句式、意象、对白质感和重复表达。对白编辑必须同时保护人物语言指纹和非语言指纹：不能把所有人修成同样完整、克制、准确的句子，也不能用通用“皱眉/沉默/看了看”给功能性对白贴动作。重点清理连续碎短句与单句段落、空洞的排除式描写、未解释的陌生术语、没有情绪目的的功能性对白，以及高频“不是A，是B”等模型腔模板。额外执行朗读检查：自然中文语序优先，连续两句发硬、像报告、信息塞得过满或需要回读时必须重写。检查所有首次出现的设施/器物是否具有清晰现实锚点。能用具体正向感官形象表达时，不用排除法代替描写。不能新增或删除关键情节，不能改变设定和人物动机。只输出完整正文。""",
                ]
                if item
            ),
        )

        aesthetic = await _run_step(
            task_id=task_id,
            role="aesthetic-editor",
            stage="aesthetic-edit",
            mode="polish",
            content=prose.content,
            instruction="\n\n".join(
                item
                for item in [
                    context,
                    """执行审美编辑，不负责修剧情，也不是把文字变华丽。只在事实、因果和人物行为成立的前提下做“选择、克制、层次、余味”：
- 找出每场最值钱的 1—3 个细节，让次要描写为它们让路；
- 删除正确但通用、安全、像标准范文的句子，优先保留只属于当前人物/场景的表达；
- 检查三到五句组成的句群节奏，而不是逐句都修得一样亮；
- 情绪已经从动作、对白、关系表现出来时，少说半句，不替读者总结；
- 该压缩的手续、赶路、重复动作直接压缩；关键选择、误会、关系变化允许慢半拍；
- 保留人物口语、停顿、粗粝感和攻击性，禁止把所有角色修成同一种“漂亮文风”；
- 不主动增加比喻、排比、意象和金句；新鲜必须建立在准确和自然上；
- 不改变事件顺序、设定、人物动机、线索来源和章末事实。
只输出完成审美取舍后的完整正文。""",
                ]
                if item
            ),
        )
        draft = aesthetic.content
        with connect() as conn:
            conn.execute(
                "UPDATE writing_tasks SET draft=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (draft, task_id),
            )

        review_outputs, _ = await _run_review_round(
            task_id=task_id,
            draft=draft,
            context=context,
            round_no=1,
        )
        context = _task_context(task_id, project_id)

        revision = await _run_step(
            task_id=task_id,
            role="revision-agent",
            stage="revision-r1",
            mode="polish",
            content=draft,
            instruction="\n\n".join(
                [
                    """根据八个独立 Reviewer、盲读 Reader B（对话真实性）、Reader C（阅读推进/作者痕迹）与 Reader D（自然首读）的结构化意见执行修订，并严格遵守冻结的“小说精修流程” Skill。按处置级别执行：REWRITE_BLOCK 重建对应段落/场景；LOCAL_REWRITE 只改最小范围；DELETE 直接删除无效内容；POLISH 仅做语言层调整。blocking 必须修复；不得把结构问题降级成润色，也不得因局部问题扩大重写范围。保留 Reviewer 标明的事实锚点与不得触碰范围。

任何 LOCAL_REWRITE 执行前必须先在内部建立 Narrative Function Contract：本段必须让读者知道什么、必须确认什么身份/关系/规则、必须发生什么决定/状态变化、后文依赖什么接口。修改完成后必须执行 Seam Check：检查重复问答、重复说明、决定/关系/动作/情绪/空间重置。不得为了改善人物或语言而写丢原场景功能。只输出重写后的完整正文。""",
                    "Reviewer 意见：\n" + "\n\n".join(review_outputs),
                    context,
                ]
            ),
        )

        with connect() as conn:
            conn.execute(
                "UPDATE review_findings SET status='addressed' WHERE task_id=? AND status='open'",
                (task_id,),
            )

        integrity_output, integrity_failed = await _run_revision_integrity_gate(
            task_id=task_id,
            before=draft,
            after=revision.content,
            context=context,
            round_no=1,
        )

        second_outputs, second_blocking = await _run_review_round(
            task_id=task_id,
            draft=revision.content,
            context=context,
            round_no=2,
            prior_outputs=review_outputs,
        )
        context = _task_context(task_id, project_id)
        if integrity_failed:
            second_outputs.append("[revision-integrity] " + integrity_output)
            second_blocking = True

        final_content = revision.content
        if second_blocking:
            second_revision = await _run_step(
                task_id=task_id,
                role="revision-agent",
                stage="revision-r2",
                mode="polish",
                content=revision.content,
                instruction="\n\n".join(
                    [
                        """第二轮复审仍有 blocking。仅处理复审结果为 FAIL 的原问题，并按原问题标识与处置级别执行；REWRITE_BLOCK 才允许重建对应范围，LOCAL_REWRITE 必须保持最小修改。不得重构已经 PASS 的部分，不得越过 Reviewer 给出的修改边界。若 blocking 包含 revision-integrity，必须先恢复原 Narrative Function Contract，再消除 Seam 重复/重置；不能只把新句子写顺。只输出完整正文。""",
                        "第二轮 Reviewer 意见：\n" + "\n\n".join(second_outputs),
                        context,
                    ]
                ),
            )
            final_content = second_revision.content
            with connect() as conn:
                conn.execute(
                    "UPDATE review_findings SET status='addressed' WHERE task_id=? AND status='open'",
                    (task_id,),
                )
            _integrity_output_2, integrity_failed_2 = await _run_revision_integrity_gate(
                task_id=task_id,
                before=draft,
                after=final_content,
                context=context,
                round_no=2,
            )
            _, final_blocking = await _run_review_round(
                task_id=task_id,
                draft=final_content,
                context=context,
                round_no=3,
                prior_outputs=second_outputs,
            )
            final_blocking = final_blocking or integrity_failed_2
        else:
            final_blocking = False

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

    except Exception:
        with connect() as conn:
            conn.execute(
                "UPDATE writing_tasks SET status='failed',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (task_id,),
            )
        raise