from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.db import connect, init_db
from app.services.book_pipeline import _chapter_text_is_usable, _create_task
from app.services.workflow_service import _run_step, _task_context
from scripts.generate_rewrite_v3_chapter import (
    CHAPTER_NUMBER,
    CHAPTER_ONE,
    GOAL,
    INSTRUCTION,
    create_project,
    keep_generation_skills_lean,
)

OUTPUT_DIR = Path("artifacts/rewrite-v3-chapter-fast-draft")


async def main() -> int:
    init_db()
    project_id, chapter_id = create_project()
    task_id = _create_task(
        project_id=project_id,
        chapter_id=chapter_id,
        goal=GOAL,
        instruction=INSTRUCTION,
    )
    keep_generation_skills_lean(task_id)

    prior = CHAPTER_ONE.read_text(encoding="utf-8")
    context = _task_context(task_id, project_id)

    base_rules = """这是快速草稿通道。整章最终目标约 3000 个中文字符，允许 2800—3200 字。
不得输出提纲、解释、审稿意见或写作说明。

【必须遵守的冻结事实】
- 时间仍是第一章同一个上午，不得突然写正午、夜晚、点灯或夜风。
- 核心对象始终是“昨日赈粮中那只破口粮袋”，不是豆粕袋，不得新造另一宗袋子。
- 孙成是西库库吏；周虎是皂班班头。禁止出现“东库孙成”“刘班头”等新身份。
- 赵六没有库账、回票或入库折纸，不得从怀里掏出账务证据。
- 粮袋不是一开始就摆在泔水车里等人发现；刘旺昨夜曾用后厨小车把它从西库附近移到后厨侧门，之后它又被别人移动。

【刘旺信息暴露顺序，禁止跳级】
1. 先把异常说成日常：谁都推车、车谁都能用、自己不知道。
2. 周虎实际复核车辙/鞋印/路线后，只承认“昨夜推过一趟”。
3. 周虎继续追问“谁叫你推”，才承认孙成。
4. 只有周虎明确问“拿没拿好处/为什么肯搬”，才承认五文钱。
5. 前述事实压实后，才承认自己放下后粮袋后来又不见了。

【调查写法】
- 陈安一次只问一个能验证的小问题，不得连续盘问。
- 赵六主要表现风险判断、收声、提醒责任，不替作者讲案情。
- 周虎先控人和现场，再拆事实。
- 线索通过走路、搬东西、等人、复核、找袋、开袋、过秤/复量和现场噪声推进。

【计量硬规则】
- 禁止再写“一百二十斤→一百一十六斤四两→短三斗一升”。
- 如写过秤，只能表示“重量对不上”。
- 最终短缺必须用与昨夜记录同口径的官斗复量，明确得出“短三斗一升”。

【作者与证据边界】
- 禁止“陈安心里清楚……”“周虎是在……”“赵六不是……而是……”等作者总结句。
- 陈安只能描述看见的痕迹，不得替周虎审案。
- 周虎不说办案金句，不用长段威胁。

【章末边界】
- 第二章只允许收到消息：马二已经死了/找到时没气了。
- 禁止描写马二尸体具体地点、姿态、鞋底、雨水、伤口或现场物证。
"""

    part1_instruction = "\n\n".join(
        [
            GOAL,
            INSTRUCTION,
            context,
            base_rules,
            """你现在只写第二章前半段，目标 1400—1600 个中文字符。
从第一章刘旺抱柴、陈安准备问话处直接接。
前半段必须完成：
1. 刘旺先回避，把车说成谁都能推；
2. 周虎进入并实际复核车辙/鞋印/路线；
3. 刘旺只承认昨夜推过一趟；
4. 周虎单独追问后，刘旺才说是孙成叫他搬；
5. 周虎再问好处，刘旺才承认五文钱；
6. 前半段结束前，刘旺承认自己把袋子放到后厨侧门后，后来袋子又不见了。
前半段不要找到粮袋，不要复量，不要出现马二死讯。
只输出正文，不要标题。""",
        ]
    )

    part1 = await _run_step(
        task_id=task_id,
        role="writer",
        stage="chapter-02-fast-part-1",
        mode="continue",
        content=prior[-2600:],
        instruction=part1_instruction,
    )
    part1_text = part1.content.strip()

    part2_instruction = "\n\n".join(
        [
            GOAL,
            INSTRUCTION,
            context,
            base_rules,
            """你现在只写第二章后半段，目标 1400—1600 个中文字符。
必须承接下面这段前半章，不得复述已经发生的问话：
=== 前半章 ===
"""
            + part1_text[-2200:]
            + """
=== 前半章结束 ===

后半段必须按顺序完成：
1. 众人根据已有痕迹继续搜索，真正找到昨日那只破口赈粮袋；
2. 明确它现在的位置与刘旺昨夜放下的位置不同；
3. 周虎调取昨夜入库记录；
4. 先用秤只能确认重量对不上；
5. 再用与昨夜相同口径的官斗复量；
6. 明确短三斗一升；
7. 所有人只能确认当前事实，不得提前定性谁偷、怎么偷；
8. 完成以上步骤后，章末才收到马二已经死了的消息。
只输出后半段正文，不要标题，不要重复前半段。""",
        ]
    )

    part2 = await _run_step(
        task_id=task_id,
        role="writer",
        stage="chapter-02-fast-part-2",
        mode="continue",
        content=part1_text[-1800:],
        instruction=part2_instruction,
    )
    part2_text = part2.content.strip()

    text = (part1_text.rstrip() + "\n\n" + part2_text.lstrip()).strip()

    # 3000 字是产品级默认目标，不为追求精确字数再发起一次整章模型调用。
    # 分段生成可避免 GLM53Flash 在 3000+ 字单次输出时超时。
    if len(text) < 2600 or len(text) > 3400:
        print(
            f"[chapter-text] WARN fast split draft chars={len(text)} "
            "(target=2800..3200, tolerated=2600..3400)",
            flush=True,
        )

    with connect() as conn:
        conn.execute(
            "UPDATE writing_tasks SET draft=?,revised_content=?,status='awaiting_approval' WHERE id=?",
            (text, text, task_id),
        )
        rows = conn.execute(
            "SELECT role,stage,status,provider,model,error FROM agent_runs WHERE task_id=? ORDER BY id",
            (task_id,),
        ).fetchall()

    manifest = {
        "task_id": task_id,
        "usable": _chapter_text_is_usable(text),
        "chars": len(text),
        "target_chars": 3000,
        "parts": {
            "part_1_chars": len(part1_text),
            "part_2_chars": len(part2_text),
        },
        "runs": [dict(row) for row in rows],
    }
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False), flush=True)
    return 0 if manifest["usable"] else 2

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "chapter-02-fast-candidate.md").write_text(
        "# 第二章 谁让你推的车\n\n" + text + "\n",
        encoding="utf-8",
    )

    with connect() as conn:
        conn.execute(
            "UPDATE writing_tasks SET draft=?,revised_content=?,status='awaiting_approval' WHERE id=?",
            (text, text, task_id),
        )
        rows = conn.execute(
            "SELECT role,stage,status,provider,model,error FROM agent_runs WHERE task_id=? ORDER BY id",
            (task_id,),
        ).fetchall()

    manifest = {
        "task_id": task_id,
        "usable": _chapter_text_is_usable(text),
        "chars": len(text),
        "runs": [dict(row) for row in rows],
    }
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False), flush=True)
    return 0 if manifest["usable"] else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
