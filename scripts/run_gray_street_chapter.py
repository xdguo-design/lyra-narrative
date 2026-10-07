from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

from app.db import connect, init_db
from app.services.book_pipeline import _chapter_text_is_usable, _create_task
from app.services.default_skills import BUILTIN_WRITING_SKILL_NAME
from app.services.workflow_service import _run_step
from scripts.generate_gray_street_chapter01 import CANON_PATH, configure_provider, create_project, keep_generation_skills_lean

REQUEST = Path(".github/requests/gray-street-chapter-run.json")
PLAN = Path("books/gray-street/arc/ch01-05-plan.md")
OUT_ROOT = Path("artifacts/gray-street-chapter-run")

TITLES = {
    2: "遗产", 3: "河灯街", 4: "十三号仓", 5: "日落",
    6: "第7号箱", 7: "阅览室", 8: "第八节", 9: "第九节", 10: "第十节",
}
SECTION_HEADERS = {2: "## 第二节《遗产》", 3: "## 第三节《河灯街》", 4: "## 第四节《十三号仓》", 5: "## 第五节《日落》"}

POST5_CANON = """【第6节以后锁定连续性】
- 主角是埃文·格雷（EVAN GREY）；雷蒙德·克莱是外部遗产主张人/代理层人物。两人绝不能混淆。
- 第5节已经完成第一笔归还：米拉·阿尔瓦合法收回母亲萨维娜的银牌；怀表上的数字1与“四日，日落以前，归还第一笔”消失，内盖只剩 EVAN GREY，走速恢复正常。
- 第5节章末：埃文收到匿名短函，只写同一海关总批次号与“SV-7 / 第7号箱”，并被铅笔重重画圈。第6节必须从这个状态自然接上。
- 怀表截至第5节只验证过：异常走时/停止、内盖文字与数字自行出现或消失、靠近银牌时密跳。禁止新增心率同步、温度变化、自动定位、危险预警、读心、污染识别、共振导航等新能力或新规则。
- 埃文是基层办事员，不是警察、侦探或打手；靠程序、记录、有限权限、人情与现实跑动推进，可以受阻、误判和付代价。
- 黑色马车/无标车辆在前五节已经达到直接出场上限，第6节起必须明显降频，不能继续当固定危险提示器。
- 禁止复制“查纸→地址→新纸”的单一推进。程序既要帮助埃文，也要造成延误、责任或被对手反利用。
- 家庭成员玛格丽特、露西已经建立；只有当主线现实成本真正碰到家庭时才进入，禁止硬插。
- 托马斯·韦德已经死亡，只能通过旧账、遗留行为和他人记忆继续塑造，不能复活或留下万能说明书。
"""

POST5_GOALS = {
    6: "从第5节最后一句之后的几分钟直接承接：信差已经把匿名短函交到埃文手里，埃文已经看见同一批次号与“SV-7 / 第7号箱”，不能重演送信、第一次拆看或第一次抄进卷宗。短函只是一条人为送来的线索，不含新的怀表规则或时间窗口。第6节的主要冲突收束为一条：代理方利用正式程序试图暂缓十三号仓相关遗物的后续处理，埃文必须在没有越权的前提下决定如何接收、登记、保留异议并守住下一步。优先使用贝恩、芬奇、雷蒙德·克莱/其律师以及已经出现的代理行；不要再新增一个海关官员进门长篇讲权限。若需要海关信息，只能通过已有索引摘录、正式来函或一句岗位性通知体现。本节至少完成一项可核实的新状态变化，但不得解释第7号箱本质。",
    7: "让第7号箱的争夺或控制关系升级；埃文必须在有限权限、程序责任和效率之间做一个有代价的选择，对手开始利用程序。",
    8: "把代价推进到人物关系或现实生活；至少一条既有关系被主线真实影响，同时获得一项可核实但不等于总答案的新事实。",
    9: "完成一次高压现实场景或正面交锋；信息来自行动、证人、物证或程序后果，埃文允许误判或付代价，怀表不能自动解题。",
    10: "完成第6—10节小阶段闭环：回收一个明确问题，确认一层更大风险，并留下更个人化的下一阶段入口；章尾不用总结句。",
}

REVIEWERS = [
    ("continuity-reviewer", "连续性与剧情", "检查时间地点、道具、人物知识来源、权限、因果、线索顺序和前后章接口。"),
    ("character-dialogue-reviewer", "人物与对白", "检查人物利益、声音、工具人倾向、规章腔、裸对白、问卷式轮流和动作是否机械填充。"),
    ("language-rhythm-reviewer", "语言与节奏", "检查小短句、单句段落、作者总结、不是A而是B、模型腔、句群和场景节奏。"),
    ("blind-reader", "普通读者", "只看当前正文和必要前文，判断是否好读、哪里假、哪里想跳过、人物是否像活人。"),
    ("cadence-character-reader", "商业读者", "检查阅读动力、章节推进、人物记忆点、钩子和是否靠短句硬推。"),
    ("blind-natural-reader", "文学自然度读者", "检查AI味、模板解释、机械过渡、过于工整和不自然中文。"),
    ("character-voice-reviewer", "人物读者", "检查每个主要人物是否按自身利益和关系行动，而非剧情工具。"),
    ("blind-dialogue-reader", "对白读者", "检查台词是否自然、具身体和空间感，是否存在脚本式问答、信息倾倒和规章腔。"),
]


def extract_plan(chapter_no: int) -> str:
    if chapter_no >= 6:
        return POST5_CANON + "\n\n【本节功能】\n" + POST5_GOALS[chapter_no] + """

【第6—10节共同硬规则】
- 正文以完整段落和自然中长句群为主，禁止大量一句一段、裸对白、问卷式问答和作者总结。
- 每节必须有现场事件、人物选择或现实阻力，不准整节只查档案。
- 不新增世界规则，不通过新设定绕开冲突。
- 世界处于类似十九世纪工业化欧洲的钢铁时代：只使用纸档、印章、钥匙、封条、账册、手写登记、实体柜架、铁路/马车/煤气灯等已经成立的技术层级。禁止“数字化档案、刷卡/刷开信物、电子系统、数据库、屏幕、二维码”等现代设施。
- 第6节不得让黑色马车、无家徽车辆重新在现场出现，也不得安排霍尔重复执行第5节已经失败的南桥跟车；若必须提到，只能作为一句既成事实回顾。
- 米拉的银牌已在第5节合法返还并由米拉本人持有，只能作为已发生事实回忆，不能再成为埃文手里的证物或当前待处理物。
- 匿名短函只写批次号与“SV-7 / 第7号箱”，没有倒计时、行动窗口或神秘指令，不得替它补含义。
- 第5节最后一句已经完成“信差递函→埃文看到内容”。第6节严禁再次写“信差把/递来/搁下短函”、再次第一次检查短函字迹、再次第一次抄入卷宗。可以从“信差刚离开、短函已压在卷宗上”之后开始。
- 第6节不新增命名海关官员承担关键说明，不让新NPC通过长对白讲权限、法律或关键历史；程序阻力尽量通过克莱律师的正式文书、贝恩的短判断、芬奇手头既有公务和埃文的具体登记动作发生。
- 第6—10节整体要形成入口→竞争/阻力→代价→局部验证→阶段回收与更危险入口。"""
    text = PLAN.read_text(encoding="utf-8")
    start = text.index(SECTION_HEADERS[chapter_no])
    next_candidates = [text.find(h, start + 1) for n, h in SECTION_HEADERS.items() if n > chapter_no]
    next_candidates = [x for x in next_candidates if x >= 0]
    end = min(next_candidates) if next_candidates else text.find("## 前五节共同硬规则", start)
    common = text[text.index("## 前五节共同硬规则"):]
    return text[start:end].strip() + "\n\n" + common.strip()


def skill_excerpt(task_id: int, limit: int = 12000) -> str:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT sv.content FROM writing_task_skills wts
            JOIN skills s ON s.id=wts.skill_id
            JOIN skill_versions sv ON sv.skill_id=wts.skill_id AND sv.version=wts.version
            WHERE wts.task_id=? AND s.name=?
            ORDER BY wts.version DESC LIMIT 1
            """,
            (task_id, BUILTIN_WRITING_SKILL_NAME),
        ).fetchone()
    return str(row["content"] or "")[-limit:] if row else ""


def verdict(text: str) -> str:
    m = re.search(r"VERDICT\s*[:：]\s*(PASS|FAIL)", text, re.I)
    return m.group(1).upper() if m else "FAIL"


def normalize_novel_output(raw: str) -> str:
    """Keep only the novel body from a model response and fail closed on leaked analysis."""
    text = str(raw or "").strip()
    text = re.sub(r"^\s*\`\`\`(?:markdown|md|text)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*\`\`\`\s*$", "", text).strip()

    # Some revision models prepend their plan/reasoning before a clearly labeled
    # final body. Accept only the body after that marker.
    markers = list(re.finditer(
        r"(?mi)^#{1,4}\s*(?:润色后正文|修订后正文|最终正文|小说正文|正文)\s*$",
        text,
    ))
    if markers:
        text = text[markers[-1].end():].strip()

    # Remove one leading chapter heading emitted by the model.
    text = re.sub(
        r"(?m)^\s*#{1,4}\s*第[^\n]{0,40}(?:节|章)[^\n]*\n+",
        "",
        text,
        count=1,
    ).strip()

    leaked = re.search(
        r"(?mi)^#{1,4}\s*(?:思考过程|分析|分析约束|修改策略|重写策略|修订策略|检查清单|说明)\s*$",
        text,
    )
    if leaked:
        raise RuntimeError("model leaked analysis/revision notes into novel body")
    return text


def static_gate(text: str, chapter_no: int = 0) -> dict:
    failures = []
    if re.search(r"(?:并)?不是[^。！？\n]{0,45}(?:而是|只是)", text):
        failures.append("ai-template:not-A-but-B")
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    pure = [bool(re.fullmatch(r"[“\"][^\n]{1,220}[”\"][。！？?!…]*", p)) for p in paras]
    streak = best = 0
    for flag in pure:
        streak = streak + 1 if flag else 0
        best = max(best, streak)
    if best >= 2:
        failures.append(f"pure-dialogue-streak:{best}")
    prose = [p for p, q in zip(paras, pure) if not q]
    short_ratio = sum(1 for p in prose if len(re.sub(r"\s+", "", p)) <= 28) / max(1, len(prose))
    if short_ratio > 0.12:
        failures.append(f"short-paragraph-ratio:{short_ratio:.1%}")
    if chapter_no >= 6:
        modern_terms = re.findall(r"数字化|电子档案|电子系统|数据库|二维码|刷卡|刷开.{0,8}(?:信物|通行|门)|复印件|时间戳", text)
        if modern_terms:
            failures.append("era-anachronism:" + "；".join(modern_terms[:4]))
        invented_watch = re.findall(r"怀表[^。！？\n]{0,45}(?:发热|升温|变冷|心率|脉搏|定位|预警|危险|共振|导航)", text)
        if invented_watch:
            failures.append("watch-rule-invention:" + "；".join(invented_watch[:3]))
        meta = re.findall(r"第[一二三四五六七八九十0-9]+节里|上一版|这版稿|当前稿|正文里|本次修订|读者会|作者", text)
        if meta:
            failures.append("meta-writing-language:" + "；".join(meta[:4]))
        if chapter_no == 6:
            if re.search(r"^(?:.|\n){0,500}(?:信差[^。！？\n]{0,50}(?:递来|递给|把[^。！？\n]{0,20}短函(?:搁|放|递)|短函[^。！？\n]{0,20}(?:搁|递|放)在))", text):
                failures.append("chapter5-ending-replayed")
            if re.search(r"(?:街角|街口|门外|路边|河堤|窗外)[^。！？\n]{0,55}(?:黑色马车|黑车|无家徽.{0,6}(?:车|马车))", text):
                failures.append("black-car-reappears-in-scene")
            if re.search(r"霍尔[^。！？\n]{0,55}(?:南桥|跟车|盯车|追车)", text):
                failures.append("repeat-hall-car-tail")
        if chapter_no == 7:
            opening = text[:1400]
            if re.search(r"(?:律师|代理行)[^。！？\n]{0,80}(?:递交|提交|送来)[^。！？\n]{0,50}(?:暂缓|争议).{0,20}申请", opening):
                failures.append("chapter6-application-scene-replayed")
            if "下午四点三十七分" in opening or "四点三十七" in opening:
                failures.append("chapter6-timestamp-replayed")
    return {"pass": not failures, "failures": failures, "short_ratio": short_ratio, "dialogue_streak": best}


async def run_reviews(task_id: int, text: str, canon: str, prior_tail: str):
    async def one(role: str, name: str, focus: str):
        try:
            blind = role in {"blind-reader","cadence-character-reader","blind-natural-reader","character-voice-reviewer","blind-dialogue-reader"}
            context = prior_tail[-6500:] if blind else (canon[-6500:] + "\n\n前文尾部：\n" + prior_tail[-4500:])
            result = await _run_step(
                task_id=task_id,
                role=role,
                stage="gray-street-short-gate",
                mode="check",
                content=text,
                instruction=f"""你是{name}。{focus}
这是章节 Gate，不改正文。{('不要参考世界观说明，只按正文与前文阅读体验判断。' if blind else '必须同时服从冻结 Canon 与前文事实。')}
只要发现成片小短句、裸对白、问卷式对话、作者解释腔、人物工具化、因果/连续性错误，就 FAIL。
第一行严格输出 VERDICT: PASS 或 VERDICT: FAIL。
之后最多列 5 条最重要逐字证据；整份报告控制在 700 个汉字以内，禁止展开长篇复盘。
参考上下文：
{context}""",
            )
            return {"name": name, "role": role, "verdict": verdict(result.content), "report": result.content, "provider": result.provider, "model": result.model}
        except Exception as exc:
            return {"name": name, "role": role, "verdict": "ERROR", "report": "", "error": f"{type(exc).__name__}: {exc}"}
    return await asyncio.gather(*(one(*spec) for spec in REVIEWERS))


async def aggregate_gate(task_id: int, text: str, reviews: list[dict], gate: dict, canon: str, prior_tail: str, chapter_no: int) -> dict:
    compact = json.dumps(reviews, ensure_ascii=False)[:22000]
    result = await _run_step(
        task_id=task_id,
        role="master-reader",
        stage=f"gray-street-aggregate-ch{chapter_no:02d}",
        mode="check",
        content=text,
        instruction=f"""你是《灰街》的总编 Gate。你收到 8 路独立审核结果，必须核对正文后做最终判断，不按多数票机械决定。

硬规则：
- 静态 Gate 失败 => FAIL。
- 经你核对属实的明显 AI 解释腔、连续裸对白/问卷式对白、人物工具化/场景消失、真正的 Canon/因果/权限/连续性错误 => FAIL。
- 单纯审美偏好、轻微润色项、误判、重复意见不能阻断。
- 某 Reviewer ERROR 若有其他 Reviewer 覆盖同一维度，且你核对正文无硬伤，可标 COVERED_ERROR；关键维度无人覆盖才 FAIL。
- 用户明确禁止大量小短句、连续裸对白、“不是A而是B”作者总结。
- 不提前泄露后续章节，不允许 Writer 为了解决审核擅自新增规则或线索。

第一行严格输出 VERDICT: PASS 或 VERDICT: FAIL。
随后写【确认的硬伤】【驳回的误判/轻微项】【Error覆盖判断】【最终理由】。

静态 Gate：
{json.dumps(gate, ensure_ascii=False)}

独立审核：
{compact}

前文尾部：
{prior_tail[-4500:]}

Canon 摘要：
{canon[-4500:]}
""",
    )
    return {
        "verdict": verdict(result.content),
        "report": result.content,
        "provider": result.provider,
        "model": result.model,
    }


async def revise(task_id: int, text: str, chapter_plan: str, canon: str, skill: str, prior_tail: str, failed: list[dict], gate: dict):
    compact = json.dumps({"failed_reviews": failed, "static_gate": gate}, ensure_ascii=False)[:18000]
    result = await _run_step(
        task_id=task_id,
        role="revision-agent",
        stage="gray-street-short-revision",
        mode="polish",
        content=text,
        instruction=f"""根据真实 Gate 失败证据统一重写当前章节。不是逐句打补丁；允许重组场景和话轮，但不得改变冻结章节功能、前文事实或提前泄露后续。
正文用完整段落和自然中长句群；禁止裸对白、问卷式问答、规章背诵、不是A而是B式作者总结、人物工具化。
不能用机械补动作作弊。
只输出完整正文。

【本章冻结功能】
{chapter_plan}

【全局 Writer Skill】
{skill}

【前文尾部】
{prior_tail[-7000:]}

【失败证据】
{compact}

【项目 Canon】
{canon[-8000:]}
""",
    )
    return result.content.strip()


async def main() -> None:
    req = json.loads(REQUEST.read_text(encoding="utf-8"))
    chapter_no = int(req["chapter_no"])
    title = str(req.get("title") or TITLES[chapter_no])
    prior_file = Path(req.get("prior_file") or "")
    prior_parts = []
    for number in range(1, chapter_no):
        path = Path(f"books/gray-street/chapters/{number:02d}.md")
        if path.exists():
            prior_parts.append(path.read_text(encoding="utf-8"))
    if prior_file and prior_file.exists() and not any(str(prior_file).endswith(f"/{number:02d}.md") for number in range(1, chapter_no)):
        prior_parts.append(prior_file.read_text(encoding="utf-8"))
    if not prior_parts:
        raise FileNotFoundError("no prior Gray Street chapters found")
    prior_text = "\n\n".join(prior_parts)
    prior_tail = prior_text[-16000:]

    configure_provider()
    # Keep heterogeneous review routing, but permit reliable AGNES fallback when
    # DOTS3 exhausts its reasoning/output budget before returning visible text.
    os.environ["NARRATIVE_REVIEW_MAX_ROUTE_ATTEMPTS"] = "2"
    os.environ["NARRATIVE_NATURAL_READER_FALLBACK_PROFILES"] = "AGNES"
    os.environ["NARRATIVE_REASONING_READER_FALLBACK_PROFILES"] = "AGNES"
    init_db()
    project_id, chapter_id = create_project()
    task_id = _create_task(project_id=project_id, chapter_id=chapter_id, goal=f"生成《灰街》第{chapter_no}节《{title}》并通过短链路 Gate。", instruction="必须通过多读者与专项审核才可进入下一节。")
    keep_generation_skills_lean(task_id)
    canon = CANON_PATH.read_text(encoding="utf-8")
    if chapter_no >= 6:
        canon += "\n\n" + POST5_CANON
    chapter_plan = extract_plan(chapter_no)
    blueprint_file = str(req.get("blueprint_file") or "").strip()
    if blueprint_file:
        blueprint_path = Path(blueprint_file)
        if not blueprint_path.exists():
            raise FileNotFoundError(f"blueprint_file not found: {blueprint_path}")
        chapter_plan += "\n\n【控制器场景骨架｜必须执行但不得复述为正文】\n" + blueprint_path.read_text(encoding="utf-8")
    extra_constraints = str(req.get("chapter_constraints") or "").strip()
    if extra_constraints:
        chapter_plan += "\n\n【本次结构级返修追加约束】\n" + extra_constraints
    skill = skill_excerpt(task_id)

    seed_file = str(req.get("seed_file") or "").strip()
    if seed_file:
        seed_path = Path(seed_file)
        if not seed_path.exists():
            raise FileNotFoundError(f"seed_file not found: {seed_path}")
        text = normalize_novel_output(seed_path.read_text(encoding="utf-8"))
    else:
        writer = await _run_step(
            task_id=task_id,
            role="writer",
            stage=f"gray-street-ch{chapter_no:02d}-draft",
            mode="continue",
            content=prior_tail,
            instruction=f"""从前文之后写《灰街》第{chapter_no}节《{title}》。只输出本节正文，不复述前文，不写提纲。
目标 3200—4500 个中文字符。
必须完整实现本章冻结功能，但只揭示这一章应该揭示的信息。
正文以完整段落和自然中长句群为主；禁止大量一句一段、裸对白、问卷式问答、不是A而是B式作者解释。
人物有自己的利益和手上事情；不要让任何人变成信息播报器。

【本章冻结功能】
{chapter_plan}

【最新全局 Writer Skill】
{skill}

【项目 Canon】
{canon[-8500:]}
""",
        )
        text = normalize_novel_output(writer.content)
    # Providers occasionally wrap valid prose or overshoot the chapter target.
    # Normalize once, then ask the platform Writer to rebuild the same chapter
    # instead of throwing away a successful model call before Reader Gate.
    if (not _chapter_text_is_usable(text)) or len(text) > 6500:
        repair = await _run_step(
            task_id=task_id,
            role="writer-retry",
            stage=f"gray-street-ch{chapter_no:02d}-draft-normalize",
            mode="continue",
            content=text,
            instruction=f"""把当前第{chapter_no}节候选稿重建为可审核的完整正文。
保留已经写出的核心事件、人物选择、线索边界和前文连续性，不新增世界规则，不改变人物身份。
硬长度：3200—5200 个中文字符；超过上限必须压缩场景与重复表达，不能截断。
结尾必须是完整句，以中文句末标点结束。不要 Markdown 代码围栏、不要提纲、不要说明，只输出小说正文。
继续服从本章冻结功能、最新 Writer Skill 和项目 Canon。""",
        )
        text = normalize_novel_output(repair.content)
    if not _chapter_text_is_usable(text):
        raise RuntimeError(f"draft unusable after normalize: chars={len(text)} tail={text[-80:]!r}")

    reviews = await run_reviews(task_id, text, canon, prior_tail)
    gate = static_gate(text, chapter_no)
    aggregate = await aggregate_gate(task_id, text, reviews, gate, canon, prior_tail, chapter_no)
    failed = [x for x in reviews if x["verdict"] != "PASS"]
    fail_count = sum(1 for x in reviews if x["verdict"] == "FAIL")
    if fail_count >= 4:
        aggregate["verdict"] = "FAIL"
        aggregate["consensus_override"] = f"{fail_count} independent readers returned FAIL; Master PASS cannot override broad disagreement."

    manual_findings = str(req.get("manual_findings") or "").strip()
    if manual_findings:
        failed.append({
            "name": "controller-manual-adjudication",
            "role": "controller",
            "verdict": "FAIL",
            "report": manual_findings,
        })

    if bool(req.get("force_revision")) or aggregate["verdict"] != "PASS" or not gate["pass"]:
        text = await revise(task_id, text, chapter_plan, canon, skill, prior_tail, failed, gate)
        text = normalize_novel_output(text)
        if not _chapter_text_is_usable(text):
            repair = await _run_step(
                task_id=task_id,
                role="writer-retry",
                stage=f"gray-street-ch{chapter_no:02d}-revision-normalize",
                mode="continue",
                content=text,
                instruction=f"""把当前返修稿补足为可审核的完整章节正文。
必须保留返修稿已经修正的连续性、人物关系和场景结构，不得把已删除的硬伤重新写回来。
硬长度：3000—4600 个中文字符；若当前过短，只通过场景感知、人物反应、利益摩擦和必要动作补足，禁止新增谜题、规则、人物或解释性总结。
继续服从本章冻结功能、Writer Skill、Canon 和本轮失败证据。只输出完整小说正文。""",
            )
            text = normalize_novel_output(repair.content)
        if not _chapter_text_is_usable(text):
            raise RuntimeError(f"revision unusable after normalize: chars={len(text)}")
        reviews = await run_reviews(task_id, text, canon, prior_tail)
        gate = static_gate(text, chapter_no)
        aggregate = await aggregate_gate(task_id, text, reviews, gate, canon, prior_tail, chapter_no)
        failed = [x for x in reviews if x["verdict"] != "PASS"]
        fail_count = sum(1 for x in reviews if x["verdict"] == "FAIL")
        if fail_count >= 4:
            aggregate["verdict"] = "FAIL"
            aggregate["consensus_override"] = f"{fail_count} independent readers returned FAIL after revision."

    passed = gate["pass"] and aggregate["verdict"] == "PASS"
    out = OUT_ROOT / f"chapter-{chapter_no:02d}"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"chapter-{chapter_no:02d}-final.md").write_text(f"# 第{chapter_no}节 {title}\n\n" + text + "\n", encoding="utf-8")
    (out / "gate.json").write_text(json.dumps({"passed": passed, "static": gate, "reviews": reviews, "aggregate": aggregate}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": passed, "chapter": chapter_no, "title": title, "chars": len(text), "master": aggregate["verdict"], "reviewer_nonpass": [x["name"] for x in failed]}, ensure_ascii=False), flush=True)
    if not passed:
        raise RuntimeError(f"chapter {chapter_no} gate failed")


if __name__ == "__main__":
    _entry_request = json.loads(REQUEST.read_text(encoding="utf-8"))
    _batch_to = int(_entry_request.get("batch_to") or _entry_request.get("chapter_no") or 0)
    _chapter_no = int(_entry_request.get("chapter_no") or 0)
    if _batch_to > _chapter_no:
        from scripts.run_gray_street_07_10_batch import main as batch_main
        asyncio.run(batch_main())
    else:
        asyncio.run(main())
