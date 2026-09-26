from __future__ import annotations

import time
from dataclasses import dataclass

from app.db import connect
from app.services.ai_service import AssistResult, assist


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
    with connect() as conn:
        conn.execute(
            "UPDATE agent_runs SET status='failed',error=? WHERE id=?",
            (str(exc)[:2000], run_id),
        )


def _record_run_metric(run_id: int, prompt_version: str, duration_ms: int) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO agent_run_metrics(run_id,prompt_version,duration_ms)
            VALUES(?,?,?)
            ON CONFLICT(run_id) DO UPDATE SET
                prompt_version=excluded.prompt_version,
                duration_ms=excluded.duration_ms
            """,
            (run_id, prompt_version, duration_ms),
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
    prompt_version = f"{stage}-v1"
    try:
        result = await assist(mode=mode, content=content, instruction=instruction)
    except Exception as exc:
        duration_ms = max(0, int((time.perf_counter() - started) * 1000))
        _record_run_metric(run_id, prompt_version, duration_ms)
        _fail_run(run_id, exc)
        raise
    duration_ms = max(0, int((time.perf_counter() - started) * 1000))
    _record_run_metric(run_id, prompt_version, duration_ms)
    _finish_run(run_id, result)
    return result


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
        for line in block.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
            elif "：" in line:
                key, value = line.split("：", 1)
            else:
                continue
            fields[key.strip().lower()] = value.strip()

        severity = fields.get("严重性") or fields.get("severity") or "suggestion"
        severity = severity.lower()
        if severity not in {"blocking", "suggestion", "info"}:
            severity = "suggestion"

        excerpt = fields.get("片段") or fields.get("excerpt") or ""
        if excerpt.upper() == "NONE":
            excerpt = ""

        summary = fields.get("问题") or fields.get("summary") or stripped
        suggestion = fields.get("建议") or fields.get("suggestion") or ""

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
                SELECT prompt_version,duration_ms
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
                        """NARRATIVEOS_REVIEW_V1
请严格使用以下格式输出；每个问题一块，多个问题用单独一行 --- 分隔：
严重性: blocking|suggestion|info
片段: 必须逐字复制正文中的连续原文；没有具体片段写 NONE
问题: 一句话说明问题
建议: 一句话给出可执行修改
如果没有问题，只输出 NO_ISSUE。""",
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
