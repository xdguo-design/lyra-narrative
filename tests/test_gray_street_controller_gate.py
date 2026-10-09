from scripts.gate_gray_street_controller_candidate import chapter_rules, scoped_canon


def test_later_chapter_rules_do_not_use_chapter_one_lock():
    rules = chapter_rules(2, "遗产")
    assert "第二节《遗产》" in rules
    assert "第一节《怀表》冻结目标" not in rules


def test_scoped_canon_trims_chapter_one_execution_lock_for_later_chapters():
    canon = "全局设定\n## 第一节《怀表》冻结目标\n第一节专属内容\n"
    assert scoped_canon(canon, 2) == "全局设定\n"
    assert scoped_canon(canon, 1) == canon


def test_post_eleven_chapter_uses_controller_blueprint_fallback():
    from scripts.run_gray_street_chapter import extract_plan

    plan = extract_plan(12)
    assert "遵循请求指定的控制器蓝图" in plan
    assert "第6节起共同硬规则" in plan
    assert "埃文·格雷" in plan


def test_existing_chapter_goals_remain_unchanged():
    from scripts.run_gray_street_chapter import extract_plan

    assert "弯钩" in extract_plan(11)


def test_short_gate_requires_grounded_temporal_conflicts():
    from pathlib import Path

    source = Path("scripts/run_gray_street_chapter.py").read_text(encoding="utf-8")
    assert "跨章时间缺口的判断" in source
    assert "不因“前文未写”而自动构成硬伤" in source
    assert "同一时刻互斥工作" in source
    assert "任何确切问题" not in source
