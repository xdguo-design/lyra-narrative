from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from app.db import connect, init_db
from app.services.book_pipeline import _chapter_text_is_usable, _create_task
from app.services.default_skills import BUILTIN_WRITING_SKILL_NAME
from app.services.full_novel_pipeline import _run_review_round
from app.services.pipeline_metrics import (
    PIPELINE_VERSION,
    epoch_ms,
    finish_pipeline_run,
    record_local_event,
    start_pipeline_run,
    sync_agent_run_events,
)
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
        "半夜": "invented-time-detail",
        "为何替人挪粮": "disclosure-answer-leak",
        "你替谁挪的粮": "disclosure-answer-leak",
        "昨夜这儿没人推过车": "evidence-overclaim",
        "只有你这双鞋印": "evidence-overclaim",
        "后厨有虫": "invented-motive",
        "马二一个人扛不动": "invented-maer-fact",
        "侧门那间小屋": "invented-location-detail",
        "草帘": "invented-location-detail",
        "刚才我想收钱": "money-continuity-drift",
        "麻绳早已磨断": "invented-bag-evidence",
        "昨日上架时": "invented-bag-history",
        "空了一半": "invented-quantity-visual",
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
【第一段：口供，目标 1150—1300 个中文字符】
从第一章末尾刘旺抱柴、陈安说“问你件事”、刘旺答“嗯”直接接。
本段只写口供，不找粮袋、不称重、不取记录、不出现马二死讯。

必须按这个披露顺序写：
1. 刘旺先回避，只说泔水车谁都能推。
2. 陈安只能指出“右轮更深/更磨、墙根有缺角左脚印、车辙像这辆车”这类可见异常；只能说“像”，不得说“就是刘旺”“只有刘旺”“昨夜没人推过”。
3. 赵六去叫周虎。周虎到场后亲自看车轮、车辙、刘旺左脚鞋后跟，再问昨夜是否推过。
4. 刘旺被证据压住后，只承认“昨夜推过一趟”。不要说半夜，不要补时辰。
5. 周虎另起一问，只能问“谁叫你推的？”或同义自然说法；绝不能问“为何替人挪粮”“你替谁挪的粮”，不能先说孙成。刘旺这时才吐出“孙成”。
6. 周虎再问“他凭什么使唤你？”刘旺先回避，不要主动补孙成的理由。
7. 周虎再追“白替他跑这一趟？”刘旺抓紧柴、犹豫、自保后才说“五文”。不得出现报酬/多少钱之类问卷词。
8. 周虎最后问袋子放哪；刘旺答“后厨侧门”。再追一句后来怎样，刘旺才说袋子后来不见了。
9. 孙成只作为名字出现，不得给他补“有虫、马二扛不动、空屋、草帘”等理由或安排。

对白要短，有停顿和身体反应；不要把八步写成八个整齐问答。
最后停在“袋子后来不见了”这个事实。
只输出正文。"""


def _part2_instruction(skill: str, part1_tail: str) -> str:
    return _shared(skill) + f"""
【第二段：找袋并称重，目标 900—1050 个中文字符】
下面是第一段末尾，只承接，不重复口供：
--- 第一段尾 ---
{part1_tail}
--- 第一段尾结束 ---

只完成以下内容，做到“重量对不上”为止：
1. 周虎留住刘旺，由皂役看着。若让刘旺同行，必须写清皂役带着他，不得出现“挣脱”。
2. 陈安、赵六、周虎沿第一章已经出现的窄车辙、木棚、蓝麻线方向复查；不要凭空新增拖痕、切痕、缝线变化。
3. 在木棚后旧木板堆旁找到昨日那只破口粮袋。只写已知破口/蓝线等既有特征，不新增“麻绳断了、重新缝过、空了一半”等物证。
4. 刘旺只确认一句意思：这不是他昨夜放袋子的地方。不要补“小屋、草帘、土堆”等新地点。
5. 周虎让皂役或库房人把袋子上秤。秤的结果只能落一句明确对白：“重量对不上。”
6. 不报斤两，不出现官斗、入库记录、马二、短三斗一升；这些全部留给第三段。

搜索要有一点现场阻力和确认过程，但不要故意拖长。
本段最后一句必须是：“重量对不上。”
只输出正文。"""


def _part3_instruction(skill: str, prior_tail: str) -> str:
    return _shared(skill) + f"""
【第三段：记录复量与死讯，目标 900—1050 个中文字符】
下面是第二段末尾，从“重量对不上”之后继续，不重复搜索和称重：
--- 第二段尾 ---
{prior_tail}
--- 第二段尾结束 ---

固定顺序：
1. 周虎这时才让人去取昨夜入库记录；记录只写昨夜用同口径官斗登记的斗数，不写斤两。
2. 在取记录/核记录时自然带出一次“昨日运粮车夫马二”，只说明身份，不暗示他出事。
3. 再取昨夜同口径官斗，由皂役/库房人按记录复量。不要逐斗报数，不要引入斛、皮重、毛重。
4. 复量结束后必须逐字出现一次：“短三斗一升。”
5. 周虎只确认分量短了、袋子位置变了；不定性谁偷、怎么偷，不猜孙成动机。
6. 粮袋与记录分开收好留查；可写“封存”，不得出现“封条、油布包裹、严令拆阅”等新增程序细节。
7. 最后才有人进院，只报一句：“马二死了。”；只有正文已经达到至少 2700 个中文字符时，才允许进入这一步。
8. “马二死了。”必须是全章最后一句，后面绝不再写任何反应、地点、尸体信息或时间锚点。

只输出正文。"""


def _full_chapter_instruction(skill: str) -> str:
    return _shared(skill) + """
【整章一次生成｜硬长度 2850—3250 个中文字符】
从第一章末尾刘旺抱柴、陈安说“问你件事”、刘旺答“嗯”直接接。整章一次写完，不拆段输出，但必须严格保持下面三阶段顺序。
硬长度要求：正文少于 2700 个中文字符时不得结束生成，也不得提前写章末死讯；请在内部自行检查长度，不输出计数。若剧情节点已经写完但长度不足，只能用既有现场动作、空间阻力、人物迟疑、观察与自然过渡补足，绝不能新增事实。

阶段一｜口供：
1. 刘旺先回避，只说泔水车谁都能推。
2. 陈安只能指出右轮更深/更磨、墙根有缺角左脚印、车辙像这辆车等可见异常，只能说“像”。
3. 赵六去叫周虎；周虎亲自看车轮、车辙、刘旺左脚鞋后跟后再问。
4. 刘旺先只承认昨夜推过一趟；周虎另起一问“谁叫你推的？”后，刘旺才说“孙成”。
5. 周虎追问后，刘旺先回避，再在“白替他跑这一趟？”的压力下才说“五文”。
6. 刘旺最后交代袋子放在“后厨侧门”，后来不见了。孙成本章本人不出场，也不得补动机。

阶段二｜找袋并称重：
1. 留住刘旺并由皂役看着。
2. 陈安、赵六、周虎沿既有窄车辙、木棚、蓝麻线复查。
3. 在木棚后旧木板堆旁找到昨日破口粮袋，只使用既有破口/蓝线特征。
4. 刘旺只确认这不是他昨夜放袋子的地方。
5. 上秤只得到一句明确结论：“重量对不上。”此处不报斤两，不提前写官斗或具体短缺。

阶段三｜记录、官斗复量与死讯：
1. 到这时才取昨夜入库记录；记录只写同口径官斗登记的斗数。
2. 自然带出“昨日运粮车夫马二”的身份，不暗示死亡。
3. 用昨夜同口径官斗复量，不逐斗报数。
4. 复量后必须逐字出现一次：“短三斗一升。”
5. 只确认分量短了、袋子位置变了，不定性谁偷、怎么偷，不猜孙成动机。
6. 粮袋与记录分开收好留查，可写“封存”，不得发明封条等程序细节。
7. 最后才有人进院，只报一句：“马二死了。”
8. “马二死了。”必须是全章最后一句，后面绝不再写任何反应、地点、尸体信息或时间锚点。

写作要求：
- 三阶段之间用自然动作与空间移动过渡，不要写成三份报告。
- 对白短、有人物压力和身体反应，避免整齐问答。
- 不得新增冻结事实之外的人物、物证、精确时辰、地点、记录、伤病或解释性证据。
- 只输出完整第二章正文，不要标题、提纲、说明。
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


def _length_distance(text: str) -> int:
    length = len(text)
    if 2700 <= length <= 3400:
        return 0
    if length < 2700:
        return 2700 - length
    return length - 3400


def _accept_length_repair(original: str, repaired: str) -> bool:
    repaired = repaired.strip()
    return bool(repaired) and _length_distance(repaired) < _length_distance(original)


async def _repair_length_if_needed(task_id: int, text: str) -> str:
    if 2700 <= len(text) <= 3400:
        return text

    is_short = len(text) < 2700
    target = "2850—3150" if is_short else "3000—3300"
    required_growth = max(0, 2850 - len(text))
    mode = "expand" if is_short else "polish"
    repair_action = (
        f"当前正文只有 {len(text)} 个字符，是过短骨架，不是成稿。"
        f"必须至少净增加约 {required_growth} 个字符，并把完整正文扩写到 {target} 个中文字符。"
        "不得原样返回，不得只做措辞润色，不得提前结束。"
        if is_short
        else f"当前正文过长，请在保留全部冻结事实的前提下压缩到 {target} 个中文字符。"
    )
    result = await _run_step(
        task_id=task_id,
        role="writer-retry",
        stage="chapter-02-length-repair",
        mode=mode,
        content=text,
        instruction=f"""{repair_action}
输出前请在内部检查长度；不要输出字符统计、说明或修改理由。
只允许补足或压缩现场动作、空间阻力、人物犹豫和已有线索之间的自然过渡，不得新增事实、人物、物证、精确时间、地点或解释性证据。

硬约束：
- 保持既有剧情顺序与冻结事实不变。
- 刘旺必须分层交代：先认昨夜推车，再交代孙成，再经过独立压力节拍才交代五文。
- 不得由周虎先说出孙成，不得出现“谁给的报酬/报酬多少/拿了多少钱”。
- 找袋子只能沿既有车辙/现场搜索自然推进，不得新增封口切痕、重新缝线等未冻结物证。
- 先明确“重量对不上”，再取昨夜同口径官斗记录复量，最后只得出“短三斗一升”。
- 不把短缺直接定性为偷窃。
- 不出现皮重、封条、精确时辰、作者元分析。
- 若原文过短，在正文达到至少 2700 个中文字符之前不得写“马二死了。”；必须先把前三阶段完整展开。
- 最后一句必须且只能是：“马二死了。”
- 只输出完整修订后的正文，不要解释。
""",
    )
    repaired = result.content.strip()
    if not _accept_length_repair(text, repaired):
        print(
            f"[length-repair] REJECT_NO_IMPROVEMENT original_chars={len(text)} "
            f"repaired_chars={len(repaired)} "
            f"original_distance={_length_distance(text)} "
            f"repaired_distance={_length_distance(repaired)}",
            flush=True,
        )
        return text
    print(
        f"[length-repair] ACCEPT_LOCAL_ONLY original_chars={len(text)} "
        f"repaired_chars={len(repaired)} "
        f"remaining_distance={_length_distance(repaired)}",
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
    pipeline = start_pipeline_run(
        task_id=task_id,
        chapter_id=chapter_id,
        chapter_number=2,
        pipeline_version=PIPELINE_VERSION,
    )
    pipeline_run_id = int(pipeline["pipeline_run_id"])

    prior = CHAPTER_ONE.read_text(encoding="utf-8")
    skill = _writer_skill_excerpt(task_id)

    draft_result = await _run_writer(
        task_id,
        "chapter-02-fast-draft",
        prior[-2600:],
        _full_chapter_instruction(skill),
    )
    text = draft_result.content.strip()
    draft_chars_initial = len(text)
    length_repair_triggered = not 2700 <= draft_chars_initial <= 3400
    length_gate_started_at_ms = epoch_ms()
    before_distance = _length_distance(text)
    length_gate_finished_at_ms = epoch_ms()
    text = await _repair_length_if_needed(task_id, text)
    record_local_event(
        pipeline_run_id=pipeline_run_id,
        stage="length-gate",
        status="triggered" if length_repair_triggered else "pass",
        started_at_ms=length_gate_started_at_ms,
        finished_at_ms=length_gate_finished_at_ms,
        chars_before=draft_chars_initial,
        chars_after=len(text),
        length_distance_before=before_distance,
        length_distance_after=_length_distance(text),
        trigger_reason=(
            "outside_2700_3400" if length_repair_triggered else "within_2700_3400"
        ),
        metadata={
            "repair_accepted": len(text) != draft_chars_initial,
            "target_min": 2700,
            "target_max": 3400,
        },
    )

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
    review_group_started_at_ms = epoch_ms()
    review_outputs, has_review_blocking = await _run_review_round(
        task_id=task_id,
        draft=text,
        context=context,
        round_no=1,
        auto_learn=False,
        retry_failed_reviewers=1,
    )
    review_group_finished_at_ms = epoch_ms()
    record_local_event(
        pipeline_run_id=pipeline_run_id,
        stage="review-group",
        status="completed",
        started_at_ms=review_group_started_at_ms,
        finished_at_ms=review_group_finished_at_ms,
        trigger_reason="three_reviewers_parallel_with_targeted_retry",
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
    finalize_started_at_ms = epoch_ms()

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
    review_retry_count = sum(
        1 for row in runs if "-retry" in str(row["stage"] or "")
    )
    length_repair_count = sum(
        1 for row in runs if str(row["stage"] or "") == "chapter-02-length-repair"
    )

    sync_agent_run_events(
        pipeline_run_id=pipeline_run_id,
        task_id=task_id,
    )
    finalize_finished_at_ms = epoch_ms()
    finalize_ms = max(0, finalize_finished_at_ms - finalize_started_at_ms)
    record_local_event(
        pipeline_run_id=pipeline_run_id,
        stage="finalize",
        status="completed",
        started_at_ms=finalize_started_at_ms,
        finished_at_ms=finalize_finished_at_ms,
    )
    pipeline_metrics = finish_pipeline_run(
        pipeline_run_id=pipeline_run_id,
        length_repair_triggered=length_repair_triggered,
        finalize_ms=finalize_ms,
        draft_chars_initial=draft_chars_initial,
        draft_chars_final=len(text),
        blocking_count=sum(
            1 for item in findings if str(item.get("severity")) == "blocking"
        ),
        hard_gate_count=len(hard_errors),
    )

    manifest = {
        "task_id": task_id,
        "pipeline_metrics": pipeline_metrics,
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
        "local_retry_policy": {
            "reviewer_failed": "retry_failed_reviewer_once_only",
            "length_failed": "repair_current_draft_once_only",
            "rerun_writer": False,
            "rerun_successful_reviewers": False,
        },
        "review_retry_count": review_retry_count,
        "length_repair_count": length_repair_count,
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
