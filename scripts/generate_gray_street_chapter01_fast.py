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
人物动作必须属于人物本身并改变交流；正文用自然中长句群和完整段落承载。""",
                "冻结 Canon：\n" + canon,
                "专项 Reviewer：\n" + "\n\n".join(reviews),
                "开放 blocking：\n" + (open_blocking_digest(task_id) or "NONE"),
                "四路独立读者：\n" + "\n\n".join(f"[{k}]\n{v}" for k, v in readers.items()),
                "静态文体 Gate：\n" + json.dumps(style, ensure_ascii=False),
            ]
        ),
    )


def export(task_id: int, provider: dict, reviews: list[str], readers: dict, style: dict):
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
                """正文目标 3000—4300 个中文字符。一次写完整。
先把人物写活，再让异常进入日常；不要用短句堆节奏。
所有对白写完都做“人物身体仍在现场吗”的检查，但不要机械插动作。
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
            prior_outputs=reviews,
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

    export(task_id, provider, reviews, readers, style)
    print(json.dumps({"ok": passed, "task_id": task_id, "chars": len(text)}, ensure_ascii=False), flush=True)
    if not passed:
        raise RuntimeError("Gray Street chapter 01 failed final fast Gate; artifact retained")


if __name__ == "__main__":
    asyncio.run(main())
