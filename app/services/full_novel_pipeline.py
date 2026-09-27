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
        return """NARRATIVEOS_REVIEW_V2
审核轮次：INITIAL。请严格按“小说精修流程 v4”的 Reviewer 统一审核输出格式执行。
每个问题一块，多个问题用单独一行 --- 分隔；没有问题只输出 NO_ISSUE。
必须包含：问题标识、严重性、处置级别、问题类型、问题定位、逐字片段、问题说明、判级理由、修改边界、必须保留事实、禁止新增内容、执行目标、建议动作、复审要求、复审结果=PENDING。
处置级别只能是 REWRITE_BLOCK / LOCAL_REWRITE / DELETE / POLISH / PASS。
REWRITE_BLOCK 必须解释为什么 LOCAL_REWRITE 不足；影响事实、因果或人物意图的问题不得降级为 POLISH。"""
    return """NARRATIVEOS_REVIEW_V2
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
            "检查人物欲望、秘密、错误选择、关系冲突与行为一致性。重点识别全员好人、人物工具化、动机不足。",
        ),
        (
            "world-science-reviewer",
            "world-science",
            "检查世界规则与科学设定能否由既定假设推导，术语是否前后一致，是否出现为了剧情临时新增规则。硬逻辑矛盾标 blocking。",
        ),
        (
            "style-reviewer",
            "style",
            "检查叙述视角、节奏、句式、对白、氛围、重复表达和说明性语言。重点抓连续碎短句、空洞排除式描写、陌生术语未落地、功能性对白和模型腔。成片问题按 Skill 判级，不要把结构问题当成 POLISH。",
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
                    """设计核心人物，不写正文。每人必须给出：表层目标、深层欲望、恐惧、秘密、历史错误、底线、会做出的错误选择、与其他核心人物的不可调和矛盾、最终变化。禁止全员好人；主要冲突必须至少有一部分来自人物主动隐瞒、利用、越线或错误选择。""",
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
                    """严格依据已确认的故事架构、世界规则、人物矛盾、章节大纲和本次冻结写作 Skill 生成当前目标章节的完整正文。不得擅自新增世界规则；设定信息优先通过行动、环境、冲突和后果呈现，不让人物充当说明书。不要默认使用碎短句；普通叙事让动作、感受与关系进入完整语流。陌生术语第一次出现必须让普通读者当场理解。对白必须带人物意图和关系温度，不能只承担问答式信息传递。只输出正文。""",
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
                    """丰富场景承载力：补足空间、感官、动作、停顿、潜台词、气氛和冲突压力，但不得改变事件顺序、事实、世界规则和人物选择。删除纯说明式设定段落，让信息从场景中长出来。只输出完整正文。""",
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
                    """只做语言编辑，并严格执行本次冻结写作 Skill：改善节奏、句式、意象、对白质感和重复表达。重点清理连续碎短句与单句段落、空洞的排除式描写、未解释的陌生术语、没有情绪目的的功能性对白，以及高频“不是A，是B”等模型腔模板。能用具体正向感官形象表达时，不用排除法代替描写。不能新增或删除关键情节，不能改变设定和人物动机。只输出完整正文。""",
                ]
                if item
            ),
        )
        draft = prose.content
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
                    """根据五个独立 Reviewer 的结构化意见执行修订，并严格遵守冻结的“小说精修流程” Skill。按处置级别执行：REWRITE_BLOCK 重建对应段落/场景；LOCAL_REWRITE 只改最小范围；DELETE 直接删除无效内容；POLISH 仅做语言层调整。blocking 必须修复；不得把结构问题降级成润色，也不得因局部问题扩大重写范围。保留 Reviewer 标明的事实锚点与不得触碰范围。只输出重写后的完整正文。""",
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