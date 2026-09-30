# ruff: noqa: I001
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


def test_yamen_generation_uses_long_form_control_pack_by_scope():
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
        assert marker in first_ten

    assert "keep_generation_skills_lean" in current
    assert "_persist_memory(" not in current
    assert '"long_form_control_pack_used": False' in current
    assert '"lean_generation_context_used": True' in current



def test_continuity_plot_reviewer_covers_long_form_drift():
    pipeline = Path("app/services/full_novel_pipeline.py").read_text(encoding="utf-8")
    ai = Path("app/services/ai_service.py").read_text(encoding="utf-8")
    review_start = pipeline.index("async def _run_review_round(")
    review_end = pipeline.index("async def run_full_novel_pipeline", review_start)
    review = pipeline[review_start:review_end]
    for marker in [
        '"continuity-plot-reviewer"',
        "长线阶段漂移",
        "技能跳级",
        "对手突然变蠢",
        "伏笔",
        "世界规则",
        "知识来源缺口",
    ]:
        assert marker in review
    assert '"continuity-plot-reviewer": "MODELSCOPE"' in ai

def test_targeted_reader_review_seeds_long_form_control_pack():
    source = Path("scripts/review_rewrite_v3_chapter.py").read_text(
        encoding="utf-8"
    )
    assert "CONTROL_SOURCES = [" in source
    assert "_persist_memory(" in source
    assert "control_context" in source
    for marker in [
        "story-bible-v1.md",
        "volume-01-outline-v1.md",
        "foreshadow-registry-v1.md",
        "proficiency-skill-tree-v1.md",
        "conflict-opponent-ladder-v1.md",
    ]:
        assert marker in source
