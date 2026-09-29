# ruff: noqa: I001
from __future__ import annotations

import datetime
import hashlib
import json
import os
import pathlib
import re
import tempfile
import uuid


WRITER_SKILL_NAME = "中文小说自然叙事"
READER_SKILL_NAME = "小说读者校验流程"


def learning_root() -> pathlib.Path:
    return pathlib.Path(
        os.getenv(
            "NARRATIVE_BUILTIN_SKILL_LEARNING_DIR",
            "data/builtin-skill-learning",
        )
    )


def _compact(value: str, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def pattern_signature(event: dict[str, str]) -> str:
    reason = str(event.get("reason") or "")
    labels = sorted(
        set(re.findall(r"\b[A-Z][A-Z0-9_]{3,}(?:_GAP|_LEAK)\b", reason))
    )
    basis = "|".join(
        [
            _compact(str(event.get("category") or ""), 100).lower(),
            ",".join(labels),
            _compact(reason, 360).lower(),
        ]
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]


def normalize_event(event: dict[str, str]) -> dict[str, str]:
    reason = str(event.get("reason") or "").strip()
    if not reason:
        raise ValueError("rejection learning event requires a reason")
    normalized = {
        "reviewer": _compact(str(event.get("reviewer") or "unknown"), 120),
        "category": _compact(str(event.get("category") or "unspecified"), 120),
        "reason": _compact(reason, 1200),
        "suggestion": _compact(str(event.get("suggestion") or ""), 700),
        "excerpt": _compact(str(event.get("excerpt") or ""), 500),
    }
    normalized["pattern_signature"] = pattern_signature(normalized)
    return normalized


def build_learning_batch(
    *,
    task_id: int,
    project_id: int,
    source: str,
    events: list[dict[str, str]],
) -> dict:
    normalized = [normalize_event(event) for event in events]
    if not normalized:
        raise ValueError("rejection learning batch must not be empty")
    return {
        "schema": "NARRATIVE_BUILTIN_SKILL_LEARNING_V2",
        "batch_id": uuid.uuid4().hex,
        "task_id": task_id,
        "project_id": project_id,
        "source": _compact(source, 120),
        "recorded_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "events": normalized,
    }


def persist_learning_batch(
    *,
    task_id: int,
    project_id: int,
    source: str,
    events: list[dict[str, str]],
) -> dict:
    payload = build_learning_batch(
        task_id=task_id,
        project_id=project_id,
        source=source,
        events=events,
    )
    batch_id = payload["batch_id"]

    root = learning_root()
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{batch_id}.json"
    fd, tmp_name = tempfile.mkstemp(prefix=".learning-", suffix=".json", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        pathlib.Path(tmp_name).replace(target)
    except (OSError, UnicodeError):
        pathlib.Path(tmp_name).unlink(missing_ok=True)
    return payload


def load_learning_batches() -> list[dict]:
    root = learning_root()
    if not root.exists():
        return []
    batches: list[dict] = []
    for path in sorted(root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if payload.get("schema") not in {
            "NARRATIVE_BUILTIN_SKILL_LEARNING_V1",
            "NARRATIVE_BUILTIN_SKILL_LEARNING_V2",
        }:
            continue
        if not isinstance(payload.get("events"), list):
            continue
        batches.append(payload)
    return batches


def _group_patterns(batches: list[dict]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for batch in batches:
        for raw in batch.get("events", []):
            if not isinstance(raw, dict):
                continue
            event = normalize_event(
                {
                    "reviewer": str(raw.get("reviewer") or ""),
                    "category": str(raw.get("category") or ""),
                    "reason": str(raw.get("reason") or ""),
                    "suggestion": str(raw.get("suggestion") or ""),
                    "excerpt": str(raw.get("excerpt") or ""),
                }
            )
            sig = str(raw.get("pattern_signature") or event["pattern_signature"])
            current = grouped.get(sig)
            if current is None:
                grouped[sig] = {
                    **event,
                    "pattern_signature": sig,
                    "occurrences": 1,
                    "sources": {str(batch.get("source") or "")},
                }
            else:
                current["occurrences"] += 1
                current["sources"].add(str(batch.get("source") or ""))
                if event["excerpt"]:
                    current["excerpt"] = event["excerpt"]
                if event["suggestion"]:
                    current["suggestion"] = event["suggestion"]
    result = list(grouped.values())
    result.sort(
        key=lambda item: (
            -int(item["occurrences"]),
            str(item["category"]),
            str(item["pattern_signature"]),
        )
    )
    return result


def render_learning_overlay(target: str, batches: list[dict] | None = None) -> str:
    batches = load_learning_batches() if batches is None else batches
    if not batches:
        return ""
    patterns = _group_patterns(batches)
    heading = (
        "【自动学习记录：Writer 防复发】"
        if target == "writer"
        else "【自动学习记录：Reader 防漏检】"
    )
    intro = (
        "以下条目来自正式打回。它们是当前内置 Skill 的主动检查项；"
        "新问题保持 CALIBRATING，同类复发不得忽略。"
    )
    lines = [heading, intro]
    for item in patterns[:120]:
        lines.append(
            f"- [{item['pattern_signature']}] "
            f"{item['category']}｜复发 {item['occurrences']} 次"
        )
        lines.append(f"  失败模式：{item['reason']}")
        if target == "writer":
            guidance = item["suggestion"] or "生成前主动规避同类表达或结构，不得只在末轮润色补救。"
            lines.append(f"  写作预防：{guidance}")
        else:
            guidance = item["suggestion"] or "复审时主动搜索同类失败，命中后不得因意思能懂而放行。"
            lines.append(f"  阅读拦截：{guidance}")
        if item["excerpt"]:
            lines.append(f"  最近样本：{item['excerpt']}")
    return "\n".join(lines)


def apply_persisted_learning_to_conn(conn, builtins) -> dict[str, int]:
    batches = load_learning_batches()
    if not batches:
        return {}

    builtin_map = {item["name"]: item for item in builtins}
    revision = len(batches)
    updated: dict[str, int] = {}
    for name, target in (
        (WRITER_SKILL_NAME, "writer"),
        (READER_SKILL_NAME, "reader"),
    ):
        builtin = builtin_map.get(name)
        if not builtin:
            continue
        skill = conn.execute(
            """
            SELECT id,current_version
            FROM skills
            WHERE project_id IS NULL AND name=?
            ORDER BY id
            LIMIT 1
            """,
            (name,),
        ).fetchone()
        if not skill:
            continue

        effective_version = int(builtin["version"]) + revision
        if int(skill["current_version"]) >= effective_version:
            updated[name] = int(skill["current_version"])
            continue

        overlay = render_learning_overlay(target, batches)
        content = str(builtin["content"]).rstrip() + "\n\n" + overlay + "\n"
        conn.execute(
            """
            INSERT OR IGNORE INTO skill_versions(skill_id,version,content,note)
            VALUES(?,?,?,?)
            """,
            (
                skill["id"],
                effective_version,
                content,
                f"replayed {revision} persisted rejection-learning batches",
            ),
        )
        conn.execute(
            """
            UPDATE skills
            SET content=?,current_version=?,enabled=1,updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (content, effective_version, skill["id"]),
        )
        updated[name] = effective_version
    return updated



def load_learning_events_from_conn(conn) -> list[dict]:
    rows = conn.execute(
        """
        SELECT batch_id,task_id,project_id,source,reviewer,category,
               pattern_signature,reason,suggestion,excerpt,created_at
        FROM builtin_skill_learning_events
        ORDER BY id
        """
    ).fetchall()
    batches: dict[str, dict] = {}
    for row in rows:
        batch_id = str(row["batch_id"])
        batch = batches.setdefault(
            batch_id,
            {
                "schema": "NARRATIVE_BUILTIN_SKILL_LEARNING_DB_V1",
                "batch_id": batch_id,
                "task_id": row["task_id"],
                "project_id": row["project_id"],
                "source": str(row["source"] or ""),
                "recorded_at": str(row["created_at"] or ""),
                "events": [],
            },
        )
        batch["events"].append(
            {
                "reviewer": str(row["reviewer"] or ""),
                "category": str(row["category"] or ""),
                "pattern_signature": str(row["pattern_signature"] or ""),
                "reason": str(row["reason"] or ""),
                "suggestion": str(row["suggestion"] or ""),
                "excerpt": str(row["excerpt"] or ""),
            }
        )
    return list(batches.values())


def apply_db_learning_to_conn(conn, builtins) -> dict[str, int]:
    batches = load_learning_events_from_conn(conn)
    if not batches:
        return {}

    builtin_map = {item["name"]: item for item in builtins}
    batch_count = len({str(item.get("batch_id") or "") for item in batches})
    updated: dict[str, int] = {}

    for name, target in (
        (WRITER_SKILL_NAME, "writer"),
        (READER_SKILL_NAME, "reader"),
    ):
        builtin = builtin_map.get(name)
        if not builtin:
            continue
        skill = conn.execute(
            """
            SELECT id,current_version,content
            FROM skills
            WHERE project_id IS NULL AND name=?
            ORDER BY id
            LIMIT 1
            """,
            (name,),
        ).fetchone()
        if not skill:
            continue

        overlay = render_learning_overlay(target, batches)
        desired_content = str(builtin["content"]).rstrip() + "\n\n" + overlay + "\n"
        if str(skill["content"]) == desired_content:
            updated[name] = int(skill["current_version"])
            continue

        next_version = max(
            int(skill["current_version"]) + 1,
            int(builtin["version"]) + batch_count,
        )
        conn.execute(
            """
            INSERT INTO skill_versions(skill_id,version,content,note)
            VALUES(?,?,?,?)
            """,
            (
                skill["id"],
                next_version,
                desired_content,
                f"auto-upgrade from {batch_count} durable rejection batches",
            ),
        )
        conn.execute(
            """
            UPDATE skills
            SET content=?,current_version=?,enabled=1,updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (desired_content, next_version, skill["id"]),
        )
        updated[name] = next_version

    return updated



def import_archived_learning_to_conn(conn) -> int:
    imported = 0
    for batch in load_learning_batches():
        batch_id = str(batch.get("batch_id") or "").strip()
        if not batch_id:
            continue
        for raw in batch.get("events", []):
            if not isinstance(raw, dict):
                continue
            event = normalize_event(
                {
                    "reviewer": str(raw.get("reviewer") or ""),
                    "category": str(raw.get("category") or ""),
                    "reason": str(raw.get("reason") or ""),
                    "suggestion": str(raw.get("suggestion") or ""),
                    "excerpt": str(raw.get("excerpt") or ""),
                }
            )
            before = conn.total_changes
            conn.execute(
                """
                INSERT OR IGNORE INTO builtin_skill_learning_events(
                    batch_id,task_id,project_id,source,reviewer,category,
                    pattern_signature,reason,suggestion,excerpt,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    batch_id,
                    batch.get("task_id"),
                    batch.get("project_id"),
                    str(batch.get("source") or "archive-migration"),
                    event["reviewer"],
                    event["category"],
                    str(raw.get("pattern_signature") or event["pattern_signature"]),
                    event["reason"],
                    event["suggestion"],
                    event["excerpt"],
                    str(batch.get("recorded_at") or ""),
                ),
            )
            if conn.total_changes > before:
                imported += 1
    return imported
