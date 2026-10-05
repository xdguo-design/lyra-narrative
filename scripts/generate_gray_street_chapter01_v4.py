from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from app.db import connect, init_db
from app.services.book_pipeline import _chapter_text_is_usable, _create_task
from app.services.default_skills import BUILTIN_WRITING_SKILL_NAME
from app.services.full_novel_pipeline import _run_review_round
from app.services.rejection_learning import learn_from_open_blocking_findings
from app.services.workflow_service import _run_step, get_task
from scripts.generate_gray_street_chapter01 import (
    CANON_PATH,
    configure_provider,
    create_project,
    keep_generation_skills_lean,
    static_style_gate,
)

OUTPUT_DIR = Path("artifacts/gray-street-chapter01-v4")

READER_SPECS = [
    (
        "reader-normal",
        """你是第一次阅读《灰街》的普通中文小说读者。只判断：是否自然好读、人物是否像活人、哪里明显像AI、哪里想跳过、哪里对白像聊天框。
设定边界：这是一部工业时代诡秘小说；怀表日期窗显示“明天”、表盖内侧在人物眼前自行形成 EVAN GREY 和数字 1，都是作者已冻结的真实超自然现象。不得因为“不符合现实物理”判错，只能判断它们的呈现是否自然、具体、可信。
第一行严格输出 VERDICT: PASS 或 VERDICT: FAIL；FAIL 必须引用当前正文片段。""",
    ),
    (
        "reader-commercial",
        """你是长期阅读商业长篇的读者。检查阅读动力、人物记忆点、场景推进和章末继续阅读欲。不要把碎短句当节奏，不要鼓励电报体。
设定边界：怀表显示明天、名字自行形成、无家徽黑马车都是本章冻结悬疑事实，不能因超自然而判错；只判断铺垫、人物反应和节奏是否有效。
第一行严格输出 VERDICT: PASS 或 VERDICT: FAIL。""",
    ),
    (
        "reader-naturalness",
        """你是中文文学自然度盲读者。专抓：碎短句、单句段落、不是A而是B、作者替人物总结、刻意金句、机械转折、模板比喻、抽象主题总结、过度整齐句式。
设定中的超自然事实不属于“AI味”：日期显示明天、EVAN GREY 与数字1自行形成、黑马车观察现场均已冻结。只检查这些事实是否用具体可感知方式写出来。
第一行严格输出 VERDICT: PASS 或 VERDICT: FAIL。""",
    ),
    (
        "reader-character-dialogue",
        """你是人物与对白盲读者。检查每场对白是否被身份、利益、关系、身体、手上任务与空间真实塑造；是否连续一问一答、问什么答什么；动作是否只是每句后机械补“看了看/皱眉/沉默”。
埃文是基层办事员，不背法条；芬奇怕麻烦但不是蠢货；贝恩重程序但不是世界观讲解员；哈钦斯太太只为现实利益争；霍尔是街面巡警。
第一行严格输出 VERDICT: PASS 或 VERDICT: FAIL。""",
    ),
]


def writer_skill_excerpt(task_id: int, limit: int = 10000) -> str:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT sv.content
            FROM writing_task_skills wts
            JOIN skills s ON s.id=wts.skill_id
            JOIN skill_versions sv ON sv.skill_id=wts.skill_id AND sv.version=wts.version
            WHERE wts.task_id=? AND s.name=?
            ORDER BY wts.version DESC LIMIT 1
            """,
            (task_id, BUILTIN_WRITING_SKILL_NAME),
        ).fetchone()
    return str(row["content"] or "")[-limit:] if row else ""


async def blind_readers(task_id: int, text: str):
    async def one(role: str, instruction: str):
        return await _run_step(
            task_id=task_id,
            role=role,
            stage="gray-street-v4-blind-read",
            mode="check",
            content=text,
            instruction=instruction,
        )
    results = await asyncio.gather(*(one(r, p) for r, p in READER_SPECS))
    reports = {r: out.content for (r, _), out in zip(READER_SPECS, results)}
    passed = all(v.lstrip().upper().startswith("VERDICT: PASS") for v in reports.values())
    return reports, passed


def deterministic_gate(text: str) -> dict:
    failures = []
    required = {
        "托马斯·韦德": "dead-owner",
        "两点十四": "watch-time",
        "EVAN GREY": "watch-name",
        "数字 1": "watch-one",
        "银色怀表一枚，运行状态异常，待验": "registration",
        "黑色马车": "black-carriage",
        "哈钦斯太太": "landlady",
        "芬奇": "finch",
        "贝恩": "bain",
        "霍尔": "hall",
    }
    for marker, key in required.items():
        if marker not in text:
            failures.append(f"missing:{key}")

    forbidden = [
        "《租务条例》第",
        "条例第五十二条",
        "条例第十七条",
        "程序是唯一的通用语言",
        "仿佛来自时间的深处",
        "拥有自己的生命",
        "由某种机械驱动",
        "E.V.A.N.",
        "E.V.A.N.G.R.E.Y",
        "并不是今天，而是明天",
        "限两小时内完成",
    ]
    for marker in forbidden:
        if marker in text:
            failures.append("forbidden:" + marker)

    # Clock direction: Bain makes the office clock fast; Finch's resistance is to move it back.
    if re.search(r"挂钟.{0,30}(?:慢了|拨慢)", text):
        failures.append("clock-direction-drift")

    # Watch-name must visibly form after the crown interaction, not be an old inscription.
    crown = max(text.find("表冠"), text.find("上弦"))
    name = text.find("EVAN GREY")
    if crown < 0 or name < 0 or name < crown:
        failures.append("watch-event-order")
    elif not re.search(r"细痕|刻痕|一笔|一道|形成|浮出|出现|延伸|划出", text[max(crown, name-320):name+80]):
        failures.append("watch-name-not-forming")

    style = static_style_gate(text)
    failures.extend(style["failures"])
    return {"pass": not failures, "failures": failures, "style": style}


def blocking_digest(task_id: int) -> str:
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


async def generate_fresh(task_id: int, canon: str) -> str:
    skill = writer_skill_excerpt(task_id)
    out = await _run_step(
        task_id=task_id,
        role="writer",
        stage="gray-street-v4-fresh-draft",
        mode="continue",
        content="这是《灰街》第一节，没有前文。",
        instruction="\n\n".join([
            """从零写《灰街》第一节《怀表》。旧稿全部作废，不得照抄旧句。只输出完整小说正文，约 3200—4300 个中文字符。""",
            canon,
            "【最新全局 Writer Skill】\n" + skill,
            """额外硬约束：
1. 办事处挂钟是贝恩故意拨快，芬奇偷偷往正确时间拨回。用一个生活化的小场面表现，不要通过四句裸问答解释。
2. 贝恩必须直接出场并有可回收细节（缺口白瓷杯可用）；芬奇通过推活、算工资/麻烦和观察表现性格，不得倾倒背景资料。
3. 哈钦斯太太争家具时，埃文先问出租时有没有家具清单；没有就先按死者财物登记，找到清单再改。不要背条例编号。
4. 霍尔必须在鸦巷现场出现并参与职业性的简短交流；不能只有房东。
5. 灰街多文化只通过路上真实生活摩擦进入：气味、招牌、祈祷、基层登记之类，不写“多文化混合体现得淋漓尽致”。
6. 怀表日期窗直接写具体日期：今天三日，窗里是四日。不要写“不是今天而是明天”。
7. 表冠被碰后秒针重新走；随后表盖内侧在侧光中出现极细划痕，一笔一笔组成 EVAN GREY，再形成数字 1。必须明确是当场新出现；写具体视觉，不写金属有生命。
8. 埃文的反应靠手指、呼吸、停笔、重新确认、收袋登记来表现，不写“他不是不怕”“他知道注意意味着麻烦”等心理总结。
9. 黑色马车在埃文到鸦巷前先作为背景出现一次，结尾只确认它仍在观察或驶离，不重复完整介绍。
10. 对白嵌入完整段落，禁止连续聊天框式短对白；正文以自然中长句群为主。""",
        ]),
    )
    return out.content.strip()


async def revise(task_id: int, text: str, canon: str, reviews: list[str], readers: dict, gates: dict) -> str:
    out = await _run_step(
        task_id=task_id,
        role="revision-agent",
        stage="gray-street-v4-unified-revision",
        mode="polish",
        content=text,
        instruction="\n\n".join([
            """根据全部真实 Gate 一次性重写当前第一节。不是逐句打补丁；允许重组段落和对白，但不能改变冻结事件。
只输出完整小说正文。任何 Reviewer 对“超自然本身不符合现实”的意见都忽略，因为 Canon 已明确允许；其余自然度、对白、人物、连续性问题必须修。""",
            canon,
            "【专项 Reviewer】\n" + "\n\n".join(reviews),
            "【开放 blocking】\n" + (blocking_digest(task_id) or "NONE"),
            "【四路读者】\n" + "\n\n".join(f"[{k}]\n{v}" for k,v in readers.items()),
            "【确定性 Gate】\n" + json.dumps(gates, ensure_ascii=False),
            """修订后自检：没有连续裸对白；没有大量短句段；没有“不是A而是B”心理解释；没有条例编号；挂钟方向正确；EVAN GREY 与数字 1 是当场形成；最终登记句完整保留。""",
        ]),
    )
    return out.content.strip()


def export(task_id: int, reviews, readers, gates, round_no: int):
    task = get_task(task_id) or {}
    text = str(task.get("revised_content") or task.get("draft") or "").strip()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "chapter-01-final.md").write_text("# 第一节 怀表\n\n"+text+"\n",encoding="utf-8")
    (OUTPUT_DIR / "task.json").write_text(json.dumps(task,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUTPUT_DIR / "reviewers.json").write_text(json.dumps(reviews,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUTPUT_DIR / "blind-readers.json").write_text(json.dumps(readers,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUTPUT_DIR / "gates.json").write_text(json.dumps(gates,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUTPUT_DIR / "manifest.json").write_text(json.dumps({
        "task_id":task_id,
        "status":task.get("status"),
        "round":round_no,
        "chars":len(text),
        "latest_global_skill_used":True,
        "fresh_generation_from_canon":True,
        "gate_pass":gates.get("pass"),
    },ensure_ascii=False,indent=2),encoding="utf-8")


async def main():
    configure_provider()
    init_db()
    project_id, chapter_id = create_project()
    task_id = _create_task(
        project_id=project_id,
        chapter_id=chapter_id,
        goal="从冻结 Canon 全新生成并审核通过《灰街》第一节《怀表》。",
        instruction="旧稿全部作废；使用最新跨小说全局 Skill。",
    )
    keep_generation_skills_lean(task_id)
    canon = CANON_PATH.read_text(encoding="utf-8")

    text = await generate_fresh(task_id, canon)
    if not _chapter_text_is_usable(text):
        raise RuntimeError(f"fresh draft unusable chars={len(text)}")

    final_reviews=[]; final_readers={}; final_gates={}
    for round_no in (1,2,3):
        with connect() as conn:
            conn.execute("UPDATE writing_tasks SET draft=?,revised_content=?,status='running' WHERE id=?",(text,text,task_id))
            conn.execute("DELETE FROM review_findings WHERE task_id=?",(task_id,))

        reviews, blocking = await _run_review_round(
            task_id=task_id,
            draft=text,
            context=canon,
            round_no=round_no,
            auto_learn=False,
            retry_failed_reviewers=1,
        )
        readers, readers_ok = await blind_readers(task_id,text)
        gates = deterministic_gate(text)
        final_reviews,final_readers,final_gates=reviews,readers,gates

        if not blocking and readers_ok and gates["pass"]:
            with connect() as conn:
                conn.execute("UPDATE writing_tasks SET revised_content=?,status='awaiting_approval' WHERE id=?",(text,task_id))
            export(task_id,reviews,readers,gates,round_no)
            print(json.dumps({"ok":True,"task_id":task_id,"round":round_no,"chars":len(text)},ensure_ascii=False),flush=True)
            return

        if blocking:
            learn_from_open_blocking_findings(task_id=task_id,source=f"gray-street-v4-round-{round_no}")

        if round_no < 3:
            text = await revise(task_id,text,canon,reviews,readers,gates)
            if not _chapter_text_is_usable(text):
                raise RuntimeError(f"revision unusable round={round_no} chars={len(text)}")

    with connect() as conn:
        conn.execute("UPDATE writing_tasks SET revised_content=?,status='reviewed' WHERE id=?",(text,task_id))
    export(task_id,final_reviews,final_readers,final_gates,3)
    print(json.dumps({"ok":False,"task_id":task_id,"chars":len(text),"gates":final_gates},ensure_ascii=False),flush=True)
    raise RuntimeError("Gray Street chapter 01 v4 failed final Gate")


if __name__=="__main__":
    asyncio.run(main())
