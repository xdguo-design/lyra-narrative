from pathlib import Path


CONTROL = Path("books/yamen-proficiency/rewrite-v3/control")


def test_long_form_control_pack_exists_and_is_frozen():
    required = {
        "story-bible-v1.md": ["FROZEN v1", "县衙空间与权力", "昌丰粮行"],
        "volume-01-outline-v1.md": ["1—30", "31—100", "孙成", "郑福"],
        "foreshadow-registry-v1.md": ["FSH-001", "FSH-018", "回收纪律"],
        "proficiency-skill-tree-v1.md": ["SK-01 寻迹", "SK-08 验伤", "1—30 章可见技能预算"],
        "conflict-opponent-ladder-v1.md": ["OPP-02 孙成", "OPP-03 郑福", "能力 vs 权力"],
    }
    for name, markers in required.items():
        text = (CONTROL / name).read_text(encoding="utf-8")
        for marker in markers:
            assert marker in text


def test_volume_outline_covers_all_first_volume_chapters():
    text = (CONTROL / "volume-01-outline-v1.md").read_text(encoding="utf-8")
    for chapter in range(11, 31):
        assert f"### {chapter}" in text


def test_yamen_generation_seeds_long_form_control_pack():
    current = Path("scripts/generate_rewrite_v3_chapter.py").read_text(
        encoding="utf-8"
    )
    first_ten = Path("scripts/run_yamen_first_ten_pipeline.py").read_text(
        encoding="utf-8"
    )
    for marker in [
        "story-bible-v1.md",
        "volume-01-outline-v1.md",
        "foreshadow-registry-v1.md",
        "proficiency-skill-tree-v1.md",
        "conflict-opponent-ladder-v1.md",
    ]:
        assert marker in current
        assert marker in first_ten


def test_long_arc_reviewer_blocks_long_form_drift():
    pipeline = Path("app/services/full_novel_pipeline.py").read_text(encoding="utf-8")
    ai = Path("app/services/ai_service.py").read_text(encoding="utf-8")
    for marker in [
        '"long-arc-reviewer"',
        "VOLUME_OUTLINE_DRIFT",
        "FORESHADOW_EARLY_REVEAL",
        "FORESHADOW_DROPPED",
        "PROFICIENCY_TIER_LEAP",
        "CONFLICT_ENGINE_DRIFT",
        "OPPONENT_FLATTENING",
        "LONG_TERM_STATE_DRIFT",
    ]:
        assert marker in pipeline
    assert '"long-arc-reviewer": "DEEPSEEKV4PRO"' in ai
