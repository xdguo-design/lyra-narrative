from __future__ import annotations

import os
from pathlib import Path

os.environ["NOVEL_DB_PATH"] = "/tmp/novel-workbench-writer-training-test.db"
os.environ["NOVEL_SEED_DEMO"] = "0"
os.environ["NOVEL_AI_KIND"] = "demo"

from fastapi.testclient import TestClient

from app.db import db_path
from app.main import app
from app.services.default_skills import (
    BUILTIN_WRITER_TRAINING_SKILL_CONTENT,
    BUILTIN_WRITER_TRAINING_SKILL_NAME,
    BUILTIN_WRITER_TRAINING_SKILL_VERSION,
)


def setup_function():
    path = db_path()
    if path.exists():
        path.unlink()


def test_writer_training_skill_has_deliberate_practice_contract():
    assert BUILTIN_WRITER_TRAINING_SKILL_VERSION == 1
    content = BUILTIN_WRITER_TRAINING_SKILL_CONTENT
    required = [
        "基线诊断",
        "场景导演训练",
        "人物行为训练",
        "语言节奏训练",
        "综合场景训练",
        "迁移测试",
        "Writer Craft Profile",
        "NEEDS_WORK / EMERGING / STABLE / TRANSFERABLE",
        "什么证据出现前绝不会承认",
        "3—5 句为最小观察单位",
        "只读规则不算训练",
        "同一段改对不等于真正掌握",
    ]
    for marker in required:
        assert marker in content


def test_writer_training_pipeline_has_attempt_feedback_rewrite_and_transfer():
    source = Path("app/services/writer_training_pipeline.py").read_text(
        encoding="utf-8"
    )
    required = [
        'stage="training-diagnosis"',
        'stage="training-scene-direction-attempt"',
        'stage="training-scene-direction-feedback"',
        'stage="training-scene-direction-rewrite"',
        'stage="training-character-behavior-attempt"',
        'stage="training-character-behavior-feedback"',
        'stage="training-character-behavior-rewrite"',
        'stage="training-rhythm-attempt"',
        'stage="training-rhythm-feedback"',
        'stage="training-rhythm-rewrite"',
        'stage="training-integrated-scene"',
        'stage="training-transfer-brief"',
        'stage="training-transfer-attempt"',
        'stage="training-transfer-review"',
        'stage="training-profile"',
        '"writer-training:craft-profile"',
    ]
    for marker in required:
        assert marker in source


def test_writer_training_api_is_exposed_and_requires_real_provider():
    with TestClient(app) as client:
        project = client.post(
            "/api/projects",
            json={"title": "作家训练测试", "genre": "架空历史"},
        )
        assert project.status_code == 201
        project_id = project.json()["id"]

        chapter_id = client.get(
            f"/api/projects/{project_id}/chapters"
        ).json()[0]["id"]
        client.patch(
            f"/api/chapters/{chapter_id}",
            json={
                "content": "刘旺低头看了眼车轮。陈安问：昨晚你推过这辆车？",
                "note": "训练基线",
            },
        )

        task = client.post(
            f"/api/projects/{project_id}/tasks",
            json={
                "chapter_id": chapter_id,
                "goal": "训练场景导演、人物行为和语言节奏",
            },
        )
        assert task.status_code == 201
        task_json = task.json()

        assert all(
            skill["name"] != BUILTIN_WRITER_TRAINING_SKILL_NAME
            for skill in task_json["skills"]
        )

        response = client.post(
            f"/api/tasks/{task_json['id']}/train-writer",
            json={},
        )
        assert response.status_code == 409
        assert "real AI provider" in response.json()["detail"]


def test_writer_training_skill_remains_discoverable_for_explicit_use():
    with TestClient(app) as client:
        project_id = client.post(
            "/api/projects",
            json={"title": "训练 Skill 可见性"},
        ).json()["id"]
        skills = client.get(f"/api/projects/{project_id}/skills").json()
        assert any(
            item["name"] == BUILTIN_WRITER_TRAINING_SKILL_NAME
            for item in skills
        )
