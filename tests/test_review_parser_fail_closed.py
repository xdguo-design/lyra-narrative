from app.services.workflow_service import _parse_review_output


def test_parser_keeps_markdown_bold_rewrite_block_as_blocking():
    output = """**问题标识**：P1-DIALOGUE
**严重性**：High
**处置级别**：REWRITE_BLOCK
**问题类型**：人物一致性
**逐字片段**：“旧句。”
**问题说明**：人物动机与前文冲突。
**建议动作**：重写这一段。
"""
    findings = _parse_review_output(output, "前文。\n“旧句。”\n后文。")
    assert len(findings) == 1
    assert findings[0]["severity"] == "blocking"
    assert "REWRITE_BLOCK" in findings[0]["suggestion"]
    assert findings[0]["excerpt"] == "“旧句。”"


def test_parser_never_downgrades_unbracketed_rewrite_block_to_suggestion():
    output = """**1. 保管规则被抹掉**
严重性：高
处置级别：REWRITE_BLOCK
问题类型：人物动机/权限
问题说明：前文写只能本人取，后文陌生人直接拿走。
建议动作：补合法核验或明确违规代价。
复审结果=PENDING。
"""
    findings = _parse_review_output(output, "")
    assert findings[0]["severity"] == "blocking"
    assert "只能本人取" in findings[0]["summary"]


def test_parser_maps_medium_local_rewrite_to_suggestion():
    output = """问题标识：P2
严重性：Medium
处置级别：LOCAL_REWRITE
问题说明：句子局部不清。
建议动作：局部改写。
"""
    findings = _parse_review_output(output, "")
    assert findings[0]["severity"] == "suggestion"


def test_parser_fallback_fails_closed_if_rewrite_block_is_present():
    output = "Reviewer output drifted badly, but verdict is REWRITE_BLOCK and must not pass."
    findings = _parse_review_output(output, "")
    assert findings[0]["severity"] == "blocking"
