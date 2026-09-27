from __future__ import annotations

import os
from pathlib import Path

os.environ["NOVEL_DB_PATH"] = "/tmp/novel-workbench-editor-training-test.db"
os.environ["NOVEL_SEED_DEMO"] = "0"
os.environ["NOVEL_AI_KIND"] = "demo"

from fastapi.testclient import TestClient

from app.db import db_path
from app.main import app
from app.services.default_skills import (
    BUILTIN_EDITOR_TRAINING_SKILL_CONTENT,
    BUILTIN_EDITOR_TRAINING_SKILL_NAME,
    BUILTIN_EDITOR_TRAINING_SKILL_VERSION,
    BUILTIN_WRITER_TRAINING_SKILL_NAME,
)


def setup_function():
    path = db_path()
    if path.exists():
        path.unlink()


def test_editor_training_skill_has_deliberate_practice_contract():
    assert BUILTIN_EDITOR_TRAINING_SKILL_VERSION == 1
    content = BUILTIN_EDITOR_TRAINING_SKILL_CONTENT
    required = [
        "基线诊断",
        "Selection Exercise",
        "Voice Preservation",
        "Anti-Overediting",
        "Reader Comparison",
        "Transfer Edit",
        "Editor Craft Profile",
        "PRESERVE / CUT / COMPRESS / SLOW / LOCAL_REWRITE / NO_TOUCH",
        "编辑后的 Reader Gate 不得比编辑前更差",
        "如果编辑后更顺，但人物更像同一个人，判 FAIL",
        "NEEDS_WORK / EMERGING / STABLE / TRANSFERABLE",
    ]
    for marker in required:
        assert marker in content


def test_training_skills_are_excluded_from_default_writing_tasks():
    with TestClient(app) as client:
        project_id = client.post(
            "/api/projects",
            json={"title": "训练 Skill 隔离测试", "genre": "架空历史"},
        ).json()["id"]

        task = client.post(
            f"/api/projects/{project_id}/tasks",
            json={"goal": "写一段正式正文"},
        )
        assert task.status_code == 201
        names = {skill["name"] for skill in task.json()["skills"]}
        assert BUILTIN_WRITER_TRAINING_SKILL_NAME not in names
        assert BUILTIN_EDITOR_TRAINING_SKILL_NAME not in names


def test_editor_training_skill_remains_discoverable_for_explicit_use():
    with TestClient(app) as client:
        project_id = client.post(
            "/api/projects",
            json={"title": "Editor Skill 可见性"},
        ).json()["id"]
        skills = client.get(f"/api/projects/{project_id}/skills").json()
        assert any(
            item["name"] == BUILTIN_EDITOR_TRAINING_SKILL_NAME
            for item in skills
        )


def test_editor_training_artifacts_record_round_results_failures_and_pass_criteria():
    roots = [
        Path("books/yamen-proficiency/manual-v6-run-001/editor-training-round-001"),
        Path("books/yamen-proficiency/manual-v6-run-001/editor-training-round-002"),
    ]
    texts = []
    for root in roots:
        for file in root.glob("*.md"):
            texts.append(file.read_text(encoding="utf-8"))
    joined = "\n".join(texts)

    required = [
        "EF001",
        "EF002",
        "EF003",
        "EF004",
        "PASS",
        "NEEDS_WORK",
        "STABLE",
        "通过标准",
        "Reader",
        "Voice",
    ]
    for marker in required:
        assert marker in joined


def test_character_stress_gate_records_two_rounds_and_all_core_characters():
    a = Path(
        "books/yamen-proficiency/manual-v6-run-001/character-stress-tests/"
        "round-a-authority-evidence.md"
    ).read_text(encoding="utf-8")
    b = Path(
        "books/yamen-proficiency/manual-v6-run-001/character-stress-tests/"
        "round-b-family-money.md"
    ).read_text(encoding="utf-8")
    profile = Path(
        "books/yamen-proficiency/manual-v6-run-001/character-stress-tests/profile.md"
    ).read_text(encoding="utf-8")

    for name in ["陈安", "陈小满", "柳氏", "赵六", "周虎", "孙成", "刘三爷"]:
        assert name in a
        assert name in b
        assert name in profile

    assert "7/7 PASS" in a
    assert "7/7 PASS" in b
    assert "Core Character Stress Gate：PASS / STABLE" in profile
    assert "失败样本" in a
    assert "失败样本" in b
    assert "通过标准" in a
    assert "通过标准" in b
