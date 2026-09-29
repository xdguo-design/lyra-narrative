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

    instruction = "\n\n".join(
        [
            GOAL,
            INSTRUCTION,
            context,
            """这是快速草稿通道。你只负责先交付一版可验收的完整第二章正文。
不得输出提纲、解释、审稿意见或写作说明。正文目标 2500—3800 个中文字符。

【必须遵守的冻结事实】
- 时间仍是第一章同一个上午，不得突然写正午、夜晚、点灯或夜风。
- 核心对象始终是“昨日赈粮中那只破口粮袋”，不是豆粕袋，不得新造另一宗袋子。
- 孙成是西库库吏；周虎是皂班班头。禁止出现“东库孙成”“刘班头”等新身份。
- 赵六没有库账、回票或入库折纸，不得从怀里掏出账务证据。
- 粮袋不是一开始就摆在泔水车里等人发现；刘旺昨夜曾用后厨小车把它从西库附近移到后厨侧门，之后它又被别人移动。具体二次位置可自然安排，但必须经过搜索/搬动/复核才找到。

【刘旺信息暴露顺序，禁止跳级】
1. 先把异常说成日常：谁都推车、车谁都能用、自己不知道。
2. 周虎实际复核车辙/鞋印/路线后，只承认“昨夜推过一趟”。
3. 周虎继续追问“谁叫你推”，才承认孙成。
4. 只有周虎明确问“拿没拿好处/为什么肯搬”，才承认五文钱。
5. 前述事实压实后，才承认自己放下后粮袋后来又不见了。
禁止一次性口述完整时间线。

【调查写法】
- 陈安一次只问一个能验证的小问题，不得连续盘问。
- 赵六主要表现风险判断、收声、提醒责任，不替作者讲案情。
- 周虎先控人和现场，再拆事实；关键账册、秤具、复量都由周虎/库房程序调取。
- 线索通过走路、搬东西、等人、复核、找袋、开袋、过秤/复量和现场噪声推进。

【计量硬规则】
- 禁止再写“一百二十斤→一百一十六斤四两→短三斗一升”。
- 如写过秤，只能表示“重量对不上”；最终短缺必须用与昨夜记录同口径的官斗复量，明确得出“短三斗一升”。
- 不得从三斗一升脑补“几个人搬多久”。

【章末边界】
- 第二章只允许收到消息：马二已经死了/找到时没气了。
- 禁止描写马二尸体具体地点、姿态、鞋底、雨水、伤口或现场物证；这些全部留给第三章。
只输出完整正文。""",
        ]
    )

    writer = await _run_step(
        task_id=task_id,
        role="writer",
        stage="chapter-02-fast-draft",
        mode="continue",
        content=prior[-3000:],
        instruction=instruction,
    )

    text = writer.content.strip()
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
