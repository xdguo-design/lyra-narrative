from pathlib import Path


def test_review_round_runs_reader_groups_in_parallel():
    source = Path("app/services/full_novel_pipeline.py").read_text(encoding="utf-8")

    for marker in [
        "reader_trace_task = asyncio.create_task",
        "dialogue_reader_task = asyncio.create_task",
        "natural_reader_task = asyncio.create_task",
        "artifice_reader_task = asyncio.create_task",
        "cadence_reader_task = asyncio.create_task",
        "specialist_results = await asyncio.gather",
    ]:
        assert marker in source

    assert source.count("await asyncio.gather(") >= 2


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
        "[model-route] FALLBACK",
    ]:
        assert marker in ai_service
