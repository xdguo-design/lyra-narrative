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
        "昨夜入库记录是五斗": "measurement-arithmetic-risk",
        "一斗四升": "measurement-arithmetic-risk",
        "心里清楚": "author-summary",
        "必然有联系": "author-summary",
        "意思都懂": "author-summary",
        "散豆": "grain-type-drift",
        "豆粕": "grain-type-drift",
        "小麦": "grain-type-drift",
        "负责看库": "ma-er-role-drift",
        "油灯": "invented-time-object",
        "抽油烟": "anachronism",
        "东库": "wrong-location",
        "塞在我耳朵": "impossible-money-action",
        "刘旺跪": "overdramatic-confession",
        "周虎是个精瘦": "character-card-drift",
        "周虎身材精瘦": "character-card-drift",
        "不存在误差": "author-absolute-claim",
        "一个字也不许提": "zhouhu-improper-silencing",
    }
    for marker, error in forbidden.items():
        if marker in text:
            errors.append(error)

    if re.search(r"(?:\\d+|[一二三四五六七八九十百]+)\\s*斤", text):
        errors.append("measurement-drift")

    if re.search(
        r"陈安.{0,30}(?:接过|拿起|提起).{0,10}官斗|"
        r"陈安.{0,30}(?:放上|放在|挂上).{0,8}秤|"
        r"陈安.{0,20}(?:读数|复量)",
        text,
    ):
        errors.append("chen-an-official-measurement")

    shortage_at = text.find("短三斗一升")
    death_message_at = text.find("马二死了")
    if death_message_at < 0:
        death_message_at = text.find("马二已经死")
    if death_message_at < 0:
        death_message_at = text.rfind("马二")

    if shortage_at >= 0 and death_message_at >= 0 and shortage_at > death_message_at:
        errors.append("death-before-shortage")

    pushed_at = text.find("推过")
    sun_at = text.find("孙成")
    five_at = text.find("五文")
    missing_at = text.find("不见")
    if min(pushed_at, sun_at, five_at, missing_at) >= 0:
        if not (pushed_at < sun_at < five_at < missing_at):
            errors.append("disclosure-order")

    who_q = max(text.find("谁让你推"), text.find("谁叫你推"))
    benefit_q = max(
        text.find("给了你什么"),
        text.find("给你什么"),
        text.find("拿他钱"),
        text.find("拿没拿好处"),
        text.find("拿了什么好处"),
    )
    side_door_at = text.find("后厨侧门")
    later_q = max(text.find("后来呢"), text.find("后来怎么"))
    if min(pushed_at, who_q, sun_at, benefit_q, five_at, side_door_at, later_q, missing_at) >= 0:
        if not (
            pushed_at < who_q < sun_at < benefit_q < five_at
            < side_door_at < later_q < missing_at
        ):
            errors.append("disclosure-turn-order")
    else:
        errors.append("missing-disclosure-turn")

    if five_at >= 0 and (benefit_q < 0 or benefit_q > five_at):
        errors.append("five-wen-without-question")

    scale_at = max(text.find("抬上秤"), text.find("挂上秤"), text.find("上秤"))
    weight_bad_at = max(text.find("重量对不上"), text.find("分量对不上"), text.find("轻了"))
    official_dou_at = text.find("官斗")
    if min(scale_at, weight_bad_at, official_dou_at, shortage_at) >= 0:
        if not (scale_at < weight_bad_at < official_dou_at < shortage_at):
            errors.append("measurement-sequence")
    else:
        errors.append("missing-measurement-sequence")

    found_location_at = max(text.find("旧木板"), text.find("木板堆"))
    not_my_place_at = max(
        text.find("不是我昨夜放"),
        text.find("不是我放的地方"),
        text.find("我放在侧门"),
    )
    if found_location_at < 0 or not_my_place_at < 0:
        errors.append("bag-relocation-not-explicit")

    if death_message_at >= 0:
        death_tail = text[death_message_at:]
        for marker in (
            "他家",
            "叫门",
            "开门",
            "巷",
            "外墙",
            "墙边",
            "鞋底",
            "尸体",
            "伤口",
            "地上躺",
            "雨水",
        ):
            if marker in death_tail:
                errors.append("next-chapter-location-leak")
                break

    sun_mentions = [
        marker
        for marker in (
            "孙成走",
            "孙成站",
            "孙成从",
            "孙成缓缓",
            "孙成看",
            "孙成脸",
            "孙成手",
        )
        if marker in text
    ]
    if sun_mentions:
        errors.append("sun-cheng-appears")

    return sorted(set(errors))


def _instruction(
    skill: str,
    rejection_notes: list[str] | None = None,
    reader_feedback: str = "",
) -> str:
    rejection_block = ""
    if rejection_notes:
        rejection_block += (
            "\n\n上一版被打回，必须整章重写，禁止局部修补。"
            "\n打回标签：" + ", ".join(rejection_notes)
        )
    if reader_feedback:
        rejection_block += (
            "\n\n上一版 Reader blocking：\n"
            + reader_feedback[:5000]
        )

    return f"""第二章《谁让你推的车》。只输出完整小说正文，不要标题、提纲、解释、审稿意见。
必须写足约 3000 字：请按 3300—3600 个中文字符来写，避免模型压缩后不足；成稿验收范围 2800—3600。

【当前 Writer Skill 最近学习】
{skill}

【承接】
第一章结尾：刘旺抱着劈柴出来，看见陈安、赵六在看泔水车。陈安转身说“问你件事”，刘旺答“嗯”。从这里自然接。

【本章冻结事实】
- 时间仍是第一章同一个上午，只能用“昨夜/今早/刚才”等已有层级，不得补造子时、卯时、申时、三更。
- 核心对象始终是昨日赈粮中那只破口粮袋。
- 孙成是西库库吏；周虎是皂班班头；马二是昨日运粮车夫。
- 刘旺左脚旧布鞋后跟缺一角；不要把缺口写到右脚。
- 周虎肩背厚、站着像堵门，不要写成精瘦文弱，也不要凭空给他武器。
- 刘旺昨夜受孙成指使，用后厨小车把破口粮袋从西库附近移到后厨侧门；收了五文钱；之后粮袋又被别人移动。
- 孙成本章本人不出场，不旁观、不提灯、不与周虎或陈安对质；只作为刘旺口供里的名字。
- 不得新增孙成请假、腿疼、失踪、外出等状态。
- 赵六没有库账、回票、折纸、抄本、小册子；账目和量具只能由周虎按县衙程序调取。
- 不得新造“记录显示昨夜有人搬动”这种自动送答案的证据。
- 粮食类型统一写“粮/米/粟米”，不要出现豆、豆粕、小麦。

【篇幅与场景节拍】
正文不要写小标题，但要把约 3000 字均匀花在下面 8 个场面，不能用几句话跳完：
1. 第一章接口：刘旺先回避，把车说成谁都能推；
2. 陈安只指出一两个可验证异常，赵六去/让人去叫周虎，现场有等待和动作；
3. 周虎到场，亲自复核车轮、车辙、刘旺鞋印/路线；
4. 刘旺分层承认推车→孙成→五文→袋子后来不见；
5. 众人按痕迹搜索，找到被再次移动的破口粮袋，并确认当前位置与刘旺昨夜放下处不同；
6. 周虎按程序调昨夜入库记录，先过秤，只确认“重量对不上”；
7. 再用昨夜相同口径官斗复量，只落地“短三斗一升”，随后封存粮袋和记录；
8. 人物刚消化压力，才有人来报“马二死了/找到时没气”，立即收章。

【刘旺披露顺序：采用固定最小话轮骨架】
下面 8 个话轮必须按顺序分别发生，不能合并回答；可在句间插入动作，但不要改变信息顺序：
1. 周虎问：昨夜这车是不是你推过；
2. 刘旺只答：推过一趟；
3. 周虎另问：谁让你推的；
4. 刘旺只答：孙成/孙库吏；
5. 周虎另问：他给了你什么/你拿他钱没有；
6. 刘旺只答：五文；
7. 周虎另问：袋子放哪儿，刘旺答：后厨侧门；
8. 周虎再问后来呢，刘旺才说今早还在、后来不见了。
禁止在第2步一次性说出孙成；禁止在第4步顺手说五文；禁止第二次重复审同一套口供。

【调查与权限】
- 陈安一次只说一个能验证的事实，不替周虎审人，不指控孙成动机，不说“你是想掩盖”等定性话。
- 赵六主要表现风险判断、县衙经验和收声，不凭空拿账。
- 周虎先控现场，再拆事实；短、直接，以动作复核，不说金句。
- 刘旺口供中昨夜只说“放在后厨侧门”；找到粮袋时必须在另一个明显不同的位置。找到后刘旺不得改口说“我昨夜其实就放在这里”。
- 昨夜记录只写“记录着这袋按官斗实量后的数目”，不要写任何斤两数字，也不要补总斗数。
- 正式秤重、官斗复量由周虎指挥皂役/库房程序执行；陈安只观察。
- 必须先出现“抬上秤/挂上秤”并由周虎或皂役确认“重量对不上”；这一步不得报数字。
- 随后才取官斗，按昨夜记录同口径复量。
- 最终只说“短三斗一升”，不要补总斗数、剩余斗数做算术。
- 只能确认当前事实，不得提前定性谁偷、怎么偷。

【语言与连续性】
- 用走路、搬东西、等人、复核、找袋、开袋、过秤、复量、院内声响推进调查；禁止出现“抽油烟”等现代厨房词。
- 禁止作者总结腔、规章腔、金句腔、问卷式连续问答。
- 人物手中物、站位、伤势必须连续；柴放下后不能自动回手里。
- 刘旺怕事但先自保，不跪地痛哭、不突然全盘招供；五文钱只能正常递到手里/塞到手里，禁止荒唐动作。
- 周虎不会在关键粮案口供刚压实后直接放刘旺走，更不会命令他“一个字也不许提”；可以让皂役把刘旺留在值房/现场等候后续问话。
- 马二始终是昨日运粮车夫，不得写成看库人、值守人。

【章末硬边界】
先完成粮案全部步骤，再进死讯。
死讯只能写“马二死了”或“找到时已经没气”，出现后立即收章。
禁止交代在哪里找到、谁去叫门、门窗状态、巷子、外墙、尸体姿态、鞋底、雨水、伤口和任何第三章现场物证。
{rejection_block}
"""


def _record_gate_reject(
    task_id: int,
    errors: list[str],
    chars: int,
    stage: str,
) -> None:
    if not errors:
        return
    record_rejection_batch(
        task_id=task_id,
        source="AUTO_FAST_GATE",
        events=[
            {
                "reviewer": "fast-hard-gate",
                "category": "fast-gate",
                "reason": f"{error}: fast chapter gate rejected {stage}; chars={chars}.",
                "suggestion": "整章重写；严格遵守冻结事实、披露顺序、计量口径、人物权限和章末边界。",
                "excerpt": "",
            }
            for error in errors
        ],
    )


def _record_reader_reject(
    task_id: int,
    review_text: str,
    stage: str,
) -> None:
    record_rejection_batch(
        task_id=task_id,
        source="AUTO_FAST_READER",
        events=[
            {
                "reviewer": "fast-reviewer",
                "category": "fast-reader-reject",
                "reason": f"{stage} rejected chapter: {review_text[:1100]}",
                "suggestion": "整章重写，逐条消除 Reader blocking；不得局部修补。",
                "excerpt": "",
            }
        ],
    )


async def _generate(
    task_id: int,
    prior: str,
    skill: str,
    stage: str,
    rejection_notes: list[str] | None = None,
    reader_feedback: str = "",
):
    return await _run_step(
        task_id=task_id,
        role="writer",
        stage=stage,
        mode="continue",
        content=prior[-3000:],
        instruction=_instruction(
            skill,
            rejection_notes=rejection_notes,
            reader_feedback=reader_feedback,
        ),
    )


async def _fast_review(task_id: int, text: str, stage: str):
    return await _run_step(
        task_id=task_id,
        role="fast-reviewer",
        stage=stage,
        mode="check",
        content=text,
        instruction="""你是第二章快速验收 Reader，只验收，不润色，不替作者补设定。

逐项检查：
1. 是否自然承接第一章，调查是否像现场发生，而非问卷式一问一答；
2. 刘旺是否严格按：回避→只认推过→被问才说孙成→另被问好处才说五文→最后才说袋子不见；
3. 陈安是否越权定罪、猜动机、替周虎审讯；
4. 赵六是否凭空拿账、回票、小册子；
5. 孙成本人是否错误出场；
6. 是否补造精确时辰、请假、腿疼、封条、口供、记录等冻结事实没有的内容；
7. 程序是否为：找到被二次移动的粮袋→调昨夜记录→秤只确认重量异常→官斗同口径复量→短三斗一升→封存；
8. 是否出现斤两/斗升混用或算术自相矛盾；
9. 对话是否口语自然，是否有作者总结腔、规章腔、金句腔、过度戏剧化下跪痛哭；
10. 马二是否始终是昨日运粮车夫；
11. 章末是否只收到“马二死了/找到时没气”，没有地点、叫门、巷子、外墙、尸体、鞋底、雨水、伤口等第三章信息；
12. 是否有手中物、站位、粮食品类、时间线连续性错误。

严格输出：
FAST_CHAPTER_REVIEW_V1
VERDICT: PASS 或 VERDICT: FAIL
【Blocking】PASS 时写 NONE；FAIL 时逐条写：标签｜逐字片段｜为什么不行｜整章重写时如何避免。
只要存在一条 blocking，VERDICT 必须 FAIL。""",
    )


def _review_passed(review_text: str) -> bool:
    return "VERDICT: PASS" in review_text.upper()


def _evaluate(text: str) -> tuple[list[str], bool, bool]:
    gate_errors = _hard_gate_errors(text)
    target_ok = 2800 <= len(text) <= 3600
    usable = _chapter_text_is_usable(text)
    return gate_errors, target_ok, usable


async def main() -> int:
    init_db()
    project_id, chapter_id = create_project()
    task_id = _create_task(
        project_id=project_id,
        chapter_id=chapter_id,
        goal=GOAL,
        instruction="第二章快速验收流水线：约3000字，Writer硬门禁+快速Reader+自动Skill学习。",
    )
    keep_generation_skills_lean(task_id)

    prior = CHAPTER_ONE.read_text(encoding="utf-8")
    skill = _writer_skill_excerpt(task_id)

    draft = await _generate(
        task_id,
        prior,
        skill,
        "chapter-02-fast-draft",
    )
    text = draft.content.strip()
    gate_errors, target_ok, usable = _evaluate(text)

    first_rejects = list(gate_errors)
    if not target_ok:
        first_rejects.append(f"length={len(text)} target=2800..3600")
    if not usable:
        first_rejects.append("chapter-text-unusable")

    if first_rejects:
        _record_gate_reject(
            task_id,
            first_rejects,
            len(text),
            "chapter-02-fast-draft",
        )
        skill = _writer_skill_excerpt(task_id)
        rewrite = await _generate(
            task_id,
            prior,
            skill,
            "chapter-02-fast-rewrite-gate",
            rejection_notes=first_rejects,
        )
        text = rewrite.content.strip()
        gate_errors, target_ok, usable = _evaluate(text)

    review_text = ""
    final_review_ok = False

    if usable and target_ok and not gate_errors:
        review = await _fast_review(
            task_id,
            text,
            "chapter-02-fast-review",
        )
        review_text = review.content.strip()
        final_review_ok = _review_passed(review_text)

        if not final_review_ok:
            _record_reader_reject(
                task_id,
                review_text,
                "chapter-02-fast-review",
            )
            skill = _writer_skill_excerpt(task_id)
            rewrite = await _generate(
                task_id,
                prior,
                skill,
                "chapter-02-fast-rewrite-reader",
                rejection_notes=["fast-reader-reject"],
                reader_feedback=review_text,
            )
            text = rewrite.content.strip()
            gate_errors, target_ok, usable = _evaluate(text)

            if usable and target_ok and not gate_errors:
                final_review = await _fast_review(
                    task_id,
                    text,
                    "chapter-02-fast-final-review",
                )
                review_text = final_review.content.strip()
                final_review_ok = _review_passed(review_text)
                if not final_review_ok:
                    _record_reader_reject(
                        task_id,
                        review_text,
                        "chapter-02-fast-final-review",
                    )
            else:
                final_review_ok = False

    final_rejects = list(gate_errors)
    if not target_ok:
        final_rejects.append(f"length={len(text)} target=2800..3600")
    if not usable:
        final_rejects.append("chapter-text-unusable")
    if usable and target_ok and not gate_errors and not final_review_ok:
        final_rejects.append("fast-reader-final-reject")
    if final_rejects:
        _record_gate_reject(
            task_id,
            final_rejects,
            len(text),
            "chapter-02-fast-final",
        )

    status = (
        "awaiting_approval"
        if usable and target_ok and not gate_errors and final_review_ok
        else "reviewed"
    )

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
        "target_ok": target_ok,
        "hard_gate_ok": not gate_errors,
        "hard_gate_errors": gate_errors,
        "fast_review_ok": final_review_ok,
        "fast_review": review_text[:5000],
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
