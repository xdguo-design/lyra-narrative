from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from app.db import connect, init_db
from app.services.book_pipeline import _chapter_text_is_usable, _create_task
from app.services.default_skills import BUILTIN_WRITING_SKILL_NAME
from app.services.full_novel_pipeline import _run_review_round
from app.services.workflow_service import _run_step, _task_context
from scripts.generate_rewrite_v3_chapter import (
    CHAPTER_ONE,
    GOAL,
    create_project,
    keep_generation_skills_lean,
)


OUTPUT_DIR = Path("artifacts/rewrite-v3-chapter-fast-draft")


def _writer_skill_excerpt(task_id: int, limit: int = 6000) -> str:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT sv.content
            FROM writing_task_skills wts
            JOIN skills s ON s.id=wts.skill_id
            JOIN skill_versions sv
              ON sv.skill_id=wts.skill_id AND sv.version=wts.version
            WHERE wts.task_id=? AND s.name=?
            ORDER BY wts.version DESC
            LIMIT 1
            """,
            (task_id, BUILTIN_WRITING_SKILL_NAME),
        ).fetchone()
    if not row:
        return ""
    return str(row["content"] or "")[-limit:]


def _hard_gate_errors(text: str) -> list[str]:
    errors: list[str] = []
    forbidden = {
        "孙成今早请假": "invented-sun-cheng-leave",
        "说腿疼": "invented-sun-cheng-leg-pain",
        "子时": "invented-time-detail",
        "卯时": "invented-time-detail",
        "申时": "invented-time-detail",
        "三更": "invented-time-detail",
        "五更": "invented-time-detail",
        "赵六从怀里掏": "zhaoliu-invented-record",
        "赵六掏出本子": "zhaoliu-invented-record",
        "赵六掏出一册": "zhaoliu-invented-record",
        "豆粕": "grain-type-drift",
        "散豆": "grain-type-drift",
        "小麦": "grain-type-drift",
        "负责看库": "ma-er-role-drift",
        "油灯": "invented-time-object",
        "抽油烟": "anachronism",
        "东库": "wrong-location",
        "刘旺跪": "overdramatic-confession",
        "周虎身材精瘦": "character-card-drift",
        "周虎是个精瘦": "character-card-drift",
        "心里清楚": "author-summary",
        "必然有联系": "author-summary",
        "意思都懂": "author-summary",
    }
    for marker, error in forbidden.items():
        if marker in text:
            errors.append(error)

    if re.search(r"(?:\\d+|[一二三四五六七八九十百]+)\\s*斤", text):
        errors.append("measurement-drift")

    required = {
        "孙成": "missing-sun-cheng",
        "五文": "missing-five-wen",
        "后厨侧门": "missing-side-door",
        "重量对不上": "missing-weight-anomaly",
        "官斗": "missing-official-dou",
        "短三斗一升": "missing-shortage",
        "马二": "missing-ma-er",
        "没气": "missing-death-message",
    }
    for marker, error in required.items():
        if marker not in text:
            errors.append(error)

    if text.count("短三斗一升") != 1:
        errors.append("shortage-count")
    if text.count("五文") < 1:
        errors.append("five-wen-missing")

    shortage_at = text.find("短三斗一升")
    death_at = max(text.rfind("马二死了"), text.rfind("马二已经死"), text.rfind("没气"))
    if shortage_at >= 0 and death_at >= 0 and shortage_at > death_at:
        errors.append("death-before-shortage")

    if death_at >= 0:
        tail = text[death_at:]
        for marker in (
            "他家", "叫门", "开门", "巷", "外墙", "墙边",
            "鞋底", "尸体", "伤口", "地上躺", "雨水",
        ):
            if marker in tail:
                errors.append("next-chapter-location-leak")
                break

    if len(text) < 2700 or len(text) > 3400:
        errors.append(f"length-{len(text)}")

    return sorted(set(errors))


def _shared(skill: str) -> str:
    return f"""【当前 Writer Skill 最近学习】
{skill}

【冻结事实】
- 第二章《谁让你推的车》，全章约 3000 个中文字符。
- 时间仍是第一章同一个上午，只用“昨夜/今早/刚才”等已有层级。
- 孙成是西库库吏；周虎是皂班班头；马二是昨日运粮车夫。
- 刘旺左脚旧布鞋后跟缺一角。
- 周虎肩背厚、站着像堵门。
- 核心对象始终是昨日赈粮中那只破口粮袋，统一写粮/米/粟米。
- 孙成本章本人不出场；只作为刘旺供述中的名字。
- 赵六没有库账、回票、抄本、小册子。
- 陈安不替周虎审讯，不定罪，不猜孙成动机。
- 不补造精确时辰、请假、腿疼、封条、口供记录等冻结材料没有的事实。
"""


def _part1_instruction(skill: str) -> str:
    return _shared(skill) + """
【只写前半章，目标约 1450 字】
从第一章末尾刘旺抱柴、陈安说“问你件事”、刘旺答“嗯”直接接。
这一段只完成刘旺分层口供，到“袋子后来不见了”为止；不要找出粮袋，不要过秤，不要官斗，不要马二死讯。

信息必须依次发生：
1. 刘旺先回避，把车说成谁都能推；
2. 陈安只指出可验证异常，赵六让人叫周虎；
3. 周虎到场先看车轮、车辙、刘旺左脚鞋印和路线；
4. 刘旺只承认昨夜推过一趟；
5. 周虎另问谁叫推，刘旺才说孙成；
6. 周虎另问拿没拿好处，刘旺才说五文；
7. 周虎另问袋子放哪，刘旺说后厨侧门；
8. 周虎再追问后来，刘旺才说袋子后来不见了。

写成小说现场，不要固定照抄问句，不要像表单。
只输出正文。"""


def _part2_instruction(skill: str, part1_tail: str) -> str:
    return _shared(skill) + f"""
【只写后半章，目标约 1550 字】
下面是前半章末尾，只负责承接，不重复已经完成的口供：
--- 前半章尾 ---
{part1_tail}
--- 前半章尾结束 ---

固定剧情顺序：
1. 周虎留住刘旺，由皂役看着，不再重复问推车、孙成、五文；
2. 众人沿痕迹搜索，在木棚后旧木板堆旁找到昨日破口粮袋；
3. 刘旺只确认那不是自己昨夜放袋子的地方；
4. 周虎按程序让皂役/库房人把袋子上秤，只确认“重量对不上”，不得报具体斤两；
5. 周虎再调昨夜入库记录；
6. 取昨夜同口径官斗，由皂役/库房程序复量；
7. 只落一个结论：“短三斗一升”；
8. 周虎封存粮袋和记录，只确认袋子被二次移动、分量短了，不定性谁偷、怎么偷；
9. 最后才有人只报：“马二死了。”或“找到时已经没气。”
10. 死讯后立即收章，不写发现地点和任何尸体现场信息。

不要让孙成本人出场。
只输出正文。"""


async def _run_writer(task_id: int, stage: str, content: str, instruction: str):
    return await _run_step(
        task_id=task_id,
        role="writer",
        stage=stage,
        mode="continue",
        content=content,
        instruction=instruction,
    )


def _insert_hard_gate_findings(task_id: int, errors: list[str], chars: int) -> None:
    if not errors:
        return
    with connect() as conn:
        for error in errors:
            conn.execute(
                """
                INSERT INTO review_findings(
                    task_id,reviewer,category,severity,summary,suggestion,status
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    task_id,
                    "deterministic-hard-gate",
                    "hard-gate",
                    "blocking",
                    f"{error}: deterministic chapter gate failed; chars={chars}.",
                    "与全部 Reader/Reviewer 结果一起统一打回；下一版必须同时消除全部 blocking。",
                    "open",
                ),
            )


def _review_summary(task_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT reviewer,category,severity,summary,suggestion
            FROM review_findings
            WHERE task_id=? AND status='open'
            ORDER BY
              CASE severity WHEN 'blocking' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
              id
            """,
            (task_id,),
        ).fetchall()
    return [dict(row) for row in rows]


async def main() -> int:
    init_db()
    project_id, chapter_id = create_project()
    task_id = _create_task(
        project_id=project_id,
        chapter_id=chapter_id,
        goal=GOAL,
        instruction=(
            "第二章约3000字。先生成完整候选；所有 Reader/Reviewer 全部审核完成后，"
            "再统一 PASS 或一次性打回；不得提前终止审核。"
        ),
    )
    keep_generation_skills_lean(task_id)

    prior = CHAPTER_ONE.read_text(encoding="utf-8")
    skill = _writer_skill_excerpt(task_id)

    part1_result = await _run_writer(
        task_id,
        "chapter-02-fast-part1",
        prior[-2600:],
        _part1_instruction(skill),
    )
    part1 = part1_result.content.strip()

    part2_result = await _run_writer(
        task_id,
        "chapter-02-fast-part2",
        part1[-1800:],
        _part2_instruction(skill, part1[-1600:]),
    )
    part2 = part2_result.content.strip()

    text = (part1.rstrip() + "\n\n" + part2.lstrip()).strip()

    # Important policy: deterministic gates collect findings but NEVER reject early.
    hard_errors = _hard_gate_errors(text)

    with connect() as conn:
        conn.execute(
            "UPDATE writing_tasks SET draft=?,revised_content=?,status='running' WHERE id=?",
            (text, text, task_id),
        )
        conn.execute("DELETE FROM review_findings WHERE task_id=?", (task_id,))

    context = _task_context(task_id, project_id)

    # Run the complete NarrativeOS review round first. auto_learn=False is critical:
    # Skill learning happens only after every reviewer has finished.
    review_outputs, has_review_blocking = await _run_review_round(
        task_id=task_id,
        draft=text,
        context=context,
        round_no=1,
        auto_learn=False,
    )

    # Add deterministic findings only after all AI reviewers have completed.
    _insert_hard_gate_findings(task_id, hard_errors, len(text))

    usable = _chapter_text_is_usable(text)
    if not usable:
        _insert_hard_gate_findings(
            task_id,
            ["chapter-text-unusable"],
            len(text),
        )

    findings = _review_summary(task_id)
    has_automated_blocking = has_review_blocking or bool(hard_errors) or not usable
    has_automated_blocking = has_automated_blocking or any(
        str(item.get("severity")) == "blocking" for item in findings
    )

    # Do not reject or learn yet. The fourth reviewer is the external
    # ChatGPT master reader. Only after that review is added may the
    # combined findings be accepted or rejected as one batch.
    learning = {"recorded": 0, "batch_id": None, "skill_versions": {}}
    status = "awaiting_master_review"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "chapter-02-fast-candidate.md").write_text(
        "# 第二章 谁让你推的车\n\n" + text + "\n",
        encoding="utf-8",
    )
    (OUTPUT_DIR / "review-report.json").write_text(
        json.dumps(
            {
                "review_outputs": review_outputs,
                "findings": findings,
                "hard_gate_errors": hard_errors,
                "learning": learning,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    with connect() as conn:
        conn.execute(
            "UPDATE writing_tasks SET draft=?,revised_content=?,status=? WHERE id=?",
            (text, text, status, task_id),
        )
        runs = conn.execute(
            "SELECT role,stage,status,provider,model,error FROM agent_runs WHERE task_id=? ORDER BY id",
            (task_id,),
        ).fetchall()

    manifest = {
        "task_id": task_id,
        "chars": len(text),
        "target_chars": 3000,
        "usable": usable,
        "hard_gate_errors": hard_errors,
        "reviewer_count": len(review_outputs),
        "finding_count": len(findings),
        "blocking_count": sum(
            1 for item in findings if str(item.get("severity")) == "blocking"
        ),
        "automated_reviewer_count": len(review_outputs),
        "automated_blocking": has_automated_blocking,
        "master_review_pending": True,
        "all_reviews_completed_before_reject": False,
        "learning_batch_id": learning.get("batch_id"),
        "status": status,
        "runs": [dict(row) for row in runs],
    }
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
