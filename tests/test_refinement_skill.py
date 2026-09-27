from app.services.default_skills import (
    BUILTIN_REFINEMENT_SKILL_CONTENT,
    BUILTIN_REFINEMENT_SKILL_VERSION,
)


def test_refinement_skill_v6_defines_executable_edit_levels():
    assert BUILTIN_REFINEMENT_SKILL_VERSION == 6

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


def test_refinement_skill_v6_has_unified_reviewer_output_contract():
    content = BUILTIN_REFINEMENT_SKILL_CONTENT

    required = [
        "阶段 9：Reviewer 统一审核输出格式（NARRATIVEOS_REVIEW_V3）",
        "【审核轮次】INITIAL",
        "【处置级别】REWRITE_BLOCK / LOCAL_REWRITE / DELETE / POLISH / PASS",
        "【问题定位】",
        "【修改边界】",
        "【必须保留的事实】",
        "【禁止新增内容】",
        "【复审要求】",
        "【复审结果】PENDING",
        "【审核轮次】RECHECK",
        "【复审检查】",
        "【复审结果】PASS / FAIL",
        "【再次打回原因】",
    ]
    for marker in required:
        assert marker in content


def test_reviewer_contract_requires_exact_location_boundaries_and_anchors():
    content = BUILTIN_REFINEMENT_SKILL_CONTENT

    assert "逐字复制正文中的连续原文" in content
    assert "为什么 LOCAL_REWRITE 不足" in content
    assert "最小修改范围" in content
    assert "允许联动范围" in content
    assert "不得触碰范围" in content
    assert "只列与当前问题有关的锚点" in content
    assert "禁止散文式、泛化式“建议优化”" in content


def test_reviewer_recheck_closes_or_returns_same_issue():
    content = BUILTIN_REFINEMENT_SKILL_CONTENT

    assert "复审沿用同一标识" in content
    assert "原问题是否消失：PASS / FAIL" in content
    assert "是否产生新的 blocking：YES / NO" in content
    assert "PASS：关闭原问题，不再重复修改" in content
    assert "FAIL：保持原处置级别或升级" in content
    assert "禁止在 PASS 后继续反复重写同一处" in content


def test_refinement_skill_v6_has_reality_and_readability_gate():
    content = BUILTIN_REFINEMENT_SKILL_CONTENT

    required = [
        "阶段 10：自然叙事硬门槛（Reality & Readability Gate）",
        "现实锚点检查",
        "先看见具体物",
        "海堤上的门",
        "朗读检查",
        "人话对白检查",
        "信息负载检查",
        "普通读者第一次阅读即可知道主要人物在哪里、在做什么、面对什么具体东西",
        "不需要替作者脑补关键物理结构",
        "不需要回读才能理解主要句子",
    ]
    for marker in required:
        assert marker in content


def test_refinement_skill_v6_escalates_scene_level_naturalness_failures():
    content = BUILTIN_REFINEMENT_SKILL_CONTENT

    assert "场景中的关键地点、设施、器物或空间关系没有现实锚点" in content
    assert "整体呈现技术报告、项目汇报、AI 摘要式语流" in content
    assert "连续多句如此 → REWRITE_BLOCK" in content
    assert "只缺一个孤立锚点 → LOCAL_REWRITE" in content


def test_refinement_skill_v6_character_humor_and_ending_rules():
    content = BUILTIN_REFINEMENT_SKILL_CONTENT
    for marker in [
        "人物立体化",
        "幽默感",
        "去 AI 收束句",
        "总得",
        "才刚刚开始",
        "优先删除",
        "新动作、新发现、新麻烦、关系变化或具体画面",
    ]:
        assert marker in content
