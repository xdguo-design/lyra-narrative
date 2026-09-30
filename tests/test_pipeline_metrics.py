from app.services.pipeline_metrics import _percentile, classify_scenario


def test_classify_pipeline_scenarios():
    assert classify_scenario(
        length_repair_triggered=False,
        initial_failed_reviewer_count=0,
        review_retry_count=0,
        retry_recovered_count=0,
        retry_failed_count=0,
    ) == "normal"

    assert classify_scenario(
        length_repair_triggered=False,
        initial_failed_reviewer_count=1,
        review_retry_count=1,
        retry_recovered_count=1,
        retry_failed_count=0,
    ) == "single_reviewer_retry"

    assert classify_scenario(
        length_repair_triggered=True,
        initial_failed_reviewer_count=0,
        review_retry_count=0,
        retry_recovered_count=0,
        retry_failed_count=0,
    ) == "length_repair"


def test_nearest_rank_percentiles():
    values = list(range(1, 101))
    assert _percentile(values, 50) == 50
    assert _percentile(values, 95) == 95
    assert _percentile([], 95) == 0


def test_init_db_creates_pipeline_latency_schema(tmp_path, monkeypatch):
    from app.db import connect, init_db

    monkeypatch.setenv("NOVEL_DB_PATH", str(tmp_path / "metrics.db"))
    monkeypatch.setenv("NOVEL_SEED_DEMO", "0")
    init_db()

    with connect() as conn:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        metric_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(agent_run_metrics)").fetchall()
        }

    assert "chapter_pipeline_runs" in tables
    assert "chapter_pipeline_events" in tables
    assert {
        "started_at_ms",
        "finished_at_ms",
        "input_chars",
        "output_chars",
        "context_tier",
    } <= metric_columns
