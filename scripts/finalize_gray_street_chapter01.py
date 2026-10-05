from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from app.db import init_db
from app.services.book_pipeline import _chapter_text_is_usable, _create_task
from app.services.workflow_service import _run_step
from scripts.generate_gray_street_chapter01 import configure_provider, create_project

INPUT = Path("artifacts/step4-input/chapter-01-step4-rewrite.md")
OUTPUT_DIR = Path("artifacts/gray-street-chapter01-final")

CHECKS = [
    ("blind-reader", "普通读者", "从普通读者角度检查好不好读、人物是否像活人、是否有明显AI腔或想跳过的地方。"),
    ("cadence-character-reader", "商业读者", "检查节奏、钩子、人物记忆点和继续阅读欲；短句多不等于节奏好。"),
    ("blind-natural-reader", "文学自然度读者", "检查AI模板句、作者总结、不是A而是B、空洞比喻、机械过渡和碎句。"),
    ("character-voice-reviewer", "人物读者", "检查人物是否有自己的利益、习惯、选择和声音，是否变成剧情工具。"),
    ("blind-dialogue-reader", "对白读者", "检查裸对白、问卷式问答、规章腔、过度理性台词，以及动作是否只是机械填充。"),
    ("continuity-reviewer", "连续性审核", "检查时间、地点、物品、权限、因果与冻结事实，不允许擅自新增设定。"),
    ("character-dialogue-reviewer", "人物对白专项", "严格检查人物和对白；任何成片规章腔、脚本式问答、角色工具化都 FAIL。"),
    ("language-rhythm-reviewer", "语言节奏专项", "严格检查小短句、单句段落、模型腔、作者解释和句群节奏。"),
]


def strip_title(text: str) -> str:
    text = text.strip()
    if text.startswith("# 第一节 怀表"):
        return text[len("# 第一节 怀表"):].strip()
    return text


def verdict(text: str) -> str:
    m = re.search(r"VERDICT\s*[:：]\s*(PASS|FAIL)", text, re.I)
    return m.group(1).upper() if m else "FAIL"


def static_gate(text: str) -> dict:
    failures = []
    required = [
        "十一月三日",
        "两点十四",
        "四日",
        "EVAN GREY",
        "银色怀表一枚，运行状态异常，待验",
        "黑色马车",
    ]
    for token in required:
        if token not in text:
            failures.append("missing:" + token)
    if re.search(r"(?:并)?不是[^。！？\n]{0,45}(?:而是|只是)", text):
        failures.append("ai-template:not-A-but-B")
    if "埃文没说什" in text:
        failures.append("typo:埃文没说什")
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    pure = [bool(re.fullmatch(r"[“\"][^\n]{1,220}[”\"][。！？?!…]*", p)) for p in paras]
    streak = best = 0
    for flag in pure:
        streak = streak + 1 if flag else 0
        best = max(best, streak)
    if best >= 2:
        failures.append(f"pure-dialogue-streak:{best}")
    short = [p for p, q in zip(paras, pure) if not q and len(re.sub(r"\s+", "", p)) <= 28]
    ratio = len(short) / max(1, sum(1 for x in pure if not x))
    if ratio > 0.12:
        failures.append(f"short-paragraph-ratio:{ratio:.1%}")
    return {"pass": not failures, "failures": failures, "short_ratio": ratio, "dialogue_streak": best}


async def revise(task_id: int, text: str, evidence: str) -> str:
    result = await _run_step(
        task_id=task_id,
        role="revision-agent",
        stage="gray-street-ch01-final-repair",
        mode="polish",
        content=text,
        instruction="""这是《灰街》第一节最后一次定向修订。只输出完整正文，不解释修改过程。

必须修：
- 删除所有“不是A而是B/这不是…而是…”式作者解释，改成具体动作、位置、选择和后果。
- 修正“埃文没说什”等残缺字。
- 埃文对房东只说基层办事员会自然说的话，不能背法律条文或长篇制度说明。
- 芬奇不要长篇自我辩护；他的怕麻烦、算计和小聪明从动作与短促自然对白里出来。
- 贝恩不要信息倾销；让任务通过办公室行为自然落地。
- 保持完整段落与自然中长句群，禁止大量一句一段和连续裸对白。
- 当天必须明确为十一月三日；怀表停在两点十四，日期窗显示四日；触碰表冠后恢复；EVAN GREY 与 1 在眼前自行形成。
- 保留原句“银色怀表一枚，运行状态异常，待验。”
- 黑色无家徽马车只构成外围压力，不解释身份。
- 不解释神秘体系，不新增设定。
""" + ("\n\n上一轮失败证据：\n" + evidence if evidence else ""),
    )
    return result.content.strip()


async def review_all(task_id: int, text: str):
    async def one(role: str, name: str, focus: str):
        try:
            result = await _run_step(
                task_id=task_id,
                role=role,
                stage="gray-street-ch01-final-gate",
                mode="check",
                content=text,
                instruction=f"""你是{name}。{focus}
只审当前正文，不给整段重写。只要存在明显裸对白、AI解释句、人物工具化、连续性错误或成片小短句，就必须 FAIL。
第一行严格输出：VERDICT: PASS 或 VERDICT: FAIL。
后面给不超过5条逐字证据。""",
            )
            return {"name": name, "role": role, "verdict": verdict(result.content), "report": result.content, "provider": result.provider, "model": result.model}
        except Exception as exc:
            return {"name": name, "role": role, "verdict": "ERROR", "report": "", "error": f"{type(exc).__name__}: {exc}"}
    return await asyncio.gather(*(one(*spec) for spec in CHECKS))


async def main() -> None:
    configure_provider()
    init_db()
    project_id, chapter_id = create_project()
    task_id = _create_task(project_id=project_id, chapter_id=chapter_id, goal="完成《灰街》第一节最终修订和短链路复审。", instruction="第一节必须过最终 Gate 后才能进入第二节。")
    source = strip_title(INPUT.read_text(encoding="utf-8"))

    text = await revise(task_id, source, "")
    if not _chapter_text_is_usable(text):
        raise RuntimeError("final repair unusable")

    reviews = await review_all(task_id, text)
    gate = static_gate(text)
    failed = [x for x in reviews if x["verdict"] != "PASS"]

    if failed or not gate["pass"]:
        evidence = json.dumps({"reviews": failed, "static": gate}, ensure_ascii=False)
        text = await revise(task_id, text, evidence)
        if not _chapter_text_is_usable(text):
            raise RuntimeError("second final repair unusable")
        reviews = await review_all(task_id, text)
        gate = static_gate(text)
        failed = [x for x in reviews if x["verdict"] != "PASS"]

    passed = not failed and gate["pass"]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "chapter-01-final.md").write_text("# 第一节 怀表\n\n" + text + "\n", encoding="utf-8")
    (OUTPUT_DIR / "gate.json").write_text(json.dumps({"passed": passed, "static": gate, "reviews": reviews}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": passed, "chars": len(text), "failed": [x["name"] for x in failed], "static": gate}, ensure_ascii=False), flush=True)
    if not passed:
        raise RuntimeError("chapter 01 final gate failed")


if __name__ == "__main__":
    asyncio.run(main())
