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

    draft_result = await _run_step(
        task_id=task_id,
        role="writer",
        stage="gray-fast-draft-06-10",
        mode="continue",
        content=outline.content,
        instruction=(
            context
            + "\n\n【第6-10节执行大纲】\n"
            + outline.content
            + "\n\n【硬约束】\n"
            + brief
            + """
\n一次性写完整第6、7、8、9、10节正文，每节约2500-3800中文字符。
必须连续，不重启故事。第6节先兑现银牌账务/核验后果，再自然推出七号箱和费恩死亡。
汤普森是警官，不是事务所职员。事务所压力由事务所内部人员承担。
红发女人前文已经出现，不得当成新角色空降。
怀表不能当万能导航器。警方信息必须有合法来源。
第7-10节不能因为一次性生成而跳过人物选择、关系代价和现实手续后果。
用完整段落、自然长短句，不写碎短句和台词墙。
只输出正文，标题格式必须是：
# 第六节　...
# 第七节　...
# 第八节　...
# 第九节　...
# 第十节　...
"""
        ),
    )
    draft = draft_result.content.strip()
    if len(re.findall(r"^# 第[六七八九十]节", draft, re.MULTILINE)) != 5:
        raise RuntimeError("writer did not return all five sections")

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
保持完整段落和自然语流。只输出五节完整正文。"""
        ),
    )
    revised = revision.content.strip()
    if len(re.findall(r"^# 第[六七八九十]节", revised, re.MULTILINE)) != 5:
        raise RuntimeError("revision lost one or more sections")

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
