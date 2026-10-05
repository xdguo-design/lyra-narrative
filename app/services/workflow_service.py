from __future__ import annotations

import time
from dataclasses import dataclass

from app.db import connect
from app.services.ai_service import AssistResult, assist
from app.services.rejection_learning import learn_from_open_blocking_findings


class WorkflowStateError(RuntimeError):
    pass


@dataclass(slots=True)
class AgentStep:
    role: str
    stage: str
    mode: str
    instruction: str


def _selected_skills(conn, task_id: int, project_id: int):
    policy = conn.execute(
        "SELECT mode FROM writing_task_skill_policy WHERE task_id=?",
        (task_id,),
    ).fetchone()

    if policy and str(policy["mode"] or "") == "default":
        # Default selection means "use the platform defaults", not "pin forever
        # to the versions that happened to exist when the task was created".
        # Global Writer/Reader Skills learn from rejections across projects, so
        # a default task must refresh its bound versions before every run.
        conn.execute(
            """
            UPDATE writing_task_skills
            SET version=(
                SELECT s.current_version
                FROM skills s
                WHERE s.id=writing_task_skills.skill_id
            )
            WHERE task_id=?
            """,
            (task_id,),
        )

    selected = conn.execute(
        """
        SELECT s.id,s.name,s.purpose,wts.version,sv.content
        FROM writing_task_skills wts
        JOIN skills s ON s.id=wts.skill_id
        JOIN skill_versions sv
          ON sv.skill_id=wts.skill_id AND sv.version=wts.version
        WHERE wts.task_id=?
        ORDER BY s.id
        """,
        (task_id,),
    ).fetchall()

    if policy:
        return selected

    return conn.execute(
        """
        SELECT s.id,s.name,s.purpose,s.current_version AS version,s.content
        FROM skills s
        WHERE s.enabled=1 AND (s.project_id IS NULL OR s.project_id=?)
        ORDER BY s.project_id IS NOT NULL DESC,s.updated_at DESC,s.id DESC
        LIMIT 12
        """,
        (project_id,),
    ).fetchall()


def _task_context(task_id: int, project_id: int) -> str:
    with connect() as conn:
        memories = conn.execute(
            """
            SELECT kind,title,content
            FROM memories
            WHERE project_id=? AND confirmed=1
            ORDER BY updated_at DESC,id DESC
            LIMIT 20
            """,
            (project_id,),
        ).fetchall()
        skills = _selected_skills(conn, task_id, project_id)

    parts: list[str] = []
    if memories:
        parts.append(
            "已确认作品记忆：\n"
            + "\n".join(
                f"- [{row['kind']}] {row['title']}: {row['content']}" for row in memories
            )
        )
    if skills:
        parts.append(
            "本次冻结技能：\n"
            + "\n".join(
                f"- {row['name']} v{row['version']}：{row['purpose']}\n  {row['content']}"
                for row in skills
            )
        )
    return "\n\n".join(parts)


def _create_run(task_id: int, role: str, stage: str, input_text: str) -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO agent_runs(task_id,role,stage,status,input_excerpt)
            VALUES(?,?,?,?,?)
            """,
            (task_id, role, stage, "running", input_text[-2000:]),
        )
        run_id = int(cur.lastrowid)
        task = conn.execute(
            """
            SELECT wt.project_id,wt.chapter_id,c.position AS chapter_position
            FROM writing_tasks wt
            LEFT JOIN chapters c ON c.id=wt.chapter_id
            WHERE wt.id=?
            """,
            (task_id,),
        ).fetchone()
        if task:
            memories = conn.execute(
                """
                SELECT m.id,m.kind,m.title,m.content,
                       COALESCE(MAX(mv.version),1) AS version
                FROM memories m
                LEFT JOIN memory_versions mv ON mv.memory_id=m.id
                WHERE m.project_id=? AND m.confirmed=1
                GROUP BY m.id
                ORDER BY m.updated_at DESC,m.id DESC
                LIMIT 20
                """,
                (task["project_id"],),
            ).fetchall()
            for memory in memories:
                conn.execute(
                    """
                    INSERT INTO agent_run_resources(
                        run_id,resource_type,resource_id,version,title,content
                    ) VALUES(?,?,?,?,?,?)
                    """,
                    (
                        run_id,
                        "memory",
                        memory["id"],
                        memory["version"],
                        f"[{memory['kind']}] {memory['title']}",
                        memory["content"],
                    ),
                )

            if task["chapter_position"] is None:
                story_state = conn.execute(
                    """
                    SELECT id,chapter_number,state_json
                    FROM story_state_snapshots
                    WHERE project_id=?
                    ORDER BY chapter_number DESC,id DESC
                    LIMIT 1
                    """,
                    (task["project_id"],),
                ).fetchone()
            else:
                story_state = conn.execute(
                    """
                    SELECT id,chapter_number,state_json
                    FROM story_state_snapshots
                    WHERE project_id=? AND chapter_number<?
                    ORDER BY chapter_number DESC,id DESC
                    LIMIT 1
                    """,
                    (task["project_id"], task["chapter_position"]),
                ).fetchone()
            if story_state:
                conn.execute(
                    """
                    INSERT INTO agent_run_resources(
                        run_id,resource_type,resource_id,version,title,content
                    ) VALUES(?,?,?,?,?,?)
                    """,
                    (
                        run_id,
                        "story_state",
                        story_state["id"],
                        story_state["chapter_number"],
                        f"Story State after chapter {story_state['chapter_number']}",
                        story_state["state_json"],
                    ),
                )

            skills = _selected_skills(
                conn,
                task_id,
                int(task["project_id"]),
            )
            for skill in skills:
                conn.execute(
                    """
                    INSERT INTO agent_run_resources(
                        run_id,resource_type,resource_id,version,title,content
                    ) VALUES(?,?,?,?,?,?)
                    """,
                    (
                        run_id,
                        "skill",
                        skill["id"],
                        skill["version"],
                        skill["name"],
                        skill["content"],
                    ),
                )
        return run_id


def _finish_run(run_id: int, result: AssistResult) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE agent_runs
            SET status='completed',output=?,provider=?,model=?,error=''
            WHERE id=?
            """,
            (result.content, result.provider, result.model, run_id),
        )


def _fail_run(run_id: int, exc: Exception) -> None:
    provider = str(getattr(exc, "provider", "") or "")
    model = str(getattr(exc, "model", "") or "")
    error = f"{type(exc).__name__}: {exc}"[:2000]
    with connect() as conn:
        conn.execute(
            """
            UPDATE agent_runs
            SET status='failed',provider=?,model=?,error=?
            WHERE id=?
            """,
            (provider, model, error, run_id),
        )


def _prompt_size(content: str, instruction: str) -> tuple[int, str]:
    user_prompt = f"当前正文：\n{content[-12000:]}"
    if instruction.strip():
        user_prompt += f"\n\n额外要求：\n{instruction.strip()}"
    input_chars = len(user_prompt)
    context_tier = (
        "short" if input_chars <= 6000
        else "medium" if input_chars <= 14000
        else "long"
    )
    return input_chars, context_tier


def _record_run_metric(
    run_id: int,
    prompt_version: str,
    duration_ms: int,
    *,
    started_at_ms: int,
    finished_at_ms: int,
    input_chars: int,
    output_chars: int,
    context_tier: str,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO agent_run_metrics(
                run_id,prompt_version,duration_ms,started_at_ms,finished_at_ms,
                input_chars,output_chars,context_tier
            ) VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(run_id) DO UPDATE SET
                prompt_version=excluded.prompt_version,
                duration_ms=excluded.duration_ms,
                started_at_ms=excluded.started_at_ms,
                finished_at_ms=excluded.finished_at_ms,
                input_chars=excluded.input_chars,
                output_chars=excluded.output_chars,
                context_tier=excluded.context_tier
            """,
            (
                run_id,
                prompt_version,
                duration_ms,
                started_at_ms,
                finished_at_ms,
                input_chars,
                output_chars,
                context_tier,
            ),
        )


async def _run_step(
    *,
    task_id: int,
    role: str,
    stage: str,
    mode: str,
    content: str,
    instruction: str,
) -> AssistResult:
    run_id = _create_run(task_id, role, stage, content)
    started = time.perf_counter()
    started_at_ms = int(time.time() * 1000)
    input_chars, context_tier = _prompt_size(content, instruction)
    prompt_version = f"{stage}-v1"
    print(
        f"[agent-step] START task={task_id} run={run_id} "
        f"role={role} stage={stage} input_chars={input_chars} "
        f"context_tier={context_tier}",
        flush=True,
    )
    try:
        result = await assist(
            mode=mode,
            content=content,
            instruction=instruction,
            role=role,
        )
    except Exception as exc:
        duration_ms = max(0, int((time.perf_counter() - started) * 1000))
        finished_at_ms = int(time.time() * 1000)
        _record_run_metric(
            run_id,
            prompt_version,
            duration_ms,
            started_at_ms=started_at_ms,
            finished_at_ms=finished_at_ms,
            input_chars=input_chars,
            output_chars=0,
            context_tier=context_tier,
        )
        _fail_run(run_id, exc)
        error_code = str(getattr(exc, "status_code", "") or "")
        print(
            f"[agent-step] FAIL task={task_id} run={run_id} "
            f"role={role} stage={stage} elapsed_ms={duration_ms} "
            f"input_chars={input_chars} output_chars=0 "
            f"context_tier={context_tier} error={type(exc).__name__} "
            f"error_code={error_code or '-'}",
            flush=True,
        )
        raise
    duration_ms = max(0, int((time.perf_counter() - started) * 1000))
    finished_at_ms = int(time.time() * 1000)
    output_chars = len(result.content or "")
    _record_run_metric(
        run_id,
        prompt_version,
        duration_ms,
        started_at_ms=started_at_ms,
        finished_at_ms=finished_at_ms,
        input_chars=input_chars,
        output_chars=output_chars,
        context_tier=context_tier,
    )
    _finish_run(run_id, result)
    print(
        f"[agent-step] DONE task={task_id} run={run_id} "
        f"role={role} stage={stage} provider={result.provider} "
        f"model={result.model} elapsed_ms={duration_ms} "
        f"input_chars={input_chars} output_chars={output_chars} "
        f"context_tier={context_tier}",
        flush=True,
    )
    return result


def _normalize_review_field_key(value: str) -> str:
    return (
        str(value or "")
        .strip()
        .strip("*_`#[]【】 ")
        .replace(" ", "")
        .lower()
    )


def _normalize_review_field_value(value: str) -> str:
    return str(value or "").strip().strip("*_` ").strip()


def _parse_review_output(text: str, draft: str) -> list[dict]:
    stripped = text.strip()
    if stripped == "NO_ISSUE":
        return [
            {
                "severity": "info",
                "summary": "未发现明确问题。",
                "suggestion": "",
                "excerpt": "",
                "start_offset": None,
                "end_offset": None,
            }
        ]

    findings: list[dict] = []
    blocks = [block.strip() for block in stripped.split("\n---\n") if block.strip()]
    for block in blocks:
        fields: dict[str, str] = {}
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("【") and "】" in line:
                key, value = line[1:].split("】", 1)
                fields[_normalize_review_field_key(key)] = _normalize_review_field_value(
                    value.lstrip("：: ")
                )
                continue
            normalized = line.lstrip("- ").strip()
            if ":" in normalized:
                key, value = normalized.split(":", 1)
            elif "：" in normalized:
                key, value = normalized.split("：", 1)
            else:
                continue
            fields[_normalize_review_field_key(key)] = _normalize_review_field_value(value)

        raw_severity = (
            fields.get("严重性")
            or fields.get("severity")
            or ""
        )
        severity_token = _normalize_review_field_value(raw_severity).lower()
        disposition = _normalize_review_field_value(
            fields.get("处置级别") or fields.get("disposition") or ""
        ).upper()
        verdict = _normalize_review_field_value(
            fields.get("verdict") or fields.get("复审结果") or ""
        ).upper()

        if severity_token in {
            "blocking",
            "high",
            "高",
            "critical",
            "严重",
            "p0",
        }:
            severity = "blocking"
        elif severity_token in {
            "info",
            "low",
            "低",
            "pass",
            "none",
        }:
            severity = "info"
        elif severity_token in {
            "suggestion",
            "medium",
            "中",
            "warning",
            "warn",
            "p1",
            "p2",
        }:
            severity = "suggestion"
        else:
            severity = "suggestion"

        # Disposition and recheck verdict are stronger than prose labels.
        # Reviewer contracts allow localized HIGH findings and explicit
        # REWRITE_BLOCK/FAIL signals; those must never be silently downgraded.
        if disposition == "REWRITE_BLOCK" or verdict == "FAIL":
            severity = "blocking"

        excerpt = (
            fields.get("逐字片段")
            or fields.get("片段")
            or fields.get("excerpt")
            or ""
        )
        if excerpt.upper() == "NONE" or excerpt.startswith("<逐字原文"):
            excerpt = ""

        summary = (
            fields.get("问题说明")
            or fields.get("问题")
            or fields.get("summary")
            or stripped
        )
        rationale = fields.get("判级理由") or ""
        objective = fields.get("执行目标") or ""
        suggestion = (
            fields.get("建议动作")
            or fields.get("建议")
            or fields.get("suggestion")
            or ""
        )
        details = []
        if disposition:
            details.append(f"处置级别={disposition}")
        if rationale:
            details.append(f"判级理由={rationale}")
        if objective:
            details.append(f"执行目标={objective}")
        if details:
            suggestion = (suggestion + ("；" if suggestion else "") + "；".join(details)).strip()

        start_offset = draft.find(excerpt) if excerpt else -1
        findings.append(
            {
                "severity": severity,
                "summary": summary,
                "suggestion": suggestion,
                "excerpt": excerpt,
                "start_offset": start_offset if start_offset >= 0 else None,
                "end_offset": (
                    start_offset + len(excerpt)
                    if start_offset >= 0 and excerpt
                    else None
                ),
            }
        )

    if findings:
        return findings

    lowered = stripped.lower()
    severity = (
        "blocking"
        if any(token in lowered for token in ("冲突", "错误", "矛盾", "阻断"))
        else "suggestion"
    )
    return [
        {
            "severity": severity,
            "summary": stripped or "Reviewer 未返回可解析内容。",
            "suggestion": "由 Revision Agent 结合人工判断处理。",
            "excerpt": "",
            "start_offset": None,
            "end_offset": None,
        }
    ]


def get_task(task_id: int) -> dict | None:
    with connect() as conn:
        task = conn.execute("SELECT * FROM writing_tasks WHERE id=?", (task_id,)).fetchone()
        if not task:
            return None
        result = dict(task)
        runs = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM agent_runs WHERE task_id=? ORDER BY id", (task_id,)
            ).fetchall()
        ]
        for run in runs:
            run["resources"] = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT resource_type,resource_id,version,title,content
                    FROM agent_run_resources
                    WHERE run_id=?
                    ORDER BY resource_type,id
                    """,
                    (run["id"],),
                ).fetchall()
            ]
            metric = conn.execute(
                """
                SELECT prompt_version,duration_ms,started_at_ms,finished_at_ms,
                       input_chars,output_chars,context_tier
                FROM agent_run_metrics
                WHERE run_id=?
                """,
                (run["id"],),
            ).fetchone()
            run["metrics"] = dict(metric) if metric else None
        result["runs"] = runs

        findings = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM review_findings WHERE task_id=? ORDER BY id", (task_id,)
            ).fetchall()
        ]
        for finding in findings:
            location = conn.execute(
                """
                SELECT excerpt,start_offset,end_offset
                FROM review_finding_refs
                WHERE finding_id=?
                """,
                (finding["id"],),
            ).fetchone()
            finding["location"] = dict(location) if location else None
        result["findings"] = findings
        result["approvals"] = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM approvals WHERE task_id=? ORDER BY id", (task_id,)
            ).fetchall()
        ]
        result["skills"] = [
            dict(row)
            for row in conn.execute(
                """
                SELECT s.id,s.name,s.purpose,wts.version,sv.content
                FROM writing_task_skills wts
                JOIN skills s ON s.id=wts.skill_id
                JOIN skill_versions sv
                  ON sv.skill_id=wts.skill_id AND sv.version=wts.version
                WHERE wts.task_id=?
                ORDER BY s.id
                """,
                (task_id,),
            ).fetchall()
        ]
        return result


async def run_task(task_id: int) -> dict:
    with connect() as conn:
        task = conn.execute("SELECT * FROM writing_tasks WHERE id=?", (task_id,)).fetchone()
        if not task:
            raise ValueError("task not found")
        if task["status"] in {"running", "awaiting_approval", "approved"}:
            raise WorkflowStateError(
                f"task cannot run while status is {task['status']}"
            )
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

    base_content = chapter["content"] if chapter else ""
    context = _task_context(task_id, int(task["project_id"]))
    writer_instruction = "\n\n".join(
        item
        for item in [
            f"写作目标：{task['goal']}",
            str(task["instruction"] or "").strip(),
            context,
            "请生成可供审阅的完整草稿；不要直接覆盖现有章节。",
        ]
        if item
    )

    try:
        writer = await _run_step(
            task_id=task_id,
            role="writer",
            stage="draft",
            mode="continue",
            content=base_content,
            instruction=writer_instruction,
        )
    except Exception:
        with connect() as conn:
            conn.execute(
                "UPDATE writing_tasks SET status='failed',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (task_id,),
            )
        raise

    writer_output = writer.content.strip()
    if base_content.strip():
        draft_content = (
            base_content.rstrip() + "\n\n" + writer_output
            if writer_output
            else base_content
        )
    else:
        draft_content = writer_output

    with connect() as conn:
        conn.execute(
            "UPDATE writing_tasks SET draft=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (draft_content, task_id),
        )
        conn.execute("DELETE FROM review_findings WHERE task_id=?", (task_id,))

    reviewer_specs = [
        (
            "continuity-reviewer",
            "continuity",
            "检查人物状态、称谓、时间线、地点、道具和世界规则连续性。列出明确问题与修改建议；没有问题也要明确说明。",
        ),
        (
            "plot-reviewer",
            "plot",
            "检查剧情因果、动机、信息揭示、冲突推进和悬念是否成立。列出阻断项和建议项。",
        ),
        (
            "style-reviewer",
            "style",
            "检查叙述视角、节奏、句式、重复表达和语言风格。只给可执行修改意见。",
        ),
    ]

    successful_reviews: list[str] = []
    for reviewer, category, review_instruction in reviewer_specs:
        try:
            review = await _run_step(
                task_id=task_id,
                role=reviewer,
                stage="review",
                mode="check",
                content=draft_content,
                instruction="\n\n".join(
                    item
                    for item in [
                        review_instruction,
                        """NARRATIVEOS_REVIEW_V2
请严格使用统一审核格式；每个问题一块，多个问题用单独一行 --- 分隔；没有问题只输出 NO_ISSUE。
【问题标识】R001 起递增
【审核轮次】INITIAL
【严重性】blocking / suggestion / info
【处置级别】REWRITE_BLOCK / LOCAL_REWRITE / DELETE / POLISH / PASS
【问题类型】continuity / causality / character / plot / exposition / dialogue / style / atmosphere
【问题定位】
- 章节/场景：可识别范围
- 段落范围：可识别范围
- 片段：必须逐字复制正文中的连续原文；没有具体片段写 NONE
【问题说明】一句话说明具体问题，禁止泛泛写“优化节奏/加强氛围”
【判级理由】说明为什么当前处置级别足够；REWRITE_BLOCK 必须说明为什么 LOCAL_REWRITE 不足
【修改边界】
- 最小修改范围：只写最少需要改动的范围
- 允许联动范围：必要时允许影响的相邻内容
- 不得触碰范围：必须保持不变的前后文或状态
【必须保留的事实】只列与当前问题直接相关的事实锚点
【禁止新增内容】针对当前问题列出禁止新增的人物/规则/线索/巧合/关系跳变/资源恢复
【执行目标】写成修改后可以客观检查的结果
【建议动作】一到三句可执行修改方向，不得发明新设定
【复审要求】说明修改后必须重新验证什么
【复审结果】PENDING
注意：处置级别与严重性不是一回事；若影响事实、因果或人物意图，不得只判 POLISH。""",
                        context,
                    ]
                    if item
                ),
            )
        except RuntimeError as exc:
            with connect() as conn:
                conn.execute(
                    """
                    INSERT INTO review_findings(
                        task_id,reviewer,category,severity,summary,suggestion,status
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        task_id,
                        reviewer,
                        category,
                        "warning",
                        f"Reviewer 执行失败：{exc}",
                        "可重试该任务；其他 Reviewer 结果仍保留。",
                        "open",
                    ),
                )
            continue

        successful_reviews.append(f"[{category}] {review.content}")
        parsed_findings = _parse_review_output(review.content, draft_content)
        with connect() as conn:
            for finding in parsed_findings:
                cur = conn.execute(
                    """
                    INSERT INTO review_findings(
                        task_id,reviewer,category,severity,summary,suggestion,status
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        task_id,
                        reviewer,
                        category,
                        finding["severity"],
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

    with connect() as conn:
        blocking = conn.execute(
            """
            SELECT 1 FROM review_findings
            WHERE task_id=? AND status='open' AND severity='blocking'
            LIMIT 1
            """,
            (task_id,),
        ).fetchone()
    if blocking:
        learn_from_open_blocking_findings(
            task_id=task_id,
            source="standard-review",
        )

    revision_instruction = "\n\n".join(
        item
        for item in [
            "根据 Reviewer 意见修订草稿。保留没有被指出问题的内容，不引入无关新设定。",
            str(task["instruction"] or "").strip(),
            "Reviewer 意见：\n" + "\n\n".join(successful_reviews)
            if successful_reviews
            else "Reviewer 本轮无可用结果；仅做保守润色，不改变事实。",
            context,
        ]
        if item
    )

    try:
        revision = await _run_step(
            task_id=task_id,
            role="revision-agent",
            stage="revision",
            mode="polish",
            content=draft_content,
            instruction=revision_instruction,
        )
    except RuntimeError:
        with connect() as conn:
            conn.execute(
                """
                UPDATE writing_tasks
                SET status='reviewed',updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (task_id,),
            )
        return get_task(task_id) or {}

    with connect() as conn:
        conn.execute(
            """
            UPDATE writing_tasks
            SET revised_content=?,status='awaiting_approval',updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (revision.content, task_id),
        )
    return get_task(task_id) or {}