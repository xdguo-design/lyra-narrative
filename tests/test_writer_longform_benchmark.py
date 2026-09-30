from pathlib import Path


def test_writer_longform_benchmark_targets_real_chapter_length():
    script = Path("scripts/benchmark_writer_profiles.py").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/writer-longform-benchmark.yml").read_text(
        encoding="utf-8"
    )

    for marker in [
        '"AGNES"',
        '"DOTS3"',
        '"SENSENOVA68"',
        '"ATRIA"',
        '"GLM52"',
        '"GLM53FLASH"',
        "硬长度 2850—3250 个中文字符",
        "2700 <= len(text) <= 3400",
        '"短三斗一升"',
        'text.endswith("马二死了。")',
        '"reasoning_effort": "low"',
    ]:
        assert marker in script

    for marker in [
        "Benchmark 3000-char writer candidates",
        "NARRATIVE_PROFILE_GLM53FLASH",
        "NARRATIVE_PROFILE_SENSENOVA68",
        "timeout-minutes: 10",
    ]:
        assert marker in workflow
