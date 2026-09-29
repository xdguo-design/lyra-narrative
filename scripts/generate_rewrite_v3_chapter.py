from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

from app.db import connect, init_db
from app.services.book_pipeline import _create_task, _run_frozen_chapter
from app.services.full_novel_pipeline import _persist_memory
from app.services.workflow_service import get_task


PROJECT_TITLE = "rewrite-v3 chapter 02 platform generation"
PROJECT_GENRE = "架空历史 / 穿越 / 县衙 / 底层成长"
CHAPTER_NUMBER = 2
CHAPTER_TITLE = "谁让你推的车"

CHAPTER_ONE = Path(
    "books/yamen-proficiency/rewrite-v3/chapter-01/final-candidate.md"
)
PLAN = Path(
    "books/yamen-proficiency/rewrite-v3/chapters-01-10-plan.md"
)
ARCHITECTURE = Path(
    "books/yamen-proficiency/manual-v6-run-001/architecture.md"
)
CHARACTERS = Path(
    "books/yamen-proficiency/manual-v6-run-001/characters.md"
)
PROFICIENCY = Path(
    "books/yamen-proficiency/manual-v6-run-001/proficiency-rules.md"
)
PROMISE = Path(
    "books/yamen-proficiency/manual-v6-run-001/genre-promise-matrix.md"
)
CONTROL_ROOT = Path("books/yamen-proficiency/rewrite-v3/control")
STORY_BIBLE = CONTROL_ROOT / "story-bible-v1.md"
VOLUME_OUTLINE = CONTROL_ROOT / "volume-01-outline-v1.md"
FORESHADOW_REGISTRY = CONTROL_ROOT / "foreshadow-registry-v1.md"
SKILL_TREE = CONTROL_ROOT / "proficiency-skill-tree-v1.md"
OPPONENT_LADDER = CONTROL_ROOT / "conflict-opponent-ladder-v1.md"

OUTPUT_DIR = Path(
    os.getenv(
        "NARRATIVE_OUTPUT_DIR",
        "artifacts/rewrite-v3-chapter-generate",
    )
)

GOAL = """通过 NarrativeOS 正式流水线重新生成 rewrite-v3 第二章《谁让你推的车》。
必须承接当前第一章，但不得读取、模仿或改写现有第二章候选稿。
本章目标：从刘旺与后厨小车继续推进失粮线；逐步压实刘旺昨夜搬过破口粮、孙成指使、粮袋被再次移动、复秤短三斗一升；章末引出昨日运粮车夫马二死亡。
陈安不得越权破案；周虎必须保持班头权限与程序意识；赵六必须有独立性格和风险判断；刘旺不能被连续问两句就把全部信息吐完。"""

INSTRUCTION = """你正在替用户通过平台生成正式小说正文，不是写说明、提纲或审稿意见。

来源边界：
- 可以使用第一章正式候选稿、冻结人物卡、架构、熟练度规则、类型承诺和 rewrite-v3 前十章规划。
- 禁止读取 books/yamen-proficiency/rewrite-v3/chapter-02/final-candidate.md；不得把现有第二章当作输入。
- 不得把人工读者给出的具体改句当成答案；只执行已沉淀进 Skill 的通用规则。

第二章硬约束：
1. 从第一章刘旺抱柴、陈安准备问话的接口自然接上。
2. 刘旺的信息暴露必须符合人物卡阈值：先回避/正常化，再承认最小事实；孙成、五文钱、袋子后续去向不得一次性主动说全。
3. 周虎不是作者代言人。短、直接、先控现场再拆事实；禁止输出可摘抄的“办案金句/原则句”。
4. 陈安只说能确认的事实，不把“像”说成“就是”，不代替周虎审讯，不突然变神探。
5. 赵六不只是笑料；他先看风险和责任，对周虎收声，对同级才贫。
6. 所有关键对白必须通过 Reader v12 的“说出口测试”：逻辑正确 ≠ 口语自然。过度工整、像作者总结、规章、金句、问卷式一问一答都必须重写。
7. 调查过程要有动作、等待、搬动、复核和现场噪声，不能变成“问一句→答一句→马上得到下一条线索”的证据板。
8. 粮袋找到后必须体现“位置异常 + 重量异常”，但人物只确认当前能确认的东西。
9. 复秤确认相较昨夜入库记录短三斗一升；不要提前定性是谁偷、怎么偷。
10. 章末只把马二死亡接进来，不解释死因，也不把粮案与死亡直接定成同一案。
11. 保持自然中文小说语流；少解释不等于少描写。禁止连续碎短句和模型腔收束。
12. 只输出完整第二章正文。"""


def configure_provider() -> dict[str, str]:
    name = os.getenv(
        "NARRATIVE_PROVIDER_NAME",
        os.getenv("NOVEL_AI_PROVIDER_NAME", "platform-writer"),
    ).strip()
    protocol = os.getenv(
        "NARRATIVE_PROVIDER_PROTOCOL",
        os.getenv("NOVEL_AI_KIND", "openai-compatible"),
    ).strip().lower()
    model = os.getenv(
        "NARRATIVE_PROVIDER_MODEL",
        os.getenv("NOVEL_AI_MODEL", ""),
    ).strip()
    base_url = os.getenv(
        "NARRATIVE_PROVIDER_BASE_URL",
        os.getenv("NOVEL_AI_BASE_URL", ""),
    ).strip()
    secret_name = os.getenv(
        "NARRATIVE_PROVIDER_SECRET_NAME",
        os.getenv("NOVEL_AI_API_KEY_ENV", ""),
    ).strip()
    api_key = (
        os.getenv("NARRATIVE_PROVIDER_API_KEY", "").strip()
        or os.getenv("NOVEL_AI_API_KEY", "").strip()
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

    return {
        "name": name,
        "protocol": protocol,
        "model": model,
    }


def _character_sections(text: str) -> list[tuple[str, str, str]]:
    matches = list(re.finditer(r"^##\s+(.+?)\s*$", text, flags=re.MULTILINE))
    result: list[tuple[str, str, str]] = []
    for index, match in enumerate(matches):
        name = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        profile = text[start:end].strip()
        role_match = re.search(r"^- 身份：(.+?)\s*$", profile, flags=re.MULTILINE)
        role = role_match.group(1).strip() if role_match else ""
        if name:
            result.append((name, role, profile))
    return result


def create_project() -> tuple[int, int]:
    chapter_one = CHAPTER_ONE.read_text(encoding="utf-8")
    character_text = CHARACTERS.read_text(encoding="utf-8")

    with connect() as conn:
        old = conn.execute(
            "SELECT id FROM projects WHERE title=?",
            (PROJECT_TITLE,),
        ).fetchone()
        if old:
            conn.execute("DELETE FROM projects WHERE id=?", (old["id"],))

        project = conn.execute(
            "INSERT INTO projects(title,description,genre) VALUES(?,?,?)",
            (
                PROJECT_TITLE,
                "由用户控制、NarrativeOS Writer/Reader 正式生成 rewrite-v3 第二章。",
                PROJECT_GENRE,
            ),
        )
        project_id = int(project.lastrowid)

        conn.execute(
            "INSERT INTO chapters(project_id,title,position,content,status) "
            "VALUES(?,?,?,?,?)",
            (project_id, "十五板子", 1, chapter_one, "approved"),
        )
        chapter_two = conn.execute(
            "INSERT INTO chapters(project_id,title,position,content,status) "
            "VALUES(?,?,?,?,?)",
            (project_id, CHAPTER_TITLE, CHAPTER_NUMBER, "", "draft"),
        )

        for name, role, profile in _character_sections(character_text):
            conn.execute(
                "INSERT INTO characters(project_id,name,role,profile,tags) "
                "VALUES(?,?,?,?,?)",
                (project_id, name, role, profile, "[]"),
            )

    return project_id, int(chapter_two.lastrowid)


def seed_context(project_id: int) -> None:
    sources = [
        (ARCHITECTURE, "architecture", "冻结故事架构"),
        (CHARACTERS, "character", "冻结人物卡"),
        (PROFICIENCY, "world", "熟练度硬规则"),
        (PROMISE, "promise", "类型承诺"),
        (PLAN, "outline", "rewrite-v3 前十章规划"),
        (STORY_BIBLE, "story-bible", "rewrite-v3 Story Bible"),
        (VOLUME_OUTLINE, "volume-outline", "第一卷 1—30 总纲"),
        (FORESHADOW_REGISTRY, "foreshadow", "伏笔总表"),
        (SKILL_TREE, "proficiency-tree", "熟练度技能树"),
        (OPPONENT_LADDER, "opponent-ladder", "矛盾与对立面升级图"),
    ]
    for path, kind, title in sources:
        _persist_memory(
            project_id=project_id,
            task_id=0,
            kind=kind,
            title=title,
            content=path.read_text(encoding="utf-8"),
        )


def export_result(
    task_id: int,
    provider: dict[str, str],
) -> Path:
    task = get_task(task_id) or {}
    content = str(task.get("revised_content") or task.get("draft") or "")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "chapter-02-platform-candidate.md").write_text(
        "# 第二章 谁让你推的车\n\n" + content.strip() + "\n",
        encoding="utf-8",
    )
    (OUTPUT_DIR / "task.json").write_text(
        json.dumps(task, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    manifest = {
        "task_id": task_id,
        "status": task.get("status"),
        "provider": provider,
        "source_policy": {
            "chapter_01_used": True,
            "chapter_02_existing_candidate_used": False,
            "plan_used": True,
            "character_cards_used": True,
            "reader_v12_used": True,
            "long_form_control_pack_used": True,
            "character_voice_review_used": True,
        },
        "runs": [
            {
                "id": run.get("id"),
                "role": run.get("role"),
                "stage": run.get("stage"),
                "status": run.get("status"),
                "provider": run.get("provider"),
                "model": run.get("model"),
                "error": run.get("error"),
            }
            for run in (task.get("runs") or [])
        ],
        "findings": task.get("findings") or [],
    }
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return OUTPUT_DIR


async def main() -> None:
    provider = configure_provider()
    init_db()
    project_id, chapter_id = create_project()
    seed_context(project_id)

    task_id = _create_task(
        project_id=project_id,
        chapter_id=chapter_id,
        goal=GOAL,
        instruction=INSTRUCTION,
    )
    prior = CHAPTER_ONE.read_text(encoding="utf-8")

    try:
        result = await _run_frozen_chapter(
            task_id=task_id,
            chapter_number=CHAPTER_NUMBER,
            prior_manuscript=prior,
        )
        output_dir = export_result(task_id, provider)
        print(
            json.dumps(
                {
                    "ok": result.get("status") == "awaiting_approval",
                    "task_id": task_id,
                    "status": result.get("status"),
                    "output_dir": str(output_dir),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    except Exception as exc:
        output_dir = export_result(task_id, provider)
        print(
            json.dumps(
                {
                    "ok": False,
                    "task_id": task_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "output_dir": str(output_dir),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        raise


if __name__ == "__main__":
    asyncio.run(main())
