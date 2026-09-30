from pathlib import Path


def test_review_round_runs_three_automated_roles_and_reserves_master_reader():
    source = Path("app/services/full_novel_pipeline.py").read_text(encoding="utf-8")

    review_start = source.index("async def _run_review_round(")
    review_end = source.index("async def run_full_novel_pipeline", review_start)
    review_source = source[review_start:review_end]

    for marker in [
        '"continuity-plot-reviewer"',
        '"character-dialogue-reviewer"',
        '"language-rhythm-reviewer"',
        "packets = await asyncio.gather(",
        "external ChatGPT controller",
    ]:
        assert marker in review_source

    assert '"master-reader"' not in review_source
    assert "character_voice_tasks" not in review_source
    assert "blind-dialogue-reader" not in review_source
    assert "blind-natural-reader" not in review_source
    assert "blind-artifice-reader" not in review_source
    assert "cadence-character-reader" not in review_source


def test_runtime_emits_agent_and_model_progress_logs():
    workflow = Path("app/services/workflow_service.py").read_text(encoding="utf-8")
    ai_service = Path("app/services/ai_service.py").read_text(encoding="utf-8")

    for marker in [
        "[agent-step] START",
        "[agent-step] DONE",
        "[agent-step] FAIL",
    ]:
        assert marker in workflow

    for marker in [
        "[model-route] TRY",
        "[model-route] DONE",
        'outcome = "FALLBACK"',
        "[model-route] {outcome}",
    ]:
        assert marker in ai_service



def test_review_round_retries_only_failed_reviewer_when_enabled():
    source = Path("app/services/full_novel_pipeline.py").read_text(encoding="utf-8")

    review_start = source.index("async def _run_review_round(")
    review_end = source.index("async def run_full_novel_pipeline", review_start)
    review_source = source[review_start:review_end]

    for marker in [
        "retry_failed_reviewers: int = 0",
        "[review-retry] RETRY_FAILED_ONLY",
        "[review-retry] RECOVERED",
        'f"review-r{round_no}-retry{retry_no}"',
        "只重试该 Reviewer",
    ]:
        assert marker in review_source


def test_chapter02_fast_path_uses_local_repair_and_targeted_review_retry():
    source = Path("scripts/generate_rewrite_v3_chapter_fast.py").read_text(
        encoding="utf-8"
    )
    main_start = source.index("async def main()")
    main_source = source[main_start:]

    assert main_source.count("await _run_writer(") == 1
    assert "text = await _repair_length_if_needed(task_id, text)" in main_source
    assert "retry_failed_reviewers=1" in main_source
    assert main_source.index("_repair_length_if_needed") < main_source.index(
        "_run_review_round"
    )


def test_length_repair_can_shorten_overlong_draft_and_expand_short_draft():
    from scripts.generate_rewrite_v3_chapter_fast import _accept_length_repair

    assert _accept_length_repair("x" * 3500, "x" * 3300)
    assert _accept_length_repair("x" * 2600, "x" * 2800)
    assert not _accept_length_repair("x" * 2600, "x" * 2500)
    assert not _accept_length_repair("x" * 3500, "x" * 3600)
