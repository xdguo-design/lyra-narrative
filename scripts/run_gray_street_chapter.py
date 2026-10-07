from __future__ import annotations

import asyncio
import json
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

TITLES = {2: "遗产", 3: "河灯街", 4: "十三号仓", 5: "日落"}
SECTION_HEADERS = {2: "## 第二节《遗产》", 3: "## 第三节《河灯街》", 4: "## 第四节《十三号仓》", 5: "## 第五节《日落》"}

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


def static_gate(text: str) -> dict:
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
之后最多列 5 条最重要逐字证据。
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
    title = TITLES[chapter_no]
    prior_file = Path(req["prior_file"])
    prior_text = prior_file.read_text(encoding="utf-8")
    prior_tail = prior_text[-12000:]

    configure_provider()
    init_db()
    project_id, chapter_id = create_project()
    task_id = _create_task(project_id=project_id, chapter_id=chapter_id, goal=f"生成《灰街》第{chapter_no}节《{title}》并通过短链路 Gate。", instruction="必须通过多读者与专项审核才可进入下一节。")
    keep_generation_skills_lean(task_id)
    canon = CANON_PATH.read_text(encoding="utf-8")
    chapter_plan = extract_plan(chapter_no)
    extra_constraints = str(req.get("chapter_constraints") or "").strip()
    if extra_constraints:
        chapter_plan += "\n\n【本次结构级返修追加约束】\n" + extra_constraints
    skill = skill_excerpt(task_id)

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
    text = writer.content.strip()
    if not _chapter_text_is_usable(text):
        raise RuntimeError("draft unusable")

    reviews = await run_reviews(task_id, text, canon, prior_tail)
    gate = static_gate(text)
    if gate["pass"] and all(x["verdict"] == "PASS" for x in reviews):
        aggregate = {
            "verdict": "PASS",
            "report": "UNANIMOUS_PASS: static gate and all 8 independent readers passed; Master call skipped by workflow optimization.",
            "provider": "local-consensus",
            "model": "eight-reader-consensus",
        }
    else:
        aggregate = await aggregate_gate(task_id, text, reviews, gate, canon, prior_tail, chapter_no)
    failed = [x for x in reviews if x["verdict"] != "PASS"]

    if aggregate["verdict"] != "PASS" or not gate["pass"]:
        text = await revise(task_id, text, chapter_plan, canon, skill, prior_tail, failed, gate)
        if not _chapter_text_is_usable(text):
            raise RuntimeError("revision unusable")
        reviews = await run_reviews(task_id, text, canon, prior_tail)
        gate = static_gate(text)
        if gate["pass"] and all(x["verdict"] == "PASS" for x in reviews):
            aggregate = {
                "verdict": "PASS",
                "report": "UNANIMOUS_PASS after revision: static gate and all 8 independent readers passed; Master call skipped.",
                "provider": "local-consensus",
                "model": "eight-reader-consensus",
            }
        else:
            aggregate = await aggregate_gate(task_id, text, reviews, gate, canon, prior_tail, chapter_no)
        failed = [x for x in reviews if x["verdict"] != "PASS"]

    passed = gate["pass"] and aggregate["verdict"] == "PASS"
    out = OUT_ROOT / f"chapter-{chapter_no:02d}"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"chapter-{chapter_no:02d}-final.md").write_text(f"# 第{chapter_no}节 {title}\n\n" + text + "\n", encoding="utf-8")
    (out / "gate.json").write_text(json.dumps({"passed": passed, "static": gate, "reviews": reviews, "aggregate": aggregate}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": passed, "chapter": chapter_no, "title": title, "chars": len(text), "master": aggregate["verdict"], "reviewer_nonpass": [x["name"] for x in failed]}, ensure_ascii=False), flush=True)
    if not passed:
        raise RuntimeError(f"chapter {chapter_no} gate failed")


if __name__ == "__main__":
    asyncio.run(main())
