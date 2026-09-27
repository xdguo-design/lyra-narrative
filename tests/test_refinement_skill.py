from pathlib import Path

from app.services.default_skills import (
    BUILTIN_READER_REVIEW_SKILL_CONTENT,
    BUILTIN_READER_REVIEW_SKILL_VERSION,
    BUILTIN_REFINEMENT_SKILL_CONTENT,
    BUILTIN_REFINEMENT_SKILL_VERSION,
    BUILTIN_WRITING_SKILL_CONTENT,
    BUILTIN_WRITING_SKILL_VERSION,
)


def test_refinement_skill_v7_defines_executable_edit_levels():
    assert BUILTIN_REFINEMENT_SKILL_VERSION == 7

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


def test_refinement_skill_v7_has_unified_reviewer_output_contract():
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


def test_refinement_skill_v7_has_reality_and_readability_gate():
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


def test_refinement_skill_v7_escalates_scene_level_naturalness_failures():
    content = BUILTIN_REFINEMENT_SKILL_CONTENT

    assert "场景中的关键地点、设施、器物或空间关系没有现实锚点" in content
    assert "整体呈现技术报告、项目汇报、AI 摘要式语流" in content
    assert "连续多句如此 → REWRITE_BLOCK" in content
    assert "只缺一个孤立锚点 → LOCAL_REWRITE" in content


def test_refinement_skill_v7_character_humor_and_ending_rules():
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


def test_full_pipeline_binds_dialogue_to_character_behavior_cards():
    source = Path("app/services/full_novel_pipeline.py").read_text(encoding="utf-8")
    required = [
        "受压时第一反应",
        "常用撒谎/回避方式",
        "面对上级/同级/弱者时的不同态度",
        "什么证据出现前绝不会承认",
        "什么情况下才会改口",
        "人物回答必须由性格与利益共同决定",
        "不能因为作者需要信息就突然老实",
        "谨慎/怕事的人是否过早坦白",
        "为了让剧情顺利推进而让人物突然变老实",
    ]
    for marker in required:
        assert marker in source


def test_writing_skill_v9_adds_human_interaction_complexity():
    assert BUILTIN_WRITING_SKILL_VERSION == 9
    content = BUILTIN_WRITING_SKILL_CONTENT
    required = [
        "作家能力：选材、视角与叙事取舍",
        "描写必须经过人物视角过滤",
        "细节必须有层级",
        "该快的地方要敢于压缩",
        "该慢的地方要敢于展开",
        "潜台词、人物声音与句群",
        "对话不是把信息从 A 搬到 B",
        "章节与长篇变化",
        "连续两章不得机械复用同一种章末钩子",
        "如果把人物名字替换掉",
        "自然首读硬门槛（Human First-Read）",
        "意思能懂但第一眼发怪",
        "对比/转折两端是否处于同一语义层级",
        "开篇前三段必须做类型第一印象检查",
        "TONE_GAP",
        "微观自然度与连续性",
        "数量关系检查",
        "微连续性检查",
        "作者造句感检查",
        "最终逐句问",
        "对话真实性硬门槛（Dialogue Authenticity Gate）",
        "去名字测试",
        "换人测试",
        "DIALOGUE_VOICE_GAP",
        "RELATIONSHIP_VOICE_GAP",
        "带身体的对白（Embodied Dialogue）",
        "真人交互复杂度（Human Interaction Complexity）",
        "非语言指纹",
        "自我形象",
        "关系记忆",
        "话轮过度对称",
        "情绪要有余波",
        "PERCEPTION_SIGNATURE_GAP",
    ]
    for marker in required:
        assert marker in content


def test_refinement_skill_v7_adds_aesthetic_editing_gate():
    content = BUILTIN_REFINEMENT_SKILL_CONTENT
    required = [
        "阶段 11：编辑审美门槛",
        "准确 > 华丽",
        "具体 > 抽象",
        "克制 > 说透",
        "人物特有 > 通用漂亮",
        "层次 > 平均用力",
        "余味 > 点题",
        "禁止“过度编辑”",
        "人物声音没有被编辑同质化",
    ]
    for marker in required:
        assert marker in content


def test_full_pipeline_has_scene_director_aesthetic_editor_and_reviewer():
    source = Path("app/services/full_novel_pipeline.py").read_text(encoding="utf-8")
    required = [
        'role="scene-director"',
        'stage="scene-blueprint"',
        'kind="scene-blueprint"',
        'role="aesthetic-editor"',
        'stage="aesthetic-edit"',
        '"aesthetic-reviewer"',
        '"aesthetic"',
        "根据八个独立 Reviewer",
        "主细节要突出",
        "人物声音被编辑同质化",
    ]
    for marker in required:
        assert marker in source


def test_full_pipeline_has_blind_reader_and_reader_gap_reviewer():
    source = Path("app/services/full_novel_pipeline.py").read_text(encoding="utf-8")
    required = [
        'role="blind-reader"',
        'stage=f"reader-trace-r{round_no}"',
        '"reader-gap-reviewer"',
        '"reader"',
        "READER_TRACE_V1",
        "semantic-gap",
        "suspense-gap",
        "不能用‘读者多读两遍就懂’作为通过理由",
    ]
    for marker in required:
        assert marker in source

    start = source.index('role="blind-reader"')
    specs = source.index("specs = [", start)
    blind_block = source[start:specs]
    assert "context," not in blind_block


def test_formal_reader_gate_enforces_unknown_boundary_labels():
    source = Path("app/services/full_novel_pipeline.py").read_text(encoding="utf-8")
    required = [
        "INTENTIONAL_UNKNOWN",
        "READER_GAP",
        "AMBIGUOUS_GAP",
        "严格按 Reader Gate v3 判定",
        "不能用‘读者多读两遍就懂’作为通过理由",
    ]
    for marker in required:
        assert marker in source


def test_reader_review_skill_v4_learns_naturalness_dialogue_and_human_interaction():
    assert BUILTIN_READER_REVIEW_SKILL_VERSION == 4
    content = BUILTIN_READER_REVIEW_SKILL_CONTENT
    required = [
        "Reader D 固定检查维度",
        "D01 语义平行",
        "D04 数量关系",
        "D06 微连续性",
        "D07 修饰冗余",
        "D09 作者造句感",
        "D10 默认节奏器",
        "D15 全文停顿测试",
        "男人左脚穿着一双旧布鞋",
        "赵六嘴里的第二颗豆子",
        "Skill 自升级协议",
        "先记录原句和漏检原因，不先改正文",
        "人工阅读是训练信号，不是永久流水线工位",
        "B01 去名字测试",
        "B02 换人测试",
        "DIALOGUE_AUTHENTICITY_V1",
        "DIALOGUE_FUNCTIONAL_GAP",
        "DIALOGUE_STATELESS_GAP",
        "B13 身体在场",
        "B18 空间权力",
        "B19 过度理性",
        "B26 场景残余",
        "EMBODIED_DIALOGUE_GAP",
        "GENERIC_ACTION_GAP",
        "OVER_RATIONAL_DIALOGUE_GAP",
        "SELF_PRESENTATION_GAP",
        "RELATIONSHIP_MEMORY_GAP",
        "TURN_TAKING_SYMMETRY_GAP",
        "EMOTIONAL_RESIDUE_GAP",
        "PERCEPTION_SIGNATURE_GAP",
    ]
    for marker in required:
        assert marker in content


def test_full_pipeline_folds_human_read_into_blind_reader_d():
    source = Path("app/services/full_novel_pipeline.py").read_text(encoding="utf-8")
    required = [
        'role="blind-natural-reader"',
        'stage=f"reader-natural-r{round_no}"',
        'role="blind-dialogue-reader"',
        'stage=f"reader-dialogue-r{round_no}"',
        "NATURAL_FIRST_READ_V2",
        "DIALOGUE_AUTHENTICITY_V1",
        "EMBODIED_DIALOGUE_GAP",
        "OVER_RATIONAL_DIALOGUE_GAP",
        "RELATIONSHIP_MEMORY_GAP",
        "EMOTIONAL_RESIDUE_GAP",
        "natural_reader_failed",
        "dialogue_reader_failed",
        "has_blocking = natural_reader_failed or dialogue_reader_failed",
        "reader-naturalness",
        '"reviewed" if final_blocking else "awaiting_approval"',
    ]
    for marker in required:
        assert marker in source

    forbidden = [
        'role="final-human-reader"',
        'stage="final-human-read"',
        'stage="final-human-fix"',
        'stage="final-human-recheck"',
    ]
    for marker in forbidden:
        assert marker not in source
