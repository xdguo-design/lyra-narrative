from pathlib import Path

from app.db import connect, init_db
from app.services.default_skills import (
    BUILTIN_READER_REVIEW_SKILL_NAME,
    BUILTIN_READER_REVIEW_SKILL_VERSION,
    BUILTIN_WRITING_SKILL_NAME,
    BUILTIN_WRITING_SKILL_VERSION,
)
from app.services.rejection_learning import record_rejection_batch


def _make_task(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVEL_DB_PATH", str(tmp_path / "learning.db"))
    monkeypatch.setenv("NOVEL_SEED_DEMO", "0")
    monkeypatch.setenv(
        "NARRATIVE_BUILTIN_SKILL_LEARNING_DIR",
        str(tmp_path / "learning-events"),
    )
    init_db()
    with connect() as conn:
        project = conn.execute(
            "INSERT INTO projects(title) VALUES(?)",
            ("内置 Skill 自动学习测试",),
        )
        project_id = int(project.lastrowid)
        task = conn.execute(
            "INSERT INTO writing_tasks(project_id,goal,status) VALUES(?,?,?)",
            (project_id, "测试", "awaiting_approval"),
        )
        task_id = int(task.lastrowid)
    return task_id


def test_rejection_upgrades_builtin_writer_and_reader_for_current_task(
    monkeypatch,
    tmp_path,
):
    task_id = _make_task(monkeypatch, tmp_path)
    result = record_rejection_batch(
        task_id=task_id,
        source="HUMAN_REJECT",
        events=[
            {
                "reviewer": "human-approval",
                "category": "human-reject",
                "reason": "ORALITY_GAP：意思正确，但不像这个人物会说的话。",
                "suggestion": "写作前做说出口测试，Reader 复审必须主动拦截。",
                "excerpt": "先记少了多少。",
            }
        ],
    )

    assert result["recorded"] == 1
    learning_files = list((tmp_path / "learning-events").glob("*.json"))
    assert len(learning_files) == 1

    with connect() as conn:
        versions = {
            row["name"]: int(row["current_version"])
            for row in conn.execute(
                "SELECT name,current_version FROM skills "
                "WHERE name IN (?,?)",
                (BUILTIN_WRITING_SKILL_NAME, BUILTIN_READER_REVIEW_SKILL_NAME),
            ).fetchall()
        }
        frozen = {
            row["name"]: int(row["version"])
            for row in conn.execute(
                """
                SELECT s.name,wts.version
                FROM writing_task_skills wts
                JOIN skills s ON s.id=wts.skill_id
                WHERE wts.task_id=? AND s.name IN (?,?)
                """,
                (
                    task_id,
                    BUILTIN_WRITING_SKILL_NAME,
                    BUILTIN_READER_REVIEW_SKILL_NAME,
                ),
            ).fetchall()
        }

    assert versions[BUILTIN_WRITING_SKILL_NAME] > BUILTIN_WRITING_SKILL_VERSION
    assert versions[BUILTIN_READER_REVIEW_SKILL_NAME] > BUILTIN_READER_REVIEW_SKILL_VERSION
    assert frozen == versions


def test_fresh_database_replays_persisted_builtin_learning(monkeypatch, tmp_path):
    learning_dir = tmp_path / "learning-events"
    monkeypatch.setenv(
        "NARRATIVE_BUILTIN_SKILL_LEARNING_DIR",
        str(learning_dir),
    )
    monkeypatch.setenv("NOVEL_SEED_DEMO", "0")

    monkeypatch.setenv("NOVEL_DB_PATH", str(tmp_path / "first.db"))
    init_db()
    with connect() as conn:
        project = conn.execute("INSERT INTO projects(title) VALUES(?)", ("一",))
        task = conn.execute(
            "INSERT INTO writing_tasks(project_id,goal,status) VALUES(?,?,?)",
            (int(project.lastrowid), "测试", "awaiting_approval"),
        )
        task_id = int(task.lastrowid)

    record_rejection_batch(
        task_id=task_id,
        source="review-round-1",
        events=[
            {
                "reviewer": "blind-dialogue-reader",
                "category": "reader-dialogue",
                "reason": "VOICE_OVERPERFORMANCE_GAP：对白像作者写的原则句。",
                "suggestion": "检查是否真是人物当场会说的话。",
                "excerpt": "漂亮原则句",
            }
        ],
    )

    monkeypatch.setenv("NOVEL_DB_PATH", str(tmp_path / "fresh.db"))
    init_db()
    with connect() as conn:
        skills = {
            row["name"]: (int(row["current_version"]), row["content"])
            for row in conn.execute(
                "SELECT name,current_version,content FROM skills "
                "WHERE name IN (?,?)",
                (BUILTIN_WRITING_SKILL_NAME, BUILTIN_READER_REVIEW_SKILL_NAME),
            ).fetchall()
        }

    assert skills[BUILTIN_WRITING_SKILL_NAME][0] > BUILTIN_WRITING_SKILL_VERSION
    assert skills[BUILTIN_READER_REVIEW_SKILL_NAME][0] > BUILTIN_READER_REVIEW_SKILL_VERSION
    assert "VOICE_OVERPERFORMANCE_GAP" in skills[BUILTIN_WRITING_SKILL_NAME][1]
    assert "VOICE_OVERPERFORMANCE_GAP" in skills[BUILTIN_READER_REVIEW_SKILL_NAME][1]


def test_machine_and_human_rejection_paths_feed_builtin_learning():
    pipeline = Path("app/services/full_novel_pipeline.py").read_text(encoding="utf-8")
    api = Path("app/main.py").read_text(encoding="utf-8")

    assert "learn_from_open_blocking_findings(" in pipeline
    assert 'source=f"review-round-{round_no}"' in pipeline
    assert 'source="HUMAN_REJECT"' in api
    assert "rejected approval requires a reason" in api


def test_formal_workflows_persist_learning_back_to_repo():
    workflows = [
        "rewrite-v3-chapter-generate.yml",
        "rewrite-v3-chapter-review.yml",
        "yamen-first-ten-pipeline.yml",
        "zero-platform-rewrite.yml",
        "long-consistency-test.yml",
    ]
    for name in workflows:
        source = Path(".github/workflows", name).read_text(encoding="utf-8")
        assert "contents: write" in source
        assert "Persist built-in Skill learning" in source
        assert "scripts/persist_builtin_skill_learning.sh" in source
