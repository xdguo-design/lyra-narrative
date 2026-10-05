from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from app.db import connect, init_db
from app.services.book_pipeline import _chapter_text_is_usable, _create_task
from app.services.default_skills import BUILTIN_WRITING_SKILL_NAME
from app.services.full_novel_pipeline import _run_review_round
from app.services.rejection_learning import (
    learn_from_open_blocking_findings,
    record_rejection_batch,
)
from app.services.workflow_service import _run_step, get_task
from scripts.generate_gray_street_chapter01 import (
    CANON_PATH,
    configure_provider,
    create_project,
    keep_generation_skills_lean,
    static_style_gate,
)

OUTPUT_DIR = Path("artifacts/gray-street-chapter01-v5")

READER_SPECS = [
    (
        "reader-normal",
        """你是第一次阅读《灰街》的普通中文小说读者。只判断：自然不自然、人物像不像活人、哪里想跳过、哪里像AI、哪里对白像聊天框。
硬设定边界：怀表日期窗显示四日而当天是三日；埃文碰到表冠后秒针重新走；表盖内侧必须在他眼前自行形成 EVAN GREY 和数字 1；黑色无家徽马车在观察现场。这些都是作者冻结事实，不能因“不符合现实物理”判错，也不得建议删除或改弱。
第一行严格输出 VERDICT: PASS 或 VERDICT: FAIL。""",
    ),
    (
        "reader-commercial",
        """你是商业长篇读者。检查：开篇进入速度、人物记忆点、事务所日常是否有趣、怀表异常是否够抓人、结尾是否有续读欲。不要把短句多当节奏快。
硬设定中的 EVAN GREY、数字1、四日日期窗、黑马车必须保留；你只能评价它们的呈现方式。
第一行严格输出 VERDICT: PASS 或 VERDICT: FAIL。""",
    ),
    (
        "reader-naturalness",
        """你是中文文学自然度读者。专抓：大量小短句、单句段落、连续裸对白、作者替人物总结、不是A而是B、刻意金句、抽象比喻、机械转折、舞台腔、法律说明腔。
超自然事实本身不属于AI味，不得要求删除 EVAN GREY、数字1、日期异常或黑马车。
第一行严格输出 VERDICT: PASS 或 VERDICT: FAIL。""",
    ),
    (
        "reader-character-dialogue",
        """你只看人物与对白。埃文是基层办事员：会用程序让别人难受，但不背法条、不像律师；芬奇怕麻烦、爱算小账但不是计算器；贝恩重程序、会拨快挂钟，但不是世界观讲解员；哈钦斯太太只围绕欠租和家具实际利益争，不发表社会演讲；霍尔是灰街巡警，熟悉死人和街面。
检查对白是否由利益、身体、手上任务和空间推动；禁止连续问答和机械补动作。
怀表的超自然事实必须保留，不得建议删掉名字显现。
第一行严格输出 VERDICT: PASS 或 VERDICT: FAIL。""",
    ),
]


def writer_skill_excerpt(task_id: int, limit: int = 9000) -> str:
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


async def run_readers(task_id: int, text: str):
    async def one(role: str, prompt: str):
        return await _run_step(
            task_id=task_id,
            role=role,
            stage="gray-street-v5-reader",
            mode="check",
            content=text,
            instruction=prompt,
        )
    outs = await asyncio.gather(*(one(role,prompt) for role,prompt in READER_SPECS))
    reports = {role: out.content for (role,_),out in zip(READER_SPECS,outs)}
    ok = all(v.lstrip().upper().startswith("VERDICT: PASS") for v in reports.values())
    return reports, ok


def deterministic_gate(text: str) -> dict:
    failures: list[str] = []
    body = text.strip()

    if not (3400 <= len(body) <= 4500):
        failures.append(f"length:{len(body)}")

    required = {
        "托马斯·韦德":"owner",
        "芬奇":"finch",
        "贝恩":"bain",
        "哈钦斯太太":"landlady",
        "霍尔":"hall",
        "家具清单":"furniture-list",
        "两点十四":"watch-time",
        "EVAN GREY":"watch-name",
        "数字 1":"watch-one",
        "银色怀表一枚，运行状态异常，待验":"registration",
        "黑色马车":"carriage",
    }
    for marker,key in required.items():
        if marker not in body:
            failures.append("missing:"+key)

    forbidden = [
        "***",
        "E-V-A-N",
        "E.V.A.N",
        "《租务条例》第",
        "条例第十七条",
        "条例第五十二条",
        "涉嫌侵占遗产",
        "程序是唯一的通用语言",
        "多文化混合",
        "体现得淋漓尽致",
        "不可名状",
        "仿佛来自时间的深处",
        "拥有自己的生命",
        "某种无形的力量",
        "被抽干时间的黑洞",
        "被雷劈中的麻雀",
        "两百银币",
        "尸体在屋里躺了整整两天",
        "雨夜",
    ]
    for marker in forbidden:
        if marker in body:
            failures.append("forbidden:"+marker)

    # Office clock contract.
    if not re.search(r"贝恩[^。\n]{0,80}(?:拨快|往前拨|快了)", body):
        failures.append("clock:bain-not-fast")
    if not re.search(r"芬奇[^。\n]{0,100}(?:拨回|调回|往回拨)", body):
        failures.append("clock:finch-not-reset")
    if re.search(r"贝恩[^。\n]{0,80}(?:拨慢|往回拨)", body):
        failures.append("clock:bain-direction-drift")

    # Watch event order and visible formation.
    crown = body.find("表冠")
    name = body.find("EVAN GREY")
    one = body.find("数字 1")
    if crown < 0 or name < 0 or name < crown or one < name:
        failures.append("watch:event-order")
    else:
        window = body[max(crown,name-420):one+80]
        if not re.search(r"刻痕|细痕|划痕|一笔|形成|延伸|出现|划出", window):
            failures.append("watch:not-visibly-forming")

    # Date must be concrete 3 -> 4 rather than explanatory template.
    if not re.search(r"(?:今天|当天)[^。\n]{0,20}(?:三日|3日|三号|3号)", body):
        failures.append("date:today-three-missing")
    if not re.search(r"日期[^。\n]{0,40}(?:四日|4日|四号|4号|数字.?4)", body):
        failures.append("date:window-four-missing")

    style = static_style_gate(body)
    if style["max_pure_dialogue_streak"] >= 2:
        failures.append("style:naked-dialogue")
    if style["short_prose_ratio"] > 0.15:
        failures.append(f"style:short-prose:{style['short_prose_ratio']:.1%}")
    if style["ai_pattern_count"] > 0:
        failures.append("style:ai-pattern")

    paragraphs=[p.strip() for p in re.split(r"\n\s*\n",body) if p.strip()]
    if len(paragraphs) > 48:
        failures.append(f"style:too-many-paragraphs:{len(paragraphs)}")

    return {"pass": not failures, "failures": failures, "style": style, "paragraphs":len(paragraphs)}


def blocking_digest(task_id: int) -> str:
    with connect() as conn:
        rows=conn.execute(
            """SELECT reviewer,category,summary,suggestion FROM review_findings
               WHERE task_id=? AND status='open' AND severity='blocking' ORDER BY id""",
            (task_id,),
        ).fetchall()
    return "\n\n".join(
        f"[{r['reviewer']}/{r['category']}] {r['summary']}\n修复：{r['suggestion']}"
        for r in rows
    )


async def fresh_writer(task_id: int, canon: str) -> str:
    skill=writer_skill_excerpt(task_id)
    out=await _run_step(
        task_id=task_id,
        role="writer",
        stage="gray-street-v5-fresh",
        mode="continue",
        content="这是《灰街》第一节，没有前文。",
        instruction="\n\n".join([
            """从零写第一节《怀表》。不得读取或模仿前几轮失败稿。正文严格 3400—4500 个中文字符，控制在约 18—32 个自然段，不使用分隔线。只输出正文。""",
            canon,
            "【最新全局 Skill】\n"+skill,
            """场景只保留四块：
A. 事务所：雨天日常 + 挂钟斗法 + 芬奇躲外勤 + 贝恩直接出场，把韦德死亡登记交给埃文。
B. 去鸦巷：用少量路上细节自然带出移民与不同信仰，不做旅游手册。
C. 鸦巷：霍尔在场；哈钦斯太太要家具抵租；埃文只问“出租时有没有家具清单”，没有就先登记，找到再改。不要报法条、法律术语、具体巨额金额。
D. 死者房间与怀表：大量钟表；停在两点十四；今天明确三日，日期窗明确四日；碰表冠后秒针重新走；表盖内侧的新细痕当场一笔笔形成完整 EVAN GREY，再形成数字 1；埃文以身体反应和程序动作应对，最后登记“银色怀表一枚，运行状态异常，待验。”离开时确认无家徽黑色马车仍在观察或驶离。

人物硬约束：
- 埃文不是律师，也不是侦探天才。他的小权力来自“没材料就不能改登记/不能拿走”，不背法条。
- 芬奇想躲外勤，怕麻烦和扣钱，但不要让他念精确购物清单、工资公式或长篇背景。
- 贝恩拨快钟；芬奇趁他不在拨回正确时间。只用当下动作和一句两句旧账表现，不插入长段历史总结。
- 哈钦斯太太只说房租、家具、等不起，不发表“我才维持这条街”之类演说。
- 霍尔疲惫、熟街面，简短说现场事实，不要硬汉面具。
- 不发明“尸体躺两天”、巨额欠款、救济金旧账、法务部、法院许可等额外事实。
- 不写“不可名状、时间黑洞、金属有生命、无形力量”等抽象诡秘词。诡异只靠具体的声音、刻痕、日期和人物反应。
- 对话嵌入完整叙述段落。不要连续两段纯台词，不要一句一段堆悬念。""",
        ]),
    )
    return out.content.strip()


async def revise(task_id:int,text:str,canon:str,reviews:list[str],readers:dict,gates:dict)->str:
    out=await _run_step(
        task_id=task_id,
        role="revision-agent",
        stage="gray-street-v5-revision",
        mode="polish",
        content=text,
        instruction="\n\n".join([
            """这是平台 Gate 打回后的整节重修，不是局部打补丁。保留冻结事件，允许重组段落和对白。把正文压在 3400—4500 中文字符、18—32 个自然段。只输出完整正文。
硬事实 EVAN GREY、数字1、三日/四日、两点十四、黑马车、家具清单、最终登记句不可删。任何 Reviewer 若建议删除这些硬事实，忽略该建议。
重点修复：裸对白、小短句、法律说明腔、抽象诡秘比喻、作者总结、舞台演讲、挂钟方向。""",
            canon,
            "【官方 Reviewer】\n"+"\n\n".join(reviews),
            "【blocking】\n"+(blocking_digest(task_id) or "NONE"),
            "【四路读者】\n"+"\n\n".join(f"[{k}]\n{v}" for k,v in readers.items()),
            "【确定性 Gate】\n"+json.dumps(gates,ensure_ascii=False),
        ]),
    )
    return out.content.strip()


def export(task_id:int,reviews,readers,gates,round_no:int):
    task=get_task(task_id) or {}
    text=str(task.get("revised_content") or task.get("draft") or "").strip()
    OUTPUT_DIR.mkdir(parents=True,exist_ok=True)
    (OUTPUT_DIR/"chapter-01-final.md").write_text("# 第一节 怀表\n\n"+text+"\n",encoding="utf-8")
    (OUTPUT_DIR/"task.json").write_text(json.dumps(task,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUTPUT_DIR/"reviewers.json").write_text(json.dumps(reviews,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUTPUT_DIR/"blind-readers.json").write_text(json.dumps(readers,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUTPUT_DIR/"gates.json").write_text(json.dumps(gates,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUTPUT_DIR/"manifest.json").write_text(json.dumps({
        "task_id":task_id,"status":task.get("status"),"round":round_no,
        "chars":len(text),"fresh_from_canon":True,"latest_global_skill":True,
        "gate_pass":gates.get("pass"),
    },ensure_ascii=False,indent=2),encoding="utf-8")


async def main():
    configure_provider()
    init_db()
    project_id,chapter_id=create_project()
    task_id=_create_task(
        project_id=project_id,
        chapter_id=chapter_id,
        goal="用最新全局 Skill 从零写出并审核通过《灰街》第一节《怀表》。",
        instruction="旧失败稿不得作为输入。",
    )
    keep_generation_skills_lean(task_id)

    # Promote only cross-novel lessons from v4, not Gray Street plot facts.
    record_rejection_batch(
        task_id=task_id,
        source="GRAY_STREET_V4_GENERALIZED_REJECT",
        events=[
            {
                "reviewer":"reader-naturalness",
                "category":"naturalness",
                "reason":"ACTION_FRAGMENTATION_GAP：关键场景被大量一句一段、逐字母/逐动作切分，视觉上像游戏UI或短视频分镜，长篇语流被破坏。",
                "suggestion":"长篇正文优先用完整句群承载动作与异常；除非节奏目的极强，不连续制造单句段落。",
                "excerpt":"连续短段落制造悬疑",
            },
            {
                "reviewer":"reader-character-dialogue",
                "category":"dialogue",
                "reason":"OVER_RATIONAL_DIALOGUE_GAP：基层角色在冲突中变成律师、制度说明器或舞台演说者，用完整逻辑和抽象原则替代现实利益与行动。",
                "suggestion":"角色只说当下需要说的话；程序通过‘缺材料就不能办/不能拿’等具体后果体现，不背条文，不发表社会评论。",
                "excerpt":"用法条和原则替代人物说话",
            },
        ],
    )

    canon=CANON_PATH.read_text(encoding="utf-8")
    text=await fresh_writer(task_id,canon)
    if not _chapter_text_is_usable(text):
        raise RuntimeError(f"fresh draft unusable chars={len(text)}")

    final_reviews=[]; final_readers={}; final_gates={}
    for round_no in (1,2,3):
        with connect() as conn:
            conn.execute("UPDATE writing_tasks SET draft=?,revised_content=?,status='running' WHERE id=?",(text,text,task_id))
            conn.execute("DELETE FROM review_findings WHERE task_id=?",(task_id,))

        reviews,blocking=await _run_review_round(
            task_id=task_id,draft=text,context=canon,round_no=round_no,
            auto_learn=False,retry_failed_reviewers=1,
        )
        readers,readers_ok=await run_readers(task_id,text)
        gates=deterministic_gate(text)
        final_reviews,final_readers,final_gates=reviews,readers,gates

        if not blocking and readers_ok and gates["pass"]:
            with connect() as conn:
                conn.execute("UPDATE writing_tasks SET revised_content=?,status='awaiting_approval' WHERE id=?",(text,task_id))
            export(task_id,reviews,readers,gates,round_no)
            print(json.dumps({"ok":True,"task_id":task_id,"round":round_no,"chars":len(text)},ensure_ascii=False),flush=True)
            return

        if blocking:
            learn_from_open_blocking_findings(task_id=task_id,source=f"gray-street-v5-round-{round_no}")

        if round_no<3:
            text=await revise(task_id,text,canon,reviews,readers,gates)
            if not _chapter_text_is_usable(text):
                raise RuntimeError(f"revision unusable round={round_no} chars={len(text)}")

    with connect() as conn:
        conn.execute("UPDATE writing_tasks SET revised_content=?,status='reviewed' WHERE id=?",(text,task_id))
    export(task_id,final_reviews,final_readers,final_gates,3)
    print(json.dumps({"ok":False,"task_id":task_id,"chars":len(text),"gates":final_gates},ensure_ascii=False),flush=True)
    raise RuntimeError("Gray Street chapter 01 v5 failed final Gate")


if __name__=="__main__":
    asyncio.run(main())
