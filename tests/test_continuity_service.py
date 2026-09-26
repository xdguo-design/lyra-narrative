from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

from app.db import connect, init_db
from app.services.ai_service import AssistResult
from app.services.continuity_service import (
    capture_story_state,
    ContinuityStateError,
    latest_story_state,
    persist_story_state,
    repetition_report,
    validate_story_state_transition,
)
from app.services.workflow_service import _create_run


def _seed_project_and_task() -> tuple[int, int]:
    with connect() as conn:
        project = conn.execute(
            "INSERT INTO projects(title,genre) VALUES(?,?)",
            ("连续性测试", "科幻"),
        )
        project_id = int(project.lastrowid)
        task = conn.execute(
            """
            INSERT INTO writing_tasks(project_id,goal,instruction,status)
            VALUES(?,?,?,?)
            """,
            (project_id, "测试状态", "", "pending"),
        )
        return project_id, int(task.lastrowid)


def test_story_state_persists_and_latest(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVEL_DB_PATH", str(tmp_path / "continuity.db"))
    monkeypatch.setenv("NOVEL_SEED_DEMO", "0")
    init_db()
    project_id, task_id = _seed_project_and_task()

    state = {
        "chapter_summary": "钥匙完成交接。",
        "characters": [
            {
                "name": "沈砚",
                "location": "控制室",
                "physical_state": "左掌受伤",
                "knowledge": ["姜岚隐瞒了实验资料"],
                "relationship_changes": ["姜岚开始直接叫沈砚"],
                "active_goal": "找到沈舟",
            }
        ],
        "items": [
            {
                "name": "黄铜钥匙",
                "holder": "沈砚",
                "location": "沈砚口袋",
                "state": "可用",
                "uses_remaining": "unknown",
            }
        ],
        "do_not_reset": ["黄铜钥匙已经交给沈砚"],
    }

    persist_story_state(
        project_id=project_id,
        task_id=task_id,
        chapter_id=None,
        chapter_number=3,
        state=state,
    )

    latest = latest_story_state(project_id)
    assert latest["chapter_number"] == 3
    assert latest["items"][0]["holder"] == "沈砚"
    assert "黄铜钥匙已经交给沈砚" in latest["do_not_reset"]


def test_repetition_report_blocks_internal_and_cross_chapter_copy():
    repeated = (
        "沈砚握着黄铜钥匙，确认钥匙已经由周启明交给自己。"
        "姜岚站在旁边，没有再重复刚才已经发生过的对话。"
        "他们必须带着这个既成事实继续往前走，不能让事件重新开始。"
    )
    prior = repeated + "\n\n" + ("前文状态已经固定。" * 20)
    current = "\n\n".join([repeated, repeated, repeated, repeated])

    report = repetition_report(current, prior)

    assert report["blocking"] is True
    assert report["max_repeat"] >= 4
    assert report["cross_ratio"] > 0


def test_agent_run_records_story_state_resource(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVEL_DB_PATH", str(tmp_path / "resources.db"))
    monkeypatch.setenv("NOVEL_SEED_DEMO", "0")
    init_db()
    project_id, state_task_id = _seed_project_and_task()

    persist_story_state(
        project_id=project_id,
        task_id=state_task_id,
        chapter_id=None,
        chapter_number=2,
        state={
            "chapter_summary": "B 出口已经封死。",
            "locations": [
                {"name": "B出口", "state": "塌落封死", "access": "不可用"}
            ],
            "do_not_reset": ["B出口不可再次使用"],
        },
    )

    with connect() as conn:
        task = conn.execute(
            """
            INSERT INTO writing_tasks(project_id,goal,instruction,status)
            VALUES(?,?,?,?)
            """,
            (project_id, "写第三章", "", "pending"),
        )
        task_id = int(task.lastrowid)

    run_id = _create_run(task_id, "writer", "chapter-03-draft", "")
    with connect() as conn:
        resource = conn.execute(
            """
            SELECT *
            FROM agent_run_resources
            WHERE run_id=? AND resource_type='story_state'
            """,
            (run_id,),
        ).fetchone()

    assert resource is not None
    assert resource["version"] == 2
    payload = json.loads(resource["content"])
    assert payload["locations"][0]["access"] == "不可用"


def test_capture_story_state_updates_full_snapshot(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVEL_DB_PATH", str(tmp_path / "capture.db"))
    monkeypatch.setenv("NOVEL_SEED_DEMO", "0")
    init_db()
    project_id, task_id = _seed_project_and_task()

    response = {
        "chapter_number": 1,
        "chapter_summary": "相位票消耗一道刻痕。",
        "characters": [
            {
                "name": "沈砚",
                "location": "2号站台",
                "physical_state": "左掌已包扎",
                "knowledge": ["确认异常窗口存在"],
                "relationship_changes": [],
                "active_goal": "调查沈舟",
            }
        ],
        "items": [
            {
                "name": "相位票",
                "holder": "沈砚",
                "location": "沈砚手中",
                "state": "剩余两道刻痕",
                "uses_remaining": 2,
            }
        ],
        "locations": [],
        "world_counters": [
            {
                "name": "相位票剩余跨界次数",
                "value": 2,
                "rule": "不可恢复",
            }
        ],
        "revealed_facts": ["异常窗口持续47秒"],
        "open_threads": ["沈舟所在分支"],
        "closed_threads": [],
        "last_scene": {
            "time": "00:07:47",
            "location": "2号站台",
            "present_characters": ["沈砚"],
            "hook": "沈舟出现在另一分支",
        },
        "do_not_reset": ["相位票只剩两次", "左掌已经受伤"],
    }

    fake = AssistResult(
        content=json.dumps(response, ensure_ascii=False),
        provider="test",
        model="test-model",
    )
    with patch(
        "app.services.continuity_service._run_step",
        new=AsyncMock(return_value=fake),
    ):
        state = asyncio.run(
            capture_story_state(
                task_id=task_id,
                project_id=project_id,
                chapter_id=None,
                chapter_number=1,
                chapter_content="第一章正文",
            )
        )

    assert state["chapter_number"] == 1
    assert state["items"][0]["uses_remaining"] == 2
    assert latest_story_state(project_id)["last_scene"]["time"] == "00:07:47"


def test_latest_story_state_respects_chapter_boundary(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVEL_DB_PATH", str(tmp_path / "boundary.db"))
    monkeypatch.setenv("NOVEL_SEED_DEMO", "0")
    init_db()
    project_id, task1 = _seed_project_and_task()

    persist_story_state(
        project_id=project_id,
        task_id=task1,
        chapter_id=None,
        chapter_number=1,
        state={
            "chapter_summary": "第一章",
            "revealed_facts": ["事实A"],
        },
    )
    with connect() as conn:
        task = conn.execute(
            """
            INSERT INTO writing_tasks(project_id,goal,instruction,status)
            VALUES(?,?,?,?)
            """,
            (project_id, "第二章状态", "", "pending"),
        )
        task2 = int(task.lastrowid)
    persist_story_state(
        project_id=project_id,
        task_id=task2,
        chapter_id=None,
        chapter_number=2,
        state={
            "chapter_summary": "第二章",
            "revealed_facts": ["事实A", "事实B"],
        },
    )

    before_two = latest_story_state(
        project_id,
        before_chapter_number=2,
    )
    assert before_two["chapter_number"] == 1
    assert before_two["revealed_facts"] == ["事实A"]


def test_story_state_transition_rejects_forgetting():
    previous = {
        "chapter_number": 2,
        "characters": [
            {
                "name": "姜岚",
                "knowledge": ["沈舟参与过实验"],
                "relationship_changes": ["开始直呼沈砚"],
            }
        ],
        "items": [{"name": "相位票"}],
        "locations": [{"name": "B出口"}],
        "world_counters": [{"name": "剩余跨界次数"}],
        "revealed_facts": ["沈舟参与过实验"],
        "open_threads": ["沈舟所在分支"],
        "closed_threads": ["周启明责任已确认"],
    }
    current = {
        "chapter_number": 3,
        "characters": [
            {
                "name": "姜岚",
                "knowledge": [],
                "relationship_changes": [],
            }
        ],
        "items": [],
        "locations": [],
        "world_counters": [],
        "revealed_facts": [],
        "open_threads": [],
        "closed_threads": [],
    }

    try:
        validate_story_state_transition(previous, current)
    except ContinuityStateError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected continuity transition failure")

    assert "人物状态被遗漏" not in message
    assert "道具状态被遗漏" in message
    assert "已知信息发生回退" in message
    assert "已揭露事实被遗忘" in message
    assert "未回收伏笔被静默丢失" in message


def test_agent_run_uses_only_story_state_before_current_chapter(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVEL_DB_PATH", str(tmp_path / "chapter-boundary.db"))
    monkeypatch.setenv("NOVEL_SEED_DEMO", "0")
    init_db()

    with connect() as conn:
        project = conn.execute(
            "INSERT INTO projects(title,genre) VALUES(?,?)",
            ("章节边界", "科幻"),
        )
        project_id = int(project.lastrowid)
        chapter2 = conn.execute(
            """
            INSERT INTO chapters(project_id,title,position,content,status)
            VALUES(?,?,?,?,?)
            """,
            (project_id, "第二章", 2, "", "draft"),
        )
        chapter2_id = int(chapter2.lastrowid)

        task1 = conn.execute(
            """
            INSERT INTO writing_tasks(project_id,goal,instruction,status)
            VALUES(?,?,?,?)
            """,
            (project_id, "第一章状态", "", "pending"),
        )
        task1_id = int(task1.lastrowid)
        task2 = conn.execute(
            """
            INSERT INTO writing_tasks(project_id,goal,instruction,status)
            VALUES(?,?,?,?)
            """,
            (project_id, "第二章状态", "", "pending"),
        )
        task2_id = int(task2.lastrowid)

    persist_story_state(
        project_id=project_id,
        task_id=task1_id,
        chapter_id=None,
        chapter_number=1,
        state={"chapter_summary": "第一章状态"},
    )
    persist_story_state(
        project_id=project_id,
        task_id=task2_id,
        chapter_id=None,
        chapter_number=2,
        state={"chapter_summary": "第二章未来状态"},
    )

    with connect() as conn:
        current_task = conn.execute(
            """
            INSERT INTO writing_tasks(project_id,chapter_id,goal,instruction,status)
            VALUES(?,?,?,?,?)
            """,
            (project_id, chapter2_id, "重跑第二章", "", "pending"),
        )
        current_task_id = int(current_task.lastrowid)

    run_id = _create_run(
        current_task_id,
        "writer",
        "chapter-02-draft",
        "",
    )
    with connect() as conn:
        resource = conn.execute(
            """
            SELECT version,content
            FROM agent_run_resources
            WHERE run_id=? AND resource_type='story_state'
            """,
            (run_id,),
        ).fetchone()

    assert resource is not None
    assert resource["version"] == 1
    assert json.loads(resource["content"])["chapter_number"] == 1
