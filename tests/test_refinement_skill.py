from app.services.default_skills import (
    BUILTIN_REFINEMENT_SKILL_CONTENT,
    BUILTIN_REFINEMENT_SKILL_VERSION,
)


def test_refinement_skill_v2_defines_executable_edit_levels():
    assert BUILTIN_REFINEMENT_SKILL_VERSION == 2

    content = BUILTIN_REFINEMENT_SKILL_CONTENT
    required = [
        "REWRITE_BLOCK",
        "LOCAL_REWRITE",
        "DELETE",
        "POLISH",
        "PASS",
        "阶段 7：修改级别判定",
        "E. 快速判定树",
        "F. Reviewer 必须给出明确处置",
    ]
    for marker in required:
        assert marker in content


def test_refinement_skill_escalates_structural_problems_and_limits_local_edits():
    content = BUILTIN_REFINEMENT_SKILL_CONTENT

    assert "人物行为缺少成立动机" in content
    assert "因果顺序错误" in content
    assert "约三分之一以上内容需要改动" in content
    assert "局部修改会连续牵动后文两句以上" in content
    assert "立即升级为 REWRITE_BLOCK" in content
    assert "删除后事实、动作、情绪和阅读理解均不受影响" in content
    assert "只有段落的事实、因果、人物意图、剧情推进全部成立时" in content


def test_refinement_skill_requires_reviewer_to_justify_rewrite_scope():
    content = BUILTIN_REFINEMENT_SKILL_CONTENT

    assert "为什么当前级别足够或为什么必须升级" in content
    assert "重写时必须保留的事实" in content
    assert "若 Reviewer 无法说明“为什么必须整段重写”" in content
    assert "影响事实、因果或人物意图" in content
    assert "不得降级为 POLISH" in content
