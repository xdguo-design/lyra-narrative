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
    assert BUILTIN_WRITER_TRAINING_SKILL_VERSION == 3
    content = BUILTIN_WRITER_TRAINING_SKILL_CONTENT
    required = [
        "基线诊断",
        "场景导演训练",
        "人物行为训练",
        "语言节奏训练",
        "读者盲读验证",
        "READER_TRACE_V1",
        "Reader Gap",
        "含糊”不等于“留白",
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
        'stage="training-reader-trace"',
        'stage="training-reader-gap"',
        'stage="training-reader-rewrite"',
        'stage="training-integrated-scene"',
        'stage="training-integrated-reader-trace"',
        'stage="training-integrated-reader-gap"',
        'stage="training-integrated-reader-recheck"',
        'stage="training-transfer-brief"',
        'stage="training-transfer-attempt"',
        'stage="training-transfer-reader-trace"',
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


def test_training_level_parser_controls_repeated_coaching():
    from app.services.writer_training_pipeline import (
        _diagnosed_level,
        _needs_coaching,
    )

    diagnosis = """WRITER_TRAINING_DIAGNOSIS_V1
【场景导演】STABLE
【人物行为】EMERGING
【语言节奏】TRANSFERABLE
"""
    assert _diagnosed_level(diagnosis, "场景导演") == "STABLE"
    assert _diagnosed_level(diagnosis, "人物行为") == "EMERGING"
    assert _diagnosed_level(diagnosis, "语言节奏") == "TRANSFERABLE"
    assert _needs_coaching("STABLE") is False
    assert _needs_coaching("TRANSFERABLE") is False
    assert _needs_coaching("EMERGING") is True
    assert _needs_coaching("NEEDS_WORK") is True


def test_blind_reader_does_not_receive_author_context():
    source = Path("app/services/writer_training_pipeline.py").read_text(
        encoding="utf-8"
    )
    start = source.index('role="blind-reader"')
    gap = source.index('role="reader-gap-coach"', start)
    blind_block = source[start:gap]
    assert "context," not in blind_block
    assert "scene_rewrite.content" not in blind_block
    assert "behavior_attempt.content" not in blind_block
    assert "READER_TRACE_V1" in blind_block


def test_reader_gate_can_force_writer_rewrite():
    source = Path("app/services/writer_training_pipeline.py").read_text(
        encoding="utf-8"
    )
    assert 'reader_gap.content.strip() == "NO_READER_GAP"' in source
    assert 'stage="training-reader-rewrite"' in source
    assert "只修 Reader Gap" in source
    assert "有效悬念继续保留" in source


def test_reader_gate_unknown_boundary_rule_and_failure_examples():
    content = BUILTIN_WRITER_TRAINING_SKILL_CONTENT
    required = [
        "读者可以不知道答案，但必须知道自己不知道的是什么",
        "INTENTIONAL_UNKNOWN",
        "READER_GAP",
        "AMBIGUOUS_GAP",
        "县衙那边也没完",
        "事情还没完",
        "他终于明白了",
        "她把钱收起来",
        "多读两遍能懂",
        "Author/Coach/Editor 均不得替 Reader 解释",
    ]
    for marker in required:
        assert marker in content


def test_training_reader_protocol_requires_unknown_labels():
    source = Path("app/services/writer_training_pipeline.py").read_text(
        encoding="utf-8"
    )
    for marker in [
        "INTENTIONAL_UNKNOWN",
        "READER_GAP",
        "AMBIGUOUS_GAP",
        "只有 INTENTIONAL_UNKNOWN 可直接 PASS",
    ]:
        assert marker in source
