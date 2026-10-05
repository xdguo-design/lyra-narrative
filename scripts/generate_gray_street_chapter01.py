from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

from app.db import connect, init_db
from app.services.book_pipeline import (
    _blocking_review_digest,
    _create_task,
    _run_frozen_chapter,
)
from app.services.default_skills import (
    BUILTIN_REFINEMENT_SKILL_NAME,
    BUILTIN_WRITING_SKILL_NAME,
)
from app.services.full_novel_pipeline import _run_review_round
from app.services.workflow_service import _run_step, get_task


PROJECT_TITLE = "灰街"
PROJECT_GENRE = "底层崛起 / 钢铁时代 / 工业诡秘 / 官僚成长"
CHAPTER_TITLE = "怀表"
CANON_PATH = Path("books/gray-street/canon.md")
OUTPUT_DIR = Path(os.getenv("NARRATIVE_OUTPUT_DIR", "artifacts/gray-street-chapter01"))

GOAL = """通过 NarrativeOS 正式流水线，从零重新生成《灰街》第一节《怀表》。
旧聊天稿全部视为废稿，不得复制、同义改写或修补旧句。只依据冻结 Canon 与全局持续进化 Skill 重新写。"""

INSTRUCTION = """这是第一节正式重写，不是提纲、说明或审稿意见。

硬要求：
1. 2500—4500 个中文字符左右，完整走完 Canon 中第一节十个冻结节点。
2. 叙述以完整段落和自然中长句群为主，不要把一句话拆成一段，不用大量碎短句制造节奏。
3. 禁止连续资料问答式对白。人物说话时，身体、手上事情、空间和关系必须继续存在；同时禁止机械地给每句台词贴“皱眉/看了看/沉默”等通用动作。
4. 重点规避已经由全局 Skill 学到的复发问题：问卷式盘问、作者总结腔、人物工具化、过度理性对白、模型腔收束。
5. 避免“不是……而是……”“他不是不怕，只是/而是……”这类替读者总结人物心理的结构。
6. 第一节不解释神秘物等级、规则—代价—反噬体系、官方神秘机构或幕后贵族。
7. 让埃文的基层行政小权力真正参与事件；芬奇、贝恩、霍尔、房东都必须像各自有生活和利益的人。
8. 只输出小说正文。"""


BLIND_READER_CONTEXT = """作品类型：工业诡秘 / 钢铁时代 / 底层成长。
本节允许且要求出现尚未解释的超自然异常：旧银怀表日期窗显示次日、停表被触碰后重新走动、表盖内侧自行形成持有者姓名与数字。
这些异常本身不是物理硬伤，不得因为“不符合现实机械常识”而判 FAIL，也不得建议删除、弱化成普通刻痕或改成写实解释。
盲读仍要严格检查：异常是否写得具体克制、人物反应是否可信、是否违反当前文本已建立事实、是否有 AI 解释腔或强行神秘化。
"""

READER_SPECS = [
    (
        "reader-normal",
        """你是普通中文小说读者，只看正文，不看作者意图。检查：是否自然好读、人物是否像活人、哪里明显像AI生成、哪里让你想跳过、哪里对白像聊天框。不要因为剧情信息正确就放行。严格输出第一行 VERDICT: PASS 或 VERDICT: FAIL；FAIL 后列出逐字片段和原因。""",
    ),
    (
        "reader-commercial",
        """你是有大量长篇阅读经验的商业小说读者。检查阅读动力、场景推进、人物记忆点和章末继续阅读欲。特别注意：不要把短句多等同于节奏快，也不要鼓励网文电报体。若节奏主要靠碎句、问答或硬钩子维持，判 FAIL。第一行必须是 VERDICT: PASS 或 VERDICT: FAIL。""",
    ),
    (
        "reader-naturalness",
        """你是中文文学自然度盲读者。只检查母语自然度和作者痕迹：碎短句、单句段落、不是A而是B、作者替人物总结、刻意金句、机械转折、模板化心理解释、过度整齐句式。意思能懂但第一眼像AI也必须指出。第一行必须是 VERDICT: PASS 或 VERDICT: FAIL。""",
    ),
    (
        "reader-character-dialogue",
        """你是人物与对白盲读者。检查每场对白是否由人物身份、利益、关系、身体和手上任务真实塑造；是否存在连续一问一答、问什么答什么、人物一开口场景就暂停。动作如果只是通用填充同样算失败。第一行必须是 VERDICT: PASS 或 VERDICT: FAIL。""",
    ),
]


def configure_provider() -> dict[str, str]:
    name = os.getenv("NARRATIVE_PROVIDER_NAME", "platform-writer").strip()
    protocol = os.getenv("NARRATIVE_PROVIDER_PROTOCOL", "openai-compatible").strip().lower()
    model = os.getenv("NARRATIVE_PROVIDER_MODEL", "").strip()
    base_url = os.getenv("NARRATIVE_PROVIDER_BASE_URL", "").strip()
    secret_name = os.getenv("NARRATIVE_PROVIDER_SECRET_NAME", "").strip()
    api_key = (
        os.getenv("NARRATIVE_PROVIDER_API_KEY", "").strip()
        or (os.getenv(secret_name, "").strip() if secret_name else "")
    )
    if not model:
        raise RuntimeError("NARRATIVE_PROVIDER_MODEL must not be empty")
    if protocol != "ollama" and not api_key:
        raise RuntimeError("platform writer API key is missing")

    os.environ["NOVEL_AI_KIND"] = protocol
    os.environ["NOVEL_AI_MODEL"] = model
    os.environ["NOVEL_AI_BASE_URL"] = base_url
    os.environ["NARRATIVE_PROVIDER_API_KEY"] = api_key
    os.environ["NOVEL_AI_API_KEY_ENV"] = "NARRATIVE_PROVIDER_API_KEY"
    os.environ["NOVEL_AI_PROVIDER_NAME"] = name
    os.environ.setdefault("NOVEL_SEED_DEMO", "0")
    return {"name": name, "protocol": protocol, "model": model}


def _character_sections(text: str):
    matches = list(re.finditer(r"^###\s+(.+?)\s*$", text, flags=re.MULTILINE))
    for index, match in enumerate(matches):
        name = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        profile = text[start:end].strip()
        identity = re.search(r"^身份：(.+?)\s*$", profile, flags=re.MULTILINE)
        if identity:
            yield name, identity.group(1).strip(), profile


def create_project() -> tuple[int, int]:
    canon = CANON_PATH.read_text(encoding="utf-8")
    with connect() as conn:
        old = conn.execute("SELECT id FROM projects WHERE title=?", (PROJECT_TITLE,)).fetchone()
        if old:
            conn.execute("DELETE FROM projects WHERE id=?", (old["id"],))

        project_id = int(
            conn.execute(
                "INSERT INTO projects(title,description,genre) VALUES(?,?,?)",
                (PROJECT_TITLE, "灰街正式平台写作项目。", PROJECT_GENRE),
            ).lastrowid
        )
        chapter_id = int(
            conn.execute(
                "INSERT INTO chapters(project_id,title,position,content,status) VALUES(?,?,?,?,?)",
                (project_id, CHAPTER_TITLE, 1, "", "draft"),
            ).lastrowid
        )
        conn.execute(
            """INSERT INTO memories(project_id,kind,title,content,source_type,source_ref,confirmed)
               VALUES(?,?,?,?,?,?,1)""",
            (project_id, "canon", "灰街冻结 Canon", canon, "manual", "books/gray-street/canon.md"),
        )
        for name, role, profile in _character_sections(canon):
            conn.execute(
                "INSERT INTO characters(project_id,name,role,profile,tags) VALUES(?,?,?,?,?)",
                (project_id, name, role, profile, "[]"),
            )
    return project_id, chapter_id


def keep_generation_skills_lean(task_id: int) -> None:
    with connect() as conn:
        conn.execute(
            """
            DELETE FROM writing_task_skills
            WHERE task_id=?
              AND skill_id NOT IN (
                  SELECT id FROM skills
                  WHERE project_id IS NULL AND name IN (?,?)
              )
            """,
            (task_id, BUILTIN_WRITING_SKILL_NAME, BUILTIN_REFINEMENT_SKILL_NAME),
        )


def static_style_gate(text: str) -> dict:
    body = str(text or "").strip()
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    pure_dialogue = [
        bool(re.fullmatch(r"[“\"][^\n]{1,180}[”\"][。！？?!…]*", p))
        for p in paragraphs
    ]
    max_dialogue_streak = 0
    streak = 0
    for is_dialogue in pure_dialogue:
        streak = streak + 1 if is_dialogue else 0
        max_dialogue_streak = max(max_dialogue_streak, streak)

    prose_paragraphs = [p for p, is_dialogue in zip(paragraphs, pure_dialogue) if not is_dialogue]
    short_count = sum(1 for p in prose_paragraphs if len(re.sub(r"\s+", "", p)) <= 28)
    short_ratio = short_count / max(1, len(prose_paragraphs))
    ai_patterns = re.findall(
        r"(?:并)?不是[^。！？\n]{0,36}(?:，|,)?(?:而是|只是)",
        body,
    )
    failures = []
    if max_dialogue_streak >= 2:
        failures.append(f"连续纯对白段落达到 {max_dialogue_streak}")
    if short_ratio > 0.15:
        failures.append(f"短叙述段落比例过高 {short_ratio:.1%}")
    if ai_patterns:
        failures.append("出现“不是…而是/只是”模板化解释：" + "；".join(ai_patterns[:4]))
    return {
        "pass": not failures,
        "paragraphs": len(paragraphs),
        "max_pure_dialogue_streak": max_dialogue_streak,
        "short_prose_ratio": round(short_ratio, 4),
        "ai_pattern_count": len(ai_patterns),
        "failures": failures,
    }


async def run_blind_readers(task_id: int, text: str):
    async def one(role: str, instruction: str):
        return await _run_step(
            task_id=task_id,
            role=role,
            stage="gray-street-final-blind-read",
            mode="check",
            content=text,
            instruction=BLIND_READER_CONTEXT + "\n\n" + instruction,
        )

    results = await asyncio.gather(*(one(role, instruction) for role, instruction in READER_SPECS))
    reports = {role: result.content for (role, _), result in zip(READER_SPECS, results)}
    passed = all(report.lstrip().upper().startswith("VERDICT: PASS") for report in reports.values())
    return reports, passed


async def final_repair(task_id: int, text: str, reader_reports: dict, style_report: dict, context: str):
    blocking = _blocking_review_digest(task_id)
    return await _run_step(
        task_id=task_id,
        role="revision-agent",
        stage="gray-street-final-gate-repair",
        mode="polish",
        content=text,
        instruction="\n\n".join(
            [
                """这是最终 Gate 打回修订。保持第一节既定事件和事实，不新增设定，不解释神秘体系。
优先解决裸对白、碎短句、人物悬空、AI式心理总结和读者指出的不自然处。
不能用给每句对白机械补动作的办法作弊；需要时重组整个话轮和段落，让人物手上的事、利益、身体与空间真正影响对白。
正文以完整段落和自然中长句群为主。只输出完整第一节正文。""",
                "现有平台 blocking：\n" + (blocking or "NONE"),
                "四路盲读：\n" + "\n\n".join(f"[{k}]\n{v}" for k, v in reader_reports.items()),
                "静态文体 Gate：\n" + json.dumps(style_report, ensure_ascii=False),
                context,
            ]
        ),
    )


def export_result(task_id: int, provider: dict, reader_reports: dict, style_report: dict) -> None:
    task = get_task(task_id) or {}
    content = str(task.get("revised_content") or task.get("draft") or "").strip()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "chapter-01-platform-candidate.md").write_text(
        "# 第一节 怀表\n\n" + content + "\n", encoding="utf-8"
    )
    (OUTPUT_DIR / "task.json").write_text(
        json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUTPUT_DIR / "blind-readers.json").write_text(
        json.dumps(reader_reports, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUTPUT_DIR / "style-gate.json").write_text(
        json.dumps(style_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(
            {
                "task_id": task_id,
                "status": task.get("status"),
                "provider": provider,
                "platform_pipeline_used": True,
                "global_skill_learning_used": True,
                "blind_reader_count": len(READER_SPECS),
                "static_style_gate": style_report,
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

    result = await _run_frozen_chapter(
        task_id=task_id,
        chapter_number=1,
        prior_manuscript="",
    )
    candidate = str(result.get("revised_content") or result.get("draft") or "").strip()
    context = CANON_PATH.read_text(encoding="utf-8")

    readers, readers_ok = await run_blind_readers(task_id, candidate)
    style = static_style_gate(candidate)
    official_ok = result.get("status") == "awaiting_approval"

    if not (official_ok and readers_ok and style["pass"]):
        repaired = await final_repair(task_id, candidate, readers, style, context)
        candidate = repaired.content.strip()
        with connect() as conn:
            conn.execute(
                "UPDATE review_findings SET status='addressed' WHERE task_id=? AND status='open'",
                (task_id,),
            )
        _, final_blocking = await _run_review_round(
            task_id=task_id,
            draft=candidate,
            context=context,
            round_no=3,
        )
        readers, readers_ok = await run_blind_readers(task_id, candidate)
        style = static_style_gate(candidate)
        final_ok = (not final_blocking) and readers_ok and style["pass"]
        with connect() as conn:
            conn.execute(
                """UPDATE writing_tasks
                   SET revised_content=?,status=?,updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (candidate, "awaiting_approval" if final_ok else "reviewed", task_id),
            )

    final_task = get_task(task_id) or {}
    export_result(task_id, provider, readers, style)
    ok = final_task.get("status") == "awaiting_approval" and readers_ok and style["pass"]
    print(json.dumps({"ok": ok, "task_id": task_id, "status": final_task.get("status")}, ensure_ascii=False))
    if not ok:
        raise RuntimeError("灰街第一节未通过最终平台 Gate，已保留审核产物但拒绝交付正文")


if __name__ == "__main__":
    asyncio.run(main())
