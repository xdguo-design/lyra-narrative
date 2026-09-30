from __future__ import annotations

import json
import math
import time
import uuid

from app.db import connect

PIPELINE_VERSION = "chapter-fast-local-retry-v5"


def epoch_ms() -> int:
    return int(time.time() * 1000)


def start_pipeline_run(
    *,
    task_id: int,
    chapter_id: int | None,
    chapter_number: int,
    pipeline_version: str = PIPELINE_VERSION,
) -> dict[str, object]:
    started_at_ms = epoch_ms()
    run_key = (
        f"ch{chapter_number:02d}-{task_id}-"
        f"{started_at_ms}-{uuid.uuid4().hex[:8]}"
    )
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO chapter_pipeline_runs(
                run_key,task_id,chapter_id,chapter_number,pipeline_version,
                status,started_at_ms
            ) VALUES(?,?,?,?,?,'running',?)
            """,
            (
                run_key,
                task_id,
                chapter_id,
                chapter_number,
                pipeline_version,
                started_at_ms,
            ),
        )
    payload = {
        "pipeline_run_id": int(cur.lastrowid),
        "run_key": run_key,
        "started_at_ms": started_at_ms,
        "pipeline_version": pipeline_version,
    }
    print(
        "[pipeline-metric] "
        + json.dumps(
            {
                "event": "pipeline_start",
                **payload,
                "task_id": task_id,
                "chapter_number": chapter_number,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        flush=True,
    )
    return payload


def record_local_event(
    *,
    pipeline_run_id: int,
    stage: str,
    status: str,
    started_at_ms: int,
    finished_at_ms: int,
    role: str = "",
    category: str = "",
    attempt: int = 1,
    chars_before: int | None = None,
    chars_after: int | None = None,
    length_distance_before: int | None = None,
    length_distance_after: int | None = None,
    trigger_reason: str = "",
    metadata: dict[str, object] | None = None,
) -> int:
    duration_ms = max(0, finished_at_ms - started_at_ms)
    metadata_json = json.dumps(
        metadata or {},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO chapter_pipeline_events(
                pipeline_run_id,stage,status,started_at_ms,finished_at_ms,
                duration_ms,role,category,attempt,chars_before,chars_after,
                length_distance_before,length_distance_after,trigger_reason,
                metadata_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                pipeline_run_id,
                stage,
                status,
                started_at_ms,
                finished_at_ms,
                duration_ms,
                role,
                category,
                attempt,
                chars_before,
                chars_after,
                length_distance_before,
                length_distance_after,
                trigger_reason,
                metadata_json,
            ),
        )
        event_id = int(cur.lastrowid)
    _log_event(
        {
            "event": "stage_end",
            "pipeline_run_id": pipeline_run_id,
            "event_id": event_id,
            "stage": stage,
            "role": role,
            "status": status,
            "attempt": attempt,
            "duration_ms": duration_ms,
            "chars_before": chars_before,
            "chars_after": chars_after,
            "trigger_reason": trigger_reason,
        }
    )
    return event_id


def _normalized_stage(role: str, source_stage: str) -> tuple[str, str, int]:
    role_key = role.strip().lower()
    category = {
        "continuity-plot-reviewer": "continuity-plot",
        "continuity-reviewer": "continuity-plot",
        "character-dialogue-reviewer": "character-dialogue",
        "language-rhythm-reviewer": "language-rhythm",
    }.get(role_key, role_key)

    if source_stage == "chapter-02-fast-draft":
        return "writer", "writer", 1
    if source_stage == "chapter-02-length-repair":
        return "length-repair", "length", 1
    if source_stage.startswith("chapter-02-length-repair-"):
        suffix = source_stage.removeprefix("chapter-02-length-repair-")
        return f"length-repair-{suffix}", "length", 1
    if source_stage.startswith("review-r1-retry"):
        prefix = category or "review"
        return f"{prefix}-review-retry", category, 2
    if source_stage == "review-r1":
        prefix = category or "review"
        return f"{prefix}-review-initial", category, 1
    return source_stage, category, 1


def _error_fields(error: str) -> tuple[str, str]:
    raw = (error or "").strip()
    if not raw:
        return "", ""
    lower = raw.lower()
    if "429" in lower:
        code = "429"
    elif "timeout" in lower:
        code = "timeout"
    else:
        code = ""
    error_type = raw.split(":", 1)[0].strip() if ":" in raw else ""
    return error_type, code


def sync_agent_run_events(*, pipeline_run_id: int, task_id: int) -> None:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT ar.id,ar.role,ar.stage,ar.status,ar.provider,ar.model,ar.error,
                   m.duration_ms,m.started_at_ms,m.finished_at_ms,
                   m.input_chars,m.output_chars,m.context_tier
            FROM agent_runs ar
            LEFT JOIN agent_run_metrics m ON m.run_id=ar.id
            WHERE ar.task_id=?
            ORDER BY ar.id
            """,
            (task_id,),
        ).fetchall()

        initial_event_by_role: dict[str, int] = {}
        for row in rows:
            source_run_id = int(row["id"])
            exists = conn.execute(
                """
                SELECT id FROM chapter_pipeline_events
                WHERE pipeline_run_id=? AND source_run_id=?
                """,
                (pipeline_run_id, source_run_id),
            ).fetchone()
            if exists:
                continue

            stage, category, attempt = _normalized_stage(
                str(row["role"] or ""),
                str(row["stage"] or ""),
            )
            error_type, error_code = _error_fields(str(row["error"] or ""))
            retry_of_event_id = (
                initial_event_by_role.get(str(row["role"] or ""))
                if attempt > 1
                else None
            )
            cur = conn.execute(
                """
                INSERT INTO chapter_pipeline_events(
                    pipeline_run_id,source_run_id,stage,source_stage,role,
                    category,attempt,retry_of_event_id,status,started_at_ms,
                    finished_at_ms,duration_ms,provider,model,input_chars,
                    output_chars,context_tier,error_type,error_code,error_message,
                    trigger_reason
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    pipeline_run_id,
                    source_run_id,
                    stage,
                    str(row["stage"] or ""),
                    str(row["role"] or ""),
                    category,
                    attempt,
                    retry_of_event_id,
                    str(row["status"] or ""),
                    int(row["started_at_ms"] or 0),
                    int(row["finished_at_ms"] or 0),
                    int(row["duration_ms"] or 0),
                    str(row["provider"] or ""),
                    str(row["model"] or ""),
                    int(row["input_chars"] or 0),
                    int(row["output_chars"] or 0),
                    str(row["context_tier"] or ""),
                    error_type,
                    error_code,
                    str(row["error"] or "")[:2000],
                    "reviewer_initial_failed" if attempt > 1 else "",
                ),
            )
            event_id = int(cur.lastrowid)
            if attempt == 1 and str(row["stage"] or "") == "review-r1":
                initial_event_by_role[str(row["role"] or "")] = event_id
            _log_event(
                {
                    "event": "stage_end",
                    "pipeline_run_id": pipeline_run_id,
                    "event_id": event_id,
                    "source_run_id": source_run_id,
                    "stage": stage,
                    "source_stage": str(row["stage"] or ""),
                    "role": str(row["role"] or ""),
                    "status": str(row["status"] or ""),
                    "attempt": attempt,
                    "provider": str(row["provider"] or ""),
                    "model": str(row["model"] or ""),
                    "duration_ms": int(row["duration_ms"] or 0),
                    "input_chars": int(row["input_chars"] or 0),
                    "output_chars": int(row["output_chars"] or 0),
                    "context_tier": str(row["context_tier"] or ""),
                    "error_type": error_type,
                    "error_code": error_code,
                }
            )


def classify_scenario(
    *,
    length_repair_triggered: bool,
    initial_failed_reviewer_count: int,
    review_retry_count: int,
    retry_recovered_count: int,
    retry_failed_count: int,
) -> str:
    if retry_failed_count:
        return "reviewer_retry_failed"
    if length_repair_triggered and review_retry_count:
        return "length_repair_and_reviewer_retry"
    if (
        not length_repair_triggered
        and initial_failed_reviewer_count == 1
        and review_retry_count == 1
        and retry_recovered_count == 1
    ):
        return "single_reviewer_retry"
    if length_repair_triggered and review_retry_count == 0:
        return "length_repair"
    if (
        not length_repair_triggered
        and initial_failed_reviewer_count == 0
        and review_retry_count == 0
    ):
        return "normal"
    return "other"


def event_summary(pipeline_run_id: int) -> dict[str, int]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT stage,source_stage,role,status,attempt,duration_ms,
                   started_at_ms,finished_at_ms
            FROM chapter_pipeline_events
            WHERE pipeline_run_id=?
            ORDER BY id
            """,
            (pipeline_run_id,),
        ).fetchall()

    writer_ms = max(
        (int(row["duration_ms"]) for row in rows if row["stage"] == "writer"),
        default=0,
    )
    length_repairs = [
        row
        for row in rows
        if str(row["source_stage"]).startswith("chapter-02-length-repair")
    ]
    initial = [row for row in rows if str(row["source_stage"]) == "review-r1"]
    retries = [
        row
        for row in rows
        if str(row["source_stage"]).startswith("review-r1-retry")
    ]

    def wall(group: list[object]) -> int:
        starts = [int(row["started_at_ms"] or 0) for row in group if row["started_at_ms"]]
        ends = [int(row["finished_at_ms"] or 0) for row in group if row["finished_at_ms"]]
        if not starts or not ends:
            return 0
        return max(0, max(ends) - min(starts))

    length_repair_ms = wall(length_repairs)
    review_initial_wall_ms = wall(initial)
    all_review = initial + retries
    review_total_wall_ms = wall(all_review)
    review_retry_wall_ms = max(0, review_total_wall_ms - review_initial_wall_ms)

    return {
        "writer_ms": writer_ms,
        "length_repair_ms": length_repair_ms,
        "review_initial_wall_ms": review_initial_wall_ms,
        "review_total_wall_ms": review_total_wall_ms,
        "review_compute_ms": sum(int(row["duration_ms"] or 0) for row in initial),
        "initial_failed_reviewer_count": sum(
            1 for row in initial if str(row["status"]) == "failed"
        ),
        "review_retry_count": len(retries),
        "review_retry_wall_ms": review_retry_wall_ms,
        "review_retry_compute_ms": sum(
            int(row["duration_ms"] or 0) for row in retries
        ),
        "retry_recovered_count": sum(
            1 for row in retries if str(row["status"]) == "completed"
        ),
        "retry_failed_count": sum(
            1 for row in retries if str(row["status"]) == "failed"
        ),
    }


def finish_pipeline_run(
    *,
    pipeline_run_id: int,
    length_repair_triggered: bool,
    finalize_ms: int,
    draft_chars_initial: int,
    draft_chars_final: int,
    blocking_count: int,
    hard_gate_count: int,
) -> dict[str, object]:
    summary = event_summary(pipeline_run_id)
    scenario = classify_scenario(
        length_repair_triggered=length_repair_triggered,
        initial_failed_reviewer_count=summary["initial_failed_reviewer_count"],
        review_retry_count=summary["review_retry_count"],
        retry_recovered_count=summary["retry_recovered_count"],
        retry_failed_count=summary["retry_failed_count"],
    )
    finished_at_ms = epoch_ms()
    with connect() as conn:
        row = conn.execute(
            "SELECT started_at_ms FROM chapter_pipeline_runs WHERE id=?",
            (pipeline_run_id,),
        ).fetchone()
        if not row:
            raise ValueError("pipeline run not found")
        core_pipeline_ms = max(0, finished_at_ms - int(row["started_at_ms"]))
        conn.execute(
            """
            UPDATE chapter_pipeline_runs
            SET status='awaiting_master_review',scenario=?,
                automated_finished_at_ms=?,core_pipeline_ms=?,
                writer_ms=?,length_repair_triggered=?,length_repair_ms=?,
                review_initial_wall_ms=?,review_total_wall_ms=?,
                review_compute_ms=?,initial_failed_reviewer_count=?,
                review_retry_count=?,review_retry_wall_ms=?,
                review_retry_compute_ms=?,retry_recovered_count=?,
                retry_failed_count=?,finalize_ms=?,draft_chars_initial=?,
                draft_chars_final=?,blocking_count=?,hard_gate_count=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (
                scenario,
                finished_at_ms,
                core_pipeline_ms,
                summary["writer_ms"],
                int(length_repair_triggered),
                summary["length_repair_ms"],
                summary["review_initial_wall_ms"],
                summary["review_total_wall_ms"],
                summary["review_compute_ms"],
                summary["initial_failed_reviewer_count"],
                summary["review_retry_count"],
                summary["review_retry_wall_ms"],
                summary["review_retry_compute_ms"],
                summary["retry_recovered_count"],
                summary["retry_failed_count"],
                finalize_ms,
                draft_chars_initial,
                draft_chars_final,
                blocking_count,
                hard_gate_count,
                pipeline_run_id,
            ),
        )
        result = conn.execute(
            "SELECT * FROM chapter_pipeline_runs WHERE id=?",
            (pipeline_run_id,),
        ).fetchone()
    payload = dict(result)
    _log_event({"event": "pipeline_end", **payload})
    return payload


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    rank = max(1, math.ceil((percentile / 100.0) * len(ordered)))
    return int(ordered[min(len(ordered), rank) - 1])


def latency_report(
    *,
    chapter_number: int,
    pipeline_version: str = PIPELINE_VERSION,
) -> dict[str, object]:
    scenarios = [
        "normal",
        "single_reviewer_retry",
        "length_repair",
        "length_repair_and_reviewer_retry",
        "reviewer_retry_failed",
    ]
    report: dict[str, object] = {}
    with connect() as conn:
        for scenario in scenarios:
            rows = conn.execute(
                """
                SELECT core_pipeline_ms,writer_ms,length_repair_ms,
                       review_initial_wall_ms,review_retry_wall_ms,finalize_ms
                FROM chapter_pipeline_runs
                WHERE chapter_number=? AND pipeline_version=?
                  AND scenario=? AND status='awaiting_master_review'
                ORDER BY id
                """,
                (chapter_number, pipeline_version, scenario),
            ).fetchall()
            metric_names = [
                "core_pipeline_ms",
                "writer_ms",
                "length_repair_ms",
                "review_initial_wall_ms",
                "review_retry_wall_ms",
                "finalize_ms",
            ]
            metrics: dict[str, object] = {}
            for metric_name in metric_names:
                values = [int(row[metric_name]) for row in rows]
                metrics[metric_name] = {
                    "p50_ms": _percentile(values, 50),
                    "p95_ms": _percentile(values, 95),
                    "max_ms": max(values, default=0),
                }
            report[scenario] = {
                "n": len(rows),
                "p95_status": (
                    "data_insufficient"
                    if len(rows) < 20
                    else "provisional" if len(rows) < 100 else "stable"
                ),
                "metrics": metrics,
            }
    return {
        "chapter_number": chapter_number,
        "pipeline_version": pipeline_version,
        "scenarios": report,
    }


def _log_event(payload: dict[str, object]) -> None:
    print(
        "[pipeline-metric] "
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        flush=True,
    )
