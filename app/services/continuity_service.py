from __future__ import annotations

import json
import re
from typing import Any

from app.db import connect
from app.services.workflow_service import _run_step


class ContinuityStateError(RuntimeError):
    pass


_STATE_KEYS = (
    "characters",
    "items",
    "locations",
    "world_counters",
    "revealed_facts",
    "open_threads",
    "closed_threads",
    "do_not_reset",
)


def empty_story_state() -> dict[str, Any]:
    return {
        "chapter_number": 0,
        "chapter_summary": "",
        "characters": [],
        "items": [],
        "locations": [],
        "world_counters": [],
        "revealed_facts": [],
        "open_threads": [],
        "closed_threads": [],
        "last_scene": {
            "time": "",
            "location": "",
            "present_characters": [],
            "hook": "",
        },
        "do_not_reset": [],
    }


def _json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    fence = re.match(
        r"^\s*```(?:json)?\s*(.*?)\s*```\s*$",
        candidate,
        re.IGNORECASE | re.DOTALL,
    )
    if fence:
        candidate = fence.group(1).strip()

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", candidate, re.DOTALL)
        if not match:
            raise ContinuityStateError("story state updater did not return JSON")
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise ContinuityStateError(
                "story state updater returned invalid JSON"
            ) from exc

    if not isinstance(parsed, dict):
        raise ContinuityStateError("story state updater must return a JSON object")
    return parsed


def normalize_story_state(
    value: dict[str, Any],
    *,
    chapter_number: int,
) -> dict[str, Any]:
    state = empty_story_state()
    state["chapter_number"] = chapter_number
    state["chapter_summary"] = str(value.get("chapter_summary") or "").strip()

    for key in _STATE_KEYS:
        raw = value.get(key)
        state[key] = raw if isinstance(raw, list) else []

    last_scene = value.get("last_scene")
    if isinstance(last_scene, dict):
        state["last_scene"] = {
            "time": str(last_scene.get("time") or "").strip(),
            "location": str(last_scene.get("location") or "").strip(),
            "present_characters": (
                last_scene.get("present_characters")
                if isinstance(last_scene.get("present_characters"), list)
                else []
            ),
            "hook": str(last_scene.get("hook") or "").strip(),
        }
    return state


def latest_story_state_record(
    project_id: int,
    *,
    before_chapter_number: int | None = None,
) -> dict[str, Any] | None:
    query = """
        SELECT *
        FROM story_state_snapshots
        WHERE project_id=?
    """
    params: list[Any] = [project_id]
    if before_chapter_number is not None:
        query += " AND chapter_number<?"
        params.append(before_chapter_number)
    query += " ORDER BY chapter_number DESC,id DESC LIMIT 1"

    with connect() as conn:
        row = conn.execute(query, tuple(params)).fetchone()
    return dict(row) if row else None


def latest_story_state(
    project_id: int,
    *,
    before_chapter_number: int | None = None,
) -> dict[str, Any]:
    row = latest_story_state_record(
        project_id,
        before_chapter_number=before_chapter_number,
    )
    if not row:
        return empty_story_state()
    try:
        parsed = json.loads(row["state_json"])
    except json.JSONDecodeError as exc:
        raise ContinuityStateError("persisted story state is invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise ContinuityStateError("persisted story state must be an object")
    return normalize_story_state(
        parsed,
        chapter_number=int(row["chapter_number"]),
    )


def _named_entries(state: dict[str, Any], key: str) -> dict[str, dict[str, Any]]:
    entries = state.get(key)
    if not isinstance(entries, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in entries:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name:
            result[name] = item
    return result


def validate_story_state_transition(
    previous: dict[str, Any],
    current: dict[str, Any],
) -> None:
    if int(previous.get("chapter_number") or 0) <= 0:
        return

    problems: list[str] = []

    for key, label in (
        ("characters", "人物"),
        ("items", "道具"),
        ("locations", "地点"),
        ("world_counters", "世界计数"),
    ):
        previous_items = _named_entries(previous, key)
        current_items = _named_entries(current, key)
        missing = sorted(set(previous_items) - set(current_items))
        if missing:
            problems.append(f"{label}状态被遗漏: {', '.join(missing)}")

    previous_characters = _named_entries(previous, "characters")
    current_characters = _named_entries(current, "characters")
    for name, old in previous_characters.items():
        new = current_characters.get(name)
        if not new:
            continue
        for field, label in (
            ("knowledge", "已知信息"),
            ("relationship_changes", "关系变化"),
        ):
            old_values = {
                str(item).strip()
                for item in (old.get(field) or [])
                if str(item).strip()
            }
            new_values = {
                str(item).strip()
                for item in (new.get(field) or [])
                if str(item).strip()
            }
            lost = sorted(old_values - new_values)
            if lost:
                problems.append(
                    f"{name}{label}发生回退: {', '.join(lost)}"
                )

    old_revealed = {
        str(item).strip()
        for item in (previous.get("revealed_facts") or [])
        if str(item).strip()
    }
    new_revealed = {
        str(item).strip()
        for item in (current.get("revealed_facts") or [])
        if str(item).strip()
    }
    lost_revealed = sorted(old_revealed - new_revealed)
    if lost_revealed:
        problems.append(
            "已揭露事实被遗忘: " + ", ".join(lost_revealed)
        )

    old_closed = {
        str(item).strip()
        for item in (previous.get("closed_threads") or [])
        if str(item).strip()
    }
    new_closed = {
        str(item).strip()
        for item in (current.get("closed_threads") or [])
        if str(item).strip()
    }
    lost_closed = sorted(old_closed - new_closed)
    if lost_closed:
        problems.append(
            "已回收伏笔被重新打开: " + ", ".join(lost_closed)
        )

    old_open = {
        str(item).strip()
        for item in (previous.get("open_threads") or [])
        if str(item).strip()
    }
    new_open = {
        str(item).strip()
        for item in (current.get("open_threads") or [])
        if str(item).strip()
    }
    silently_lost = sorted(old_open - new_open - new_closed)
    if silently_lost:
        problems.append(
            "未回收伏笔被静默丢失: " + ", ".join(silently_lost)
        )

    if problems:
        raise ContinuityStateError(
            "story state transition is not monotonic: "
            + "；".join(problems)
        )


def render_story_state(state: dict[str, Any]) -> str:
    if int(state.get("chapter_number") or 0) <= 0:
        return "【Story State】这是第一章，目前没有动态连续性状态。"
    return (
        "【Story State / 连续性台账｜权威状态，不得重置】\n"
        + json.dumps(state, ensure_ascii=False, indent=2)
    )


def persist_story_state(
    *,
    project_id: int,
    task_id: int,
    chapter_id: int | None,
    chapter_number: int,
    state: dict[str, Any],
) -> int:
    normalized = normalize_story_state(state, chapter_number=chapter_number)
    payload = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    summary = str(normalized.get("chapter_summary") or "")[:2000]

    with connect() as conn:
        existing = conn.execute(
            "SELECT id FROM story_state_snapshots WHERE task_id=?",
            (task_id,),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE story_state_snapshots
                SET project_id=?,chapter_id=?,chapter_number=?,state_json=?,
                    summary=?,updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    project_id,
                    chapter_id,
                    chapter_number,
                    payload,
                    summary,
                    existing["id"],
                ),
            )
            return int(existing["id"])

        cur = conn.execute(
            """
            INSERT INTO story_state_snapshots(
                project_id,task_id,chapter_id,chapter_number,state_json,summary
            ) VALUES(?,?,?,?,?,?)
            """,
            (
                project_id,
                task_id,
                chapter_id,
                chapter_number,
                payload,
                summary,
            ),
        )
        return int(cur.lastrowid)


async def capture_story_state(
    *,
    task_id: int,
    project_id: int,
    chapter_id: int | None,
    chapter_number: int,
    chapter_content: str,
) -> dict[str, Any]:
    previous = latest_story_state(
        project_id,
        before_chapter_number=chapter_number,
    )
    instruction = f"""你是长篇小说 Story State 更新器。你的任务不是评价文字，而是把第 {chapter_number} 章结束后的客观连续性状态整理成结构化 JSON。

上一章结束后的权威 Story State：
{json.dumps(previous, ensure_ascii=False, indent=2)}

当前第 {chapter_number} 章完整正文：
---BEGIN CHAPTER---
{chapter_content}
---END CHAPTER---

规则：
1. 输出的是“本章结束后完整当前状态”，不是只输出本章增量。
2. 已发生且没有被正文明确改变的状态必须继承，绝不能恢复成初始状态。
3. 继承上一版状态时，已有 characters/items/locations/world_counters 的 name 必须原样保留；已有 knowledge、relationship_changes、revealed_facts、closed_threads 条目必须逐字继承，不要同义改写。
4. 人物 knowledge 只记录其确实已经知道的信息；秘密一旦揭露不能重新变成未知。
5. 伤势、道具持有人、剩余次数、地点损坏/封锁、时间、称谓与关系变化必须保留。
6. 世界硬规则只能记录被正文验证/消耗后的计数或状态，不能创造新规则。
7. open_threads 是尚未回收的伏笔/承诺；closed_threads 是本章已回收事项。
8. do_not_reset 写出下一章最容易被错误重置的事实。
9. 只输出 JSON，不要 Markdown，不要解释。

严格使用以下结构：
{{
  "chapter_number": {chapter_number},
  "chapter_summary": "本章造成的不可逆变化，100字以内",
  "characters": [
    {{
      "name": "人物名",
      "location": "当前地点",
      "physical_state": "伤势/体力/永久特征",
      "knowledge": ["已经明确知道的事实"],
      "relationship_changes": ["已经发生的关系/称谓变化"],
      "active_goal": "当前目标"
    }}
  ],
  "items": [
    {{
      "name": "道具",
      "holder": "当前持有人",
      "location": "当前位置",
      "state": "损坏/消耗/是否可用",
      "uses_remaining": "明确数字或unknown"
    }}
  ],
  "locations": [
    {{"name": "地点", "state": "完好/封死/损坏等", "access": "可用性"}}
  ],
  "world_counters": [
    {{"name": "计数/窗口", "value": "当前值", "rule": "不能违反的既定约束"}}
  ],
  "revealed_facts": ["已经成为故事事实的秘密或信息"],
  "open_threads": ["尚未回收伏笔"],
  "closed_threads": ["本章已经回收伏笔"],
  "last_scene": {{
    "time": "章末时间",
    "location": "章末地点",
    "present_characters": ["章末在场人物"],
    "hook": "章末钩子"
  }},
  "do_not_reset": ["下一章绝不能恢复/遗忘的状态"]
}}"""

    result = await _run_step(
        task_id=task_id,
        role="continuity-state-updater",
        stage=f"chapter-{chapter_number:02d}-story-state",
        mode="check",
        content="",
        instruction=instruction,
    )
    raw_state = _json_object(result.content)
    required_keys = {
        "chapter_summary",
        "characters",
        "items",
        "locations",
        "world_counters",
        "revealed_facts",
        "open_threads",
        "closed_threads",
        "last_scene",
        "do_not_reset",
    }
    missing = sorted(required_keys - raw_state.keys())
    if missing:
        raise ContinuityStateError(
            "story state updater omitted required keys: " + ", ".join(missing)
        )
    returned_chapter = raw_state.get("chapter_number")
    if returned_chapter not in {None, chapter_number}:
        raise ContinuityStateError(
            f"story state updater returned chapter {returned_chapter}, "
            f"expected {chapter_number}"
        )

    state = normalize_story_state(
        raw_state,
        chapter_number=chapter_number,
    )
    validate_story_state_transition(previous, state)
    persist_story_state(
        project_id=project_id,
        task_id=task_id,
        chapter_id=chapter_id,
        chapter_number=chapter_number,
        state=state,
    )
    return state


def _paragraphs(text: str) -> list[str]:
    parts = re.split(r"\n\s*\n+", text)
    return [
        re.sub(r"\s+", " ", part).strip()
        for part in parts
        if len(re.sub(r"\s+", " ", part).strip()) >= 80
    ]


def repetition_report(text: str, prior_text: str = "") -> dict[str, Any]:
    paragraphs = _paragraphs(text)
    prior = set(_paragraphs(prior_text))

    seen: dict[str, int] = {}
    internal_duplicate_chars = 0
    cross_duplicate_chars = 0
    internal_examples: list[str] = []
    cross_examples: list[str] = []

    for paragraph in paragraphs:
        count = seen.get(paragraph, 0)
        if count:
            internal_duplicate_chars += len(paragraph)
            if len(internal_examples) < 5 and paragraph not in internal_examples:
                internal_examples.append(paragraph[:240])
        seen[paragraph] = count + 1

        if paragraph in prior:
            cross_duplicate_chars += len(paragraph)
            if len(cross_examples) < 5 and paragraph not in cross_examples:
                cross_examples.append(paragraph[:240])

    denominator = max(1, len(re.sub(r"\s+", "", text)))
    internal_ratio = internal_duplicate_chars / denominator
    cross_ratio = cross_duplicate_chars / denominator
    max_repeat = max(seen.values(), default=1)

    blocking = (
        internal_ratio >= 0.08
        or cross_ratio >= 0.12
        or max_repeat >= 4
    )
    return {
        "blocking": blocking,
        "internal_ratio": round(internal_ratio, 4),
        "cross_ratio": round(cross_ratio, 4),
        "max_repeat": max_repeat,
        "internal_examples": internal_examples,
        "cross_examples": cross_examples,
    }


def repetition_feedback(report: dict[str, Any]) -> str:
    return (
        "重复检测："
        f"章内重复占比={report['internal_ratio']:.1%}；"
        f"与前文章节完全重复占比={report['cross_ratio']:.1%}；"
        f"同段最大重复次数={report['max_repeat']}。"
    )


async def repair_repetition(
    *,
    task_id: int,
    chapter_number: int,
    draft: str,
    prior_manuscript: str,
    story_state_context: str,
) -> tuple[str, dict[str, Any]]:
    first = repetition_report(draft, prior_manuscript)
    if not first["blocking"]:
        return draft, first

    repaired = await _run_step(
        task_id=task_id,
        role="continuity-repair",
        stage=f"chapter-{chapter_number:02d}-deduplicate",
        mode="polish",
        content=draft,
        instruction="\n\n".join(
            [
                story_state_context,
                repetition_feedback(first),
                """当前章节出现严重的章内循环或复制前文章节问题。请重写为单一、向前推进的完整章节：
- 删除所有重复场景、重复对白和重复的“第一次”事件；
- 已经发生过的事件只能作为既成事实产生后果，禁止重新演一遍；
- 不得新增世界规则、人物秘密或道具能力；
- 保留本章真正的新事件与章末钩子；
- 只输出去重后的完整当前章节，不包含任何前文章节。""",
            ]
        ),
    )
    second = repetition_report(repaired.content, prior_manuscript)
    return repaired.content, second


def record_repetition_blocking(
    *,
    task_id: int,
    report: dict[str, Any],
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO review_findings(
                task_id,reviewer,category,severity,summary,suggestion,status
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (
                task_id,
                "continuity-guard",
                "continuity",
                "blocking",
                repetition_feedback(report),
                "删除跨章复制与章内循环后重新审核；禁止用新增设定绕过。",
                "open",
            ),
        )
