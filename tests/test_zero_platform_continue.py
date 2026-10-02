from scripts.run_zero_platform_continue import (
    extract_continuation_titles,
    parse_source_chapters,
)


def test_parse_source_chapters_keeps_published_positions() -> None:
    source = """# 第 4 章 A

正文A。

# 第 5 章 B

正文B。

# 第 6 章 C

正文C。
"""
    chapters = parse_source_chapters(source)
    assert list(sorted(chapters)) == [4, 5, 6]
    assert chapters[4]["title"] == "A"
    assert chapters[6]["content"] == "正文C。"


def test_extract_continuation_titles_requires_seven_and_eight() -> None:
    outline = """[CHAPTER 07] 标题：回声
内容

[CHAPTER 08] 标题：零点以后
内容
"""
    assert extract_continuation_titles(outline) == {
        7: "回声",
        8: "零点以后",
    }
