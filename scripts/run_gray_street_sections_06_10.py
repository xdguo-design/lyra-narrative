from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

from app.db import connect, init_db
from app.services.book_pipeline import _create_task
from app.services.full_novel_pipeline import (
    _run_review_round,
    _run_revision_integrity_gate,
)
from app.services.workflow_service import _parse_review_output, _run_step, _task_context


OUTPUT_DIR = Path("artifacts/gray-street-sections-06-10")
CONTENT_ROOT = Path(os.getenv("GRAY_STREET_CONTENT_ROOT", "content-repo"))
LOCKED_SOURCE = CONTENT_ROOT / "novels/gray-street/versions/sections-01-05-platform-locked.md"
FALLBACK_SOURCE = CONTENT_ROOT / "novels/gray-street/versions/sections-01-05-reader-input-v1.md"
BRIEF_PATH = CONTENT_ROOT / "novels/gray-street/plans/sections-06-10-brief.md"
CANON_PATH = CONTENT_ROOT / "novels/gray-street/bible/project-canon.md"

SECTION_NUMBERS = [6, 7, 8, 9, 10]
CN_SECTION = {
    6: "第六节",
    7: "第七节",
    8: "第八节",
    9: "第九节",
    10: "第十节",
}

REVIEW_FORMAT = """NARRATIVEOS_REVIEW_V3
每个问题一块，多个问题用单独一行 --- 分隔；没有问题只输出 NO_ISSUE。
每个问题必须包含：
问题标识：
严重性：High / Medium / Low
处置级别：REWRITE_BLOCK / LOCAL_REWRITE / DELETE / POLISH / PASS
问题类型：
问题定位：
逐字片段：
问题说明：
判级理由：
修改边界：
必须保留事实：
禁止新增内容：
执行目标：
建议动作：
复审要求：
复审结果=PENDING

High 或 REWRITE_BLOCK 才阻断交付。不要把个人偏好当 blocking。"""


def _split_locked_sections(text: str) -> list[tuple[int, str, str]]:
    pattern = re.compile(r"^# 第([一二三四五])节[　 ]+(.+?)\s*$", re.MULTILINE)
    number_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5}
    matches = list(pattern.finditer(text))
    sections: list[tuple[int, str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        num = number_map[match.group(1)]
        title = match.group(2).strip()
        body = text[start:end].strip()
        if body.endswith("---"):
            body = body[:-3].rstrip()
        sections.append((num, title, body))
    if len(sections) != 5:
        raise RuntimeError(f"expected 5 locked sections, got {len(sections)}")
    return sections


def _create_project(
    sections: list[tuple[int, str, str]],
    canon: str,
    brief: str,
) -> tuple[int, list[int]]:
    with connect() as conn:
        project = conn.execute(
            "INSERT INTO projects(title,description,genre,status) VALUES(?,?,?,?)",
            (
                "灰街",
                "NarrativeOS 平台正式续写：第6—10节",
                "悬疑 / 怪谈 / 都市遗产调查",
                "draft",
            ),
        )
        project_id = int(project.lastrowid)
        chapter_ids: list[int] = []
        for num, title, body in sections:
            row = conn.execute(
                "INSERT INTO chapters(project_id,title,position,content,status) VALUES(?,?,?,?,?)",
                (project_id, f"第{num}节 {title}", num, body, "approved"),
            )
            chapter_ids.append(int(row.lastrowid))
            conn.execute(
                "INSERT INTO chapter_versions(chapter_id,content,note) VALUES(?,?,?)",
                (row.lastrowid, body, "NarrativeOS 平台锁定版"),
            )

        memories = [
            (
                "canon",
                "《灰街》锁定 Canon",
                canon,
            ),
            (
                "outline",
                "第6—10节用户与项目约束",
                brief,
            ),
            (
                "continuity",
                "第5节结束状态",
                (
                    "银牌已交到米拉手中；怀表‘归还第一笔’清空；SV-7 极淡再现。"
                    "埃文对银牌的遗产/核验手续仍未结清，下一节必须兑现现实后果。"
                ),
            ),
            (
                "continuity",
                "钥匙与红发女人",
                (
                    "七年前银牌与封存钥匙入仓；六年前只在仓内转柜/单独封存；"
                    "克莱死前九天红发女人凭旧授权真正领取钥匙离库。红发女人戴手套。"
                ),
            ),
            (
                "continuity",
                "阶段线索",
                (
                    "第6—10节核心链必须由既有现实记录推出：事务所核账 → 未结资产/附页 → "
                    "七号箱 → 费恩死亡 → 红发女人现实介入。不得让怀表直接充当导航器。"
                ),
            ),
        ]
        for kind, title, value in memories:
            m = conn.execute(
                "INSERT INTO memories(project_id,kind,title,content,source_type,source_ref,confirmed) VALUES(?,?,?,?,?,?,1)",
                (project_id, kind, title, value, "manual", f"gray-street-continuation:{title}"),
            )
            conn.execute(
                "INSERT INTO memory_versions(memory_id,version,kind,title,content,confirmed,note) VALUES(?,?,?,?,?,?,?)",
                (
                    m.lastrowid,
                    1,
                    kind,
                    title,
                    value,
                    1,
                    "Gray Street sections 6-10 continuation",
                ),
            )

        characters = [
            (
                "埃文·格雷",
                "主角；格兰特遗产与资产清算事务所职员",
                (
                    "理性、重证据和手续；遇到异常先用现实证据验证。不是警察，不能越权取得"
                    "尸检、内部警务资料或所有权结论。对白短而具体，但不是冷冰冰的问答机器。"
                ),
                ["主角", "遗产清算", "现实责任"],
            ),
            (
                "米拉·阿尔瓦",
                "钟表铺经营者；第七码头资产处旧成员",
                (
                    "掌握部分 SV-7 历史但强烈限制信息暴露。她会回避、试探和保留，不会主动"
                    "完整解释超自然机制。第9节前后必须因过去隐瞒付出关系代价。"
                ),
                ["SV-7", "隐瞒", "银牌"],
            ),
            (
                "汤普森",
                "警官",
                (
                    "务实，守权限边界。若费恩死亡使埃文进入调查，只能因为埃文确实是近期到访者/"
                    "证人/相关人；不会为了推进剧情向埃文泄露完整内部调查。"
                ),
                ["警察", "权限", "费恩死亡"],
            ),
            (
                "鲍勃·费恩",
                "十三号仓保管人",
                (
                    "此前允许埃文核验银牌；他知道仓储和旧授权链的一部分。第6—7节死亡进入现实"
                    "事件链，但死亡原因、责任人不能凭空确定。"
                ),
                ["十三号仓", "保管链", "死亡事件"],
            ),
            (
                "红发女人",
                "身份未知；克莱死前九天领取封存钥匙的人",
                (
                    "红发、戴手套；从第6节起必须从远景观察者进入现实行动线。身份与完整目的仍可未知，"
                    "但她必须通过可观察的行动改变局势，而不是只在章尾出现。"
                ),
                ["红发", "手套", "钥匙", "未知身份"],
            ),
        ]
        for name, role, profile, tags in characters:
            conn.execute(
                "INSERT INTO characters(project_id,name,role,profile,tags) VALUES(?,?,?,?,?)",
                (project_id, name, role, profile, json.dumps(tags, ensure_ascii=False)),
            )

        new_chapters: list[int] = []
        for num in SECTION_NUMBERS:
            row = conn.execute(
                "INSERT INTO chapters(project_id,title,position,content,status) VALUES(?,?,?,?,?)",
                (project_id, f"{CN_SECTION[num]} 待生成", num, "", "draft"),
            )
            new_chapters.append(int(row.lastrowid))
    return project_id, new_chapters


async def _make_outline(project_id: int, section5: str, brief: str) -> dict:
    task_id = _create_task(
        project_id=project_id,
        chapter_id=None,
        goal="规划《灰街》第6—10节，不写正文",
        instruction="必须承接锁定的1—5节与第6—10节约束；不重启故事，不改主角，不提前揭开完整SV-7机制。",
    )
    context = _task_context(task_id, project_id)
    result = await _run_step(
        task_id=task_id,
        role="plot-planner",
        stage="gray-street-outline-06-10",
        mode="continue",
        content=section5,
        instruction="\n\n".join(
            [
                context,
                "【第6—10节硬约束】\n" + brief,
                """输出仅包含第6、7、8、9、10节可执行大纲，不写正文。
每节必须明确：
- 临时标题；
- 开场状态；
- 埃文的现实目标；
- 阻碍；
- 关键现场；
- 新信息从哪里合法获得；
- 人物主动选择与代价；
- 红发女人的可观察行动（若本节出现）；
- 七号箱状态变化（若推进）；
- 现实手续/警方/事务所后果；
- 必须保留的未知；
- 章末钩子类型。

额外硬门槛：
1. 第6节必须先兑现银牌交接/核账后果，再推出七号箱与费恩死亡。
2. 埃文不是警察；警务信息必须有合法来源。
3. 怀表不能连续充当导航器或每章结尾弹字。
4. 第10节必须形成阶段小高潮，并同时改变至少两项状态。
5. 不新增完整超自然规则，不把米拉写成说明书。
6. 不用巧合把线索送到主角手里。""",
            ]
        ),
    )
    outline = result.content.strip()
    if not outline:
        raise RuntimeError("plot planner returned empty outline")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "outline-06-10.md").write_text(outline + "\n", encoding="utf-8")
    with connect() as conn:
        m = conn.execute(
            "INSERT INTO memories(project_id,kind,title,content,source_type,source_ref,confirmed) VALUES(?,?,?,?,?,?,1)",
            (
                project_id,
                "outline",
                "NarrativeOS 第6—10节执行大纲",
                outline,
                "agent",
                "gray-street:outline-06-10",
            ),
        )
        conn.execute(
            "INSERT INTO memory_versions(memory_id,version,kind,title,content,confirmed,note) VALUES(?,?,?,?,?,?,?)",
            (
                m.lastrowid,
                1,
                "outline",
                "NarrativeOS 第6—10节执行大纲",
                outline,
                1,
                "平台生成并冻结用于6—10节",
            ),
        )
    return {
        "task_id": task_id,
        "provider": result.provider,
        "model": result.model,
        "outline": outline,
    }


def _reader_instruction(kind: str, round_no: int, prior: str = "") -> str:
    if kind == "ordinary":
        focus = """你是普通小说读者，不是编辑。只判断：
1. 是否好读、能否自然看懂现场与人物在做什么；
2. 哪些地方假、硬、绕、像作者强推剧情；
3. 哪些地方会想跳过；
4. 人物是否鲜活，是否像真人而非线索运输车；
5. 读完是否自然想继续。
不要因为你没立刻知道谜底就判错。悬疑允许未知。"""
    elif kind == "commercial":
        focus = """你是商业阅读 Reader。检查：
1. 本节是否有明确推进和压力；
2. 开头是否承接上一节而不是重启；
3. 中段是否存在可跳过的手续/说明；
4. 角色记忆点、冲突和续读欲；
5. 章末是否真的改变局势，而不是机械弹出新名词/新文字。
禁止为了所谓网文感要求大量短句、一句一段、夸张打脸或强行反转。"""
    else:
        focus = """你是文学自然度 Reader。专门检查：
1. AI味、模板句、作者替读者总结、过度工整的金句；
2. 叙事是否像办案纪要、设定说明或功能清单；
3. 对话是否真人会说，是否台词墙；
4. 是否有连续碎短句、机械动作填充、泛化比喻；
5. 现场、物感、潜台词是否自然，不要求华丽。
不要改变事实、设定和悬疑边界。"""

    mode = (
        "这是 INITIAL 审核。"
        if round_no == 1
        else "这是 RECHECK。优先复查上一轮原问题是否消失；若已解决，不得换个措辞继续挑同一偏好。"
    )
    return "\n\n".join(
        item
        for item in [focus, mode, prior, REVIEW_FORMAT]
        if item
    )


async def _run_external_readers(
    *,
    task_id: int,
    draft: str,
    round_no: int,
    prior_outputs: list[str] | None = None,
) -> tuple[list[str], bool]:
    specs = [
        ("blind-reader", "ordinary"),
        ("master-reader", "commercial"),
        ("blind-natural-reader", "literary-naturalness"),
    ]

    async def run_one(index: int, role: str, kind: str):
        prior = ""
        if prior_outputs and index < len(prior_outputs):
            prior = "上一轮同一 Reader 输出：\n" + prior_outputs[index]
        try:
            result = await _run_step(
                task_id=task_id,
                role=role,
                stage=f"gray-street-{kind}-r{round_no}",
                mode="check",
                content=draft,
                instruction=_reader_instruction(kind, round_no, prior),
            )
            return {
                "ok": True,
                "kind": kind,
                "content": result.content,
                "provider": result.provider,
                "model": result.model,
                "error": "",
            }
        except (RuntimeError, ValueError) as exc:  # platform reviewer failure must fail closed
            return {
                "ok": False,
                "kind": kind,
                "content": "",
                "provider": "",
                "model": "",
                "error": f"{type(exc).__name__}: {exc}",
            }

    packets = await asyncio.gather(
        *[
            run_one(index, role, kind)
            for index, (role, kind) in enumerate(specs)
        ]
    )
    outputs: list[str] = []
    blocking = False
    for packet in packets:
        if not packet["ok"]:
            blocking = True
            outputs.append(
                f"[{packet['kind']}] REVIEW_EXECUTION_FAILED: {packet['error']}"
            )
            continue
        text = str(packet["content"])
        outputs.append(f"[{packet['kind']}] {text}")
        findings = _parse_review_output(text, draft)
        if any(item["severity"] == "blocking" for item in findings):
            blocking = True
    return outputs, blocking


async def _review_bundle(
    *,
    task_id: int,
    draft: str,
    context: str,
    round_no: int,
    prior_platform: list[str] | None = None,
    prior_readers: list[str] | None = None,
) -> tuple[list[str], list[str], bool]:
    platform_task = _run_review_round(
        task_id=task_id,
        draft=draft,
        context=context,
        round_no=round_no,
        prior_outputs=prior_platform,
        auto_learn=True,
        retry_failed_reviewers=1,
    )
    readers_task = _run_external_readers(
        task_id=task_id,
        draft=draft,
        round_no=round_no,
        prior_outputs=prior_readers,
    )
    (platform_outputs, platform_blocking), (
        reader_outputs,
        reader_blocking,
    ) = await asyncio.gather(platform_task, readers_task)
    return platform_outputs, reader_outputs, platform_blocking or reader_blocking


async def _generate_section(
    *,
    project_id: int,
    chapter_id: int,
    section_num: int,
    outline: str,
    brief: str,
) -> dict:
    section_name = CN_SECTION[section_num]
    task_id = _create_task(
        project_id=project_id,
        chapter_id=chapter_id,
        goal=f"写《灰街》{section_name}完整正文",
        instruction=(
            f"只写{section_name}。必须承接前文与冻结大纲；不得提前写第{section_num + 1}节正文。"
            "正文以完整段落、自然语流为主，不写成碎短句或台词墙。"
        ),
    )
    context = _task_context(task_id, project_id)

    blueprint = await _run_step(
        task_id=task_id,
        role="scene-director",
        stage=f"gray-street-{section_num}-scene-blueprint",
        mode="continue",
        content=outline,
        instruction="\n\n".join(
            [
                context,
                f"只为{section_name}做场景导演卡，不写正文。",
                brief,
                """给出：本节核心张力、2—3个主细节、流程压缩点、必须慢写的选择/关系变化、
在场人物各自想得到/怕暴露/不会直说的内容、空间与手上任务、潜台词、必须承接的前节接口、
章尾类型。不得新增线索来源和超自然规则。""",
            ]
        ),
    )

    context = _task_context(task_id, project_id)
    writer = await _run_step(
        task_id=task_id,
        role="writer",
        stage=f"gray-street-{section_num}-draft",
        mode="continue",
        content=blueprint.content,
        instruction="\n\n".join(
            [
                f"写作任务：只输出《灰街》{section_name}完整正文。",
                context,
                "【冻结第6—10节大纲】\n" + outline,
                "【本节场景导演卡】\n" + blueprint.content,
                """硬要求：
- 埃文·格雷始终是主角与主要视角；
- 不重述前五节，不用说明书复盘；
- 现实手续要成为人物压力，不写成账务教程；
- 费恩死亡、警方信息、七号箱都必须有合法信息来源；
- 红发女人必须通过可观察行动改变局势；
- 超自然原因继续未知，怀表不得替代调查；
- 对话嵌入动作、空间、利益与回避，不写问一句答一句的台词墙；
- 不要大量一行一句，不追求金句；
- 本节结尾优先行动后果、关系变化或现实危险。
只输出正文，不输出大纲、解释、标签。""",
            ]
        ),
    )

    prose = await _run_step(
        task_id=task_id,
        role="prose-editor",
        stage=f"gray-street-{section_num}-prose",
        mode="polish",
        content=writer.content,
        instruction="\n\n".join(
            [
                context,
                """只做小说语言与场景编辑，不改事件顺序、线索来源和人物选择。
重点：
- 去办案纪要感、报告腔、解释性废话；
- 保留完整段落与自然长短句，不切成大量短句；
- 对话要有人物利益、潜台词、身体状态与空间；
- 增加必要现场物感，但每场最多突出2—3个值钱细节；
- 删除AI式总结、模板收束、过度工整对白；
- 不把米拉或其他人物改成世界观讲解员。
只输出完整正文。""",
            ]
        ),
    )
    draft = prose.content.strip()
    if not draft:
        raise RuntimeError(f"{section_name} writer returned empty draft")

    with connect() as conn:
        conn.execute(
            "UPDATE writing_tasks SET draft=?,status='reviewed' WHERE id=?",
            (draft, task_id),
        )

    platform_r1, readers_r1, blocking_r1 = await _review_bundle(
        task_id=task_id,
        draft=draft,
        context=context,
        round_no=1,
    )

    revision = await _run_step(
        task_id=task_id,
        role="revision-agent",
        stage=f"gray-street-{section_num}-revision-r1",
        mode="polish",
        content=draft,
        instruction="\n\n".join(
            [
                f"只修《灰街》{section_name}，不续写下一节。",
                "平台 Reviewer：\n" + "\n\n".join(platform_r1),
                "三类 Reader：\n" + "\n\n".join(readers_r1),
                context,
                """blocking 必须修；LOCAL_REWRITE 只改最小范围。
普通读者/商业阅读/文学自然度意见如果只是偏好不能改 Canon。
禁止因修语言删掉关键线索、人物选择、现实后果与章末接口。
保持完整段落、自然长短句和连续叙事。
只输出修订后的完整正文。""",
            ]
        ),
    )
    revised = revision.content.strip() or draft

    with connect() as conn:
        conn.execute(
            "UPDATE review_findings SET status='addressed' WHERE task_id=? AND status='open'",
            (task_id,),
        )

    integrity_task = _run_revision_integrity_gate(
        task_id=task_id,
        before=draft,
        after=revised,
        context=context,
        round_no=1,
    )
    recheck_task = _review_bundle(
        task_id=task_id,
        draft=revised,
        context=context,
        round_no=2,
        prior_platform=platform_r1,
        prior_readers=readers_r1,
    )
    (integrity_output, integrity_failed), (
        platform_r2,
        readers_r2,
        blocking_r2,
    ) = await asyncio.gather(integrity_task, recheck_task)

    final = revised
    final_blocking = integrity_failed or blocking_r2
    platform_r3: list[str] = []
    readers_r3: list[str] = []

    # One bounded repair pass. If it still fails after this, do not lock it.
    if final_blocking:
        repair = await _run_step(
            task_id=task_id,
            role="revision-agent",
            stage=f"gray-street-{section_num}-revision-r2",
            mode="polish",
            content=revised,
            instruction="\n\n".join(
                [
                    f"这是《灰街》{section_name}最后一次平台自动修订，只处理R2仍未关闭的blocking。",
                    "R2平台 Reviewer：\n" + "\n\n".join(platform_r2),
                    "R2三类 Reader：\n" + "\n\n".join(readers_r2),
                    "Revision Integrity：\n" + integrity_output,
                    context,
                    "不得扩大重写范围，不得新增规则、人物、证物或巧合。只输出当前节完整正文。",
                ]
            ),
        )
        final = repair.content.strip() or revised
        with connect() as conn:
            conn.execute(
                "UPDATE review_findings SET status='addressed' WHERE task_id=? AND status='open'",
                (task_id,),
            )
        integrity2_task = _run_revision_integrity_gate(
            task_id=task_id,
            before=revised,
            after=final,
            context=context,
            round_no=2,
        )
        recheck2_task = _review_bundle(
            task_id=task_id,
            draft=final,
            context=context,
            round_no=3,
            prior_platform=platform_r2,
            prior_readers=readers_r2,
        )
        (integrity2_output, integrity2_failed), (
            platform_r3,
            readers_r3,
            blocking_r3,
        ) = await asyncio.gather(integrity2_task, recheck2_task)
        integrity_output += "\n\n=== R2 REPAIR INTEGRITY ===\n" + integrity2_output
        final_blocking = integrity2_failed or blocking_r3

    with connect() as conn:
        conn.execute(
            "UPDATE chapters SET title=?,content=?,status=? WHERE id=?",
            (
                f"{section_name} 平台续写",
                final,
                "draft" if final_blocking else "approved",
                chapter_id,
            ),
        )
        conn.execute(
            "INSERT INTO chapter_versions(chapter_id,content,note) VALUES(?,?,?)",
            (
                chapter_id,
                final,
                "NarrativeOS 第6—10节平台候选"
                if final_blocking
                else "NarrativeOS 第6—10节平台通过版",
            ),
        )
        conn.execute(
            "UPDATE writing_tasks SET revised_content=?,status=? WHERE id=?",
            (
                final,
                "reviewed" if final_blocking else "awaiting_approval",
                task_id,
            ),
        )

    return {
        "task_id": task_id,
        "section_num": section_num,
        "section_name": section_name,
        "blueprint": blueprint.content,
        "draft": draft,
        "platform_r1": platform_r1,
        "readers_r1": readers_r1,
        "blocking_r1": blocking_r1,
        "revision_r1": revised,
        "platform_r2": platform_r2,
        "readers_r2": readers_r2,
        "integrity": integrity_output,
        "blocking_r2": blocking_r2,
        "platform_r3": platform_r3,
        "readers_r3": readers_r3,
        "final_blocking": final_blocking,
        "final": final,
    }


async def main() -> int:
    init_db()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    source_path = LOCKED_SOURCE if LOCKED_SOURCE.exists() else FALLBACK_SOURCE
    if not source_path.exists():
        raise RuntimeError(
            "sections 1-5 source not found; expected locked or reader-input source"
        )
    if not BRIEF_PATH.exists():
        raise RuntimeError(f"continuation brief not found: {BRIEF_PATH}")
    if not CANON_PATH.exists():
        raise RuntimeError(f"project canon not found: {CANON_PATH}")

    locked_text = source_path.read_text(encoding="utf-8")
    brief = BRIEF_PATH.read_text(encoding="utf-8")
    canon = CANON_PATH.read_text(encoding="utf-8")
    prior_sections = _split_locked_sections(locked_text)

    project_id, new_chapter_ids = _create_project(prior_sections, canon, brief)

    # When the 1-5 platform-lock job is still running, the continuation may
    # start from the preserved Reader input for prose continuity only. Canon
    # and the continuation brief override any known stale factual wording.
    # A later final continuity pass must be rerun against the locked 1-5 file.
    if source_path != LOCKED_SOURCE:
        with connect() as conn:
            m = conn.execute(
                "INSERT INTO memories(project_id,kind,title,content,source_type,source_ref,confirmed) VALUES(?,?,?,?,?,?,1)",
                (
                    project_id,
                    "continuity",
                    "1-5来源状态",
                    (
                        "当前续写运行使用外部Reader输入版仅作为文风与第5节场景承接。"
                        "已确认的修订事实以项目Canon和第6-10节约束为最高优先级："
                        "六年前钥匙仅仓内转柜；九天前才离库；银牌核验/所有权和事务所账目后果继续存在。"
                    ),
                    "manual",
                    "gray-street:source-fallback",
                ),
            )
            conn.execute(
                "INSERT INTO memory_versions(memory_id,version,kind,title,content,confirmed,note) VALUES(?,?,?,?,?,?,?)",
                (
                    m.lastrowid,
                    1,
                    "continuity",
                    "1-5来源状态",
                    (
                        "Reader输入版只用于承接；Canon覆盖已知旧稿硬伤。"
                    ),
                    1,
                    "Temporary continuation source guard",
                ),
            )

    outline_info = await _make_outline(
        project_id,
        prior_sections[-1][2],
        brief,
    )

    results: list[dict] = []
    for chapter_id, section_num in zip(new_chapter_ids, SECTION_NUMBERS, strict=True):
        result = await _generate_section(
            project_id=project_id,
            chapter_id=chapter_id,
            section_num=section_num,
            outline=outline_info["outline"],
            brief=brief,
        )
        results.append(result)
        # Never let a failed section become the basis of the next one.
        if result["final_blocking"]:
            break

    combined = "# 《灰街》第六至十节｜NarrativeOS 平台续写\n\n"
    for item in results:
        status = "BLOCKED" if item["final_blocking"] else "PASS"
        combined += (
            f"# {item['section_name']}　[{status}]\n\n"
            f"{item['final'].strip()}\n\n---\n\n"
        )
    (OUTPUT_DIR / "sections-06-10-platform.md").write_text(
        combined.rstrip() + "\n",
        encoding="utf-8",
    )

    report = []
    for item in results:
        report.append(
            {
                key: value
                for key, value in item.items()
                if key
                not in {
                    "blueprint",
                    "draft",
                    "revision_r1",
                    "final",
                }
            }
        )
    (OUTPUT_DIR / "review-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    all_pass = len(results) == 5 and all(not item["final_blocking"] for item in results)
    manifest = {
        "project": "灰街",
        "source": str(source_path),
        "source_is_platform_locked": source_path == LOCKED_SOURCE,
        "outline_task_id": outline_info["task_id"],
        "outline_provider": outline_info["provider"],
        "outline_model": outline_info["model"],
        "generated_sections": [item["section_num"] for item in results],
        "sections": [
            {
                "section": item["section_num"],
                "task_id": item["task_id"],
                "blocking_r1": item["blocking_r1"],
                "blocking_r2": item["blocking_r2"],
                "final_blocking": item["final_blocking"],
            }
            for item in results
        ],
        "all_final_gates_pass": all_pass,
        "status": "awaiting_human_approval" if all_pass else "blocked",
    }
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False), flush=True)
    return 0 if all_pass else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
