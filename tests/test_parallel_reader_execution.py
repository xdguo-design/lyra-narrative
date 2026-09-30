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



def test_chapter02_pipeline_metrics_are_structured_for_p50_p95():
    db_source = Path("app/db.py").read_text(encoding="utf-8")
    metrics_source = Path("app/services/pipeline_metrics.py").read_text(
        encoding="utf-8"
    )
    fast_source = Path("scripts/generate_rewrite_v3_chapter_fast.py").read_text(
        encoding="utf-8"
    )

    for marker in [
        "CREATE TABLE IF NOT EXISTS chapter_pipeline_runs",
        "CREATE TABLE IF NOT EXISTS chapter_pipeline_events",
        "started_at_ms INTEGER NOT NULL DEFAULT 0",
        "input_chars INTEGER NOT NULL DEFAULT 0",
        "context_tier TEXT NOT NULL DEFAULT ''",
    ]:
        assert marker in db_source

    for marker in [
        'PIPELINE_VERSION = "chapter-fast-local-retry-v5"',
        '"normal"',
        '"single_reviewer_retry"',
        '"length_repair"',
        "review_initial_wall_ms",
        "review_retry_wall_ms",
        "p50_ms",
        "p95_ms",
        "p95_status",
        "[pipeline-metric]",
    ]:
        assert marker in metrics_source

    for marker in [
        "start_pipeline_run(",
        'stage="length-gate"',
        'stage="review-group"',
        "sync_agent_run_events(",
        "finish_pipeline_run(",
        '"pipeline_metrics": pipeline_metrics',
    ]:
        assert marker in fast_source


def test_agent_run_metrics_capture_failure_latency_and_prompt_shape():
    source = Path("app/services/workflow_service.py").read_text(encoding="utf-8")
    for marker in [
        "started_at_ms = int(time.time() * 1000)",
        "input_chars, context_tier = _prompt_size(content, instruction)",
        "output_chars=0",
        "finished_at_ms=finished_at_ms",
        "context_tier=context_tier",
        "error_code=",
    ]:
        assert marker in source

def test_chapter02_short_draft_uses_local_patch_repair():
    ai_source = Path("app/services/ai_service.py").read_text(encoding="utf-8")
    fast_source = Path("scripts/generate_rewrite_v3_chapter_fast.py").read_text(
        encoding="utf-8"
    )
    workflow = Path(".github/workflows/rewrite-v3-chapter-fast.yml").read_text(
        encoding="utf-8"
    )

    assert '"patch": (' in ai_source
    assert "async def _repair_short_draft_with_patches" in fast_source
    assert "search_result, measurement_result = await asyncio.gather(" in fast_source
    assert "正文少于 2700 个中文字符时不得结束生成" in fast_source
    assert "NARRATIVE_ROLE_WRITER_SEARCH_PATCH_PROFILE: AGNES" in workflow
    assert "NARRATIVE_ROLE_WRITER_MEASUREMENT_PATCH_PROFILE: DOTS3" in workflow



def test_writer_retry_has_dedicated_output_budget_and_diagnostic_artifact():
    ai_source = Path("app/services/ai_service.py").read_text(encoding="utf-8")
    fast_source = Path("scripts/generate_rewrite_v3_chapter_fast.py").read_text(
        encoding="utf-8"
    )
    workflow = Path(".github/workflows/rewrite-v3-chapter-fast.yml").read_text(
        encoding="utf-8"
    )

    assert 'normalized_role == "writer-retry"' in ai_source
    assert "NARRATIVE_WRITER_RETRY_MAX_TOKENS" in ai_source
    assert "NARRATIVE_WRITER_RETRY_TIMEOUT_SECONDS" in ai_source
    assert 'NARRATIVE_WRITER_RETRY_MAX_TOKENS: "10000"' in workflow
    assert 'NARRATIVE_WRITER_RETRY_TIMEOUT_SECONDS: "150"' in workflow
    assert '"run-started.json"' in fast_source



def test_short_length_repair_uses_two_local_patches_not_whole_rewrite():
    source = Path("scripts/generate_rewrite_v3_chapter_fast.py").read_text(
        encoding="utf-8"
    )
    for marker in [
        "async def _repair_short_draft_with_patches",
        'role="writer-search-patch"',
        'stage="chapter-02-length-repair-search"',
        'role="writer-measurement-patch"',
        'stage="chapter-02-length-repair-measurement"',
        "search_result, measurement_result = await asyncio.gather(",
        "_assemble_short_draft_patches(",
    ]:
        assert marker in source


def test_short_patch_assembly_replaces_post_weight_segment_and_keeps_one_hook():
    from scripts.generate_rewrite_v3_chapter_fast import (
        _assemble_short_draft_patches,
    )

    original = (
        "口供段。\n\n找袋段。\n\n重量对不上。\n\n"
        "旧的跑偏段落，写了不该有的东西。\n\n马二死了。"
    )
    repaired = _assemble_short_draft_patches(
        original,
        "新增找袋现场。",
        "官斗复量后，只确认：短三斗一升。有人快步进院。",
    )
    assert "新增找袋现场。" in repaired
    assert "旧的跑偏段落" not in repaired
    assert "短三斗一升" in repaired
    assert repaired.count("马二死了。") == 1
    assert repaired.endswith("马二死了。")



def test_short_patch_repair_uses_two_rounds_and_three_insertions():
    source = Path("scripts/generate_rewrite_v3_chapter_fast.py").read_text(
        encoding="utf-8"
    )
    workflow = Path(".github/workflows/rewrite-v3-chapter-fast.yml").read_text(
        encoding="utf-8"
    )
    for marker in [
        "async def _repair_short_draft_round",
        "for round_no in range(1, 3):",
        'role="writer-search-patch"',
        'role="writer-measurement-patch"',
        'role="writer-transition-patch"',
        '_insert_before_first(text, "重量对不上", search_patch)',
        '_insert_before_first(repaired, "短三斗一升", measurement_patch)',
        '_insert_before_last(repaired, "马二死了。", transition_patch)',
    ]:
        assert marker in source
    assert "NARRATIVE_ROLE_WRITER_TRANSITION_PATCH_PROFILE: AGNES" in workflow


def test_three_patch_assembly_preserves_exact_hook_and_inserts_all_segments():
    from scripts.generate_rewrite_v3_chapter_fast import (
        _assemble_short_draft_patches,
    )

    original = (
        "口供。\n\n重量对不上。\n\n复量后说：短三斗一升。"
        "\n\n马二死了。"
    )
    repaired = _assemble_short_draft_patches(
        original,
        "找袋现场扩写。",
        "官斗复量过程扩写。",
        "收好粮袋与记录，院里脚步一停。",
    )
    assert "找袋现场扩写。" in repaired
    assert "官斗复量过程扩写。" in repaired
    assert "院里脚步一停。" in repaired
    assert repaired.count("马二死了。") == 1
    assert repaired.endswith("马二死了。")
