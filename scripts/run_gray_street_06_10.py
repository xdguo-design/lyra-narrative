from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from app.db import connect, init_db
from app.services.book_pipeline import _create_task, _run_frozen_chapter
from app.services.full_novel_pipeline import _persist_memory
from app.services.workflow_service import get_task


PROJECT_TITLE = "灰街｜第6—10节正式续写"
PROJECT_GENRE = "都市悬疑 / 神秘规则 / 灰街基层调查"
OUTPUT_DIR = Path(os.getenv("NARRATIVE_OUTPUT_DIR", "artifacts/gray-street-06-10"))

PREVIOUS_FIVE = """【前五节锁定连续性包】
第1节《怀表》：克莱得到一只异常怀表。怀表不是万能外挂，而是带规则的神秘物；规则被违反会产生反噬。它与克莱后续被迫卷入的“归还”机制有关。
第2节《遗产》：遗产/委托线正式建立，并出现明确时限压力。第一阶段存在“四日”期限，克莱必须在现实生活与有限权限下处理，不能凭超能力直接解题。
第3节《河灯街》：故事在三节内进入核心冲突。时间压力与现实阻力/竞争者至少两项同时存在，后续不得退回单纯查资料流水线。
第4节《十三号仓》：克莱沿现实可核查线索进入十三号仓相关事件，关键物件“银牌”和名字/线索“维尔”进入主线。克莱只能依靠基层职权、观察、跑动、有限程序空间推进，不是警察，不可突然越权或神探化。
第5节《日落》：第一笔“归还”在日落前完成，银牌被交回米拉。节末正式抛出“SV-7 / 第7号箱”，作为下一阶段的明确入口。
已锁定：前五节剧情、线索、时间、人物行动与 Canon 不得被回写或篡改。当前续写必须从第5节结束状态自然接上。
"""

STYLE_AND_GATE = """【用户长期文风与硬 Gate】
1. 正文以完整段落、连续叙事和自然长短句搭配为主；禁止大量碎短句、单句段落、台词墙。
2. 对话必须嵌入动作、神态、视线、空间、手上任务和关系压力；禁止问一句答一句的审讯表/资料表。
3. 减少作者替读者总结、解释腔、纪要腔、模型腔、金句式收束；增加现场感、物感、潜台词。
4. 神秘物必须有稳定规则，违反规则会反噬；不能把怀表写成方便剧情的万能提示器。
5. 克莱靠有限基层权限和现实办法推进；允许出错、受阻、判断不完整，不能突然能打能杀、越权破案或全知。
6. “SV-7 / 第7号箱”是第6节入口，但第6—10节不得一次揭尽总谜底。五节要形成一个完整小阶段：推进、受阻、代价、局部确认、打开更大问题。
7. 不得复制或沿用聊天里未经平台审核的第6—10节草稿；本次必须独立生成。
8. 创作总控单章审核 + 最终连续阅读者完整阶段审核均为硬 Gate；任一 FAIL 不视为正式稿。
"""

SECTION_GOALS = {
    6: "直接承接《日落》末尾的 SV-7 / 第7号箱。让线索从名词变成现实行动，同时迅速出现一个可感知的现实阻力或竞争者。不要用整节查档案代替戏。",
    7: "继续追索第7号箱，让克莱有限权限真正成为限制与工具。推动对手/竞争者主动行动，使克莱必须做一个有风险但不越权的选择。",
    8: "让第7号箱线进入更近身的代价层。怀表规则或反噬只能在既有原则内表现，不新增万能功能；人物关系和现实生活压力必须影响选择。",
    9: "完成一次高压场景或现实 confrontation，让克莱得到局部可验证的新确认，但不能解决总谜底。信息必须靠行动、代价、证据边界获得。",
    10: "完成第6—10节这一小阶段的阶段闭环：第一层问题得到部分回收，同时产生更明确、更个人化或更危险的下一阶段入口。章尾不许总结主题或喊口号。",
}


def create_project() -> tuple[int, dict[int, int]]:
    with connect() as conn:
        old = conn.execute("SELECT id FROM projects WHERE title=?", (PROJECT_TITLE,)).fetchone()
        if old:
            conn.execute("DELETE FROM projects WHERE id=?", (old["id"],))

        project = conn.execute(
            "INSERT INTO projects(title,description,genre) VALUES(?,?,?)",
            (
                PROJECT_TITLE,
                "《灰街》前五节锁定后，由 NarrativeOS 正式生成第6—10节。",
                PROJECT_GENRE,
            ),
        )
        project_id = int(project.lastrowid)

        # 前五节用已确认连续性包占位。平台只允许读取锁定事实，不把聊天草稿6—10作为输入。
        locked_titles = ["怀表", "遗产", "河灯街", "十三号仓", "日落"]
        for pos, title in enumerate(locked_titles, start=1):
            conn.execute(
                "INSERT INTO chapters(project_id,title,position,content,status) VALUES(?,?,?,?,?)",
                (project_id, title, pos, PREVIOUS_FIVE if pos == 5 else "", "approved"),
            )

        chapter_ids: dict[int, int] = {}
        for number in range(6, 11):
            cur = conn.execute(
                "INSERT INTO chapters(project_id,title,position,content,status) VALUES(?,?,?,?,?)",
                (project_id, f"第{number}节", number, "", "draft"),
            )
            chapter_ids[number] = int(cur.lastrowid)

        conn.execute(
            "INSERT INTO characters(project_id,name,role,profile,tags) VALUES(?,?,?,?,?)",
            (
                project_id,
                "克莱",
                "主角 / 灰街基层办事员",
                "权限有限，靠观察、跑动、程序缝隙和现实人情推进。不能越权破案，不能神探化。遇到不确定信息会保留判断，也可能判断错误。压力下仍先考虑现实后果。",
                '["基层权限","克制","会受阻","非全知"]',
            ),
        )
        conn.execute(
            "INSERT INTO characters(project_id,name,role,profile,tags) VALUES(?,?,?,?,?)",
            (
                project_id,
                "米拉",
                "与第一笔归还直接相关的人物",
                "已确认收到克莱归还的银牌。她与前五节秘密线有关，但未冻结的身世、动机和知识边界不得由 Writer 随意一次补全。必须保留真实的人物自保、隐瞒与关系压力。",
                '["银牌","第一笔归还","信息边界"]',
            ),
        )

    _persist_memory(
        project_id=project_id,
        task_id=0,
        kind="canon",
        title="《灰街》前五节锁定 Canon",
        content=PREVIOUS_FIVE,
    )
    _persist_memory(
        project_id=project_id,
        task_id=0,
        kind="style",
        title="《灰街》写作风格与硬 Gate",
        content=STYLE_AND_GATE,
    )
    return project_id, chapter_ids


def export_task(task_id: int, number: int) -> tuple[str, dict]:
    task = get_task(task_id) or {}
    content = str(task.get("revised_content") or task.get("draft") or "").strip()
    (OUTPUT_DIR / f"section-{number:02d}.md").write_text(
        f"# 第{number}节\n\n{content}\n",
        encoding="utf-8",
    )
    (OUTPUT_DIR / f"task-{number:02d}.json").write_text(
        json.dumps(task, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return content, task


async def main() -> None:
    os.environ.setdefault("NOVEL_SEED_DEMO", "0")
    init_db()
    project_id, chapter_ids = create_project()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    prior_manuscript = PREVIOUS_FIVE
    manifest = {
        "project_id": project_id,
        "sections": [],
        "machine_gate": "PASS",
        "source_policy": {
            "locked_sections_1_5_full_text_available": False,
            "locked_canon_pack_used": True,
            "unreviewed_chat_draft_6_10_used": False,
            "platform_writer_used": True,
            "heterogeneous_review_rounds": 2,
        },
    }

    full = []
    for number in range(6, 11):
        task_id = _create_task(
            project_id=project_id,
            chapter_id=chapter_ids[number],
            goal=f"正式续写《灰街》第{number}节，并完成本节剧情功能。",
            instruction="\n\n".join(
                [
                    STYLE_AND_GATE,
                    f"【本节目标】\n{SECTION_GOALS[number]}",
                    "只输出当前一节完整小说正文。不得解释工作流，不得写提纲，不得复述前五节。",
                ]
            ),
        )
        result = await _run_frozen_chapter(
            task_id=task_id,
            chapter_number=number,
            prior_manuscript=prior_manuscript,
        )
        content, task = export_task(task_id, number)
        manifest["sections"].append(
            {
                "number": number,
                "task_id": task_id,
                "status": task.get("status"),
                "chars": len(content),
                "runs": [
                    {
                        "role": run.get("role"),
                        "stage": run.get("stage"),
                        "status": run.get("status"),
                        "provider": run.get("provider"),
                        "model": run.get("model"),
                        "error": run.get("error"),
                    }
                    for run in (task.get("runs") or [])
                ],
                "open_blocking_findings": [
                    item
                    for item in (task.get("findings") or [])
                    if item.get("status") == "open" and item.get("severity") == "blocking"
                ],
            }
        )
        full.append(f"# 第{number}节\n\n{content}")
        prior_manuscript += f"\n\n# 第{number}节\n\n{content}"

        if task.get("status") != "awaiting_approval":
            manifest["machine_gate"] = "FAIL"
            manifest["stopped_at"] = number
            break

    combined = "\n\n---\n\n".join(full).strip() + "\n"
    (OUTPUT_DIR / "gray-street-06-10-machine-candidate.md").write_text(
        combined,
        encoding="utf-8",
    )
    (OUTPUT_DIR / "master-reader-packet.md").write_text(
        "# Master Reader Blind Packet\n\n"
        "请连续阅读下面第6—10节候选稿。不要读取机器 Reviewer 结果。"
        "按普通读者、商业阅读感、文学自然度三视角判断；创作总控与最终连续阅读者任一 FAIL 均需返修。\n\n"
        + combined,
        encoding="utf-8",
    )
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
