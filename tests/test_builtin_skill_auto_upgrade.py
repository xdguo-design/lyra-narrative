from pathlib import Path

from app.db import connect, init_db
from app.services.default_skills import (
    BUILTIN_READER_REVIEW_SKILL_NAME,
    BUILTIN_WRITING_SKILL_NAME,
)
from app.services.rejection_learning import record_rejection_batch


def _versions():
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT name,current_version,content
            FROM skills
            WHERE project_id IS NULL
              AND name IN (?,?)
            ORDER BY name
            """,
            (
                BUILTIN_WRITING_SKILL_NAME,
                BUILTIN_READER_REVIEW_SKILL_NAME,
            ),
        ).fetchall()
    return {
        row["name"]: (int(row["current_version"]), str(row["content"]))
        for row in rows
    }


def _task() -> int:
    with connect() as conn:
        project_id = int(
            conn.execute(
                "INSERT INTO projects(title) VALUES(?)",
                ("自动学习测试",),
            ).lastrowid
        )
        chapter_id = int(
            conn.execute(
                "INSERT INTO chapters(project_id,title,position) VALUES(?,?,?)",
                (project_id, "第一章", 1),
            ).lastrowid
        )
        return int(
            conn.execute(
                "INSERT INTO writing_tasks(project_id,chapter_id,goal,status) "
                "VALUES(?,?,?,?)",
                (project_id, chapter_id, "测试打回学习", "awaiting_approval"),
            ).lastrowid
        )


def test_rejection_auto_upgrades_builtin_writer_and_reader(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVEL_DB_PATH", str(tmp_path / "learning.db"))
    monkeypatch.setenv("NOVEL_SEED_DEMO", "0")
    monkeypatch.setenv(
        "NARRATIVE_BUILTIN_SKILL_LEARNING_DIR",
        str(tmp_path / "audit"),
    )
    init_db()
    task_id = _task()

    before = _versions()
    result = record_rejection_batch(
        task_id=task_id,
        source="HUMAN_REJECT",
        events=[
            {
                "reviewer": "human-approval",
                "category": "dialogue",
                "reason": "对白逻辑正确但像作者总结，人物不会这样说。",
                "suggestion": "生成时先做说出口测试；Reader 命中时必须阻断。",
                "excerpt": "先记少了多少，别先替它写成丢了多少。",
            }
        ],
    )
    after = _versions()

    assert result["recorded"] == 1
    assert after[BUILTIN_WRITING_SKILL_NAME][0] > before[BUILTIN_WRITING_SKILL_NAME][0]
    assert after[BUILTIN_READER_REVIEW_SKILL_NAME][0] > before[BUILTIN_READER_REVIEW_SKILL_NAME][0]
    assert "对白逻辑正确但像作者总结" in after[BUILTIN_WRITING_SKILL_NAME][1]
    assert "对白逻辑正确但像作者总结" in after[BUILTIN_READER_REVIEW_SKILL_NAME][1]

    with connect() as conn:
        durable = conn.execute(
            "SELECT COUNT(*) AS n FROM builtin_skill_learning_events"
        ).fetchone()["n"]
        bindings = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM writing_task_skills
            WHERE task_id=?
            """,
            (task_id,),
        ).fetchone()["n"]
    assert durable == 1
    assert bindings >= 2


def test_builtin_learning_replays_from_database_after_restart(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVEL_DB_PATH", str(tmp_path / "restart.db"))
    monkeypatch.setenv("NOVEL_SEED_DEMO", "0")
    monkeypatch.setenv(
        "NARRATIVE_BUILTIN_SKILL_LEARNING_DIR",
        str(tmp_path / "audit"),
    )
    init_db()
    task_id = _task()

    record_rejection_batch(
        task_id=task_id,
        source="reader-round-1",
        events=[
            {
                "reviewer": "blind-natural-reader",
                "category": "naturalness",
                "reason": "测试持久学习事件。",
                "suggestion": "下轮必须拦截。",
                "excerpt": "样本",
            }
        ],
    )
    learned = _versions()

    init_db()
    replayed = _versions()
    assert replayed == learned


def test_every_rejection_path_calls_builtin_learning():
    full = Path("app/services/full_novel_pipeline.py").read_text(
        encoding="utf-8"
    )
    book = Path("app/services/book_pipeline.py").read_text(
        encoding="utf-8"
    )
    workflow = Path("app/services/workflow_service.py").read_text(
        encoding="utf-8"
    )
    main = Path("app/main.py").read_text(encoding="utf-8")

    assert 'source=f"review-round-{round_no}"' in full
    assert 'source=f"revision-integrity-r{round_no}"' in full
    assert 'source="final-repetition-gate"' in book
    assert 'source="continuity-state-updater"' in book
    assert 'source="standard-review"' in workflow
    assert 'source="HUMAN_REJECT"' in main
