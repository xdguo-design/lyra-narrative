from __future__ import annotations

import os

from app.db import connect
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
审核轮次：INITIAL。请严格按“小说精修流程 v7”的 Reviewer 统一审核输出格式执行。
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


async def _run_review_round(
    *,
    task_id: int,
    draft: str,
    context: str,
    round_no: int,
    prior_outputs: list[str] | None = None,
) -> tuple[list[str], bool]:
    reader_trace_result = await _run_step(
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
    )

    specs = [
        (
            "continuity-reviewer",
            "continuity",
            "检查人物状态、称谓、时间线、地点、道具、伏笔和已确认世界规则是否连续。发现硬冲突必须标 blocking。",
        ),
        (
            "plot-reviewer",
            "plot",
            "检查因果、人物动机、冲突升级、信息揭示、场景目标、代价和章末钩子。剧情靠解释推进或冲突不足时明确指出。",
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
            "style-reviewer",
            "style",
            "检查叙述视角、节奏、句式、对白、氛围、人物外貌/神态塑造、幽默来源、重复表达和说明性语言。重点抓连续碎短句、空洞排除式描写、陌生术语未落地、功能性对白、模型腔，以及前文已表达后又用总结句点题的 AI 式收束。重要人物首次出场只有姓名/职业而没有可记忆特征时也要指出。成片问题按 Skill 判级，不要把结构问题当成 POLISH。",
        ),
        (
            "naturalness-reviewer",
            "readability",
            "执行自然叙事硬门槛：逐段检查现实锚点、首次出现顺序、空间关系、普通读者一次阅读可理解性、朗读顺滑度、人物可记忆性和段尾/章尾自然度。重点抓作者脑内成立但正文没有说明的设施/器物、报告腔、百科腔、过密信息、需要回读的句子，以及“总得、至少、这一次、他知道、才刚刚开始”一类替读者总结的 AI 式收束。重要人物首次正式出场至少应由外貌/神态/动作/衣着/声音中的两项形成记忆点；幽默只能来自人物与处境。关键空间关系不清或成片拗口必须判 blocking + REWRITE_BLOCK；孤立名词或单句才允许 LOCAL_REWRITE。",
        ),
        (
            "aesthetic-reviewer",
            "aesthetic",
            "做审美复审，不按“华丽程度”评分。检查：细节是否有主次、描写是否经过当前人物视角、关键处是否舍得慢写而流程是否敢压缩、人物声音是否被编辑同质化、情绪是否说得过满、是否存在正确但无味的标准句群、比喻/金句是否抢戏、连续章节是否复用同一种动作形态/笑点/金手指展示/章尾钩子。审美问题必须给可定位证据；单句可 POLISH/DELETE，成片模板化或视角平均化可 REWRITE_BLOCK。不得把个人偏好冒充 blocking。",
        ),
        (
            "reader-gap-reviewer",
            "reader",
            "这是独立盲读者的首次阅读报告：\n"
            + reader_trace_result.content
            + "\n\n你不是模拟读者，而是 Reader Gap Reviewer。结合正文与已确认上下文，检查作者意图是否真正落在正文里。重点区分：semantic-gap、causal-gap、motivation-gap、relationship-gap、salience-gap、suspense-gap、emotion-gap。有意悬念可以保留，但读者必须清楚自己不知道什么；如果读者连句子对象、人物目的、关系变化或必要因果都要靠作者资料才能补全，必须指出。不能用‘读者多读两遍就懂’作为通过理由。严格按 Reader Gate v3 判定：INTENTIONAL_UNKNOWN 可 PASS；READER_GAP 必须修；AMBIGUOUS_GAP 只有多个解释均为作者有意且不损害当前场景理解时才可 PASS。关键理解缺失可判 blocking；孤立语义支点缺失可 LOCAL_REWRITE。",
        ),
    ]

    outputs: list[str] = []
    has_blocking = False
    for index, (role, category, instruction) in enumerate(specs):
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
                    """设计核心人物，不写正文。每人必须给出：表层目标、深层欲望、恐惧、秘密、历史错误、底线、会做出的错误选择、与其他核心人物的不可调和矛盾、最终变化；并新增行为约束字段：正常状态下的说话方式、受压时第一反应、常用撒谎/回避方式、面对上级/同级/弱者时的不同态度、什么证据出现前绝不会承认、什么情况下才会改口、被逼到角落时会攻击/示弱/沉默/逃跑中的哪一种。禁止全员好人；主要冲突必须至少有一部分来自人物主动隐瞒、利用、越线或错误选择。人物卡必须能直接约束对白与行动，不得只写形容词。""",
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
                    """把架构、世界规则和人物矛盾编排为可执行章节大纲，不写正文。每章必须列：开场状态、人物目标、阻碍、冲突升级、新信息、错误选择/代价、转折、章末钩子。世界规则的揭示必须通过事件和选择完成，禁止连续说明设定。""",
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
6. 潜台词与沉默点：哪些意思不要说透；
7. 本章幽默来源；若不需要幽默就明确写 NONE，禁止硬塞；
8. 与最近章节相比必须避免复用的动作形态、笑点、金手指展示和章尾钩子；
9. 章尾类型：优先从行动后果、关系变化、未完成选择、现实麻烦中选择，禁止模板化姓名/物证/系统弹窗打卡。
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
                    """严格依据已确认的故事架构、世界规则、人物矛盾、章节大纲和本次冻结写作 Skill 生成当前目标章节的完整正文。不得擅自新增世界规则；设定信息优先通过行动、环境、冲突和后果呈现，不让人物充当说明书。不要默认使用碎短句；普通叙事让动作、感受与关系进入完整语流。陌生术语第一次出现必须让普通读者当场理解。任何地点、设施、器物第一次出现时，先让读者看懂它在哪里、是什么、做什么用，再使用专业名；禁止用“海堤上的门”这类缺少现实空间锚点的诗性概括要求读者自行脑补。对白必须带人物意图和关系温度，不能只承担问答式信息传递。写每场对白前必须先读取在场人物卡，明确每个人“想得到什么、怕暴露什么、愿意承认到什么程度、会如何拖延/反问/撒谎/试探”。人物回答必须由性格与利益共同决定，不能因为作者需要信息就突然老实。写前必须读取“场景导演卡”，把它当作取舍约束而不是待勾选清单：主细节要突出，次要流程敢于压缩，关键决定与关系变化敢于慢写；描写经过当前人物视角过滤，不平均用力。对白允许不合作和留白，人物不必把真实目的说出来。先完成准确、有性格的正文，再考虑漂亮；不得为了金句、比喻或所谓文学感抢走人物和事件。正文完成后按正常语速自读，凡需回读才能理解的句子先改顺。额外执行 Natural First-Read：逐句找“意思能懂但第一眼发怪”的表达；检查对比/转折两端是否同一语义层级、是否依赖读者自动补词、幽默是否来自人物而非作者抖机灵。开篇前三段必须做类型第一印象检查，若气质与作品定位不符先重写。重要人物首次正式出场必须有可记忆的外貌、神态或动作特征；允许轻微幽默，但必须来自人物和处境。段尾、场景尾、章尾执行去 AI 收束检查：若只是总结、点题、重复情绪或用“总得、至少、这一次、他知道、才刚刚开始”等句式制造力度，删除或改成具体动作、发现、麻烦、关系变化或画面。只输出正文。""",
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
                    """只做语言编辑，并严格执行本次冻结写作 Skill：改善节奏、句式、意象、对白质感和重复表达。重点清理连续碎短句与单句段落、空洞的排除式描写、未解释的陌生术语、没有情绪目的的功能性对白，以及高频“不是A，是B”等模型腔模板。额外执行朗读检查：自然中文语序优先，连续两句发硬、像报告、信息塞得过满或需要回读时必须重写。检查所有首次出现的设施/器物是否具有清晰现实锚点。能用具体正向感官形象表达时，不用排除法代替描写。不能新增或删除关键情节，不能改变设定和人物动机。只输出完整正文。""",
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

        revision = await _run_step(
            task_id=task_id,
            role="revision-agent",
            stage="revision-r1",
            mode="polish",
            content=draft,
            instruction="\n\n".join(
                [
                    """根据八个独立 Reviewer 的结构化意见执行修订，并严格遵守冻结的“小说精修流程” Skill。按处置级别执行：REWRITE_BLOCK 重建对应段落/场景；LOCAL_REWRITE 只改最小范围；DELETE 直接删除无效内容；POLISH 仅做语言层调整。blocking 必须修复；不得把结构问题降级成润色，也不得因局部问题扩大重写范围。保留 Reviewer 标明的事实锚点与不得触碰范围。只输出重写后的完整正文。""",
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

        second_outputs, second_blocking = await _run_review_round(
            task_id=task_id,
            draft=revision.content,
            context=context,
            round_no=2,
            prior_outputs=review_outputs,
        )

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
                        """第二轮复审仍有 blocking。仅处理复审结果为 FAIL 的原问题，并按原问题标识与处置级别执行；REWRITE_BLOCK 才允许重建对应范围，LOCAL_REWRITE 必须保持最小修改。不得重构已经 PASS 的部分，不得越过 Reviewer 给出的修改边界。只输出完整正文。""",
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
            _, final_blocking = await _run_review_round(
                task_id=task_id,
                draft=final_content,
                context=context,
                round_no=3,
                prior_outputs=second_outputs,
            )
        else:
            final_blocking = False

        final_human_failed = False
        if not final_blocking:
            final_human = await _run_step(
                task_id=task_id,
                role="final-human-reader",
                stage="final-human-read",
                mode="check",
                content=final_content,
                instruction="""你是最终交付前最后一名普通中文小说读者。你只看正文，不看作者意图、人物卡、Scene Card、Reviewer 结论，也不要替作者脑补。

你的任务不是检查剧情是否完整，而是检查“正常人读起来怪不怪”。重点逐句检查：
1. 意思虽然能猜懂，但中文母语直觉是否别扭；
2. “不是A，是B / 先A后B / A而不是B”等结构两端是否处于同一语义层级；
3. 是否需要自动补一个隐藏词才能让句子成立；
4. 幽默是否来自人物/处境，还是作者跳出来抖机灵；
5. 开篇前三段给出的类型第一印象是否与正文真正气质一致；
6. 关键转折句、章尾句是否自然，而不是刻意做效果；
7. 是否把作者自己的别扭句误当成“人物口语毛刺”。

强制参考失败样本：
“陈安醒过来的时候，先感觉到的不是头疼，是屁股。”
这句话即使能脑补成“屁股疼”，仍应判 FAIL：头疼是症状，屁股是部位，语义层级不平；并且作为开篇把气质推向段子式穿越。

严格输出：
FINAL_HUMAN_READ_V1
VERDICT: PASS 或 VERDICT: FAIL
【怪句】逐字引用；没有则写 NONE
【类型】NATURALNESS_GAP / TONE_GAP / AUTHOR_JOKE_GAP / NONE
【为什么第一眼不自然】
【最小修改边界】

只要开篇、关键转折或章尾仍有一个明确 NATURALNESS_GAP / TONE_GAP，就必须 VERDICT: FAIL。""",
            )
            final_human_failed = "VERDICT: PASS" not in final_human.content.upper()

            if final_human_failed:
                human_revision = await _run_step(
                    task_id=task_id,
                    role="final-delivery-editor",
                    stage="final-human-fix",
                    mode="polish",
                    content=final_content,
                    instruction="\n\n".join(
                        [
                            final_human.content,
                            """只修 Final Human Read 明确指出的自然度/气质问题。保持事实、事件顺序、人物动机、信息边界和已经通过的段落不变。对 NATURALNESS_GAP 修语义层级、搭配或缺失支点；对 TONE_GAP 去掉错误的段子感/作者表演感；对 AUTHOR_JOKE_GAP 把幽默还给人物与处境。不得顺手重写其他内容。只输出完整正文。""",
                        ]
                    ),
                )
                final_content = human_revision.content

                human_recheck = await _run_step(
                    task_id=task_id,
                    role="final-human-reader",
                    stage="final-human-recheck",
                    mode="check",
                    content=final_content,
                    instruction="""再次只作为普通中文小说读者做最终首读。不得看作者意图，不得因为上一轮已经修改就放宽标准。检查 NATURALNESS_GAP / TONE_GAP / AUTHOR_JOKE_GAP，尤其开篇前三段、关键转折、章尾。
严格输出：
FINAL_HUMAN_READ_V1
VERDICT: PASS 或 VERDICT: FAIL
【怪句】
【类型】
【为什么第一眼不自然】
【最小修改边界】""",
                )
                final_human_failed = "VERDICT: PASS" not in human_recheck.content.upper()

        with connect() as conn:
            conn.execute(
                """
                UPDATE writing_tasks
                SET revised_content=?,status=?,updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    final_content,
                    "reviewed" if (final_blocking or final_human_failed) else "awaiting_approval",
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