from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from app.db import connect, init_db
from app.services.book_pipeline import run_book_pipeline


PROJECT_TITLE = "零点站台（NarrativeOS 平台重写）"
PROJECT_GENRE = "都市悬疑 / 科幻"
SUPPORTED_PROTOCOLS = {"openai-compatible", "anthropic", "gemini", "ollama"}

GOAL = """从零重写《零点站台》为一部 8 章完整中篇科幻悬疑小说。必须形成完整开端、升级、高潮和收束，不写成设定展示稿。"""

INSTRUCTION = """创作要求：
1. 科幻规则必须自洽，设定由规则推导，不临时加规则。
2. 先架构、世界观、人物、大纲，再写正文。
3. 人物必须有秘密、利益冲突和错误选择，不能全员好人。
4. 场景承担信息表达，避免说明书式对白。
5. 每章必须推动风险或人物关系变化。
6. 全流程必须经过 Reviewer 和 Revision。
"""


def configure_provider() -> dict[str, str]:
    name = os.getenv("NARRATIVE_PROVIDER_NAME", "默认写作").strip()
    protocol = os.getenv(
        "NARRATIVE_PROVIDER_PROTOCOL", "openai-compatible"
    ).strip().lower()
    model = os.getenv("NARRATIVE_PROVIDER_MODEL", "gpt-5.6-sol").strip()
    base_url = os.getenv(
        "NARRATIVE_PROVIDER_BASE_URL", "https://api.openai.com/v1"
    ).strip()
    secret_name = os.getenv(
        "NARRATIVE_PROVIDER_SECRET_NAME", "OPENAI_API_KEY"
    ).strip()

    if not name:
        raise RuntimeError("NARRATIVE_PROVIDER_NAME must not be empty")
    if protocol not in SUPPORTED_PROTOCOLS:
        raise RuntimeError(f"unsupported provider protocol: {protocol}")
    if not model:
        raise RuntimeError("NARRATIVE_PROVIDER_MODEL must not be empty")

    # Keep legacy runtime environment available for pipeline guards and fallback.
    os.environ["NOVEL_AI_KIND"] = protocol
    os.environ["NOVEL_AI_MODEL"] = model
    os.environ["NOVEL_AI_BASE_URL"] = base_url
    os.environ["NOVEL_AI_API_KEY_ENV"] = "NARRATIVE_PROVIDER_API_KEY"
    os.environ["NOVEL_AI_PROVIDER_NAME"] = name
    os.environ.setdefault("NOVEL_AI_REASONING_EFFORT", "high")
    os.environ.setdefault("NOVEL_AI_MAX_TOKENS", "8000")
    os.environ.setdefault("NOVEL_SEED_DEMO", "0")

    return {
        "name": name,
        "protocol": protocol,
        "model": model,
        "base_url": base_url,
        "secret_name": secret_name,
        "api_key_env": "NARRATIVE_PROVIDER_API_KEY",
    }


def register_provider_profile(config: dict[str, str]) -> int:
    with connect() as conn:
        conn.execute("UPDATE provider_profiles SET is_default=0")
        existing = conn.execute(
            "SELECT id FROM provider_profiles WHERE name=?",
            (config["name"],),
        ).fetchone()
        if existing:
            provider_id = int(existing["id"])
            conn.execute(
                """
                UPDATE provider_profiles
                SET protocol=?,base_url=?,api_key_env=?,default_model=?,
                    enabled=1,is_default=1,updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    config["protocol"],
                    config["base_url"],
                    config["api_key_env"],
                    config["model"],
                    provider_id,
                ),
            )
            return provider_id

        cur = conn.execute(
            """
            INSERT INTO provider_profiles(
                name,protocol,base_url,api_key_env,default_model,enabled,is_default
            ) VALUES(?,?,?,?,?,1,1)
            """,
            (
                config["name"],
                config["protocol"],
                config["base_url"],
                config["api_key_env"],
                config["model"],
            ),
        )
        return int(cur.lastrowid)


def create_project() -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO projects(title,description,genre) VALUES(?,?,?)",
            (
                PROJECT_TITLE,
                "由 Lyra Narrative Full Book Pipeline 生成。",
                PROJECT_GENRE,
            ),
        )
        return int(cur.lastrowid)


def export_snapshot(
    *,
    output: Path,
    project_id: int,
    provider_id: int,
    provider_config: dict[str, str],
    result: dict | None,
    error: dict[str, str] | None,
) -> None:
    output.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        project = conn.execute(
            "SELECT * FROM projects WHERE id=?",
            (project_id,),
        ).fetchone()
        chapters = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM chapters WHERE project_id=? ORDER BY position,id",
                (project_id,),
            ).fetchall()
        ]
        tasks = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM writing_tasks WHERE project_id=? ORDER BY id",
                (project_id,),
            ).fetchall()
        ]
        findings = [
            dict(row)
            for row in conn.execute(
                """
                SELECT rf.*
                FROM review_findings rf
                JOIN writing_tasks wt ON wt.id=rf.task_id
                WHERE wt.project_id=?
                ORDER BY rf.id
                """,
                (project_id,),
            ).fetchall()
        ]
        story_states = [
            dict(row)
            for row in conn.execute(
                """
                SELECT * FROM story_state_snapshots
                WHERE project_id=?
                ORDER BY chapter_number,id
                """,
                (project_id,),
            ).fetchall()
        ]
        memories = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM memories WHERE project_id=? ORDER BY id",
                (project_id,),
            ).fetchall()
        ]
        agent_runs = [
            dict(row)
            for row in conn.execute(
                """
                SELECT ar.*
                FROM agent_runs ar
                JOIN writing_tasks wt ON wt.id=ar.task_id
                WHERE wt.project_id=?
                ORDER BY ar.id
                """,
                (project_id,),
            ).fetchall()
        ]

    planning_task = next(
        (task for task in reversed(tasks) if task["chapter_id"] is None),
        None,
    )
    latest_task_by_chapter: dict[int, dict] = {}
    for task in tasks:
        chapter_id = task.get("chapter_id")
        if chapter_id is not None:
            latest_task_by_chapter[int(chapter_id)] = task

    manuscript_parts: list[str] = []
    for index, chapter in enumerate(chapters, start=1):
        task = latest_task_by_chapter.get(int(chapter["id"]), {})
        content = str(
            task.get("revised_content")
            or task.get("draft")
            or chapter.get("content")
            or ""
        ).strip()
        if not content:
            continue
        manuscript_parts.append(
            f"# 第 {index} 章 {chapter['title']}\n\n{content}"
        )

    planning = ""
    if planning_task:
        planning = str(
            planning_task.get("revised_content")
            or planning_task.get("draft")
            or ""
        ).strip()

    manifest = {
        "provider": {
            "id": provider_id,
            "name": provider_config["name"],
            "protocol": provider_config["protocol"],
            "model": provider_config["model"],
            "base_url": provider_config["base_url"],
            "secret_name": provider_config["secret_name"],
        },
        "project": dict(project) if project is not None else {"id": project_id},
        "result": result,
        "error": error,
        "counts": {
            "chapters": len(chapters),
            "tasks": len(tasks),
            "review_findings": len(findings),
            "story_states": len(story_states),
            "agent_runs": len(agent_runs),
        },
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output / "planning.md").write_text(planning, encoding="utf-8")
    (output / "manuscript.md").write_text(
        "\n\n".join(manuscript_parts),
        encoding="utf-8",
    )
    for filename, payload in [
        ("tasks.json", tasks),
        ("review-findings.json", findings),
        ("story-state.json", story_states),
        ("memories.json", memories),
        ("agent-runs.json", agent_runs),
    ]:
        (output / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


async def main() -> None:
    provider_config = configure_provider()
    init_db()
    provider_id = register_provider_profile(provider_config)
    project_id = create_project()
    output = Path(
        os.getenv(
            "NARRATIVE_OUTPUT_DIR",
            "artifacts/zero-platform-platform-rewrite",
        )
    )
    output.mkdir(parents=True, exist_ok=True)

    result: dict | None = None
    error: dict[str, str] | None = None
    try:
        result = await run_book_pipeline(
            project_id=project_id,
            goal=GOAL,
            instruction=INSTRUCTION,
            chapter_count=8,
        )
    except Exception as exc:
        error = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        print(
            json.dumps(
                {"status": "failed", "error": error},
                ensure_ascii=False,
            ),
            flush=True,
        )
        raise
    finally:
        try:
            export_snapshot(
                output=output,
                project_id=project_id,
                provider_id=provider_id,
                provider_config=provider_config,
                result=result,
                error=error,
            )
        except Exception as export_exc:
            print(
                f"[artifact-export] FAILED: {type(export_exc).__name__}: {export_exc}",
                flush=True,
            )
            if error is None:
                raise

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
