from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from app.db import connect, init_db
from app.services.book_pipeline import _chapter_text_is_usable, _create_task
from app.services.default_skills import BUILTIN_WRITING_SKILL_NAME
from app.services.full_novel_pipeline import _run_review_round
from app.services.rejection_learning import record_rejection_batch
from app.services.workflow_service import _run_step, get_task
from scripts.generate_gray_street_chapter01 import (
    CANON_PATH,
    configure_provider,
    create_project,
    keep_generation_skills_lean,
    run_blind_readers,
    static_style_gate,
)

SOURCE = Path("books/gray-street/review/chapter-01-fast-rejected.md")
OUTPUT_DIR = Path("artifacts/gray-street-chapter01-repair")


def writer_skill_excerpt(task_id: int, limit: int = 11000) -> str:
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


def deterministic_gate(text: str) -> dict:
    failures = []
    required = [
        "托马斯·韦德",
        "两点十四",
        "EVAN GREY",
        "银色怀表一枚，运行状态异常，待验",
        "黑色马车",
    ]
    for marker in required:
        if marker not in text:
            failures.append("missing:" + marker)

    forbidden = [
        "E.V.A.N.",
        "条例管不了现实",
        "仿佛来自时间的深处",
        "拥有自己的生命",
        "由某种机械驱动",
        "微型博弈",
        "程序是唯一的通用语言",
        "限两小时内完成",
        "《租务条例》第",
        "条例第五十二条",
        "条例第十七条",
    ]
    for marker in forbidden:
        if marker in text:
            failures.append("forbidden:" + marker)

    # The watch text must appear as an event, not as an old inscription.
    evan_at = text.find("EVAN GREY")
    watch_at = text.find("怀表")
    if evan_at >= 0 and watch_at >= 0:
        window = text[max(watch_at, evan_at - 260):evan_at + 120]
        if not re.search(r"刻痕|细线|银屑|一道|逐渐|慢慢|出现|成形|浮出|延伸", window):
            failures.append("watch-name-not-visibly-forming")

    if "挂钟" in text:
        # Bain makes it fast; Finch's private resistance is to move it back.
        if "慢了五分钟" in text or "拨快了" in text and "芬奇" in text:
            failures.append("clock-direction-drift")

    style = static_style_gate(text)
    failures.extend(style["failures"])
    return {"pass": not failures, "failures": failures, "style": style}


LEARNING_EVENTS = [
    {
        "reviewer": "reader-normal",
        "category": "naturalness",
        "reason": "AUTHOR_SUMMARY_GAP / GENERIC_ACTION_GAP：正文用“似乎在核对什么”“带着故意营造的忙碌感”“这是职业本能”等抽象旁白替代可见行为，人物行动被作者解释。",
        "suggestion": "所有小说中优先写可见动作、正在处理的具体对象与后果；删掉不新增事实的心理总结和泛化职业总结。",
        "excerpt": "似乎在核对什么数字 / 带着一种故意营造的忙碌感",
    },
    {
        "reviewer": "reader-character-dialogue",
        "category": "dialogue",
        "reason": "EMBODIED_DIALOGUE_GAP / ORALITY_GAP：冲突场景退化为规章宣读与功能性问答，人物手上任务和现实利益停止，只剩台词交换。",
        "suggestion": "对白先由利益、关系、现场动作和自保驱动；程序只给对方造成具体后果，不背条文，不把角色写成制度说明器。",
        "excerpt": "根据《租务条例》第十七条……条例第五十二条规定……",
    },
    {
        "reviewer": "reader-naturalness",
        "category": "author-summary",
        "reason": "AUTHOR_EFFECT_GAP：用“不是A而是B”、自我纠错式短句、宏大空泛比喻和作者点题制造悬疑，形成明显模型腔。",
        "suggestion": "异常场景只呈现可验证的视觉、声音、触觉和人物选择；不替读者解释，不用短句自问自答制造神秘。",
        "excerpt": "并不是今天，而是明天 / 不，不对 / 仿佛来自时间的深处",
    },
]


async def run_revision(task_id: int, source: str, canon: str, extra: str = "") -> str:
    skill = writer_skill_excerpt(task_id)
    result = await _run_step(
        task_id=task_id,
        role="revision-agent",
        stage="gray-street-evidence-rewrite",
        mode="polish",
        content=source,
        instruction="\n\n".join(
            [
                """把这份被平台打回的《灰街》第一节真正重写，不是逐句润色。保持冻结事件节点，但允许重组段落、话轮和现场动作。
必须修复：
- 办事处挂钟逻辑：贝恩习惯把钟拨快，芬奇私下把它往正确时间拨回；不要写反。
- 删除派工单“限两小时”等未冻结精确要求。
- 芬奇不能一开口就倾倒资料；让他的推活、怕扣钱、熟悉灰街从动作和利益里出来。埃文不要凭空指控或展示神探式观察。
- 哈钦斯太太只围绕欠租、家具、现实损失施压；不说哲学金句。埃文先确认有没有租赁家具清单，再用“没清单就先登记，找到再改”的程序后果挡她；不要背法条、条例编号。
- 尸体不能“注视”天花板；不要替死者写表情心理。
- 旧银怀表必须按 Canon：停在两点十四；登记单/当天日期是三日，日期窗却显示四日；埃文碰表冠后秒针重新走；随后表盖内侧在他眼前形成 EVAN GREY 和数字 1。这个“自行形成”是硬 Canon，绝不能改成早就刻好的旧字，也不要写成作者自我纠错。
- 异常表现克制、具体：细痕在侧光中一笔笔形成即可。不要“金属有生命”“时间深处”“沉默抗议”之类比喻。
- 黑色马车在埃文到鸦巷附近时先被背景性看见一次；结尾再确认它仍在/离开。不要机械马匹比喻，不要重复介绍。
- 埃文最终登记必须出现：银色怀表一枚，运行状态异常，待验。
- 全文以完整段落与自然中长句群为主；不写大量一句一段；不写连续聊天框对白；不为了“有动作”给每句台词机械补动作。
- 删除“不是A而是B”“他不是不怕……”式作者心理总结和抽象主题总结。
- 第一节不解释神秘物体系、幕后贵族或官方秘密机构。""",
                "冻结 Canon：\n" + canon,
                "最新全局 Writer Skill：\n" + skill,
                extra,
                "只输出完整第一节正文，不要标题外的说明。",
            ]
        ),
    )
    return result.content.strip()


def open_findings(task_id: int) -> str:
    with connect() as conn:
        rows = conn.execute(
            """SELECT reviewer,category,summary,suggestion
               FROM review_findings
               WHERE task_id=? AND status='open' AND severity='blocking'
               ORDER BY id""",
            (task_id,),
        ).fetchall()
    return "\n\n".join(
        f"[{r['reviewer']}/{r['category']}] {r['summary']}\n修复：{r['suggestion']}"
        for r in rows
    )


def export(task_id: int, reviews: list[str], readers: dict, gates: dict) -> None:
    task = get_task(task_id) or {}
    content = str(task.get("revised_content") or task.get("draft") or "").strip()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "chapter-01-final-candidate.md").write_text(
        "# 第一节 怀表\n\n" + content + "\n", encoding="utf-8"
    )
    (OUTPUT_DIR / "task.json").write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT_DIR / "reviewers.json").write_text(json.dumps(reviews, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT_DIR / "blind-readers.json").write_text(json.dumps(readers, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT_DIR / "gates.json").write_text(json.dumps(gates, ensure_ascii=False, indent=2), encoding="utf-8")


async def main() -> None:
    configure_provider()
    init_db()
    project_id, chapter_id = create_project()
    task_id = _create_task(
        project_id=project_id,
        chapter_id=chapter_id,
        goal="根据平台真实打回证据重写《灰街》第一节《怀表》，直到 Reviewer/多读者/静态 Gate 通过。",
        instruction="这是打回重写，不得把旧稿当模板照抄。",
    )
    keep_generation_skills_lean(task_id)

    # Blind-reader misses are formal cross-novel learning signals, not book-only notes.
    record_rejection_batch(
        task_id=task_id,
        source="GRAY_STREET_BLIND_READER_REJECT",
        events=LEARNING_EVENTS,
    )

    canon = CANON_PATH.read_text(encoding="utf-8")
    source = SOURCE.read_text(encoding="utf-8")
    text = await run_revision(task_id, source, canon)
    if not _chapter_text_is_usable(text):
        raise RuntimeError(f"first repair unusable: chars={len(text)}")

    final_reviews = []
    final_readers = {}
    final_gates = {}

    for round_no in (1, 2):
        with connect() as conn:
            conn.execute(
                "UPDATE writing_tasks SET draft=?,revised_content=?,status='running' WHERE id=?",
                (text, text, task_id),
            )
            conn.execute("DELETE FROM review_findings WHERE task_id=?", (task_id,))

        reviews, blocking = await _run_review_round(
            task_id=task_id,
            draft=text,
            context=canon,
            round_no=round_no,
            auto_learn=False,
            retry_failed_reviewers=1,
        )
        readers, readers_ok = await run_blind_readers(task_id, text)
        gates = deterministic_gate(text)
        final_reviews, final_readers, final_gates = reviews, readers, gates

        if not blocking and readers_ok and gates["pass"]:
            with connect() as conn:
                conn.execute(
                    "UPDATE writing_tasks SET revised_content=?,status='awaiting_approval' WHERE id=?",
                    (text, task_id),
                )
            export(task_id, reviews, readers, gates)
            print(json.dumps({"ok": True, "task_id": task_id, "round": round_no, "chars": len(text)}, ensure_ascii=False))
            return

        # Formalize official blocking before the next rewrite so global Skill evolves.
        with connect() as conn:
            official_blocking = conn.execute(
                "SELECT COUNT(*) AS n FROM review_findings WHERE task_id=? AND status='open' AND severity='blocking'",
                (task_id,),
            ).fetchone()["n"]
        if official_blocking:
            from app.services.rejection_learning import learn_from_open_blocking_findings
            learn_from_open_blocking_findings(
                task_id=task_id,
                source=f"gray-street-repair-round-{round_no}",
            )

        if round_no == 1:
            text = await run_revision(
                task_id,
                text,
                canon,
                extra="\n\n本轮未通过。官方 blocking：\n"
                + (open_findings(task_id) or "NONE")
                + "\n\n四路读者：\n"
                + "\n\n".join(f"[{k}]\n{v}" for k, v in readers.items())
                + "\n\n确定性 Gate：\n"
                + json.dumps(gates, ensure_ascii=False),
            )
            if not _chapter_text_is_usable(text):
                raise RuntimeError("second repair unusable")

    with connect() as conn:
        conn.execute(
            "UPDATE writing_tasks SET revised_content=?,status='reviewed' WHERE id=?",
            (text, task_id),
        )
    export(task_id, final_reviews, final_readers, final_gates)
    print(json.dumps({"ok": False, "task_id": task_id, "chars": len(text), "gates": final_gates}, ensure_ascii=False))
    raise RuntimeError("Gray Street chapter 01 still failed after two evidence-driven platform rewrites")


if __name__ == "__main__":
    asyncio.run(main())
