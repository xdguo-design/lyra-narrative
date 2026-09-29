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


def _writer_skill_excerpt(task_id: int, limit: int = 5200) -> str:
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
        "子时": "invented-time-detail",
        "卯时": "invented-time-detail",
        "申时": "invented-time-detail",
        "三更": "invented-time-detail",
        "赵六从怀里掏": "zhaoliu-invented-record",
        "赵六掏出本子": "zhaoliu-invented-record",
        "赵六掏出一册": "zhaoliu-invented-record",
        "一百二十斤": "measurement-drift",
        "一百一十六斤": "measurement-drift",
        "五十斤": "measurement-drift",
        "昨夜入库记录是五斗": "measurement-arithmetic-risk",
        "一斗四升": "measurement-arithmetic-risk",
        "心里清楚": "author-summary",
        "必然有联系": "author-summary",
        "意思都懂": "author-summary",
        "散豆": "grain-type-drift",
        "小麦碎屑": "grain-type-drift",
    }
    for marker, error in forbidden.items():
        if marker in text:
            errors.append(error)

    shortage_at = text.find("短三斗一升")
    death_at = text.rfind("马二")
    if shortage_at >= 0 and death_at >= 0 and shortage_at > death_at:
        errors.append("death-before-shortage")

    pushed_at = text.find("推过")
    sun_at = text.find("孙成")
    five_at = text.find("五文")
    missing_at = text.find("不见")
    if min(pushed_at, sun_at, five_at, missing_at) >= 0:
        if not (pushed_at < sun_at < five_at < missing_at):
            errors.append("disclosure-order")

    if death_at >= 0:
        death_tail = text[death_at:]
        for marker in (
            "他家",
            "门开",
            "巷",
            "墙边",
            "鞋底",
            "尸体",
            "伤口",
            "地上躺",
        ):
            if marker in death_tail:
                errors.append("next-chapter-location-leak")
                break

    return sorted(set(errors))


def _instruction(skill: str, retry_errors: list[str] | None = None) -> str:
    retry_note = ""
    if retry_errors:
        retry_note = (
            "\n\n上一版被程序门禁打回，必须整章重写，禁止局部修补。"
            "\n打回标签：" + ", ".join(retry_errors)
        )

    return f"""第二章《谁让你推的车》。只输出完整小说正文，不要标题、提纲、解释、审稿意见。
目标 2800—3200 个中文字符，正常落点约 3000 字。

【当前 Writer Skill 最近学习】
{skill}

【承接】
从第一章末尾：刘旺抱着劈柴出来，看见陈安、赵六在看泔水车；陈安转身说“问你件事”，刘旺答“嗯”。从这里自然接。

【本章冻结事实】
- 时间仍是第一章同一个上午，不得跳到正午、夜晚、点灯、夜风，也不要自造子时/卯时/申时。
- 核心对象始终是昨日赈粮中那只破口粮袋。
- 孙成是西库库吏；周虎是皂班班头。
- 刘旺昨夜受孙成指使，用后厨小车把破口粮袋从西库附近移到后厨侧门，收了五文钱；之后粮袋又被别人移动。
- 不得擅自新增孙成请假、腿疼、失踪、外出等状态。
- 赵六没有库账、回票、折纸、抄本、小册子；账目和量具只能由周虎按县衙程序调取。
- 不得新造“记录显示昨夜有人搬动”这种自动送答案的证据。

【刘旺披露顺序，必须逐层发生】
1. 先回避，把车说成谁都能推、天天都用；
2. 周虎亲自复核车轮/车辙/鞋印/路线后，刘旺才只承认“昨夜推过一趟”；
3. 周虎另问“谁叫你推”，刘旺才回答孙成；周虎不能自己先报孙成名字逼他确认；
4. 周虎再单独问“拿没拿好处/为什么肯搬”，刘旺才承认五文钱；
5. 前述事实压实后，刘旺才承认自己把袋子放到后厨侧门后，后来袋子又不见了。
禁止第二次重复审同一套口供。

【调查顺序】
- 陈安不连环盘问，不替周虎审人；一次只指出一个可验证异常。
- 赵六负责风险判断、提醒和县衙经验，不给他凭空变出账册。
- 周虎先控人和现场，再拆事实；靠动作、复核、调账、复量建立权力，不说办案金句。
- 根据已有痕迹搜索，真正找到昨日那只破口粮袋。
- 明确粮袋当前所在处与刘旺昨夜放下的位置不同。
- 周虎按程序调取昨夜入库记录。
- 先用秤只确认“重量对不上”，禁止报具体斤两。
- 再用昨夜相同口径的官斗复量。
- 最终只给冻结结论：“短三斗一升”。不要补总斗数、剩余斗数，也不要让算术重新漂移。
- 只能确认当前事实，不得提前定性谁偷、怎么偷。

【语言与连续性】
- 调查必须通过走路、搬东西、等人、复核、找袋、开袋、过秤、复量和现场噪声推进，不能写成问卷式一问一答。
- 禁止“心里清楚”“必然有联系”等作者总结句。
- 对话要像当场的人说话，不像规章、金句或作者结论。
- 人物手中物、站位、伤势要连续；放下的柴不能后文自动又回到手里。
- 粮食类型保持一致，统一写“粮/米/粟米”即可，不得突然出现散豆、豆粕、小麦。
- 不要让刘旺突然跪地痛哭并全盘招供；他怕事，但仍应先自保。

【章末硬边界】
必须先完成找到粮袋、位置异常、调取记录、秤重异常、官斗复量、确认短三斗一升。
全部完成后，才允许有人来报：“马二死了”或“找到时已经没气”。
死讯出现后立刻收章。禁止写在哪里找到、谁去叫门、门窗状态、尸体姿态、鞋底、雨水、伤口或任何第三章现场物证。
{retry_note}
"""


async def _generate(task_id: int, prior: str, skill: str, stage: str, retry_errors=None):
    return await _run_step(
        task_id=task_id,
        role="writer",
        stage=stage,
        mode="continue",
        content=prior[-2800:],
        instruction=_instruction(skill, retry_errors),
    )


async def main() -> int:
    init_db()
    project_id, chapter_id = create_project()
    task_id = _create_task(
        project_id=project_id,
        chapter_id=chapter_id,
        goal=GOAL,
        instruction="第二章快速整章草稿：每章约3000字，严格遵守当前Writer防复发规则。",
    )
    keep_generation_skills_lean(task_id)

    prior = CHAPTER_ONE.read_text(encoding="utf-8")
    skill = _writer_skill_excerpt(task_id)

    result = await _generate(
        task_id,
        prior,
        skill,
        "chapter-02-fast-draft",
    )
    text = result.content.strip()
    gate_errors = _hard_gate_errors(text)
    target_ok = 2600 <= len(text) <= 3400
    usable = _chapter_text_is_usable(text)

    if not usable or not target_ok or gate_errors:
        retry_errors = list(gate_errors)
        if not target_ok:
            retry_errors.append(f"length={len(text)} target=2800..3200")
        if not usable:
            retry_errors.append("chapter-text-unusable")
        result = await _generate(
            task_id,
            prior,
            skill,
            "chapter-02-fast-rewrite",
            retry_errors,
        )
        text = result.content.strip()
        gate_errors = _hard_gate_errors(text)
        target_ok = 2600 <= len(text) <= 3400
        usable = _chapter_text_is_usable(text)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "chapter-02-fast-candidate.md").write_text(
        "# 第二章 谁让你推的车\n\n" + text + "\n",
        encoding="utf-8",
    )

    status = "awaiting_approval" if usable and target_ok and not gate_errors else "reviewed"
    with connect() as conn:
        conn.execute(
            "UPDATE writing_tasks SET draft=?,revised_content=?,status=? WHERE id=?",
            (text, text, status, task_id),
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
        "status": status,
        "runs": [dict(row) for row in rows],
    }
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False), flush=True)
    return 0 if status == "awaiting_approval" else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
