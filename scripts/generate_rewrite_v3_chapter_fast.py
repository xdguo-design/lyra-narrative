from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from app.db import connect, init_db
from app.services.book_pipeline import _chapter_text_is_usable, _create_task
from app.services.default_skills import BUILTIN_WRITING_SKILL_NAME
from app.services.rejection_learning import record_rejection_batch
from app.services.workflow_service import _run_step
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


def _common_forbidden(text: str) -> list[str]:
    errors: list[str] = []
    forbidden = {
        "孙成今早请假": "invented-sun-cheng-leave",
        "说腿疼": "invented-sun-cheng-leg-pain",
        "子时": "invented-time-detail",
        "卯时": "invented-time-detail",
        "申时": "invented-time-detail",
        "三更": "invented-time-detail",
        "五更": "invented-time-detail",
        "半夜": "invented-time-detail",
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
    return errors


def _part1_errors(text: str) -> list[str]:
    errors = _common_forbidden(text)

    required = {
        "推过": "p1-missing-pushed",
        "孙成": "p1-missing-sun-cheng",
        "五文": "p1-missing-five-wen",
        "后厨侧门": "p1-missing-side-door",
    }
    for marker, error in required.items():
        if marker not in text:
            errors.append(error)

    pushed_at = text.find("推过")
    who_q = max(text.find("谁让你推"), text.find("谁叫你推"))
    sun_at = text.find("孙成")
    benefit_q = max(
        text.find("给了你什么"),
        text.find("给你什么"),
        text.find("拿他钱"),
        text.find("拿没拿好处"),
        text.find("拿了什么好处"),
    )
    five_at = text.find("五文")
    side_at = text.find("后厨侧门")
    later_q = max(
        text.find("后来呢"),
        text.find("后来怎么"),
        text.find("之后呢"),
        text.find("再后来"),
        text.find("后来怎么样"),
    )
    missing_at = max(
        text.find("不见"),
        text.find("没了"),
        text.find("找不到"),
        text.find("不在了"),
    )

    if min(
        pushed_at, who_q, sun_at, benefit_q, five_at, side_at, later_q, missing_at
    ) < 0:
        errors.append("p1-missing-disclosure-turn")
    elif not (
        pushed_at < who_q < sun_at < benefit_q < five_at
        < side_at < later_q < missing_at
    ):
        errors.append("p1-disclosure-order")

    if text.count("五文") > 2:
        errors.append("p1-five-wen-repeated")
    if missing_at < 0:
        errors.append("p1-missing-bag-gone")
    if "短三斗一升" in text or "马二死" in text or "没气" in text:
        errors.append("p1-leaks-later-events")

    return sorted(set(errors))


def _part2_errors(text: str) -> list[str]:
    errors = _common_forbidden(text)

    required = {
        "破口": "p2-missing-bag",
        "木板": "p2-missing-second-location",
        "重量对不上": "p2-missing-weight-anomaly",
        "官斗": "p2-missing-official-dou",
        "短三斗一升": "p2-missing-shortage",
        "马二": "p2-missing-ma-er",
        "没气": "p2-missing-death-message",
    }
    for marker, error in required.items():
        if marker not in text:
            errors.append(error)

    # Part 2 must not re-run the already completed interrogation.
    for marker in (
        "谁让你推",
        "谁叫你推",
        "给了你什么",
        "拿没拿好处",
        "拿了什么好处",
        "五文钱",
    ):
        if marker in text:
            errors.append("p2-repeats-interrogation")
            break

    scale_at = max(text.find("抬上秤"), text.find("挂上秤"), text.find("上秤"))
    weight_at = text.find("重量对不上")
    record_at = max(text.find("入库记录"), text.find("昨夜记录"))
    dou_at = text.find("官斗")
    shortage_at = text.find("短三斗一升")

    if min(scale_at, weight_at, record_at, dou_at, shortage_at) < 0:
        errors.append("p2-missing-measurement-sequence")
    elif not (scale_at < weight_at < record_at < dou_at < shortage_at):
        errors.append("p2-measurement-order")

    if "不是我昨夜放" not in text and "不是我放的地方" not in text:
        errors.append("p2-bag-relocation-not-explicit")

    death_at = max(text.find("马二死了"), text.find("马二已经死"), text.find("没气"))
    if death_at < shortage_at:
        errors.append("p2-death-before-shortage")
    if death_at >= 0:
        tail = text[death_at:]
        for marker in (
            "他家", "叫门", "开门", "巷", "外墙", "墙边",
            "鞋底", "尸体", "伤口", "地上躺", "雨水",
        ):
            if marker in tail:
                errors.append("next-chapter-location-leak")
                break

    if "孙成走" in text or "孙成站" in text or "孙成从" in text or "孙成看" in text:
        errors.append("sun-cheng-appears")

    return sorted(set(errors))


def _global_errors(text: str) -> list[str]:
    errors = _common_forbidden(text)
    if text.count("短三斗一升") != 1:
        errors.append("global-shortage-count")
    if text.count("五文") != 1:
        errors.append("global-five-wen-count")
    if text.count("马二") < 1:
        errors.append("global-missing-ma-er")
    if text.count("没气") < 1:
        errors.append("global-missing-death-message")
    if text.count("重量对不上") < 1:
        errors.append("global-missing-weight-anomaly")
    if text.count("官斗") < 1:
        errors.append("global-missing-official-dou")
    if len(text) < 2700 or len(text) > 3400:
        errors.append(f"global-length-{len(text)}")
    return sorted(set(errors))


def _record_reject(task_id: int, source: str, errors: list[str], chars: int) -> None:
    if not errors:
        return
    record_rejection_batch(
        task_id=task_id,
        source=source,
        events=[
            {
                "reviewer": "fast-hard-gate",
                "category": "fast-gate",
                "reason": f"{error}: rejected; chars={chars}.",
                "suggestion": "只重写当前失败段；保留已经通过的段落，不得整章洗稿。",
                "excerpt": "",
            }
            for error in errors
        ],
    )


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
- 不补造精确时辰、请假、腿疼、封条、口供记录等冻结材料没有的事实。
- 陈安不替周虎审讯，不定罪，不猜孙成动机。
- 周虎短、直接，以控现场和复核建立权力，不说办案金句。
"""


def _part1_instruction(skill: str, errors: list[str] | None = None) -> str:
    retry = ""
    if errors:
        retry = "\n上一版前半段被打回：" + ", ".join(errors)
    return _shared(skill) + f"""
【只写前半章，目标 1350—1550 字】
从第一章末尾刘旺抱柴、陈安说“问你件事”、刘旺答“嗯”直接接。
这一段只完成刘旺分层口供，到“袋子后来不见了”为止；不要找出粮袋，不要过秤，不要官斗，不要马二死讯。

必须按以下话轮顺序分别发生，不能合并：
1. 刘旺先把车说成谁都能推、天天都用，回避异常；
2. 陈安只指出一个可验证异常，赵六去叫/让人叫周虎；
3. 周虎到场，先看车轮、车辙、刘旺左脚鞋印和路线；
4. 周虎问“昨夜这车是不是你推过”，刘旺只答“推过一趟”；
5. 周虎另问“谁让你推的”，刘旺只答“孙成/孙库吏”；
6. 周虎另问“他给了你什么/你拿他钱没有”，刘旺只答“五文”；
7. 周虎另问“袋子放哪儿”，刘旺答“后厨侧门”；
8. 周虎再问“后来呢”，刘旺才说今早还在，后来不见了。

写动作、等待、站位、伤势和现场声响，不能写成问卷。
刘旺可以回避、停顿、顶一句，但不能跪地痛哭。
只输出小说正文，不要标题。{retry}
"""


def _part2_instruction(skill: str, part1_tail: str, errors: list[str] | None = None) -> str:
    retry = ""
    if errors:
        retry = "\n上一版后半段被打回：" + ", ".join(errors)
    return _shared(skill) + f"""
【只写后半章，目标 1450—1650 字】
下面是已经通过的前半章末尾，只负责承接，不得重复审刘旺：
--- 前半章尾 ---
{part1_tail}
--- 前半章尾结束 ---

后半章固定顺序：
1. 周虎控制刘旺留在现场/值房，由皂役看住，不再重复问推车、孙成、五文；
2. 众人沿已有痕迹搜索，在木棚后旧木板堆旁找到昨日破口粮袋；
3. 刘旺只需确认一句“不是我昨夜放的地方”，不得再重新口供；
4. 周虎按程序让皂役/库房人把袋子抬上秤，只确认“重量对不上”，不得报任何斤两；
5. 周虎再调昨夜入库记录，记录只说明昨夜按官斗实量后的数目，不写总斗数；
6. 取昨夜同口径官斗，由皂役/库房程序复量；
7. 只落一个结论：“短三斗一升”，不要补总数、剩余数，不做换算；
8. 周虎封存粮袋和记录，只确认“袋子被二次移动、分量短了”，不得定性谁偷、怎么偷；
9. 人物刚消化压力，才有皂役跑来只报一句：“马二死了。”或“找到时已经没气。”
10. 死讯后立即收章，一个字也不要交代发现地点、叫门、巷子、外墙、尸体、鞋底、雨水、伤口。

不要让孙成本人出场。
不要重复“五文钱”“谁让你推”这些已经完成的话轮。
只输出小说正文，不要标题。{retry}
"""


async def _run_writer(task_id: int, stage: str, content: str, instruction: str):
    return await _run_step(
        task_id=task_id,
        role="writer",
        stage=stage,
        mode="continue",
        content=content,
        instruction=instruction,
    )


async def _generate_part1(task_id: int, prior: str, skill: str) -> str:
    result = await _run_writer(
        task_id,
        "chapter-02-fast-part1",
        prior[-2600:],
        _part1_instruction(skill),
    )
    text = result.content.strip()
    errors = _part1_errors(text)
    if errors or len(text) < 1100 or len(text) > 1750:
        errors = errors + ([f"p1-length-{len(text)}"] if len(text) < 1100 or len(text) > 1750 else [])
        _record_reject(task_id, "AUTO_FAST_PART1", errors, len(text))
        skill = _writer_skill_excerpt(task_id)
        result = await _run_writer(
            task_id,
            "chapter-02-fast-part1-rewrite",
            prior[-2600:],
            _part1_instruction(skill, errors),
        )
        text = result.content.strip()
        errors = _part1_errors(text)
    if errors:
        raise RuntimeError("part1 failed hard gates: " + ",".join(errors))
    return text


async def _generate_part2(task_id: int, part1: str, skill: str) -> str:
    result = await _run_writer(
        task_id,
        "chapter-02-fast-part2",
        part1[-1800:],
        _part2_instruction(skill, part1[-1600:]),
    )
    text = result.content.strip()
    errors = _part2_errors(text)
    if errors or len(text) < 1200 or len(text) > 1850:
        errors = errors + ([f"p2-length-{len(text)}"] if len(text) < 1200 or len(text) > 1850 else [])
        _record_reject(task_id, "AUTO_FAST_PART2", errors, len(text))
        skill = _writer_skill_excerpt(task_id)
        result = await _run_writer(
            task_id,
            "chapter-02-fast-part2-rewrite",
            part1[-1800:],
            _part2_instruction(skill, part1[-1600:], errors),
        )
        text = result.content.strip()
        errors = _part2_errors(text)
    if errors:
        raise RuntimeError("part2 failed hard gates: " + ",".join(errors))
    return text


async def main() -> int:
    init_db()
    project_id, chapter_id = create_project()
    task_id = _create_task(
        project_id=project_id,
        chapter_id=chapter_id,
        goal=GOAL,
        instruction="第二章约3000字：AGNES两段独立生成、独立硬门禁、只重写失败段。",
    )
    keep_generation_skills_lean(task_id)

    prior = CHAPTER_ONE.read_text(encoding="utf-8")
    skill = _writer_skill_excerpt(task_id)

    part1 = await _generate_part1(task_id, prior, skill)
    skill = _writer_skill_excerpt(task_id)
    part2 = await _generate_part2(task_id, part1, skill)

    text = (part1.rstrip() + "\n\n" + part2.lstrip()).strip()
    global_errors = _global_errors(text)
    usable = _chapter_text_is_usable(text)

    status = "awaiting_approval" if usable and not global_errors else "reviewed"
    if global_errors:
        _record_reject(task_id, "AUTO_FAST_GLOBAL", global_errors, len(text))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "chapter-02-fast-candidate.md").write_text(
        "# 第二章 谁让你推的车\n\n" + text + "\n",
        encoding="utf-8",
    )

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
        "hard_gate_ok": not global_errors,
        "hard_gate_errors": global_errors,
        "chars": len(text),
        "target_chars": 3000,
        "part1_chars": len(part1),
        "part2_chars": len(part2),
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
