from pathlib import Path


def test_platform_chapter_generation_excludes_existing_chapter2_as_input():
    source = Path("scripts/generate_rewrite_v3_chapter.py").read_text(
        encoding="utf-8"
    )
    assert "chapter-01/final-candidate.md" in source
    assert "chapters-01-10-plan.md" in source
    assert "manual-v6-run-001/characters.md" in source
    assert "chapter-02/final-candidate.md" in source
    assert "禁止读取 books/yamen-proficiency/rewrite-v3/chapter-02/final-candidate.md" in source
    assert "CHAPTER_TWO" not in source
    assert "_run_frozen_chapter(" in source


def test_platform_generation_workflow_uses_writer_and_reader_profiles():
    source = Path(
        ".github/workflows/rewrite-v3-chapter-generate.yml"
    ).read_text(encoding="utf-8")
    for marker in [
        "Rewrite v3 Chapter Platform Generate",
        "NARRATIVE_WRITER_PROFILE: ATRIA",
        "NARRATIVE_NATURAL_READER_PROFILE: GLM52",
        "NARRATIVE_REASONING_READER_PROFILE: DEEPSEEKV4PRO",
        "NARRATIVE_ROLE_CHARACTER_VOICE_REVIEWER_PROFILE: GLM52",
        "Generate chapter 02 through NarrativeOS",
    ]:
        assert marker in source
