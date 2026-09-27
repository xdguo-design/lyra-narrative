from app.services.default_skills import (
    BUILTIN_REFINEMENT_SKILL_CONTENT,
    BUILTIN_REFINEMENT_SKILL_VERSION,
)


def test_refinement_skill_v3_defines_executable_edit_levels():
    assert BUILTIN_REFINEMENT_SKILL_VERSION == 3

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


def test_refinement_skill_local_rewrite_template_is_minimal_and_escalates():
    content = BUILTIN_REFINEMENT_SKILL_CONTENT

    required = [
        "模板一：LOCAL_REWRITE 局部修改执行模板",
        "【原文范围】",
        "【必须保留】",
        "【禁止新增】",
        "【修改目标】",
        "【影响范围】",
        "只修改导致问题的最小单元",
        "前一句—修改句—后一句",
        "立即停止并升级 REWRITE_BLOCK",
        "【连锁影响】无 / 有",
        "【是否需要升级】否 / 是",
    ]
    for marker in required:
        assert marker in content


def test_refinement_skill_rewrite_block_template_rebuilds_scene_from_anchors():
    content = BUILTIN_REFINEMENT_SKILL_CONTENT

    required = [
        "模板二：REWRITE_BLOCK 整段/整场打回重写执行模板",
        "【为什么不能局部修】",
        "【本场必须完成的叙事任务】",
        "【必须保留的事实锚点】",
        "【允许调整】",
        "【禁止新增】",
        "进入 → 摩擦 → 选择/行动 → 信息或代价 → 状态变化 → 退出",
        "不看原段句序",
        "【重写后的正文】",
        "【重写后状态变化】",
        "【自检结果】",
        "【是否再次打回】否 / 是",
    ]
    for marker in required:
        assert marker in content


def test_refinement_skill_templates_separate_reviewer_and_revision_responsibility():
    content = BUILTIN_REFINEMENT_SKILL_CONTENT

    assert "Reviewer 只负责判级、定位、说明原因和给出锚点" in content
    assert "Revision Agent 负责执行修改" in content
    assert "LOCAL_REWRITE 不输出整章重写" in content
    assert "REWRITE_BLOCK 不允许只替换几个词后宣称完成" in content
    assert "Reviewer 必须再次审核修改结果" in content
    assert "多个相邻 LOCAL_REWRITE" in content
    assert "应合并并升级为 REWRITE_BLOCK" in content
