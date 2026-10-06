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
                "第一节夜里怀表显示“四日”；第二节中午仍显示“四日”，但“四”比前夜变浅；第三节米拉说克莱第一次见到时也是四，并称“第二天变成三”；第四节早晨埃文发现数字已经是“三日”。机制原因尚未知。"
            ),
            (
                "continuity",
                "十三号仓旧稿状态事实",
                "第四节旧稿写：七年前寄存；六年前转存；三年前补费；克莱死前九天有“取出”；随后又叙述“后来钥匙被转走”，并让费恩确认九天前红发女人拿走钥匙。请只依据正文判断状态链是否连续。"
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
    missing = [item for item in required if item not in output]
    return {
        "task_id": task_id,
        "provider": result.provider,
        "model": result.model,
        "output": output,
        "required": required,
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
                ACCEPTED_REPAIR_CONTRACT,
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

    with connect() as conn:
        conn.execute(
            "UPDATE review_findings SET status='addressed' WHERE task_id=? AND status='open'",
            (task_id,),
        )
        conn.execute(
            "UPDATE writing_tasks SET revised_content=?,status='reviewed' WHERE id=?",
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
                    ACCEPTED_REPAIR_CONTRACT,
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
