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
