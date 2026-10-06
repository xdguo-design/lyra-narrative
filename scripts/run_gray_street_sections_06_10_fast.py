from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

from app.db import connect, init_db
from app.services.book_pipeline import _create_task
from app.services.workflow_service import _parse_review_output, _run_step, _task_context

OUTPUT_DIR = Path("artifacts/gray-street-sections-06-10-fast")
CONTENT_ROOT = Path(os.getenv("GRAY_STREET_CONTENT_ROOT", "content-repo"))
LOCKED_SOURCE = CONTENT_ROOT / "novels/gray-street/versions/sections-01-05-platform-locked.md"
FALLBACK_SOURCE = CONTENT_ROOT / "novels/gray-street/versions/sections-01-05-reader-input-v1.md"
BRIEF_PATH = CONTENT_ROOT / "novels/gray-street/plans/sections-06-10-brief.md"
CANON_PATH = CONTENT_ROOT / "novels/gray-street/bible/project-canon.md"

REVIEW_FORMAT = """NARRATIVEOS_REVIEW_V3
没有问题只输出 NO_ISSUE。
每个问题必须包含：
严重性：High / Medium / Low
处置级别：REWRITE_BLOCK / LOCAL_REWRITE / POLISH / PASS
问题定位：
逐字片段：
问题说明：
修改边界：
必须保留事实：
执行目标：
建议动作：
复审结果=PENDING
多个问题用单独一行 --- 分隔。"""


def _section5(text: str) -> str:
    match = re.search(r"^# 第五节[　 ]+.+?$", text, re.MULTILINE)
    if not match:
        raise RuntimeError("section 5 not found")
    return text[match.end():].strip()


def _create_project(source_text: str, canon: str, brief: str) -> int:
    with connect() as conn:
        row = conn.execute(
            "INSERT INTO projects(title,description,genre,status) VALUES(?,?,?,?)",
            ("灰街", "NarrativeOS fast batch: sections 6-10", "悬疑 / 怪谈", "draft"),
        )
        project_id = int(row.lastrowid)
        memories = [
            ("canon", "锁定Canon", canon),
            ("outline", "第6-10节硬约束", brief),
            (
                "continuity",
                "前五节交接",
                (
                    "第5节结束：银牌已交给米拉；怀表第一笔清空；SV-7极淡再现。"
                    "银牌仍存在遗产/核验/所有权后果。汤普森始终是警官，不是事务所职员。"
                    "红发女人此前已被费恩描述为年轻、红发、戴手套，并在十三号仓二楼窗后出现。"
                ),
            ),
        ]
        for kind, title, value in memories:
            m = conn.execute(
                "INSERT INTO memories(project_id,kind,title,content,source_type,source_ref,confirmed) VALUES(?,?,?,?,?,?,1)",
                (project_id, kind, title, value, "manual", f"gray-fast:{title}"),
            )
            conn.execute(
                "INSERT INTO memory_versions(memory_id,version,kind,title,content,confirmed,note) VALUES(?,?,?,?,?,?,?)",
                (m.lastrowid, 1, kind, title, value, 1, "Gray Street fast batch"),
            )

        chars = [
            ("埃文·格雷", "主角；遗产清算事务所职员", "理性、重证据和手续；不是警察。"),
            ("米拉·阿尔瓦", "钟表铺经营者；七码头资产处旧成员", "掌握部分历史但不讲完整规则。"),
            ("汤普森", "警官", "跨机构调查者；不负责事务所账务。"),
            ("红发女人", "身份未知；钥匙领取者", "红发、戴手套；已在前文出现，不是新空降角色。"),
        ]
        for name, role, profile in chars:
            conn.execute(
                "INSERT INTO characters(project_id,name,role,profile,tags) VALUES(?,?,?,?,?)",
                (project_id, name, role, profile, "[]"),
            )
    return project_id


def _compact_findings(outputs: list[str], draft: str, limit: int = 14000) -> str:
    rows: list[str] = []
    for idx, output in enumerate(outputs, start=1):
        try:
            findings = _parse_review_output(output, draft)
        except (TypeError, ValueError):
            findings = []
        for f in findings:
            if f.get("severity") == "info":
                continue
            row = [f"[{idx}] {str(f.get('severity') or '').upper()} {str(f.get('summary') or '').strip()}"]
            excerpt = str(f.get("excerpt") or "").strip()
            suggestion = str(f.get("suggestion") or "").strip()
            if excerpt:
                row.append("原文：" + excerpt[:600])
            if suggestion:
                row.append("动作：" + suggestion[:900])
            rows.append("\n".join(row))
    return ("\n\n".join(rows) or "无需要修改的问题。")[:limit]


async def _review(task_id: int, draft: str, kind: str, role: str, focus: str) -> str:
    result = await _run_step(
        task_id=task_id,
        role=role,
        stage=f"gray-fast-{kind}",
        mode="check",
        content=draft,
        instruction=focus + "\n\n" + REVIEW_FORMAT,
    )
    return result.content



def _extract_outline_section(outline: str, number: int) -> str:
    cn = {6: "六", 7: "七", 8: "八", 9: "九", 10: "十"}[number]
    next_cn = {6: "七", 7: "八", 8: "九", 9: "十", 10: None}[number]
    start_match = re.search(
        rf"(?m)^#{1,3}\s*第{cn}节.*$|^第{cn}节.*$",
        outline,
    )
    if not start_match:
        return outline
    start = start_match.start()
    if next_cn is None:
        return outline[start:].strip()
    next_match = re.search(
        rf"(?m)^#{1,3}\s*第{next_cn}节.*$|^第{next_cn}节.*$",
        outline[start_match.end():],
    )
    if not next_match:
        return outline[start:].strip()
    end = start_match.end() + next_match.start()
    return outline[start:end].strip()


def _section_body_length(text: str) -> int:
    body = re.sub(r"(?m)^#\s*第[六七八九十]节[^\n]*\n?", "", text, count=1)
    return len(body.strip())


async def _write_one_section(
    *,
    task_id: int,
    number: int,
    outline: str,
    brief: str,
    context: str,
) -> str:
    cn = {6: "六", 7: "七", 8: "八", 9: "九", 10: "十"}[number]
    section_outline = _extract_outline_section(outline, number)
    result = await _run_step(
        task_id=task_id,
        role="writer",
        stage=f"gray-fast-draft-{number}",
        mode="continue",
        content=section_outline,
        instruction=(
            f"只写《灰街》第{cn}节完整正文。不要写其他节。\n\n"
            + context[-10000:]
            + "\n\n【本节大纲】\n"
            + section_outline
            + "\n\n【全局续写约束】\n"
            + brief[-8000:]
            + f"""
\n硬要求：
- 正文目标 2500—3800 中文字符；少于2200字符视为未完成，不允许写成梗概；
- 必须有完整场景弧：开场现实任务 → 阻碍升级 → 人物选择/关系或证据变化 → 章末状态变化；
- 埃文始终是主要视角；
- 汤普森始终是警官，不是事务所职员或埃文上级；
- 红发女人是前文已出现的人，不是新角色空降；
- 怀表不能当万能导航器；警方信息必须有合法来源；
- 完整段落、自然长短句，不要大量一行一句和台词墙；
- 只输出标题与正文，标题格式：# 第{cn}节　<标题>。
"""
        ),
    )
    text = result.content.strip()
    if _section_body_length(text) >= 2200:
        return text

    # One targeted expansion retry for under-length prose. This keeps the
    # five-section benchmark honest without rerunning the entire pipeline.
    expanded = await _run_step(
        task_id=task_id,
        role="writer",
        stage=f"gray-fast-expand-{number}",
        mode="expand",
        content=text,
        instruction=(
            f"当前第{cn}节只有约{_section_body_length(text)}字符，属于未完成短章。"
            "在不改变事件顺序、Canon、线索来源和章末状态的前提下扩成完整小说正文，"
            "补足现场、动作、人物犹豫、潜台词与必要过渡，不加新人物/新规则/新巧合。"
            "目标2500—3800中文字符，至少2200字符。保持完整段落。只输出本节完整正文。"
        ),
    )
    return expanded.content.strip()


def _validate_five_sections(text: str) -> dict[int, int]:
    lengths: dict[int, int] = {}
    cn_to_num = {"六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    pattern = re.compile(r"(?m)^# 第([六七八九十])节[^\n]*$")
    matches = list(pattern.finditer(text))
    for idx, match in enumerate(matches):
        number = cn_to_num[match.group(1)]
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        lengths[number] = len(text[match.end():end].strip())
    return lengths


async def main() -> int:
    init_db()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    source_path = LOCKED_SOURCE if LOCKED_SOURCE.exists() else FALLBACK_SOURCE
    if not source_path.exists():
        raise RuntimeError("sections 1-5 source missing")

    source_text = source_path.read_text(encoding="utf-8")
    canon = CANON_PATH.read_text(encoding="utf-8")
    brief = BRIEF_PATH.read_text(encoding="utf-8")
    project_id = _create_project(source_text, canon, brief)

    task_id = _create_task(
        project_id=project_id,
        chapter_id=None,
        goal="一次生成并修订《灰街》第6-10节连续正文",
        instruction="快速批处理，但必须遵守NarrativeOS Skill、Canon和多Reader Gate。",
    )
    context = _task_context(task_id, project_id)

    outline = await _run_step(
        task_id=task_id,
        role="plot-planner",
        stage="gray-fast-outline",
        mode="continue",
        content=_section5(source_text),
        instruction=(
            context
            + "\n\n【硬约束】\n"
            + brief
            + "\n\n只输出第6-10节执行大纲。每节给：标题、现实目标、阻碍、场景、线索来源、人物选择、章末状态变化。"
        ),
    )

    section_drafts = await asyncio.gather(
        *[
            _write_one_section(
                task_id=task_id,
                number=number,
                outline=outline.content,
                brief=brief,
                context=context,
            )
            for number in (6, 7, 8, 9, 10)
        ]
    )
    draft = "\n\n".join(section.strip() for section in section_drafts).strip()
    draft_lengths = _validate_five_sections(draft)
    if set(draft_lengths) != {6, 7, 8, 9, 10}:
        raise RuntimeError(f"writer did not return all five sections: {draft_lengths}")
    if any(length < 2200 for length in draft_lengths.values()):
        raise RuntimeError(f"one or more sections remain under-length: {draft_lengths}")

    reviews = await asyncio.gather(
        _review(
            task_id,
            draft,
            "continuity",
            "continuity-plot-reviewer",
            """只审第6-10节的连续性、实体状态、权限、线索来源和前五节接缝。
重点检查：汤普森机构身份、银牌现实后果、钥匙保管链、红发女人既有伏笔、费恩死亡信息权限、七号箱来源。
未知超自然机制不是错误，已观测事实冲突才是错误。""",
        ),
        _review(
            task_id,
            draft,
            "ordinary",
            "blind-reader",
            """你是普通读者。检查哪里不好读、人物假、推进硬、想跳过，以及是否自然想继续。
不要把不知道谜底本身当问题。""",
        ),
        _review(
            task_id,
            draft,
            "commercial",
            "master-reader",
            """你是商业阅读Reader。检查五节整体节奏、每节推进、人物记忆点、续读欲与章末状态变化。
不要要求大量短句或网文化碎段。""",
        ),
        _review(
            task_id,
            draft,
            "naturalness",
            "blind-natural-reader",
            """你是文学自然度Reader。检查AI味、模板句、作者替读者总结、办案纪要感、台词墙、碎短句和过度工整对白。""",
        ),
        _review(
            task_id,
            draft,
            "dialogue",
            "character-dialogue-reviewer",
            """检查人物动机和对白。对白必须与角色利益、已知信息和机构身份相符；不要把功能角色写成说明书。""",
        ),
        _review(
            task_id,
            draft,
            "rhythm",
            "language-rhythm-reviewer",
            """检查语言节奏与段落自然度。只抓真实问题，不做审美偏好式过度重写。""",
        ),
    )

    revision = await _run_step(
        task_id=task_id,
        role="revision-agent",
        stage="gray-fast-revision-06-10",
        mode="polish",
        content=draft,
        instruction=(
            "【精简审核问题】\n"
            + _compact_findings(list(reviews), draft)
            + "\n\n【必须保留】\n"
            + brief[-9000:]
            + """
\n一次性修订第6-10节。blocking必须修，普通偏好不要乱改Canon。
不得新增角色、规则、物证或巧合；不得删掉现实账务后果、警方权限边界、红发女人既有伏笔。
保持完整段落和自然语流。每节不得压缩成梗概，必须保留至少2200中文字符。只输出五节完整正文。"""
        ),
    )
    revised = revision.content.strip()
    revised_lengths = _validate_five_sections(revised)
    if set(revised_lengths) != {6, 7, 8, 9, 10}:
        raise RuntimeError(f"revision lost one or more sections: {revised_lengths}")
    if any(length < 2000 for length in revised_lengths.values()):
        raise RuntimeError(f"revision over-compressed one or more sections: {revised_lengths}")

    final_reviews = await asyncio.gather(
        _review(
            task_id,
            revised,
            "final-continuity",
            "continuity-plot-reviewer",
            """最终Gate：只检查是否还存在会阻断交付的连续性、状态、权限、因果、章间接缝问题。
没有blocking只输出NO_ISSUE。""",
        ),
        _review(
            task_id,
            revised,
            "final-reader",
            "blind-reader",
            """最终普通读者Gate：只抓会明显影响阅读、人物可信度或续读的问题。没有blocking只输出NO_ISSUE。""",
        ),
        _review(
            task_id,
            revised,
            "final-naturalness",
            "blind-natural-reader",
            """最终自然度Gate：只抓明显AI味、台词墙、碎短句、作者总结式问题。没有blocking只输出NO_ISSUE。""",
        ),
    )

    blocking = False
    for output in final_reviews:
        for finding in _parse_review_output(output, revised):
            if finding.get("severity") == "blocking":
                blocking = True

    (OUTPUT_DIR / "sections-06-10-fast.md").write_text(revised + "\n", encoding="utf-8")
    (OUTPUT_DIR / "outline.md").write_text(outline.content + "\n", encoding="utf-8")
    (OUTPUT_DIR / "reviews.json").write_text(
        json.dumps(
            {"initial": list(reviews), "final": list(final_reviews)},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    manifest = {
        "project": "灰街",
        "mode": "fast-batch",
        "source": str(source_path),
        "source_is_platform_locked": source_path == LOCKED_SOURCE,
        "sections": [6, 7, 8, 9, 10],
        "draft_lengths": draft_lengths,
        "final_lengths": revised_lengths,
        "final_blocking": blocking,
        "status": "awaiting_human_approval" if not blocking else "blocked",
    }
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False), flush=True)
    return 0 if not blocking else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
