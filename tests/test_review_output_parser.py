from app.services.workflow_service import _parse_review_output


def test_markdown_high_rewrite_block_is_blocking():
    text = """# NARRATIVEOS_REVIEW_V3

**标识**：ISSUE_01
**严重性**：高
**处置级别**：REWRITE_BLOCK
**问题说明**：人物对白像规章宣读。
**逐字片段**：“根据条例……”
**建议动作**：重写整个话轮。
"""
    findings = _parse_review_output(text, "他说：“根据条例……”")
    assert findings
    assert findings[0]["severity"] == "blocking"
    assert findings[0]["excerpt"] == "“根据条例……”"


def test_verdict_fail_is_blocking_even_without_native_severity():
    text = """DIALOGUE_AUTHENTICITY_V1
VERDICT: FAIL

【问题说明】对白整体失真。
【处置级别】LOCAL_REWRITE
【复审结果】FAIL
"""
    findings = _parse_review_output(text, "正文")
    assert findings
    assert findings[0]["severity"] == "blocking"


def test_medium_local_rewrite_remains_suggestion():
    text = """【问题标识】R002
【严重性】中
【处置级别】LOCAL_REWRITE
【问题说明】局部对白偏书面。
【片段】“请您依照相关程序办理。”
"""
    findings = _parse_review_output(text, "他说：“请您依照相关程序办理。”")
    assert findings[0]["severity"] == "suggestion"


def test_low_polish_maps_to_info():
    text = """**严重性**：低
**处置级别**：POLISH
**问题说明**：一个比喻略显用力。
"""
    findings = _parse_review_output(text, "正文")
    assert findings[0]["severity"] == "info"


def test_english_high_maps_to_blocking():
    text = """severity: HIGH
disposition: LOCAL_REWRITE
summary: factual continuity gap
"""
    findings = _parse_review_output(text, "正文")
    assert findings[0]["severity"] == "blocking"
