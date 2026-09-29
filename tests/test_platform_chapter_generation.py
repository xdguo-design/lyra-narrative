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
        "NARRATIVE_WRITER_PROFILE: SENSENOVA",
        "NARRATIVE_NATURAL_READER_PROFILE: AGNES",
        "NARRATIVE_REASONING_READER_PROFILE: MODELSCOPE",
        "NARRATIVE_ROLE_CHARACTER_VOICE_REVIEWER_PROFILE: AGNES",
        "Generate chapter 02 through NarrativeOS",
    ]:
        assert marker in source



def test_platform_chapter_generation_uses_lean_context_after_human_reject():
    source = Path("scripts/generate_rewrite_v3_chapter.py").read_text(
        encoding="utf-8"
    )
    for marker in [
        "CORE_CHARACTER_NAMES",
        "keep_generation_skills_lean",
        'source="HUMAN_REJECT"',
        "问卷式盘问",
        "作者总结腔",
        "ORALITY_GAP",
        "VOICE_OVERPERFORMANCE_GAP",
        "INVESTIGATION_WORKSHEET_GAP",
    ]:
        assert marker in source

    for forbidden in [
        "_persist_memory(",
        "STORY_BIBLE",
        "VOLUME_OUTLINE",
        "FORESHADOW_REGISTRY",
        "OPPONENT_LADDER",
    ]:
        assert forbidden not in source



def test_chapter_gate_rejects_truncated_successful_outputs():
    source = Path("app/services/book_pipeline.py").read_text(encoding="utf-8")
    for marker in [
        "len(stripped) < 1800",
        "len(body) < 1600",
        'terminal not in "。！？…」』”）】"',
        "2500—4500",
        "writer returned invalid chapter stub after semantic retry",
    ]:
        assert marker in source
    assert 'stage="book-architecture"' in source
    assert 'content=""' in source



def test_writer_route_prunes_slow_providers():
    source = Path(
        ".github/workflows/rewrite-v3-chapter-generate.yml"
    ).read_text(encoding="utf-8")
    assert "NARRATIVE_WRITER_PROFILE: SENSENOVA" in source
    writer_line = next(
        line.strip()
        for line in source.splitlines()
        if "NARRATIVE_WRITER_FALLBACK_PROFILES:" in line
    )
    assert writer_line == "NARRATIVE_WRITER_FALLBACK_PROFILES:"
    assert 'NOVEL_AI_TIMEOUT_SECONDS: "60"' in source
    assert 'NOVEL_AI_HTTP_RETRIES: "0"' in source


def test_benchmark_selected_writer_profile_is_wired():
    source = Path(".github/workflows/rewrite-v3-chapter-generate.yml").read_text(encoding="utf-8")
    for marker in [
        "NARRATIVE_PROFILE_SENSENOVA: ${{ vars.SENSENOVA }}",
        "NARRATIVE_PROFILE_SECRET_SENSENOVA: ${{ secrets.SENSENOVA }}",
        "NARRATIVE_WRITER_PROFILE: SENSENOVA",
        "NARRATIVE_ROLE_WRITER_RETRY_PROFILE: AGNES",
        "Validate selected writer profiles",
    ]:
        assert marker in source
