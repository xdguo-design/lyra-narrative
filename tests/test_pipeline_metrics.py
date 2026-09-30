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
