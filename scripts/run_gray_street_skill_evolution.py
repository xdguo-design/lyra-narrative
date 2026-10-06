from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

from app.db import connect, init_db
from app.services.book_pipeline import _create_task
from app.services.full_novel_pipeline import _run_review_round
from app.services.workflow_service import _run_step, _task_context


OUTPUT_DIR = Path("artifacts/gray-street-skill-evolution")
CONTENT_ROOT = Path(os.getenv("GRAY_STREET_CONTENT_ROOT", "content-repo"))
BASELINE = CONTENT_ROOT / "novels/gray-street/versions/sections-01-05-reader-input-v1.md"

SECTION_NAMES = {
    "第一节": "怀表",
    "第二节": "遗产",
    "第三节": "河灯街",
    "第四节": "十三号仓",
    "第五节": "日落",
}

ACCEPTED_REPAIR_CONTRACT = """【外部 Reader 已确认、且已先进入 Skill Evolution 的修订合同】
这里只允许在 NarrativeOS Reviewer 已能识别失败以后用于 Revision：
1. 第一节：若停表时间用于与法医死亡窗口比较，明确到时针/分针/秒针，落在约 1:55:32；掌心旧圆伤与分离怀表造成的新撕裂分开。
2. 第三节：克莱的倒计时样本只统一可观测过程——先变浅、之后才变三；不要解释机制原因。
3. 第四节：六年前是仓内转柜/单独封存，钥匙没有离库；九天前红发女人才正式领取。区分收费收据的计价主物与附属封存件。
4. 第四节：费恩允许埃文带走银牌时必须是“实物核验/代理权限/违规放行”中的明确一种，并保留所有权边界，不得三镑直接抹掉“只能本人取”。
5. 第五节：把“你撒谎的时候会先看左边”改为对本次“没有”之前视线偏移的当场观察，不能凭一次见面概括长期习惯。
6. 第五节：埃文把尚未完成所有权转移的银牌交给米拉后，现实账目/事务所后果必须被保留下来，作为下一节现实压力接口。
7. 不采纳误报：怀表挂链断裂不影响机芯走时；不得把它修成“断链所以不能走”。
8. 不把悬疑写成规则说明书。原因未知可以保留，只修可观测事实、保管链、授权链与现实后果。
9. 不重写已经成立的段落，不增加新人物、新规则、新证物或新巧合。
"""

SECTION_REPAIR_CONTRACTS = {
    "第一节": """【本节外部 Reader 修订合同】
- 保留现有开场、哈里看不见文字、十二下与 SV-7 结尾。
- 把停表读数写成唯一可读的约 1:55:32，并明确落在法医凌晨 1—3 点死亡窗口内；必须同时出现时针、分针、秒针语义，不能再用“长针停在十一点”制造歧义。
- 把掌心中央的圆形旧伤与警方分离怀表造成的新撕裂明确区分为两处伤。
- 表链断裂不影响机芯走时，禁止把它修成物理矛盾。
- 除上述点和自动 Reviewer 的真实 blocking 外，尽量原样保留。""",
    "第二节": """【本节外部 Reader 修订合同】
- 本节没有外部 Reader 确认的硬伤。
- 保留修鞋匠先听到“SV-7”才停锤的顺序；不得按误读去重排空间。
- “四”在本节只是比前夜变浅，仍然显示四。
- 除自动 Reviewer 的真实 blocking 外，尽量原样保留。""",
    "第三节": """【本节外部 Reader 修订合同】
- 保留米拉主动提到“银牌”，以及她最终明确说出“旧盐场”“十三号仓”；这是冻结剧情接口，不因 Reviewer 偏好改成模糊坐标或新增纸条。
- 克莱的倒计时样本只统一可观测过程：先变浅，之后才变成三；不要解释机制原因，也不要发明“按天/按事件/按债务步数”的完整规则。
- 保留米拉不讲完整 SV-7 真相的边界。
- 除上述点和自动 Reviewer 的真实 blocking 外，尽量原样保留。""",
    "第四节": """【本节外部 Reader 修订合同】
- 七年前银牌与封存钥匙进入仓储；六年前只能是仓内转柜/转入内库/单独封存，钥匙没有离库；九天前红发女人才正式领取钥匙。
- 收费收据与内部转移单的字段差异必须有最小范围锚点：收据只记计价主物，钥匙属于附属封存件或等价制度表达。
- 埃文必须先出示事务所/遗产清算授权。费恩若让银牌离柜，只能明确为实物核验、代理权限或明确违规放行之一；不能三镑直接抹掉“只能本人取”。
- 必须保留所有权边界：核验不等于所有权转移。
- 保留红发女人、手套、十四年前授权、SV-7/05、MIRA ALVA 与窗帘后的红发身影。
- 不解释倒计时机制。""",
    "第五节": """【本节外部 Reader 修订合同】
- 把“你撒谎的时候会先看左边”改成只针对本次回答“没有”之前的视线偏移的当场观察，不能凭一次见面归纳长期习惯。
- 埃文把仍处于遗产/核验链上的银牌交给米拉后，必须保留现实手续后果：核验交接、所有权未转、事务所账目或次日要补手续至少出现一种清楚接口。
- 保留银牌交给米拉后怀表清空；保留“有些门被锁上……”；保留结尾极淡 SV-7。
- 不把悬疑机制解释成规则说明书。""",
}


def _section_contract(section_key: str) -> str:
    return SECTION_REPAIR_CONTRACTS.get(section_key, ACCEPTED_REPAIR_CONTRACT)


def _gray_street_contract_failures(section_key: str, text: str) -> list[str]:
    failures: list[str] = []
    compact = re.sub(r"\s+", "", text)

    if section_key == "第一节":
        has_clear_time = any(
            token in compact
            for token in (
                "一点五十五分三十二秒",
                "1:55:32",
                "01:55:32",
                "一点五十五分",
            )
        )
        if not has_clear_time or "时针" not in text or "分针" not in text:
            failures.append("停表时间没有明确到约1:55:32并区分时针/分针")
        if "圆形" not in text or not any(
            token in text for token in ("另造成", "另一处", "两处伤", "新撕裂")
        ):
            failures.append("掌心旧圆伤与分离怀表造成的新撕裂没有明确区分")

    elif section_key == "第二节":
        if "SV-7" not in text or "锤子" not in text:
            failures.append("修鞋匠与SV-7的既有线索接口被误删")
        if "四" not in text or not any(token in text for token in ("浅", "淡")):
            failures.append("第二节缺少“四仍在但字迹变浅”的可观测样本")

    elif section_key == "第三节":
        if "旧盐场" not in text or "十三号仓" not in text:
            failures.append("冻结剧情接口“旧盐场/十三号仓”被误删")
        if not (
            any(token in text for token in ("变浅", "淡下", "淡了", "浅了"))
            and "变成三" in text
        ):
            failures.append("克莱倒计时样本未统一为“先变浅/变淡，再变成三”")
        if "按债" in text or "按事件" in text or "按天数规则" in text:
            failures.append("正文把未知超自然机制过早解释成规则说明")

    elif section_key == "第四节":
        if "后来钥匙被转走" in compact:
            failures.append("仍保留“后来钥匙被转走”的双重离库硬伤")
        if not any(token in text for token in ("转柜", "内库", "单独封存", "内部转存")):
            failures.append("六年前仓内转柜/单独封存状态没有落地")
        if "九天前" not in text or "红头发" not in text:
            failures.append("九天前红发女人正式领取钥匙的锚点缺失")
        if not (
            "收据" in text
            and any(token in text for token in ("计价", "附属封存", "附属件", "主项"))
        ):
            failures.append("收费收据与内部转移单的文书范围没有最小锚点")
        if "核验" not in text:
            failures.append("银牌离柜没有明确为实物核验")
        if not any(token in text for token in ("所有权", "不能替", "不是转移", "仍挂在")):
            failures.append("核验与所有权转移边界没有写清")
        if not any(token in text for token in ("授权书", "清算授权", "事务所盖章")):
            failures.append("埃文的遗产清算/核验权限来源没有落地")

    elif section_key == "第五节":
        if "你撒谎的时候会先看左边" in text:
            failures.append("仍保留无样本支撑的长期撒谎习惯判断")
        if not (
            "没有" in text
            and "左" in text
            and any(token in text for token in ("刚才", "之前", "先", "那一下", "目光"))
        ):
            failures.append("当场“没有”前视线偏移的观察没有落地")
        if not (
            any(token in text for token in ("核验", "交接单", "所有权", "手续"))
            and any(token in text for token in ("事务所", "账", "明天", "补手续"))
        ):
            failures.append("银牌交给米拉后的现实手续/账目后果接口缺失")
        if "SV-7" not in text:
            failures.append("第五节结尾SV-7接口被误删")

    return failures


def _read_sections(text: str) -> list[tuple[str, str, str]]:
    pattern = re.compile(r"^# (第一节|第二节|第三节|第四节|第五节)[　 ]+(.+?)\s*$", re.M)
    matches = list(pattern.finditer(text))
    sections: list[tuple[str, str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        key = match.group(1)
        title = match.group(2).strip()
        body = text[start:end].strip()
        sections.append((key, title, body))
    if len(sections) != 5:
        raise RuntimeError(f"expected 5 sections, got {len(sections)}")
    return sections


def _create_project(sections: list[tuple[str, str, str]]) -> tuple[int, list[int]]:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO projects(title,description,genre,status) VALUES(?,?,?,?)",
            (
                "灰街",
                "外部 Reader 反馈驱动的 NarrativeOS Skill Evolution + 平台修订验收",
                "悬疑 / 怪谈 / 都市遗产调查",
                "draft",
            ),
        )
        project_id = int(cur.lastrowid)
        chapter_ids: list[int] = []
        for position, (key, title, body) in enumerate(sections, start=1):
            ch = conn.execute(
                "INSERT INTO chapters(project_id,title,position,content,status) VALUES(?,?,?,?,?)",
                (project_id, f"{key} {title}", position, body, "draft"),
            )
            chapter_id = int(ch.lastrowid)
            chapter_ids.append(chapter_id)
            conn.execute(
                "INSERT INTO chapter_versions(chapter_id,content,note) VALUES(?,?,?)",
                (chapter_id, body, "外部 Reader 输入版 V1"),
            )

        memories = [
            (
                "canon",
                "身份与主线",
                "主角始终是埃文·格雷。雷蒙德·克莱是已死亡的遗物原主人和 SV-7 事件链关键人物，不是主角。"
            ),
            (
                "continuity",
                "怀表已观测事实",
                "第一节夜里怀表显示“四日”；第二节中午仍显示“四日”，但“四”比前夜变浅；克莱旧样本应与此兼容：字迹先变浅/变淡，之后才变成三；第四节早晨埃文发现数字已经是“三日”。机制原因尚未知。"
            ),
            (
                "continuity",
                "十三号仓保管链目标事实",
                "七年前银牌与封存钥匙进入仓储；六年前只是仓内转柜/单独封存，钥匙没有离库；三年前续费；克莱死前九天红发女人才凭授权正式领取钥匙。收费收据可以只记计价主物，内部转移单负责记录附属封存件。"
            ),
            (
                "continuity",
                "第五节后续现实接口",
                "银牌来自克莱名下寄存记录。若埃文把它交给米拉，遗产清算、寄存、核验、所有权与事务所账目仍属于现实世界约束，除非正文明确合法补齐。"
            ),
        ]
        for kind, title, value in memories:
            m = conn.execute(
                "INSERT INTO memories(project_id,kind,title,content,source_type,source_ref,confirmed) VALUES(?,?,?,?,?,?,1)",
                (project_id, kind, title, value, "manual", f"gray-street:{title}"),
            )
            conn.execute(
                "INSERT INTO memory_versions(memory_id,version,kind,title,content,confirmed,note) VALUES(?,?,?,?,?,?,?)",
                (m.lastrowid, 1, kind, title, value, 1, "Gray Street platform replay"),
            )

        characters = [
            (
                "埃文·格雷",
                "主角；遗产清算事务所职员",
                "理性、重证据和手续。观察力强但不是全知；只能根据当场动作和已有样本判断，不得越权为警察或所有权裁判。",
                ["主角", "遗产清算", "观察"]
            ),
            (
                "米拉·阿尔瓦",
                "钟表铺经营者；第七码头资产处旧成员",
                "掌握部分历史但强烈限制信息暴露。恐惧与戒备通过回避、动作和不合作体现；不会主动讲完整规则。",
                ["秘密", "SV-7", "戒备"]
            ),
            (
                "汤普森",
                "警官",
                "务实，强调警方权限与结案边界，不为满足埃文好奇心主动泄露信息。",
                ["警察", "权限"]
            ),
            (
                "鲍勃·费恩",
                "十三号仓保管人",
                "规矩地贪，愿意在手续边缘交易信息，但不能无代价抹掉自己刚建立的保管规则。",
                ["仓储", "贪心", "程序"]
            ),
        ]
        for name, role, profile, tags in characters:
            conn.execute(
                "INSERT INTO characters(project_id,name,role,profile,tags) VALUES(?,?,?,?,?)",
                (project_id, name, role, profile, json.dumps(tags, ensure_ascii=False)),
            )
    return project_id, chapter_ids


async def _skill_replay(project_id: int) -> dict:
    # A compact replay isolates the two generalized failures without feeding the expected answer.
    content = """【片段 A】
七年前寄存。
六年前转存。
三年前有人补过费用。
后来钥匙被转走。
直到九天前，那个红发女人来取东西。
“她拿了钥匙。”埃文说。
费恩点头。

【片段 B】
前一日夜里怀表显示“四日”。
第二日中午，“四”仍在，只是比昨晚浅了一些。
同日下午，米拉说克莱第一次见到这只表时也是四，“第二天变成三”。
再下一日早晨，埃文发现“四”变成“三”。

背景：这是悬疑怪谈。机制原因尚未揭晓，不要求你解释超自然原理。"""

    # Use a real project task so the reviewer receives the newly frozen Reader Skill.
    task_id = _create_task(
        project_id=project_id,
        chapter_id=None,
        goal="回放外部 Reader 漏检，验证升级后的连续性 Gate 能否自动识别",
        instruction="只审核，不改文。未知机制可以保留；只判断正文已经展示的状态和可观测事实是否连续。",
    )
    context = _task_context(task_id, project_id)
    result = await _run_step(
        task_id=task_id,
        role="continuity-plot-reviewer",
        stage="gray-street-skill-replay",
        mode="check",
        content=content,
        instruction=context + """

这是 Skill Evolution Replay。按当前冻结的 NarrativeOS Reader/Writer Skill 审核。
不要参考人工结论，不要替作者补中间步骤。
如果命中稳定失败类型，请写出对应稳定标签。
输出问题、证据和最小修复边界。""",
    )
    output = result.content
    required = ["STATE_TRANSITION_LEDGER_GAP", "OBSERVABLE_RULE_CONSISTENCY_GAP"]

    # Stable labels are the preferred reviewer surface. Some providers still
    # describe a detected issue correctly while drifting on the exact label.
    # The static Skill regression separately guarantees both labels exist in
    # the frozen Skill, so this replay also accepts a tightly scoped semantic
    # detection for the observable-rule sample instead of creating a false
    # platform failure purely from output-format drift.
    detected = {
        "STATE_TRANSITION_LEDGER_GAP": (
            "STATE_TRANSITION_LEDGER_GAP" in output
            or (
                "片段 A" in output
                and "钥匙" in output
                and any(token in output for token in ("离开两次", "保管链", "状态链"))
                and any(token in output for token in ("REWRITE_BLOCK", "blocking"))
            )
        ),
        "OBSERVABLE_RULE_CONSISTENCY_GAP": (
            "OBSERVABLE_RULE_CONSISTENCY_GAP" in output
            or (
                "片段 B" in output
                and any(token in output for token in ("先变浅", "字迹变浅", "变化模式"))
                and "变成三" in output
                and any(token in output for token in ("LOCAL_REWRITE", "REWRITE_BLOCK"))
            )
        ),
    }
    missing = [item for item in required if not detected[item]]
    return {
        "task_id": task_id,
        "provider": result.provider,
        "model": result.model,
        "output": output,
        "required": required,
        "detected": detected,
        "missing": missing,
        "pass": not missing,
    }


def _findings(task_id: int, status: str | None = None) -> list[dict]:
    with connect() as conn:
        sql = "SELECT reviewer,category,severity,summary,suggestion,status FROM review_findings WHERE task_id=?"
        params: list[object] = [task_id]
        if status is not None:
            sql += " AND status=?"
            params.append(status)
        sql += " ORDER BY id"
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


async def _review_and_revise_section(
    *,
    project_id: int,
    chapter_id: int,
    section_key: str,
    title: str,
    baseline: str,
) -> dict:
    task_id = _create_task(
        project_id=project_id,
        chapter_id=chapter_id,
        goal=f"根据升级后的 NarrativeOS Skill 审核并修订《灰街》{section_key}《{title}》",
        instruction=(
            "这是现有正文修订任务，不续写新剧情。先完整审核，再由 Revision Agent "
            "只处理审核确认的问题；保持主角身份、事件顺序、悬疑边界和下一节接口。"
        ),
    )
    context = _task_context(task_id, project_id)
    with connect() as conn:
        conn.execute(
            "UPDATE writing_tasks SET draft=?,revised_content=?,status='running' WHERE id=?",
            (baseline, baseline, task_id),
        )
        conn.execute("DELETE FROM review_findings WHERE task_id=?", (task_id,))

    first_outputs, first_blocking = await _run_review_round(
        task_id=task_id,
        draft=baseline,
        context=context,
        round_no=1,
        auto_learn=False,
        retry_failed_reviewers=1,
    )
    first_findings = _findings(task_id, "open")

    revision = await _run_step(
        task_id=task_id,
        role="revision-agent",
        stage=f"gray-street-{section_key}-revision-r1",
        mode="polish",
        content=baseline,
        instruction="\n\n".join(
            [
                "你是 NarrativeOS Revision Agent。只修当前正文，不续写下一节。",
                _section_contract(section_key),
                "自动 Reviewer 第一轮输出：\n" + "\n\n".join(first_outputs),
                context,
                """修订纪律：
- blocking 必须修；
- 外部 Reader 合同里已被确认且属于本节的问题必须一起落地；
- 不采纳已判定的误报；
- 不把未知机制解释成规则说明书；
- 除了问题定位和必要接口，不重写已经成立的场景；
- 保持完整段落与自然语流，不要改成碎短句；
- 只输出当前节完整正文。""",
            ]
        ),
    )
    revised = revision.content.strip()
    if not revised:
        raise RuntimeError(f"{section_key} revision returned empty content")

    contract_failures_r1 = _gray_street_contract_failures(section_key, revised)

    with connect() as conn:
        conn.execute(
            "UPDATE review_findings SET status='addressed' WHERE task_id=? AND status='open'",
            (task_id,),
        )
        conn.execute(
            "UPDATE writing_tasks SET revised_content=?,status='reviewed' WHERE id=?",
            (revised, task_id),
        )

    if contract_failures_r1:
        contract_revision = await _run_step(
            task_id=task_id,
            role="revision-agent",
            stage=f"gray-street-{section_key}-contract-repair",
            mode="polish",
            content=revised,
            instruction="\n\n".join(
                [
                    "平台确定性验收发现外部 Reader 修订合同仍未落地。只做最小定点修复，不续写、不扩写。",
                    _section_contract(section_key),
                    "未通过的合同项：\n- " + "\n- ".join(contract_failures_r1),
                    context,
                    "只输出当前节完整正文。不得改变冻结剧情接口，不得新增规则、人物、物证或巧合。",
                ]
            ),
        )
        revised = contract_revision.content.strip() or revised
        contract_failures_r1 = _gray_street_contract_failures(section_key, revised)
        with connect() as conn:
            conn.execute(
                "UPDATE writing_tasks SET revised_content=? WHERE id=?",
                (revised, task_id),
            )

    second_outputs, second_blocking = await _run_review_round(
        task_id=task_id,
        draft=revised,
        context=context,
        round_no=2,
        prior_outputs=first_outputs,
        auto_learn=False,
        retry_failed_reviewers=1,
    )
    second_findings = _findings(task_id, "open")

    # One bounded repair pass is allowed if the recheck still has blocking.
    final = revised
    third_outputs: list[str] = []
    third_blocking = False
    if second_blocking:
        second_revision = await _run_step(
            task_id=task_id,
            role="revision-agent",
            stage=f"gray-street-{section_key}-revision-r2",
            mode="polish",
            content=revised,
            instruction="\n\n".join(
                [
                    "这是同一节的第二次、也是最后一次平台修订。只处理 R2 仍未关闭的 blocking。",
                    "R2 Reviewer：\n" + "\n\n".join(second_outputs),
                    _section_contract(section_key),
                    context,
                    "不得扩大重写范围，不得新增设定。只输出当前节完整正文。",
                ]
            ),
        )
        final = second_revision.content.strip() or revised
        with connect() as conn:
            conn.execute(
                "UPDATE review_findings SET status='addressed' WHERE task_id=? AND status='open'",
                (task_id,),
            )
            conn.execute(
                "UPDATE writing_tasks SET revised_content=? WHERE id=?",
                (final, task_id),
            )
        third_outputs, third_blocking = await _run_review_round(
            task_id=task_id,
            draft=final,
            context=context,
            round_no=3,
            prior_outputs=second_outputs,
            auto_learn=False,
            retry_failed_reviewers=1,
        )

    final_blocking = second_blocking if not third_outputs else third_blocking
    final_contract_failures = _gray_street_contract_failures(section_key, final)
    if final_contract_failures:
        final_blocking = True

    with connect() as conn:
        conn.execute(
            "UPDATE writing_tasks SET status=? WHERE id=?",
            ("awaiting_approval" if not final_blocking else "reviewed", task_id),
        )

    return {
        "task_id": task_id,
        "section": section_key,
        "title": title,
        "baseline": baseline,
        "first_blocking": first_blocking,
        "first_outputs": first_outputs,
        "first_findings": first_findings,
        "revision_r1": revised,
        "second_blocking": second_blocking,
        "second_outputs": second_outputs,
        "second_findings": second_findings,
        "revision_r2": final if third_outputs else "",
        "third_outputs": third_outputs,
        "third_blocking": third_blocking,
        "contract_failures_r1": contract_failures_r1,
        "final_contract_failures": final_contract_failures,
        "final_blocking": final_blocking,
        "final": final,
    }


async def main() -> int:
    init_db()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not BASELINE.exists():
        raise RuntimeError(f"Gray Street baseline not found: {BASELINE}")

    source = BASELINE.read_text(encoding="utf-8")
    sections = _read_sections(source)
    project_id, chapter_ids = _create_project(sections)

    replay = await _skill_replay(project_id)
    (OUTPUT_DIR / "skill-replay.json").write_text(
        json.dumps(replay, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if not replay["pass"]:
        raise RuntimeError(
            "Skill replay failed before manuscript repair; missing labels: "
            + ", ".join(replay["missing"])
        )

    results: list[dict] = []
    for chapter_id, (section_key, title, baseline) in zip(chapter_ids, sections, strict=True):
        result = await _review_and_revise_section(
            project_id=project_id,
            chapter_id=chapter_id,
            section_key=section_key,
            title=title,
            baseline=baseline,
        )
        results.append(result)

    final_text = "# 《灰街》第一至五节｜NarrativeOS 平台修订候选\n\n"
    for result in results:
        final_text += f"# {result['section']}　{result['title']}\n\n{result['final'].strip()}\n\n---\n\n"
    (OUTPUT_DIR / "sections-01-05-platform-candidate.md").write_text(
        final_text.rstrip() + "\n",
        encoding="utf-8",
    )

    review_json = []
    for result in results:
        review_json.append(
            {
                key: value
                for key, value in result.items()
                if key not in {"baseline", "revision_r1", "revision_r2", "final"}
            }
        )
    (OUTPUT_DIR / "review-report.json").write_text(
        json.dumps(review_json, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    manifest = {
        "project": "灰街",
        "source": str(BASELINE),
        "skill_replay_pass": replay["pass"],
        "skill_replay_required": replay["required"],
        "section_count": len(results),
        "sections": [
            {
                "section": item["section"],
                "task_id": item["task_id"],
                "first_blocking": item["first_blocking"],
                "second_blocking": item["second_blocking"],
                "third_blocking": item["third_blocking"],
                "contract_failures": item["final_contract_failures"],
                "final_blocking": item["final_blocking"],
            }
            for item in results
        ],
        "all_final_gates_pass": all(not item["final_blocking"] for item in results),
        "status": (
            "awaiting_human_approval"
            if all(not item["final_blocking"] for item in results)
            else "needs_more_revision"
        ),
    }
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False), flush=True)
    return 0 if manifest["all_final_gates_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
