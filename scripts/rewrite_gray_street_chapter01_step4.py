from __future__ import annotations

import json
from pathlib import Path

from app.db import connect, init_db
from app.services.book_pipeline import _chapter_text_is_usable, _create_task
from app.services.default_skills import BUILTIN_WRITING_SKILL_NAME
from app.services.workflow_service import _run_step
from scripts.generate_gray_street_chapter01 import (
    CANON_PATH,
    configure_provider,
    create_project,
    keep_generation_skills_lean,
)

DRAFT_PATH = Path("artifacts/step1-input/chapter-01-step1-draft.md")
SPECIALIST_PATH = Path("artifacts/step2-input/specialist-review.json")
READERS_PATH = Path("artifacts/step3-input/multi-reader-review.json")
OUTPUT_DIR = Path("artifacts/gray-street-chapter01-step4")


def _strip_title(text: str) -> str:
    text = text.strip()
    if text.startswith("# 第一节 怀表"):
        return text[len("# 第一节 怀表"):].strip()
    return text


def _skill_excerpt(task_id: int, limit: int = 14000) -> str:
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


def _compact_specialist(payload: dict) -> str:
    parts = []
    for item in payload.get("findings", []):
        parts.append(
            " | ".join(
                [
                    str(item.get("reviewer", "")),
                    str(item.get("category", "")),
                    str(item.get("severity", "")),
                    str(item.get("summary", "")),
                    str(item.get("suggestion", "")),
                ]
            )
        )
    if not parts:
        for out in payload.get("review_outputs", []):
            parts.append(str(out))
    return "\n".join(parts)[:18000]


def _compact_readers(payload: dict) -> str:
    parts = []
    for item in payload.get("readers", []):
        parts.append(
            "\n".join(
                [
                    f"[{item.get('reader','')}/{item.get('provider','')}/{item.get('model','')}]",
                    f"VERDICT={item.get('verdict','')}",
                    str(item.get("report", "")),
                ]
            )
        )
    return "\n\n".join(parts)[:18000]


async def main() -> None:
    configure_provider()
    init_db()
    project_id, chapter_id = create_project()
    task_id = _create_task(
        project_id=project_id,
        chapter_id=chapter_id,
        goal="根据 Step 2 专项审核与 Step 3 多读者盲读，统一重写《灰街》第一节。",
        instruction="分步流水线 Step 4：只做一次统一重写，不做复审。",
    )
    keep_generation_skills_lean(task_id)

    draft = _strip_title(DRAFT_PATH.read_text(encoding="utf-8"))
    specialist = json.loads(SPECIALIST_PATH.read_text(encoding="utf-8"))
    readers = json.loads(READERS_PATH.read_text(encoding="utf-8"))
    canon = CANON_PATH.read_text(encoding="utf-8")
    skill = _skill_excerpt(task_id)

    result = await _run_step(
        task_id=task_id,
        role="revision-agent",
        stage="gray-street-chapter01-step4-unified-rewrite",
        mode="polish",
        content=draft,
        instruction="\n\n".join(
            [
                """这是《灰街》第一节的统一打回重写。不要逐句润色；按审核证据重新组织整个章节，但必须保留冻结 Canon 的事件顺序与事实。

硬要求：
1. 解决专项审核和四路盲读指出的问题，优先处理 blocking/HIGH/FAIL。
2. 禁止连续裸对白、问卷式一问一答、规章背诵、人物作为信息工具。
3. 不喜欢大量小短句和一句一段；正文以完整段落、自然中长句群为主。
4. 禁止“不是A而是B”“他不是不怕，只是/而是”等作者替人物总结心理的模板句。
5. 不要为了修对白机械添加“皱眉、看了看、沉默一下”；动作必须属于人物并真正影响话轮。
6. 埃文通过手续产生现实效果，但不能像法规机器人；芬奇、贝恩、霍尔、哈钦斯太太必须有不同利益和语言。
7. 挂钟方向必须正确：贝恩习惯拨快，芬奇私下往回调。
8. 明确当天是三号；怀表日期窗是四号；碰表冠后恢复走动；表盖内侧的 EVAN GREY 和数字 1 必须在埃文眼前自行形成。
9. 怀表登记原句保留：银色怀表一枚，运行状态异常，待验。
10. 第一节只露异常，不解释神秘物体系、官方秘密机构或幕后贵族。
11. 章尾黑色无家徽马车只提供外围压力，不解释身份。
12. 只输出完整小说正文。""",
                "【冻结 Canon】\n" + canon,
                "【最新全局 Writer Skill】\n" + skill,
                "【Step 2 专项审核】\n" + _compact_specialist(specialist),
                "【Step 3 四路盲读】\n" + _compact_readers(readers),
            ]
        ),
    )

    text = result.content.strip()
    if not _chapter_text_is_usable(text):
        raise RuntimeError(f"Step 4 revision unusable: chars={len(text)}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "chapter-01-step4-rewrite.md").write_text(
        "# 第一节 怀表\n\n" + text + "\n",
        encoding="utf-8",
    )
    manifest = {
        "step": 4,
        "task_id": task_id,
        "chars": len(text),
        "provider": result.provider,
        "model": result.model,
        "status": "rewrite_ready",
        "next_step": "final_recheck",
    }
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
