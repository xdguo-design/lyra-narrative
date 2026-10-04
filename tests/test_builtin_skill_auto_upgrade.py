from pathlib import Path

from app.db import connect, init_db
from app.services.default_skills import (
    BUILTIN_READER_REVIEW_SKILL_NAME,
    BUILTIN_WRITING_SKILL_NAME,
)
from app.services.rejection_learning import record_rejection_batch
from app.services.workflow_service import _selected_skills


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



def _task_with_skill_policy(*, title: str, mode: str = "default") -> tuple[int, int, int]:
    with connect() as conn:
        project_id = int(
            conn.execute(
                "INSERT INTO projects(title) VALUES(?)",
                (title,),
            ).lastrowid
        )
        task_id = int(
            conn.execute(
                "INSERT INTO writing_tasks(project_id,goal,status) VALUES(?,?,?)",
                (project_id, "测试跨项目 Skill 进化", "pending"),
            ).lastrowid
        )
        conn.execute(
            "INSERT INTO writing_task_skill_policy(task_id,mode) VALUES(?,?)",
            (task_id, mode),
        )
        writer = conn.execute(
            """
            SELECT id,current_version
            FROM skills
            WHERE project_id IS NULL AND name=?
            """,
            (BUILTIN_WRITING_SKILL_NAME,),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO writing_task_skills(task_id,skill_id,version)
            VALUES(?,?,?)
            """,
            (task_id, int(writer["id"]), int(writer["current_version"])),
        )
        return project_id, task_id, int(writer["current_version"])


def test_default_task_refreshes_global_skill_after_other_project_learns(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("NOVEL_DB_PATH", str(tmp_path / "cross-project.db"))
    monkeypatch.setenv("NOVEL_SEED_DEMO", "0")
    monkeypatch.setenv(
        "NARRATIVE_BUILTIN_SKILL_LEARNING_DIR",
        str(tmp_path / "audit"),
    )
    init_db()

    _, stale_task_id, stale_version = _task_with_skill_policy(title="先建的新书")
    learning_task_id = _task()

    record_rejection_batch(
        task_id=learning_task_id,
        source="HUMAN_REJECT",
        events=[
            {
                "reviewer": "human-controller",
                "category": "author-summary",
                "reason": "AUTHOR_SUMMARY_GAP：不要用作者总结替人物行动下结论。",
                "suggestion": "后续所有小说的默认 Writer 必须主动规避同类表达。",
                "excerpt": "他不是不怕，而是已经没有退路。",
            }
        ],
    )

    with connect() as conn:
        latest_version = int(
            conn.execute(
                "SELECT current_version FROM skills "
                "WHERE project_id IS NULL AND name=?",
                (BUILTIN_WRITING_SKILL_NAME,),
            ).fetchone()["current_version"]
        )
        assert latest_version > stale_version

        selected = _selected_skills(conn, stale_task_id, 1)
        effective = next(
            row for row in selected if row["name"] == BUILTIN_WRITING_SKILL_NAME
        )
        assert int(effective["version"]) == latest_version

        persisted = int(
            conn.execute(
                """
                SELECT wts.version
                FROM writing_task_skills wts
                JOIN skills s ON s.id=wts.skill_id
                WHERE wts.task_id=? AND s.name=?
                """,
                (stale_task_id, BUILTIN_WRITING_SKILL_NAME),
            ).fetchone()["version"]
        )
        assert persisted == latest_version


def test_explicit_task_keeps_pinned_skill_version_after_global_learning(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("NOVEL_DB_PATH", str(tmp_path / "explicit-pin.db"))
    monkeypatch.setenv("NOVEL_SEED_DEMO", "0")
    monkeypatch.setenv(
        "NARRATIVE_BUILTIN_SKILL_LEARNING_DIR",
        str(tmp_path / "audit"),
    )
    init_db()

    project_id, pinned_task_id, pinned_version = _task_with_skill_policy(
        title="显式固定技能",
        mode="explicit",
    )
    learning_task_id = _task()

    record_rejection_batch(
        task_id=learning_task_id,
        source="HUMAN_REJECT",
        events=[
            {
                "reviewer": "human-controller",
                "category": "dialogue",
                "reason": "TURN_TAKING_SYMMETRY_GAP：连续问答像聊天框。",
                "suggestion": "默认任务升级，但显式固定任务保持可复现。",
                "excerpt": "“去哪儿？”“外面。”",
            }
        ],
    )

    with connect() as conn:
        selected = _selected_skills(conn, pinned_task_id, project_id)
        effective = next(
            row for row in selected if row["name"] == BUILTIN_WRITING_SKILL_NAME
        )
        assert int(effective["version"]) == pinned_version
