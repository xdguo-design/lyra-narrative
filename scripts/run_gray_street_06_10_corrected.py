from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

from app.db import connect, init_db
from app.services.book_pipeline import _create_task, _run_frozen_chapter
from app.services.continuity_service import capture_story_state
from app.services.full_novel_pipeline import _persist_memory
from app.services.workflow_service import _run_step, get_task


PROJECT_TITLE = "灰街｜第6—10节正式续写｜全文连续性修正版"
PROJECT_GENRE = "都市悬疑 / 神秘规则 / 灰街基层调查"
OUTPUT_DIR = Path(os.getenv("NARRATIVE_OUTPUT_DIR", "artifacts/gray-street-corrected-06-10"))
BOOK_DIR = Path("books/gray-street/chapters")
KEEP_SKILLS = {"中文小说自然叙事", "小说精修流程", "小说读者校验流程"}

LOCKED_TITLES = {
    1: "怀表",
    2: "遗产",
    3: "河灯街",
    4: "十三号仓",
    5: "日落",
}

CANON = """【《灰街》前五节锁定 Canon｜以仓库 books/gray-street/chapters/01.md—05.md 正文为最高事实源】
1. 主角是埃文·格雷（EVAN GREY），第七码头街区事务所基层办事员。雷蒙德·克莱是外部遗产主张人/代理层人物，不是主角。禁止混淆两人姓名、身份和视角。
2. 第1节：托马斯·韦德死后，埃文清点遗物时发现异常银色怀表。怀表从 2:14 恢复走动，内盖自行出现“EVAN GREY”和数字“1”。
3. 第2节：怀表出现“四日，日落以前，归还第一笔”。雷蒙德·克莱提交继承主张并表现出对怀表异常细节的超常熟悉。河灯街十三号仓进入主线。
4. 第3—4节：埃文、霍尔等通过现实手续和现场行动追到旧检货房；发现被烧毁/翻动的材料、海关批次、托马斯私人账册和银牌。账册第一页记录“萨维娜·阿尔瓦 / 十二先令 / 冬祭后，归还给米拉”。怀表靠近银牌时出现密跳反应。克莱及律师知道过多信息，但其知识边界尚未揭明。
5. 第5节：米拉·阿尔瓦完成合法领取银牌。数字“1”和“四日，日落以前，归还第一笔”从怀表内盖消失；怀表恢复正常走速，内盖只剩“EVAN GREY”。这证明“归还”可被现实完成，但不允许据此创造新能力。
6. 第5节末：海关索引确认旧账子号“SV-7 / 第7号箱”，且同一财产代理行在前一天查阅过同批次。埃文刚收到一封匿名短函，只有同一海关总批次号和“SV-7 / 第7号箱”，该行被铅笔重重画圈。第6节必须从这个状态自然接续。
7. 怀表截至第5节只验证了正文已经明确出现的现象：异常走时/停止、内盖文字与数字自行出现或消失、靠近银牌时密跳。禁止新增“心率同步、温度变化、自动定位、危险预警、读心、共振识别污染物”等任何未在前五节出现的规则。
8. 埃文不是警察、侦探或打手。优势是程序意识、记录、观察、有限权限、人情与现实跑动；他可以受阻、误判、承担代价，不能突然越权搜查、徒手制服人或全知。
9. 黑色马车/无标车辆在前五节已经高频使用，第6节起必须明显降频，不能继续把“黑车出现”当固定危险提示器。
10. 第6节以后禁止复制“查一张纸→找到地址→再查一张纸”的单一推进结构。程序必须同时成为工具与阻力，允许被对手利用，并与时间、人情、责任、家庭现实成本发生冲突。
11. 家庭成员玛格丽特、露西已经建立，后续不能长期消失；但家庭线只能在确有剧情成本时进入，禁止为完成清单硬插。
12. 托马斯·韦德已死亡。他应通过旧账、他人记忆、遗留行为和矛盾选择逐渐立体，不得复活、现身或突然留下万能说明书。
13. 前五节已正式通过单章 Gate 与连续阅读 Gate。不得回写、重置或改写这些既成事实。
"""

STYLE_AND_GATE = """【本次生产硬 Gate】
1. 正文以完整段落、连续叙事和自然长短句为主，禁止大量单句段、碎短句和台词墙。
2. 对话必须长在人物关系、动作、空间和利益里；禁止资料问答式对白。
3. 先让读者看见、听见、摸到，再允许解释；禁止作者连续替读者总结“这意味着/显然/不是A而是B”。
4. 不新增世界规则，不新增怀表能力，不通过新设定绕开冲突。
5. 每节必须有现场事件、人物选择或现实阻力，不准整节只查档案。
6. 埃文必须保持有限权限；程序既帮助他，也要造成延误、责任或被对手反利用的可能。
7. 第6—10节构成一个完整小阶段：入口→竞争/阻力→代价→局部验证→阶段回收与更危险入口。不得一次揭尽总谜底。
8. Writer / Revision 必须使用平台最新“中文小说自然叙事”“小说精修流程”；Reader 使用“小说读者校验流程”。
9. 任一单章 machine gate 未到 awaiting_approval，立即停止；不能把失败稿当正式正文继续喂给下一节。
10. 第6—10节全部单章通过后，还必须做连续盲读。连续读者 FAIL，则整批不锁稿。
"""

SECTION_GOALS = {
    6: "承接匿名短函与“SV-7 / 第7号箱”。把线索立即变成现实行动或现实冲突；本节必须让某个既有角色/机构主动制造阻力。禁止再用黑车作为主危险提示，也禁止新增怀表规则。",
    7: "让第7号箱的争夺或控制关系升级。埃文必须在有限权限、程序责任和效率之间做一个有代价的选择；对手要学会利用程序，而不是只在暗处观察。",
    8: "把代价推进到人物关系或现实生活。家庭/同事/米拉至少一条既有关系受主线影响，但不得硬插支线；同时给出一项可核实、但不等于总答案的新事实。",
    9: "完成一次高压现实场景或正面交锋。信息必须来自行动、证人、物证或程序后果；埃文允许判断错误或付出代价，不能靠怀表自动解题。",
    10: "完成第6—10节的小阶段闭环：回收一个明确问题，确认一层更大的真实风险，并给下一阶段留下更个人化的入口。章尾靠事件/动作/关系变化收束，不写主题总结句。",
}


def clean_chapter_file(text: str) -> str:
    return re.sub(r"^\s*#\s*第[一二三四五六七八九十0-9]+节[^\n]*\n+", "", text, count=1).strip()


def load_locked_chapters() -> dict[int, str]:
    chapters: dict[int, str] = {}
    for number in range(1, 6):
        path = BOOK_DIR / f"{number:02d}.md"
        if not path.exists():
            raise FileNotFoundError(f"missing locked chapter: {path}")
        chapters[number] = clean_chapter_file(path.read_text(encoding="utf-8"))
    return chapters


def restrict_task_skills(task_id: int) -> None:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT wts.skill_id,s.name,wts.version
            FROM writing_task_skills wts
            JOIN skills s ON s.id=wts.skill_id
            WHERE wts.task_id=?
            """,
            (task_id,),
        ).fetchall()
        keep_ids = [int(row["skill_id"]) for row in rows if str(row["name"]) in KEEP_SKILLS]
        if not keep_ids:
            raise RuntimeError("required narrative skills are not available")
        placeholders = ",".join("?" for _ in keep_ids)
        conn.execute(
            f"DELETE FROM writing_task_skills WHERE task_id=? AND skill_id NOT IN ({placeholders})",
            (task_id, *keep_ids),
        )


def create_state_task(project_id: int, chapter_id: int, number: int) -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO writing_tasks(project_id,chapter_id,goal,instruction,status)
            VALUES(?,?,?,?,?)
            """,
            (
                project_id,
                chapter_id,
                f"从已锁定第{number}节建立 Story State",
                "只提取正文已经成立的连续性事实，不评价、不改写、不补设定。",
                "running",
            ),
        )
        task_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO writing_task_skill_policy(task_id,mode) VALUES(?,?)",
            (task_id, "custom"),
        )
    return task_id


def create_project(locked: dict[int, str]) -> tuple[int, dict[int, int], dict[int, int]]:
    with connect() as conn:
        old = conn.execute("SELECT id FROM projects WHERE title=?", (PROJECT_TITLE,)).fetchone()
        if old:
            conn.execute("DELETE FROM projects WHERE id=?", (old["id"],))

        cur = conn.execute(
            "INSERT INTO projects(title,description,genre) VALUES(?,?,?)",
            (
                PROJECT_TITLE,
                "基于 dev 已锁定前五节全文与最新平台 Skill，正式生成《灰街》第6—10节。",
                PROJECT_GENRE,
            ),
        )
        project_id = int(cur.lastrowid)

        locked_ids: dict[int, int] = {}
        for number in range(1, 6):
            c = conn.execute(
                "INSERT INTO chapters(project_id,title,position,content,status) VALUES(?,?,?,?,?)",
                (
                    project_id,
                    LOCKED_TITLES[number],
                    number,
                    locked[number],
                    "approved",
                ),
            )
            locked_ids[number] = int(c.lastrowid)

        new_ids: dict[int, int] = {}
        for number in range(6, 11):
            c = conn.execute(
                "INSERT INTO chapters(project_id,title,position,content,status) VALUES(?,?,?,?,?)",
                (project_id, f"第{number}节", number, "", "draft"),
            )
            new_ids[number] = int(c.lastrowid)

        characters = [
            ("埃文·格雷", "主角 / 第七码头街区事务所基层办事员",
             "程序意识强，习惯记录、核对时间、编号和证据边界。不是警察也不是格斗型人物；面对异常先记录、验证、保留判断。家庭现实和稳定收入对他很重要。"),
            ("雷蒙德·克莱", "遗产主张人 / 外部代理层人物",
             "三十出头，体面克制，常戴皮手套，与律师同行；对韦德遗物、十三号仓和批次信息知道得过多，但截至第5节只处于第一层代理位置，知识边界仍需逐步揭示。"),
            ("米拉·阿尔瓦", "第一笔归还对象 / 洗熨工",
             "萨维娜之女，已合法收回母亲银牌；右手虎口有旧烫疤，有自己的判断和戒心。面对高价收购主动拒绝，并要求查清是谁让韦德拖了七年。"),
            ("艾萨克·芬奇", "事务所同事",
             "怕麻烦、会算小账、熟旧街关系；挂钟、六便士欠账和窗口办事形成稳定人物记忆点。"),
            ("哈罗德·贝恩", "事务所主管",
             "经验型程序判断，使用缺口白瓷杯；知道异常物存在但不抢着解释，强调看见什么写什么。"),
            ("霍尔", "警员 / 埃文的现实协作方",
             "守权限、重现场记录；危险真正发生时能处置，但不会为埃文越权。"),
            ("玛格丽特", "埃文家人",
             "负责家中现实账目与生活压力；煤钱、衣物、收入等现实成本已进入故事。"),
            ("露西", "埃文家人",
             "说话直接，和埃文有熟人式互损与关心；家庭线中的现实声音。"),
            ("托马斯·韦德", "已故钟表匠 / 事件源头",
             "六十一岁，已死亡。留下怀表、旧账、十三号仓相关线索和迟延七年的银牌返还；后续只能通过遗留痕迹和他人记忆继续塑造。"),
        ]
        for name, role, profile in characters:
            conn.execute(
                "INSERT INTO characters(project_id,name,role,profile,tags) VALUES(?,?,?,?,?)",
                (project_id, name, role, profile, "[]"),
            )

    _persist_memory(
        project_id=project_id,
        task_id=0,
        kind="canon",
        title="《灰街》前五节锁定 Canon / identity guard",
        content=CANON,
    )
    _persist_memory(
        project_id=project_id,
        task_id=0,
        kind="style",
        title="《灰街》第6—10节生产 Gate",
        content=STYLE_AND_GATE,
    )
    return project_id, locked_ids, new_ids


async def seed_story_state(project_id: int, locked_ids: dict[int, int], locked: dict[int, str]) -> None:
    for number in range(1, 6):
        task_id = create_state_task(project_id, locked_ids[number], number)
        await capture_story_state(
            task_id=task_id,
            project_id=project_id,
            chapter_id=locked_ids[number],
            chapter_number=number,
            chapter_content=locked[number],
        )
        with connect() as conn:
            conn.execute(
                "UPDATE writing_tasks SET status='awaiting_approval',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (task_id,),
            )


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


async def continuous_reader(project_id: int, combined: str) -> tuple[str, dict]:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO writing_tasks(project_id,chapter_id,goal,instruction,status)
            VALUES(?,?,?,?,?)
            """,
            (
                project_id,
                None,
                "连续盲读《灰街》第6—10节并做最终阶段 Gate",
                STYLE_AND_GATE,
                "running",
            ),
        )
        task_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO writing_task_skill_policy(task_id,mode) VALUES(?,?)",
            (task_id, "default"),
        )
        skills = conn.execute(
            "SELECT id,current_version,name FROM skills WHERE enabled=1 AND (project_id IS NULL OR project_id=?)",
            (project_id,),
        ).fetchall()
        for row in skills:
            if str(row["name"]) == "小说读者校验流程":
                conn.execute(
                    "INSERT INTO writing_task_skills(task_id,skill_id,version) VALUES(?,?,?)",
                    (task_id, row["id"], row["current_version"]),
                )

    result = await _run_step(
        task_id=task_id,
        role="master-continuous-reader",
        stage="sections-06-10-continuous-read",
        mode="check",
        content=combined,
        instruction="""你是《灰街》第6—10节最终连续阅读者。不要读取任何机器 Reviewer 结论，只把自己当成第一次连续读这五节的真实读者。

必须同时用三个视角：
- 普通读者：好不好看、人物是否活、哪里假、哪里想跳过；
- 商业阅读：推进、钩子、人物记忆点、五节是否形成阶段闭环；
- 文学自然度：AI味、模板句、碎短句、作者总结、对白是否书面化、场景是否有可感知表面。

额外硬检查：
1. 主角必须始终是埃文·格雷，不能与雷蒙德·克莱混淆。
2. 不得新增前五节没有验证过的怀表能力/规则。
3. 黑色马车/无标车辆不得再次被当作高频固定危险提示。
4. 不得退回“查纸→地址→新纸”的单一推进模板。
5. 埃文不能越权神探化、格斗化或全知。
6. 第6—10节必须既有局部兑现，又留下更危险但明确的下一阶段问题。
7. 若任何一条硬问题成立，总判定必须 FAIL。

最后严格写一行：
VERDICT: PASS
或
VERDICT: FAIL
并在前面给出可定位、可执行的阅读意见。""",
    )
    verdict = "PASS" if re.search(r"VERDICT:\s*PASS\b", result.content, re.I) else "FAIL"
    with connect() as conn:
        conn.execute(
            "UPDATE writing_tasks SET draft=?,revised_content=?,status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (
                result.content,
                result.content,
                "awaiting_approval" if verdict == "PASS" else "reviewed",
                task_id,
            ),
        )
    return verdict, {"task_id": task_id, "provider": result.provider, "model": result.model, "review": result.content}


async def main() -> None:
    os.environ.setdefault("NOVEL_SEED_DEMO", "0")
    init_db()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    locked = load_locked_chapters()
    project_id, locked_ids, chapter_ids = create_project(locked)
    await seed_story_state(project_id, locked_ids, locked)

    prior_manuscript = "\n\n".join(
        f"# 第{number}节 {LOCKED_TITLES[number]}\n\n{locked[number]}"
        for number in range(1, 6)
    )

    manifest = {
        "project_id": project_id,
        "base_sha": os.getenv("GITHUB_SHA", ""),
        "source_policy": {
            "locked_sections_1_5_full_text_loaded_from_repo": True,
            "story_state_seeded_from_full_locked_text": True,
            "wrong_previous_section_6_reused": False,
            "latest_writer_refinement_reader_skills_retained": True,
        },
        "sections": [],
        "machine_gate": "PASS",
        "continuous_reader_gate": "NOT_RUN",
    }

    generated: list[str] = []
    for number in range(6, 11):
        task_id = _create_task(
            project_id=project_id,
            chapter_id=chapter_ids[number],
            goal=f"正式续写《灰街》第{number}节；必须承接已锁定前文与 Story State。",
            instruction="\n\n".join(
                [
                    CANON,
                    STYLE_AND_GATE,
                    f"【本节功能】\n{SECTION_GOALS[number]}",
                    "只输出当前一节完整正文，不输出章名、提纲、解释、审核说明或工作流状态。",
                ]
            ),
        )
        restrict_task_skills(task_id)
        await _run_frozen_chapter(
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
                "open_blocking_findings": [
                    item
                    for item in (task.get("findings") or [])
                    if item.get("status") == "open" and item.get("severity") == "blocking"
                ],
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
            }
        )
        if task.get("status") != "awaiting_approval":
            manifest["machine_gate"] = "FAIL"
            manifest["stopped_at"] = number
            break
        generated.append(f"# 第{number}节\n\n{content}")
        prior_manuscript += f"\n\n# 第{number}节\n\n{content}"

    combined = "\n\n---\n\n".join(generated).strip() + ("\n" if generated else "")
    (OUTPUT_DIR / "gray-street-06-10-machine-candidate.md").write_text(combined, encoding="utf-8")

    if manifest["machine_gate"] == "PASS" and len(generated) == 5:
        verdict, reader = await continuous_reader(project_id, combined)
        manifest["continuous_reader_gate"] = verdict
        manifest["continuous_reader"] = reader
        (OUTPUT_DIR / "continuous-reader.md").write_text(reader["review"], encoding="utf-8")
    else:
        manifest["continuous_reader_gate"] = "NOT_RUN"

    final_pass = (
        manifest["machine_gate"] == "PASS"
        and manifest["continuous_reader_gate"] == "PASS"
        and len(generated) == 5
    )
    manifest["final_lock_candidate"] = final_pass

    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False), flush=True)

    if not final_pass:
        raise RuntimeError("Gray Street 06-10 did not pass all platform gates")


if __name__ == "__main__":
    asyncio.run(main())
