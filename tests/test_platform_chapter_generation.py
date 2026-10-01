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
        "NARRATIVE_WRITER_PROFILE: AGNES",
        "NARRATIVE_ROLE_CONTINUITY_PLOT_REVIEWER_PROFILE: GLM53FLASH",
        "NARRATIVE_ROLE_CHARACTER_DIALOGUE_REVIEWER_PROFILE: AGNES",
        "NARRATIVE_ROLE_LANGUAGE_RHYTHM_REVIEWER_PROFILE: DOTS3",
        "NARRATIVE_PROFILE_DOTS3: ${{ vars.DOTS3 }}",
        "NARRATIVE_PROFILE_SENSENOVA68: ${{ vars.SENSENOVA68 }}",
        "Generate chapter 02 through NarrativeOS",
    ]:
        assert marker in source
    assert "NARRATIVE_ROLE_MASTER_READER_PROFILE" not in source

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
    assert "NARRATIVE_WRITER_PROFILE: AGNES" in source
    writer_line = next(
        line.strip()
        for line in source.splitlines()
        if "NARRATIVE_WRITER_FALLBACK_PROFILES:" in line
    )
    assert writer_line == "NARRATIVE_WRITER_FALLBACK_PROFILES: DOTS3,SENSENOVA68,ATRIA"
    assert "GLM53FLASH" not in writer_line
    assert "XINGCHENAGI" not in writer_line
    assert 'NOVEL_AI_TIMEOUT_SECONDS: "120"' in source
    assert 'NOVEL_AI_HTTP_RETRIES: "0"' in source


def test_benchmark_selected_writer_profile_is_wired():
    source = Path(".github/workflows/rewrite-v3-chapter-generate.yml").read_text(encoding="utf-8")
    for marker in [
        "NARRATIVE_PROFILE_DOTS3: ${{ vars.DOTS3 }}",
        "NARRATIVE_PROFILE_SENSENOVA68: ${{ vars.SENSENOVA68 }}",
        "NARRATIVE_WRITER_PROFILE: AGNES",
        "NARRATIVE_ROLE_WRITER_RETRY_PROFILE: DOTS3",
        "Validate selected writer profiles",
    ]:
        assert marker in source



def test_fast_chapter_waits_for_external_master_before_reject_learning():
    source = Path("scripts/generate_rewrite_v3_chapter_fast.py").read_text(
        encoding="utf-8"
    )
    assert "import re" in source
    assert "re.search(" in source
    assert "_run_review_round(" in source
    assert "auto_learn=False" in source
    assert "_insert_hard_gate_findings(" in source
    assert 'status = "awaiting_master_review"' in source
    assert '"master_review_pending": True' in source
    assert '"all_reviews_completed_before_reject": False' in source
    assert "learn_from_open_blocking_findings(" not in source


def test_full_review_round_can_defer_learning_until_all_automated_reviewers_finish():
    source = Path("app/services/full_novel_pipeline.py").read_text(
        encoding="utf-8"
    )
    assert "auto_learn: bool = True" in source
    assert "if has_blocking and auto_learn:" in source
    assert "_safe_review_task(" in source
    assert "REVIEW_EXECUTION_FAILED" in source


def test_review_skill_is_compressed_into_three_automated_plus_external_master():
    source = Path("app/services/full_novel_pipeline.py").read_text(encoding="utf-8")
    review_start = source.index("async def _run_review_round(")
    review_end = source.index("async def run_full_novel_pipeline", review_start)
    review_source = source[review_start:review_end]

    for role in [
        "continuity-plot-reviewer",
        "character-dialogue-reviewer",
        "language-rhythm-reviewer",
    ]:
        assert role in review_source

    assert "external ChatGPT controller" in review_source
    assert '"master-reader"' not in review_source
    assert "一次审核本章所有主要角色" in review_source



def test_fast_chapter_exports_blind_controller_reader_packet():
    source = Path("scripts/generate_rewrite_v3_chapter_fast.py").read_text(
        encoding="utf-8"
    )
    for marker in [
        "master-reader-packet.md",
        "BLIND REVIEW",
        "external-controller-blind-reader",
        '"master_reader_sees_automated_reviews": False',
        "不得读取 review-report.json",
    ]:
        assert marker in source

def test_book_pipeline_rejection_learning_import_is_not_function_local():
    source = Path("app/services/book_pipeline.py").read_text(encoding="utf-8")
    marker = "from app.services.rejection_learning import learn_from_open_blocking_findings"
    function_start = source.index("async def _run_frozen_chapter(")
    function_end = source.index("async def run_book_pipeline(", function_start)

    assert marker in source[:function_start]
    assert marker not in source[function_start:function_end]

