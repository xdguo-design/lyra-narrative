from pathlib import Path


def test_review_round_runs_exactly_four_merged_roles_in_parallel():
    source = Path("app/services/full_novel_pipeline.py").read_text(encoding="utf-8")

    for marker in [
        '"master-reader"',
        '"continuity-plot-reviewer"',
        '"character-dialogue-reviewer"',
        '"language-rhythm-reviewer"',
        "packets = await asyncio.gather(",
        "for packet, (role, category, _instruction) in zip(",
    ]:
        assert marker in source

    # Per-character reviewer fan-out is no longer active inside the review round.
    review_start = source.index("async def _run_review_round(")
    review_end = source.index("async def run_full_novel_pipeline", review_start)
    review_source = source[review_start:review_end]
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
