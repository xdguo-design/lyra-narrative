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
    payload: dict | None = None,
) -> dict:
    payload = payload or build_learning_batch(
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


WRITER_REJECTION_FAMILIES = (
    (
        "dialogue-voice",
        "人物与对白",
        (
            "ORALITY_GAP",
            "VOICE_OVERPERFORMANCE_GAP",
            "DIALOGUE_",
            "RELATIONSHIP_",
            "OVER_RATIONAL_DIALOGUE_GAP",
            "TURN_TAKING_SYMMETRY_GAP",
            "EMOTIONAL_RESIDUE_GAP",
            "人物不会这样说",
            "对白",
            "问卷",
            "口语",
        ),
        "人物先按身份、利益、关系和压力说话，再承担信息功能。关键台词必须做“说出口测试”；不要为了推进剧情让人物突然老实，也不要写成作者总结、规章或金句。",
    ),
    (
        "continuity-facts",
        "连续性与事实",
        (
            "CONTINUITY",
            "MICRO_CONTINUITY_GAP",
            "QUANTITY_GAP",
            "REFERENCE_GAP",
            "measurement",
            "time",
            "location",
            "identity",
            "role-drift",
            "unit",
            "计量",
            "时辰",
            "时间",
            "地点",
            "身份",
            "连续",
            "算术",
        ),
        "动笔前锁定时间、地点、身份、物件、伤势、计量口径和动作状态；正文中的数字必须可复算，前后动作必须能连续接上，不能靠读者替作者补。",
    ),
    (
        "plot-causality",
        "剧情因果与推进",
        (
            "CAUS",
            "PLOT",
            "MOTIVATION",
            "PROTAGONIST_AGENCY_GAP",
            "INVESTIGATION_WORKSHEET_GAP",
            "CLUE_",
            "COINCIDENCE",
            "因果",
            "动机",
            "剧情",
            "线索",
            "主角",
            "调查",
        ),
        "推进必须来自人物选择、阻力和可验证证据，不能靠作者安排的连续巧合或“发现→解释→立刻验证”的解题板。主角至少要有一个真正改变局面的观察、选择、代价或策略。",
    ),
    (
        "reader-information",
        "信息边界与读者理解",
        (
            "READER_GAP",
            "AMBIGUOUS_GAP",
            "KNOWLEDGE_PROVENANCE_GAP",
            "UNSEEDED_CALLBACK_GAP",
            "SALIENT_SIGNAL_ORPHAN_GAP",
            "信息",
            "知识来源",
            "读者",
            "回调",
            "伏笔",
            "泄漏",
        ),
        "读者可以暂时不知道答案，但必须知道问题是什么。人物知道一件事必须有来源；回调必须有播种；显著异常必须被人物接收；后续章节信息不得提前泄漏。",
    ),
    (
        "language-rhythm",
        "语言、叙事与节奏",
        (
            "NATURALNESS_GAP",
            "AUTHOR_",
            "SCENE_TEXTURE_GAP",
            "ACTION_FRAGMENTATION_GAP",
            "COLLOCATION_GAP",
            "TONE_GAP",
            "style",
            "aesthetic",
            "naturalness",
            "语言",
            "节奏",
            "作者总结",
            "模型腔",
            "自然",
            "描写",
        ),
        "优先写自然中文和可感知场景。删掉解释回声、作者点题、模板金句和机械碎句；关键处慢写，手续流程敢压缩，让动作、声音、触感和空间承担叙事。进入正题后，禁止把章节写成“查到→确认→登记→前往”的高质量纪要；关键线索应尽量通过人物抵达答案前的动作、物感、阻力、潜台词与选择落地。",
    ),
    (
        "world-skill-boundary",
        "世界规则、权限与技能边界",
        (
            "WORLD",
            "PROFICIENCY",
            "SYSTEM_",
            "permission",
            "权限",
            "世界规则",
            "技能",
            "系统",
            "越权",
            "设定",
        ),
        "冻结设定、职业权限、程序和技能能力必须约束正文。不能为方便剧情临时新增规则，也不能让角色越权、系统替人物下结论或技能无练习跳级。",
    ),
)


def _writer_rejection_family(item: dict) -> tuple[str, str, str]:
    haystack = " ".join(
        [
            str(item.get("category") or ""),
            str(item.get("reason") or ""),
            str(item.get("suggestion") or ""),
        ]
    ).lower()
    for key, title, markers, guidance in WRITER_REJECTION_FAMILIES:
        if any(marker.lower() in haystack for marker in markers):
            return key, title, guidance
    return (
        "other",
        "其他已确认写作失败",
        "正式打回即视为下轮写作约束：生成前主动检查，不能只等 Reader 在末轮发现。",
    )


def _summarize_writer_patterns(patterns: list[dict]) -> list[dict]:
    """Collapse project-specific evidence into cross-project capabilities.

    Raw reasons, suggestions, excerpts, character names, objects, numbers and
    plot nodes remain in the rejection-learning evidence store. They must not
    be copied into the global runtime Skill, otherwise a new novel inherits
    another novel's facts instead of the learned capability.
    """
    grouped: dict[str, dict] = {}
    for item in patterns:
        key, title, guidance = _writer_rejection_family(item)
        current = grouped.setdefault(
            key,
            {
                "key": key,
                "title": title,
                "guidance": guidance,
                "occurrences": 0,
                "pattern_count": 0,
                "labels": set(),
            },
        )
        current["occurrences"] += int(item.get("occurrences") or 0)
        current["pattern_count"] += 1
        current["labels"].update(
            re.findall(
                r"\b[A-Z][A-Z0-9_]{3,}(?:_GAP|_LEAK|_DRIFT)\b",
                str(item.get("reason") or ""),
            )
        )

    result = list(grouped.values())
    result.sort(
        key=lambda item: (
            -int(item["occurrences"]),
            str(item["title"]),
        )
    )
    return result


def render_learning_overlay(target: str, batches: list[dict] | None = None) -> str:
    batches = load_learning_batches() if batches is None else batches
    if not batches:
        return ""
    patterns = _group_patterns(batches)
    summaries = _summarize_writer_patterns(patterns)

    shared_boundary = (
        "历史打回中的人物名、地点、道具、数字、台词、剧情节点和项目专属程序只属于原项目；"
        "它们保留在证据库用于回放，但绝不能成为新作品的事实、必检词或剧情约束。"
    )

    if target == "writer":
        lines = [
            "【作者 Skill：正式打回经验总结】",
            (
                "以下规则由全部正式打回归纳为跨作品能力。原始 reason / suggestion / excerpt "
                "完整保存在 builtin_skill_learning_events / JSON 证据库，不进入运行时 Skill。"
            ),
            shared_boundary,
            "执行顺序：写前读取 → 写中主动规避 → 写后自检。复发项优先级高于一次性新问题。",
        ]
        for item in summaries:
            lines.append(
                f"- {item['title']}｜累计打回 {item['occurrences']} 次｜"
                f"{item['pattern_count']} 个独立失败模式"
            )
            lines.append(f"  作者规则：{item['guidance']}")
            labels = sorted(item["labels"])
            if labels:
                lines.append("  关联标签：" + ", ".join(labels[:16]))
        return "\n".join(lines)

    lines = [
        "【Reader Skill：跨作品防漏检能力】",
        (
            "Reader 只继承历史失败中可泛化的检查能力，不继承任何旧作品实体或剧情答案。"
            "当前作品的事实只能来自当前项目 Canon / Story State / 正文。"
        ),
        shared_boundary,
        "命中历史失败族时，先在当前文本中寻找同类结构证据；没有当前文本证据就不得判 FAIL。",
    ]
    for item in summaries:
        lines.append(
            f"- {item['title']}｜历史命中 {item['occurrences']} 次｜"
            f"{item['pattern_count']} 个独立失败模式"
        )
        lines.append(f"  阅读拦截：{item['guidance']}")
        labels = sorted(item["labels"])
        if labels:
            lines.append("  关联标签：" + ", ".join(labels[:16]))
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
