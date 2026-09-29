from __future__ import annotations

from collections.abc import Iterable

from app.db import connect
from app.services.default_skills import (
    BUILTIN_READER_REVIEW_SKILL_NAME,
    BUILTIN_SKILLS,
    BUILTIN_WRITING_SKILL_NAME,
)
from app.services.skill_learning_store import (
    apply_db_learning_to_conn,
    build_learning_batch,
    persist_learning_batch,
)


def record_rejection_batch(
    *,
    task_id: int,
    source: str,
    events: Iterable[dict[str, str]],
) -> dict:
    event_list = [dict(event) for event in events if str(event.get("reason") or "").strip()]
    if not event_list:
        return {"recorded": 0, "batch_id": None, "skill_versions": {}}

    with connect() as conn:
        task = conn.execute(
            "SELECT project_id FROM writing_tasks WHERE id=?",
            (task_id,),
        ).fetchone()
        if not task:
            raise ValueError("task not found")
        project_id = int(task["project_id"])

    payload = build_learning_batch(
        task_id=task_id,
        project_id=project_id,
        source=source,
        events=event_list,
    )

    with connect() as conn:
        for event in payload["events"]:
            conn.execute(
                """
                INSERT INTO builtin_skill_learning_events(
                    batch_id,task_id,project_id,source,reviewer,category,
                    pattern_signature,reason,suggestion,excerpt
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    payload["batch_id"],
                    task_id,
                    project_id,
                    payload["source"],
                    event["reviewer"],
                    event["category"],
                    event["pattern_signature"],
                    event["reason"],
                    event["suggestion"],
                    event["excerpt"],
                ),
            )
            conn.execute(
                """
                INSERT INTO skill_rejection_events(
                    task_id,project_id,batch_id,source,reviewer,category,
                    pattern_signature,reason,suggestion,excerpt
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    task_id,
                    project_id,
                    payload["batch_id"],
                    payload["source"],
                    event["reviewer"],
                    event["category"],
                    event["pattern_signature"],
                    event["reason"],
                    event["suggestion"],
                    event["excerpt"],
                ),
            )

        versions = apply_db_learning_to_conn(conn, BUILTIN_SKILLS)
        for skill_name in (
            BUILTIN_WRITING_SKILL_NAME,
            BUILTIN_READER_REVIEW_SKILL_NAME,
        ):
            skill = conn.execute(
                """
                SELECT id,current_version
                FROM skills
                WHERE project_id IS NULL AND name=?
                ORDER BY id
                LIMIT 1
                """,
                (skill_name,),
            ).fetchone()
            if not skill:
                continue
            conn.execute(
                """
                INSERT INTO writing_task_skills(task_id,skill_id,version)
                VALUES(?,?,?)
                ON CONFLICT(task_id,skill_id)
                DO UPDATE SET version=excluded.version
                """,
                (task_id, int(skill["id"]), int(skill["current_version"])),
            )

    # Optional audit archive only; DB rows above are the source of truth.
    persist_learning_batch(
        task_id=task_id,
        project_id=project_id,
        source=source,
        events=event_list,
    )

    return {
        "recorded": len(payload["events"]),
        "batch_id": payload["batch_id"],
        "skill_versions": versions,
    }


def learn_from_open_blocking_findings(
    *,
    task_id: int,
    source: str,
) -> dict:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT rf.id,rf.reviewer,rf.category,rf.summary,rf.suggestion,
                   rr.excerpt
            FROM review_findings rf
            LEFT JOIN review_finding_refs rr ON rr.finding_id=rf.id
            WHERE rf.task_id=? AND rf.status='open' AND rf.severity='blocking'
            ORDER BY rf.id
            """,
            (task_id,),
        ).fetchall()

    events = [
        {
            "reviewer": str(row["reviewer"] or ""),
            "category": str(row["category"] or ""),
            "reason": str(row["summary"] or ""),
            "suggestion": str(row["suggestion"] or ""),
            "excerpt": str(row["excerpt"] or ""),
        }
        for row in rows
    ]
    return record_rejection_batch(
        task_id=task_id,
        source=source,
        events=events,
    )
