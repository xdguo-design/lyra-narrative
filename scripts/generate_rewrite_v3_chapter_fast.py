from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.db import connect, init_db
from app.services.book_pipeline import _chapter_text_is_usable, _create_task
from app.services.default_skills import BUILTIN_WRITING_SKILL_NAME
from app.services.workflow_service import _run_step
from scripts.generate_rewrite_v3_chapter import (
    CHAPTER_ONE,
    GOAL,
    create_project,
    keep_generation_skills_lean,
)


OUTPUT_DIR = Path("artifacts/rewrite-v3-chapter-fast-draft")


def _writer_skill_excerpt(task_id: int, limit: int = 3600) -> str:
    """Keep the newest Writer anti-regression rules without shipping huge context."""
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

    required = {
        "孙成": "missing-sun-cheng",
        "五文": "missing-five-wen",
        "短三斗一升": "missing-final-shortage",
        "马二": "missing-ma-er",
        "没气": "missing-death-message",
    }
    for marker, error in required.items():
        if marker not in text:
            errors.append(error)

    forbidden = {
        "孙成今早请假": "invented-sun-cheng-leave",
        "说腿疼": "invented-sun-cheng-leg-pain",
        "去他家叫门": "next-chapter-location-leak",
        "门开着": "next-chapter-location-leak",
        "西库外墙": "next-chapter-location-leak",
        "鞋底": "next-chapter-evidence-leak",
        "心里清楚": "author-summary",
        "必然有联系": "author-summary",
        "一百二十斤": "measurement-drift",
        "一百一十六斤": "measurement-drift",
        "昨夜入库记录是五斗": "measurement-arithmetic-risk",
        "一斗四升": "measurement-arithmetic-risk",
    }
    for marker, error in forbidden.items():
        if marker in text:
            errors.append(error)

    shortage_at = text.find("短三斗一升")
    death_at = text.find("马二")
    if shortage_at >= 0 and death_at >= 0 and shortage_at > death_at:
        errors.append("death-before-shortage")

    pushed_at = text.find("推过")
    sun_at = text.find("孙成")
    five_at = text.find("五文")
    missing_at = text.find("不见")
    if min(pushed_at, sun_at, five_at, missing_at) >= 0:
        if not (pushed_at < sun_at < five_at < missing_at):
            errors.append("disclosure-order")

    return sorted(set(errors))


async def main() -> int:
    init_db()
    project_id, chapter_id = create_project()
    task_id = _create_task(
        project_id=project_id,
        chapter_id=chapter_id,
        goal=GOAL,
        instruction="第二章快速分段草稿：每章约3000字，严格遵守当前Writer防复发规则。",
    )
    keep_generation_skills_lean(task_id)

    prior = CHAPTER_ONE.read_text(encoding="utf-8")
    skill = _writer_skill_excerpt(task_id)

    shared = """第二章《谁让你推的车》，整章最终目标约 3000 个中文字符，允许 2800—3200 字。
只输出小说正文，不得输出标题、提纲、解释、审稿意见。

【冻结事实】
- 时间仍是第一章同一个上午。
- 核心对象始终是昨日赈粮中那只破口粮袋。
- 孙成是西库库吏；周虎是皂班班头。
- 刘旺昨夜受孙成指使，用后厨小车把破口粮袋从西库附近移到后厨侧门，并收五文钱；之后粮袋又被别人移动。
- 不得擅自新增孙成请假、腿疼、失踪等状态。
- 赵六没有库账、回票或入库折纸。

【人物】
- 陈安只问能验证的小问题，不连续盘问，不越权下结论。
- 赵六先看风险和责任，对周虎收声，对陈安才贫。
- 周虎先控人和现场，再复核事实；不用办案金句。
- 刘旺先回避，再在证据压力下一层一层承认，绝不一次性吐完整时间线。

【硬边界】
- 不得写作者总结腔，如“心里清楚”“必然有联系”。
- 不得新造冻结设定没有的证据、伤病、请假、行踪。
- 计量最终只冻结一个结论：同口径官斗复量后“短三斗一升”。不要擅自补总斗数、剩余斗数来做算术。
- 第二章章末只允许收到消息“马二死了/找到时已经没气”。不得写发现地点、门窗、尸体姿态、鞋底、雨水、伤口和现场物证。
"""

    part1 = await _run_step(
        task_id=task_id,
        role="writer",
        stage="chapter-02-fast-part-1",
        mode="continue",
        content=prior[-1800:],
        instruction="\n\n".join(
            [
                GOAL,
                "【当前Writer Skill最近学习】\n" + skill,
                shared,
                """只写前段，约 900—1100 字。从第一章刘旺抱柴、陈安准备问话直接接。
必须依次完成：
1. 刘旺先把车说成谁都能推，回避昨夜异常；
2. 周虎到场，实际复核车辙/鞋印/路线；
3. 刘旺只承认“昨夜推过一趟”；
4. 周虎另问“谁叫你推”，刘旺才说孙成；
5. 周虎再另问好处，刘旺才说五文钱；
6. 前段最后，刘旺才承认袋子放到后厨侧门后，后来又不见了。
到此停止。不要找出粮袋，不要复量，不要出现马二死讯。""",
            ]
        ),
    )
    part1_text = part1.content.strip()

    part2 = await _run_step(
        task_id=task_id,
        role="writer",
        stage="chapter-02-fast-part-2",
        mode="continue",
        content=part1_text[-1500:],
        instruction="\n\n".join(
            [
                "【当前Writer Skill最近学习】\n" + skill,
                shared,
                """只写中段，约 900—1100 字。承接当前正文，禁止复述前段问话。
必须依次完成：
1. 周虎带人按已有痕迹搜索；
2. 真正找到昨日那只破口赈粮袋；
3. 明确它现在的位置与刘旺昨夜放在后厨侧门的位置不同；
4. 周虎按程序调取昨夜入库记录；
5. 先用秤复核，只确认“重量对不上”；
6. 准备按昨夜相同口径用官斗复量。
到“准备/开始官斗复量”处停止。不要先说短缺数字，不要出现马二死讯。""",
            ]
        ),
    )
    part2_text = part2.content.strip()

    part3 = await _run_step(
        task_id=task_id,
        role="writer",
        stage="chapter-02-fast-part-3",
        mode="continue",
        content=part2_text[-1500:],
        instruction="\n\n".join(
            [
                "【当前Writer Skill最近学习】\n" + skill,
                shared,
                """只写后段，约 900—1100 字。承接当前正文，禁止复述前两段。
必须依次完成：
1. 用与昨夜相同口径的官斗完成复量；
2. 只给冻结结论“短三斗一升”，不要再补总斗数/剩余斗数；
3. 周虎封存粮袋和记录，只确认当前能确认的事实，不定性是谁偷、怎么偷；
4. 陈安、赵六保持各自权限和说话方式；
5. 所有粮案步骤完成后，才有人来报马二已经死了/找到时没气；
6. 死讯到这里立刻收章，不得交代发现地点和任何尸体现场信息。
只输出正文。""",
            ]
        ),
    )
    part3_text = part3.content.strip()

    text = "\n\n".join(
        item.strip()
        for item in (part1_text, part2_text, part3_text)
        if item.strip()
    ).strip()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "chapter-02-fast-candidate.md").write_text(
        "# 第二章 谁让你推的车\n\n" + text + "\n",
        encoding="utf-8",
    )

    gate_errors = _hard_gate_errors(text)
    target_ok = 2600 <= len(text) <= 3400
    usable = _chapter_text_is_usable(text)

    with connect() as conn:
        conn.execute(
            "UPDATE writing_tasks SET draft=?,revised_content=?,status=? WHERE id=?",
            (
                text,
                text,
                "awaiting_approval" if usable and target_ok and not gate_errors else "reviewed",
                task_id,
            ),
        )
        rows = conn.execute(
            "SELECT role,stage,status,provider,model,error FROM agent_runs WHERE task_id=? ORDER BY id",
            (task_id,),
        ).fetchall()

    manifest = {
        "task_id": task_id,
        "usable": usable,
        "target_ok": target_ok,
        "hard_gate_ok": not gate_errors,
        "hard_gate_errors": gate_errors,
        "chars": len(text),
        "target_chars": 3000,
        "parts": {
            "part_1_chars": len(part1_text),
            "part_2_chars": len(part2_text),
            "part_3_chars": len(part3_text),
        },
        "runs": [dict(row) for row in rows],
    }
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False), flush=True)
    return 0 if usable and target_ok and not gate_errors else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
