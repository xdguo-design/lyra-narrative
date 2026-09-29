from app.db import connect, init_db
from app.services.full_novel_pipeline import _active_character_cards


def test_active_character_cards_are_selected_from_current_draft(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVEL_DB_PATH", str(tmp_path / "character-voice.db"))
    monkeypatch.setenv("NOVEL_SEED_DEMO", "0")
    init_db()

    with connect() as conn:
        project = conn.execute(
            "INSERT INTO projects(title) VALUES(?)",
            ("角色声音测试",),
        )
        project_id = int(project.lastrowid)
        for name in ["陈安", "周虎", "赵六", "未出场人物"]:
            conn.execute(
                "INSERT INTO characters(project_id,name,role,profile,tags) "
                "VALUES(?,?,?,?,?)",
                (project_id, name, "测试角色", f"{name}角色卡", "[]"),
            )

    cards = _active_character_cards(
        project_id,
        "周虎看了陈安一眼。周虎问了一句。赵六没接话。",
    )

    assert [item["name"] for item in cards] == ["周虎", "陈安", "赵六"]


def test_character_voice_review_is_a_blocking_parallel_gate():
    source = open(
        "app/services/full_novel_pipeline.py",
        encoding="utf-8",
    ).read()
    for marker in [
        'role="character-voice-reviewer"',
        "CHARACTER_VOICE_REVIEW_V1",
        "每一句对白都必须逐句列出",
        "说出口测试",
        "character_voice_tasks",
        "await asyncio.gather(*character_voice_tasks)",
        "bool(character_voice_failures)",
        "[character-voice:{name}]",
    ]:
        assert marker in source


def test_targeted_chapter_review_seeds_character_cards():
    source = open(
        "scripts/review_rewrite_v3_chapter.py",
        encoding="utf-8",
    ).read()
    for name in ["陈安", "赵六", "周虎", "刘旺"]:
        assert f'"{name}"' in source
    assert "INSERT INTO characters" in source
