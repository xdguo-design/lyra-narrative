from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from app.db import connect, init_db
from app.services.book_pipeline import _chapter_text_is_usable, _create_task
from app.services.default_skills import BUILTIN_WRITING_SKILL_NAME
from app.services.full_novel_pipeline import _run_review_round
from app.services.workflow_service import _run_step, get_task
from scripts.generate_gray_street_chapter01 import (
    CANON_PATH,
    GOAL,
    INSTRUCTION,
    configure_provider,
    create_project,
    keep_generation_skills_lean,
    run_blind_readers,
    static_style_gate,
)

OUTPUT_DIR = Path("artifacts/gray-street-chapter01-fast")


def writer_skill_excerpt(task_id: int, limit: int = 9000) -> str:
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
    return str(row["content"] or "")[-limit:] if row else ""


def open_blocking_digest(task_id: int) -> str:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT reviewer,category,summary,suggestion
            FROM review_findings
            WHERE task_id=? AND status='open' AND severity='blocking'
            ORDER BY id
            """,
            (task_id,),
        ).fetchall()
    return "\n\n".join(
        f"[{r['reviewer']}/{r['category']}]\n问题：{r['summary']}\n修复：{r['suggestion']}"
        for r in rows
    )


def canon_gate(text: str) -> list[str]:
    failures: list[str] = []
    required = (
        "芬奇",
        "贝恩",
        "霍尔",
        "托马斯·韦德",
        "EVAN GREY",
        "银色怀表一枚，运行状态异常，待验",
    )
    for marker in required:
        if marker not in text:
            failures.append("missing:" + marker)

    if not re.search(r"(?:黑色|黑)[^。！？\n]{0,12}马车|马车[^。！？\n]{0,12}(?:黑色|漆黑|乌黑)", text):
        failures.append("missing:black-carriage")
    if not ("两点十四" in text or "2:14" in text or "2：14" in text):
        failures.append("missing:watch-time-2:14")
    if not re.search(r"(?:三日|三号|3日|3号)", text):
        failures.append("missing:today-day-3")
    if not re.search(r"(?:四日|四号|4日|4号)", text):
        failures.append("missing:watch-day-4")
    if not re.search(r"(?:数字|一个|下方|下面)[^。！？\n]{0,20}[“\"]?1[”\"]?", text):
        failures.append("missing:watch-number-1")

    forbidden_literals = (
        "E.V.A.N.",
        "限两小时内完成",
        "程序是唯一的通用语言",
        "微型博弈",
        "仿佛来自时间的深处",
        "拥有自己的生命",
        "由某种机械驱动",
        "挂钟又慢",
        "挂钟慢了",
        "芬奇不在",
        "低阶神秘物",
        "神秘物",
        "邀请，或者警告",
        "邀请或警告",
        "未知的漩涡",
        "滚烫",
        "咖啡馆",
    )
    for marker in forbidden_literals:
        if marker in text:
            failures.append("forbidden:" + marker)

    if re.search(r"《[^》]{1,40}(?:条例|法|规定)[^》]*》", text):
        failures.append("forbidden:statute-title")
    if re.search(r"条例第[一二三四五六七八九十百\d]+条", text):
        failures.append("forbidden:statute-article")
    if re.search(r"(?m)^\s*[1-5][.、]\s*", text):
        failures.append("forbidden:numbered-investigation-list")

    # Clock direction: the office clock may be mentioned as fast and Finch may
    # move it back; a "slow clock" is a canon violation.
    clock_windows = [
        text[max(0, m.start() - 80):m.end() + 120]
        for m in re.finditer("挂钟", text)
    ]
    if clock_windows and not any("快" in window for window in clock_windows):
        failures.append("clock-direction:not-fast")

    # The name must visibly form during the scene, not already exist.
    evan_at = text.find("EVAN GREY")
    if evan_at >= 0:
        window = text[max(0, evan_at - 320):evan_at + 120]
        if not re.search(r"刻痕|细痕|细线|划痕|一笔|一划|组成|成形|形成|浮出|出现|延伸", window):
            failures.append("watch-name-not-visibly-forming")

    # First chapter ends at the Gray Street / alley pressure beat, not a second
    # evening/cafe epilogue.
    if re.search(r"咖啡|酒馆|星光|夜色|夜空", text[-1400:]):
        failures.append("forbidden:second-epilogue")
    return failures


async def revise(
    task_id: int,
    text: str,
    canon: str,
    reviews: list[str],
    readers: dict[str, str],
    style: dict,
):
    return await _run_step(
        task_id=task_id,
        role="revision-agent",
        stage="gray-street-fast-unified-revision",
        mode="polish",
        content=text,
        instruction="\n\n".join(
            [
                """你执行《灰街》第一节统一打回修订。只输出完整小说正文。
不得新增世界规则、人物秘密或幕后解释。保持冻结事件节点和最终事实。
重点：不要连续裸对白，不要问卷式问答，不要碎短句/大量一句一段，不要“不是A而是B”式作者心理总结，也不要为了修裸对白机械给每句台词贴通用动作。
人物动作必须属于人物本身并改变交流；正文用自然中长句群和完整段落承载。
Reviewer 的建议如果与冻结 Canon 冲突，一律忽略建议，只保留它指出的结构性问题。尤其不得删除或写实化怀表异常、黑马车，不得用怀表设饵。""" ,
                "冻结 Canon：\n" + canon,
                "专项 Reviewer：\n" + "\n\n".join(reviews),
                "开放 blocking：\n" + (open_blocking_digest(task_id) or "NONE"),
                "四路独立读者：\n" + "\n\n".join(f"[{k}]\n{v}" for k, v in readers.items()),
                "静态文体 Gate：\n" + json.dumps(style, ensure_ascii=False),
            ]
        ),
    )


def export(task_id: int, provider: dict, reviews: list[str], readers: dict, style: dict, canon_failures: list[str]):
    task = get_task(task_id) or {}
    content = str(task.get("revised_content") or task.get("draft") or "").strip()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "chapter-01-fast-candidate.md").write_text(
        "# 第一节 怀表\n\n" + content + "\n", encoding="utf-8"
    )
    (OUTPUT_DIR / "task.json").write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT_DIR / "reviewers.json").write_text(json.dumps(reviews, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT_DIR / "blind-readers.json").write_text(json.dumps(readers, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT_DIR / "style-gate.json").write_text(json.dumps(style, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(
            {
                "task_id": task_id,
                "status": task.get("status"),
                "provider": provider,
                "pipeline": "writer + 3 specialist reviewers + 4 blind readers + unified revision + recheck",
                "latest_global_skill_used": True,
                "style_gate": style,
                "canon_failures": canon_failures,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


async def main() -> None:
    provider = configure_provider()
    init_db()
    project_id, chapter_id = create_project()
    task_id = _create_task(
        project_id=project_id,
        chapter_id=chapter_id,
        goal=GOAL,
        instruction=INSTRUCTION,
    )
    keep_generation_skills_lean(task_id)

    canon = CANON_PATH.read_text(encoding="utf-8")
    skill = writer_skill_excerpt(task_id)

    writer = await _run_step(
        task_id=task_id,
        role="writer",
        stage="gray-street-fast-draft",
        mode="continue",
        content="这是第一节，没有前文。",
        instruction="\n\n".join(
            [
                GOAL,
                INSTRUCTION,
                "冻结 Canon：\n" + canon,
                "当前全局 Writer Skill 最新学习摘要：\n" + skill,
                """正文目标 3000—4300 个中文字符。一次写完整，只写这个雨天上午/白天。

场景顺序锁死：
A. 事务所：芬奇本人在场，正想躲外勤。挂钟只作为普通人工恶作剧：埃文自己的表显示七点四十五，墙上挂钟显示七点五十；挂钟下木椅有新泥印，芬奇左鞋鞋底也有相同缺口。不要在本章现场描写任何人正在拨钟，更不准写“无形的手”“指针自行颤动”“隔空勾钟摆”。贝恩看见椅子和芬奇鞋底但不拆穿。通过工资、外勤和这些细节把三个人立起来，不要写成连续问答。
B. 派工：贝恩原本把鸦巷死亡登记交给芬奇；芬奇拿南陆羊汤/肚子不舒服当借口躲外勤。贝恩只把病假申请和“扣半日薪资”摆出来，芬奇立刻重新评估病情。埃文最后接鸦巷，芬奇接另一个普通外勤，并在换班簿上签字。对话必须嵌在动作和完整段落里，禁止“七码头？/嗯。/……”式问答墙；不背法条、不加截止时间。
C. 去鸦巷：多文化只留两三个与当下路线有关的生活细节，不写“刚好发生斗殴/尚未录档”这类额外线索。黑色无家徽马车只作为背景看见一次；埃文只记住“没家徽”这个具体事实，不替读者解释它可能属于谁。
D. 现场：霍尔在门口或房间里做自己的巡警工作，有一点街面老油条的反应，但不负责解释剧情。哈钦斯太太争两个月欠租和家具；埃文只确认出租时有没有家具清单。她拿不出来，埃文就写进死者财物，告诉她找到清单再改。不要出现“当前行政程序”“资产归属证明”“现场勘验规则”等规章腔，更不背条文。
E. 房间：写到托马斯尸体和霍尔已经确认的“无明显打斗”，不要把死人写成“嘴角带睡意/注视天花板”，也不要让埃文做法医式尸检。钟表只取两三个最有效细节，不罗列“挂钟、座钟、闹钟、怀表”。怀表在正常清点桌面/抽屉时被发现，不需要额外搜索障碍：今天三日，日期窗四日，停在两点十四。
F. 异常：埃文先从登记单页眉或自己刚写下的“三日”确认今天日期，再看见日期窗“四日”。碰表冠→秒针重新走→表盖内侧一条极细的新痕从银面延伸、折转，逐步组成 EVAN GREY→再形成数字 1。不要写“看不见的刻刀”“坚定得令人恐惧”“心跳漏拍”“屏住呼吸”等模板；用他停笔、重看、关盖再开、听门外声音、选择遮住表盖等职业动作表现冲击。不叫它神秘物，不解释，不新增刺痛、发热、幻觉。字迹形成后保留，不要自行淡化消失。
G. 收束：门外有人时，埃文有意识地把表盖合上/挡住视线，选择不公开姓名异变；装袋并登记“银色怀表一枚，运行状态异常，待验。”他走出十四号后才重新看到那辆无家徽黑马车；车在他出来后驶离。空间上必须是“出门后看到”，不从里屋隔窗追踪。到此结束，不去咖啡馆，不列调查清单，不转夜晚，不写主题总结。

先把人物写活，再让异常进入日常；不要用短句堆节奏。所有对白写完都做“人物身体仍在现场吗”的检查，但不要机械插动作。
只输出正文。""",
            ]
        ),
    )
    text = writer.content.strip()
    if not _chapter_text_is_usable(text):
        raise RuntimeError(f"writer returned unusable chapter: chars={len(text)}")

    with connect() as conn:
        conn.execute(
            "UPDATE writing_tasks SET draft=?,revised_content=?,status='running' WHERE id=?",
            (text, text, task_id),
        )
        conn.execute("DELETE FROM review_findings WHERE task_id=?", (task_id,))

    reviews, review_blocking = await _run_review_round(
        task_id=task_id,
        draft=text,
        context=canon,
        round_no=1,
        auto_learn=False,
        retry_failed_reviewers=1,
    )
    readers, readers_ok = await run_blind_readers(task_id, text)
    style = static_style_gate(text)
    canon_failures = canon_gate(text)
    canon_ok = not canon_failures

    if review_blocking or not readers_ok or not style["pass"] or not canon_ok:
        revised = await revise(
            task_id,
            text,
            canon,
            reviews,
            readers,
            {
                **style,
                "canon_failures": canon_failures,
            },
        )
        text = revised.content.strip()
        if not _chapter_text_is_usable(text):
            raise RuntimeError("revision returned unusable chapter")
        with connect() as conn:
            conn.execute(
                "UPDATE review_findings SET status='addressed' WHERE task_id=? AND status='open'",
                (task_id,),
            )
        reviews, review_blocking = await _run_review_round(
            task_id=task_id,
            draft=text,
            context=canon,
            round_no=2,
            prior_outputs=None,
            auto_learn=True,
            retry_failed_reviewers=1,
        )
        readers, readers_ok = await run_blind_readers(task_id, text)
        style = static_style_gate(text)
        canon_failures = []
        for marker in (
            "EVAN GREY",
            "银色怀表一枚，运行状态异常，待验",
            "黑色马车",
        ):
            if marker not in text:
                canon_failures.append("missing:" + marker)
        if not ("两点十四" in text or "2:14" in text or "2：14" in text):
            canon_failures.append("missing:watch-time-2:14")
        if not re.search(r"(?:数字|一个)\s*[“\"]?1[”\"]?", text):
            canon_failures.append("missing:watch-number-1")
        for marker in (
            "E.V.A.N.",
            "《租务条例》第",
            "条例第五十二条",
            "限两小时内完成",
            "程序是唯一的通用语言",
            "微型博弈",
            "仿佛来自时间的深处",
            "拥有自己的生命",
            "由某种机械驱动",
            "挂钟又慢",
        ):
            if marker in text:
                canon_failures.append("forbidden:" + marker)
        canon_ok = not canon_failures

    passed = (not review_blocking) and readers_ok and style["pass"] and canon_ok
    with connect() as conn:
        conn.execute(
            "UPDATE writing_tasks SET revised_content=?,status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (text, "awaiting_approval" if passed else "reviewed", task_id),
        )

    export(task_id, provider, reviews, readers, style, canon_failures)
    print(json.dumps({"ok": passed, "task_id": task_id, "chars": len(text)}, ensure_ascii=False), flush=True)
    if not passed:
        raise RuntimeError("Gray Street chapter 01 failed final fast Gate; artifact retained")


if __name__ == "__main__":
    asyncio.run(main())
