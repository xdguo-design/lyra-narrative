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
        "皮重": "measurement-term-drift",
        "更鼓": "time-anchor-drift",
        "预设答案": "author-meta-commentary",
        "第二层筛选": "author-meta-commentary",
        "问得很有技巧": "author-meta-commentary",
        "视觉事实": "author-meta-commentary",
        "成分一样": "evidence-overreach",
        "谁给的报酬": "disclosure-threshold-gap",
        "报酬多少": "disclosure-threshold-gap",
        "拿了多少钱": "disclosure-threshold-gap",
        "孙库吏昨晚没吩咐": "disclosure-threshold-gap",
        "入库总称": "measurement-unit-drift",
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
    }
    for marker, error in required.items():
        if marker not in text:
            errors.append(error)

    if "马二死了" not in text and "已经没气" not in text and "没气了" not in text:
        errors.append("missing-death-message")

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
- 禁止叙述者替读者解释审讯技巧，不能出现“预设答案”“第二层筛选”“视觉事实”“问得很有技巧”之类元分析。
- 证据只写人物能直接观察或按现场程序验证的内容；不得写“成分一样”这种未经检验的结论。
- 称重阶段只确认“重量对不上”，不要写皮重/毛重术语；具体短缺只由后面的官斗复量给出。
"""


def _part1_instruction(skill: str) -> str:
    return _shared(skill) + """
【只写前半章，目标 1550—1700 个中文字符】
从第一章末尾刘旺抱柴、陈安说“问你件事”、刘旺答“嗯”直接接。
这一段只完成刘旺分层口供，到“袋子后来不见了”为止；不要找出粮袋，不要过秤，不要官斗，不要马二死讯。

信息必须依次发生：
1. 刘旺先回避，把车说成谁都能推；
2. 陈安只指出可验证异常，赵六让人叫周虎；
3. 周虎到场先看车轮、车辙、刘旺左脚鞋印和路线；
4. 刘旺只承认昨夜推过一趟；
5. 周虎不把答案递到嘴边，要从“为何替人挪粮”继续施压，刘旺为撇清主动偷粮才说孙成；
6. 再经过一个独立压力节拍。固定节奏是：周虎先问“他凭什么使唤你？”→刘旺回避→周虎再追“白替他跑这一趟？”→刘旺抓紧柴、犹豫后才吐出五文。禁止出现“谁给的报酬”“报酬多少”“拿了多少钱”；
7. 周虎再追袋子放哪，刘旺说后厨侧门；
8. 周虎再追问后来，刘旺才说袋子后来不见了。

写成小说现场，不要固定照抄问句，不要像表单。
只输出正文。"""


def _part2_instruction(skill: str, part1_tail: str) -> str:
    return _shared(skill) + f"""
【只写后半章，目标 1600—1750 个中文字符】
下面是前半章末尾，只负责承接，不重复已经完成的口供：
--- 前半章尾 ---
{part1_tail}
--- 前半章尾结束 ---

固定剧情顺序：
1. 周虎留住刘旺，由皂役看着，不再重复问推车、孙成、五文；
2. 众人沿痕迹搜索，在木棚后旧木板堆旁找到昨日破口粮袋；
3. 刘旺只确认那不是自己昨夜放袋子的地方；
4. 周虎按程序让皂役/库房人把袋子上秤；皂役必须明确说出“重量对不上”五个字，不得报具体斤两，不得出现皮重/毛重术语；
5. 周虎这时才让人去取昨夜入库记录；不得让记录提前藏在周虎怀里。记录必须明确是昨夜用同口径官斗登记的斗数，不得写“入库总称”或斤两；在取记录的动作里自然带出一次“昨日运粮车夫马二”，只说明身份，不提前暗示他出事；
6. 再取昨夜同口径官斗，由皂役/库房程序复量；不要逐斗报“一、二、三”制造算术歧义，只写按记录应有斗数逐斗复核；
7. 对照同口径记录后只落一个结论：“短三斗一升”；
8. 周虎把粮袋与记录分开收好留作查验；可以写“封存”，但不得新增“封条”这一具体物件；不定性谁偷、怎么偷，也不要让人物用“二次移动”这种总结式术语说话；
9. 最后才有人进院，只报一句：“马二死了。”
10. “马二死了。”必须是本章最后一句。死讯后不再补“找到时没气”、人物反应、时间锚点、更鼓、发现地点或尸体现场信息。

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


async def _repair_length_if_needed(task_id: int, text: str) -> str:
    if 2700 <= len(text) <= 3400:
        return text

    target = "2850—3150" if len(text) < 2700 else "3000—3300"
    result = await _run_step(
        task_id=task_id,
        role="writer-retry",
        stage="chapter-02-length-repair",
        mode="polish",
        content=text,
        instruction=f"""请完整重写当前第二章正文，控制在 {target} 个中文字符。
只允许补足现场动作、空间阻力、人物犹豫和已有线索之间的自然过渡，不得新增事实、人物、物证、精确时间、地点或解释性证据。

硬约束：
- 保持既有剧情顺序与冻结事实不变。
- 刘旺必须分层交代：先认昨夜推车，再交代孙成，再经过独立压力节拍才交代五文。
- 不得由周虎先说出孙成，不得出现“谁给的报酬/报酬多少/拿了多少钱”。
- 找袋子只能沿既有车辙/现场搜索自然推进，不得新增封口切痕、重新缝线等未冻结物证。
- 先明确“重量对不上”，再取昨夜同口径官斗记录复量，最后只得出“短三斗一升”。
- 不把短缺直接定性为偷窃。
- 不出现皮重、封条、精确时辰、作者元分析。
- 最后一句必须且只能是：“马二死了。”
- 只输出完整修订后的正文，不要解释。
""",
    )
    repaired = result.content.strip()
    if len(repaired) <= len(text):
        print(
            f"[length-repair] REJECT shorter_output original_chars={len(text)} "
            f"repaired_chars={len(repaired)}",
            flush=True,
        )
        return text
    print(
        f"[length-repair] ACCEPT original_chars={len(text)} "
        f"repaired_chars={len(repaired)}",
        flush=True,
    )
    return repaired


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


def _master_reader_packet(prior: str, draft: str) -> str:
    prior_tail = prior[-1800:].strip()
    return f"""# Controller Master Reader Packet

> BLIND REVIEW: 在完成本文件审核前，不得读取 review-report.json 或其他 Reviewer 输出。

## 角色

你现在不是主控/编辑，而是一名第一次读到这一章的独立读者。只从读者体验判断，不替作者解释，不补设定，不参考其他模型意见。

重点检查：
1. 第一遍是否读得懂，哪里会停、疑惑、出戏；
2. 人物说话是否像真人，是否问什么答什么、为剧情主动交代；
3. 线索是否由动作和现场自然出现，而不是作者解释；
4. 节奏是否拖、赶、重复或突然跳步；
5. 章末钩子是否有效；
6. 若问题会阻断成稿，标 P0/P1；可局部改善标 P2。

输出固定为：
VERDICT: PASS 或 REWRITE
P0: ...
P1: ...
P2: ...
READER_TRACE: 按阅读顺序写最明显的卡点
HOOK: 对章末钩子的判断

## 前章尾段

{prior_tail}

## 待审第二章

{draft}
"""


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
    text = await _repair_length_if_needed(task_id, text)

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
    (OUTPUT_DIR / "master-reader-packet.md").write_text(
        _master_reader_packet(prior, text),
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
        "master_reader_mode": "external-controller-blind-reader",
        "master_reader_packet": "master-reader-packet.md",
        "master_reader_sees_automated_reviews": False,
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
