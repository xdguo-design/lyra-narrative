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
