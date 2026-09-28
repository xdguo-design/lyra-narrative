from pathlib import Path


BASE = Path("books/yamen-proficiency/manual-v6-run-001")


def test_reader_three_perspective_gate_is_frozen():
    protocol = Path("docs/reader-three-perspective-calibration.md").read_text(encoding="utf-8")
    profile = (BASE / "reader-calibration-round-001/profile.md").read_text(encoding="utf-8")
    for marker in [
        "Reader A — 首读理解",
        "Reader B — 人物 / 关系",
        "Reader C — 阅读动力",
        "Reader D — 自然首读 / 气质",
        "NATURALNESS_GAP",
        "TONE_GAP",
        "AUTHOR_JOKE_GAP",
        "INTENTIONAL_UNKNOWN",
        "READER_GAP",
        "AMBIGUOUS_GAP",
    ]:
        assert marker in protocol
    assert "PASS / STABLE" in profile
    assert "RC001" in profile


def test_three_chapter_mini_arc_passes_long_form_gate():
    review = (BASE / "mini-arc-training-001/recheck.md").read_text(encoding="utf-8")
    for marker in [
        "债务谈判",
        "工作/身份",
        "调查/行动",
        "LONG002",
        "Gate 6",
        "PASS / STABLE",
    ]:
        assert marker in review


def test_genre_promise_matrix_has_non_investigation_guardrails():
    matrix = (BASE / "genre-promise-matrix.md").read_text(encoding="utf-8")
    required = [
        "底层县衙生存",
        "钱 / 债 / 家庭",
        "熟练度真实成长",
        "身份 / 职业晋升",
        "县城生活与社会层级",
        "案件与危险",
        "每 5—8 章",
        "GP001｜案件吞书",
        "GP008｜爽点无成本",
        "PASS / FROZEN v1",
    ]
    for marker in required:
        assert marker in matrix


def test_rewrite_freeze_pack_requires_all_fiction_gates():
    freeze = (BASE / "rewrite-freeze-pack-v1.md").read_text(encoding="utf-8")
    status = (BASE / "pre-rewrite-status.md").read_text(encoding="utf-8")
    for marker in [
        "Writer：PASS",
        "Editor：PASS",
        "Reader Calibration：PASS",
        "Failure Corpus：PASS",
        "Character Stress：PASS",
        "Three-Chapter Mini-Arc：PASS",
        "Genre Promise Matrix：PASS",
    ]:
        assert marker in freeze
    assert "小说改进 / 训练门槛" in status
    assert "**ALL PASS**" in status


def test_failure_corpus_freezes_unnatural_but_understandable_case():
    corpus = Path("docs/writer-failure-corpus.md").read_text(encoding="utf-8")
    required = [
        "F016｜能懂但第一眼就是怪",
        "先感觉到的不是头疼，是屁股",
        "NATURALNESS_GAP",
        "TONE_GAP",
        "对比两端是在比同一种东西吗",
    ]
    for marker in required:
        assert marker in corpus


def test_reader_naturalness_regression_corpus_has_fail_and_pass_boundaries():
    corpus = Path("docs/reader-naturalness-regression-corpus.md").read_text(encoding="utf-8")
    fail_markers = [
        "RN001",
        "RN003",
        "RN005",
        "RN007",
        "RN012",
        "NATURALNESS_GAP",
        "QUANTITY_GAP",
        "MICRO_CONTINUITY_GAP",
        "AUTHOR_EFFECT_GAP",
    ]
    pass_markers = [
        "RP001",
        "RP002",
        "RP003",
        "RP004",
        "CHARACTER_ROUGHNESS",
        "不得误杀",
    ]
    for marker in fail_markers + pass_markers:
        assert marker in corpus


def test_rewrite_workflow_has_no_permanent_final_human_stage():
    freeze = (BASE / "rewrite-freeze-pack-v1.md").read_text(encoding="utf-8")
    status = (BASE / "pre-rewrite-status.md").read_text(encoding="utf-8")

    assert "Reader D Natural First-Read" in freeze
    assert "人工阅读不是永久流水线工位" in freeze
    assert "Final Human Read" not in freeze
    assert "Final Human Recheck" not in freeze
    assert "不新增永久人工工序" in status


def test_dialogue_authenticity_failure_and_pass_corpus():
    corpus = Path("docs/dialogue-authenticity-regression-corpus.md").read_text(encoding="utf-8")
    fail_markers = [
        "DA001",
        "DA002",
        "DA003",
        "DA004",
        "DA005",
        "DIALOGUE_FUNCTIONAL_GAP",
        "DIALOGUE_VOICE_GAP",
        "RELATIONSHIP_VOICE_GAP",
        "DIALOGUE_STATELESS_GAP",
    ]
    pass_markers = [
        "DP001",
        "DP002",
        "DP003",
        "DP004",
        "DP005",
        "不允许通过强行增加口头禅",
    ]
    for marker in fail_markers + pass_markers:
        assert marker in corpus


def test_failure_corpus_freezes_functional_dialogue_pattern():
    corpus = Path("docs/writer-failure-corpus.md").read_text(encoding="utf-8")
    for marker in [
        "F017｜对白只有功能，没有人物",
        "去掉人物名字，我还能分清谁是谁吗",
        "把两个人台词互换",
        "DIALOGUE_VOICE_GAP",
        "DIALOGUE_FUNCTIONAL_GAP",
    ]:
        assert marker in corpus


def test_skill_evolution_protocol_is_formalized():
    protocol = Path("docs/skill-evolution-protocol.md").read_text(encoding="utf-8")
    required = [
        "SKILL_EVOLUTION_CASE_V1",
        "先归因，不先改正文",
        "泛化门槛",
        "正例 / 反例双向回归",
        "Skill 版本升级",
        "CANDIDATE",
        "CALIBRATING",
        "STABLE",
        "TRANSFERABLE",
        "Remove Human Crutch",
        "Case SE-001",
        "Case SE-002",
        "Definition of Done",
    ]
    for marker in required:
        assert marker in protocol


def test_embodied_dialogue_regression_corpus():
    corpus = Path("docs/embodied-dialogue-regression-corpus.md").read_text(encoding="utf-8")
    for marker in [
        "ED001",
        "ED006",
        "EP001",
        "EP005",
        "EMBODIED_DIALOGUE_GAP",
        "GENERIC_ACTION_GAP",
        "不允许为了通过 Gate 在每句对白后机械添加动作",
    ]:
        assert marker in corpus


def test_failure_corpus_freezes_embodied_and_human_interaction_gaps():
    corpus = Path("docs/writer-failure-corpus.md").read_text(encoding="utf-8")
    required = [
        "F018｜人物只有嘴，没有身体",
        "F019｜人物过度理性，像在解释自己",
        "F020｜人物没有自我形象与面子",
        "F021｜熟人没有关系记忆",
        "F022｜话轮过度整齐",
        "F023｜情绪没有余波",
        "F024｜人物感知同质化",
        "EMBODIED_DIALOGUE_GAP",
        "OVER_RATIONAL_DIALOGUE_GAP",
        "SELF_PRESENTATION_GAP",
        "RELATIONSHIP_MEMORY_GAP",
        "TURN_TAKING_SYMMETRY_GAP",
        "EMOTIONAL_RESIDUE_GAP",
        "PERCEPTION_SIGNATURE_GAP",
    ]
    for marker in required:
        assert marker in corpus


def test_human_interaction_regression_corpus_has_fail_and_pass_boundaries():
    corpus = Path("docs/human-interaction-regression-corpus.md").read_text(encoding="utf-8")
    for marker in [
        "HI001",
        "HI006",
        "HP001",
        "HP006",
        "OVER_RATIONAL_DIALOGUE_GAP",
        "RELATIONSHIP_MEMORY_GAP",
        "TURN_TAKING_SYMMETRY_GAP",
        "EMOTIONAL_RESIDUE_GAP",
        "PERCEPTION_SIGNATURE_GAP",
        "False-positive boundaries",
    ]:
        assert marker in corpus


def test_core_character_cards_have_voice_body_self_image_memory_and_perception():
    characters = (BASE / "characters.md").read_text(encoding="utf-8")
    for name in ["陈安", "赵六", "周虎", "刘旺", "陈小满", "柳氏", "孙成", "刘三爷"]:
        section = characters.split(f"## {name}", 1)[1]
        if "\n## " in section:
            section = section.split("\n## ", 1)[0]
        for marker in [
            "语言指纹：",
            "非语言指纹：",
            "自我形象：",
            "关系记忆：",
            "感知指纹：",
        ]:
            assert marker in section


def test_skill_evolution_protocol_tracks_embodied_and_deeper_interaction_cases():
    protocol = Path("docs/skill-evolution-protocol.md").read_text(encoding="utf-8")
    for marker in [
        "Case SE-003｜人物只有嘴，没有身体",
        "Case SE-004｜更深层的机器人式互动",
        "自我形象",
        "关系记忆",
        "话轮不对称",
        "情绪残留",
        "感知差异",
    ]:
        assert marker in protocol


def test_revision_integrity_failure_and_pass_corpus():
    corpus = Path("docs/revision-integrity-regression-corpus.md").read_text(encoding="utf-8")
    for marker in [
        "RI001",
        "RI005",
        "RIP001",
        "RIP004",
        "SCENE_FUNCTION_DRIFT",
        "LOCAL_REWRITE_SEAM_GAP",
        "Blind Reader 不承担",
    ]:
        assert marker in corpus


def test_failure_corpus_freezes_scene_function_and_seam_gaps():
    corpus = Path("docs/writer-failure-corpus.md").read_text(encoding="utf-8")
    for marker in [
        "F025｜局部重写把场景功能写丢",
        "F026｜局部重写接口裂缝",
        "SCENE_FUNCTION_DRIFT",
        "LOCAL_REWRITE_SEAM_GAP",
        "Narrative Function Contract",
        "Seam Check",
    ]:
        assert marker in corpus


def test_skill_evolution_protocol_tracks_revision_integrity_case():
    protocol = Path("docs/skill-evolution-protocol.md").read_text(encoding="utf-8")
    for marker in [
        "Case SE-005｜局部重写功能漂移与接口裂缝",
        "Revision Integrity Reviewer",
        "F025 / F026",
        "Revision Integrity Regression Corpus",
    ]:
        assert marker in protocol


def test_author_artifice_regression_corpus_has_fail_and_pass_boundaries():
    corpus = Path("docs/author-artifice-regression-corpus.md").read_text(encoding="utf-8")
    fail_markers = [
        "AF001",
        "AF012",
        "INTERPRETATION_ECHO_GAP",
        "PREMISE_CHECKLIST_GAP",
        "DIALOGUE_LOOP_GAP",
        "VOICE_OVERPERFORMANCE_GAP",
        "FINGERPRINT_OVERUSE_GAP",
        "BODY_STATE_TICKER_GAP",
        "CLUE_LADDER_GAP",
        "CLUE_DENSITY_GAP",
        "CONVENIENT_MEMORY_RECALL_GAP",
        "SYSTEM_CONFIRMATION_LEAK",
        "COINCIDENCE_CLUSTER_GAP",
        "EVIDENCE_DISPLAY_STAGING",
    ]
    pass_markers = [
        "AP001",
        "AP010",
        "False-positive boundaries",
        "不允许为了降低作者痕迹机械增加废话",
    ]
    for marker in fail_markers + pass_markers:
        assert marker in corpus


def test_failure_corpus_freezes_author_artifice_and_clue_flow_modes():
    corpus = Path("docs/writer-failure-corpus.md").read_text(encoding="utf-8")
    required = [
        "F027｜动作说完，旁白再解释一遍",
        "F028｜开篇像在勾人物设定卡",
        "F029｜人物关系变化已经完成，对话还在原地绕",
        "F030｜人物声音过度表演",
        "F031｜人物指纹打卡",
        "F032｜身体状态播报器",
        "F033｜线索阶梯",
        "F034｜线索密度过高",
        "F035｜剧情缺什么，记忆就刚好补什么",
        "F036｜系统通过奖励时机认证答案",
        "F037｜多个“正好”叠成巧合集群",
        "F038｜嫌疑人物变成证据展示台",
    ]
    for marker in required:
        assert marker in corpus


def test_skill_evolution_protocol_tracks_author_artifice_case():
    protocol = Path("docs/skill-evolution-protocol.md").read_text(encoding="utf-8")
    required = [
        "Case SE-006｜作者施工痕迹与线索人工感",
        "Writer v11",
        "Reader Skill v6",
        "Refinement v9",
        "blind-artifice-reader",
        "F027—F038",
        "Author Artifice & Clue Flow Regression Corpus",
        "EVIDENCE_DISPLAY_STAGING",
    ]
    for marker in required:
        assert marker in protocol
