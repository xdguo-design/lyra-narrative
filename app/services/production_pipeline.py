from __future__ import annotations

import asyncio
import os
from typing import Any

from app.db import connect
from app.services.ai_service import AssistResult, assist


class ProductionConfigurationError(RuntimeError):
    pass


class ProductionStateError(RuntimeError):
    pass


FOUNDATION_STAGES = [
    {
        "stage": "architecture",
        "role": "story-architect",
        "mode": "architect",
        "reviewer": "architecture-reviewer",
        "review_instruction": (
            "审查故事架构是否具备明确主题、核心矛盾、升级路径、高潮、结局与伏笔回收。"
            "重点检查冲突是否足以支撑长篇/中篇，而不是只有设定。"
        ),
    },
    {
        "stage": "world",
        "role": "world-builder",
        "mode": "world",
        "reviewer": "world-science-reviewer",
        "review_instruction": (
            "审查世界观、科学假设、规则边界与因果链。所有关键现象必须能从少量底层规则推导；"
            "发现自相矛盾、万能规则或结局无法由前置规则推出时必须 REJECT。"
        ),
    },
    {
        "stage": "characters",
        "role": "character-designer",
        "mode": "characters",
        "reviewer": "character-conflict-reviewer",
        "review_instruction": (
            "审查人物欲望、秘密、错误、利益冲突、关系张力与人物弧。"
            "如果主要人物都过度善良、冲突可通过沟通轻易解决、反派只有功能性动机，必须 REJECT。"
        ),
    },
    {
        "stage": "outline",
        "role": "plot-planner",
        "mode": "outline",
        "reviewer": "outline-reviewer",
        "review_instruction": (
            "审查章节推进、因果、信息揭示、人物选择与代价。"
            "每章必须有目标、阻碍、变化与钩子；禁止连续章节只解释设定。"
        ),
    },
]

CHAPTER_REVIEWERS = [
    (
        "continuity-reviewer",
        "连续性",
        "检查时间线、地点、人物状态、道具、称谓、伏笔和前后事实连续性。",
    ),
    (
        "plot-reviewer",
        "剧情",
        "检查因果、冲突升级、信息揭示、人物选择与章节钩子是否成立。",
    ),
    (
        "character-reviewer",
        "人物",
        "检查人物动机、秘密、立场和行为是否与人物设计一致，人物是否为了推进剧情而降智。",
    ),
    (
        "world-science-reviewer",
        "世界/科学",
        "检查正文是否违反世界规则、科学假设、装置能力边界和跨界限制。",
    ),
    (
        "style-reviewer",
        "文风",
        "检查气氛、节奏、句式、对白、解释性语言与场景承载力；避免用人物对白直接倾倒设定。",
    ),
]


def _ensure_schema() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS production_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                brief TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                final_chapter TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS production_artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL REFERENCES production_runs(id) ON DELETE CASCADE,
                stage TEXT NOT NULL,
                version INTEGER NOT NULL,
                role TEXT NOT NULL,
                status TEXT NOT NULL,
                content TEXT NOT NULL,
                provider TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(run_id, stage, version)
            );

            CREATE TABLE IF NOT EXISTS production_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL REFERENCES production_runs(id) ON DELETE CASCADE,
                artifact_id INTEGER NOT NULL REFERENCES production_artifacts(id) ON DELETE CASCADE,
                reviewer TEXT NOT NULL,
                category TEXT NOT NULL,
                decision TEXT NOT NULL,
                content TEXT NOT NULL,
                provider TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_production_artifacts_run_stage
            ON production_artifacts(run_id, stage, version);

            CREATE INDEX IF NOT EXISTS idx_production_reviews_run
            ON production_reviews(run_id, artifact_id);
            """
        )


def _require_real_provider() -> None:
    kind = os.getenv("NOVEL_AI_KIND", "demo").strip().lower()
    if kind in {"", "demo", "mock"}:
        raise ProductionConfigurationError(
            "完整小说生产流水线禁止使用 demo/mock provider。请先配置真实模型 Provider。"
        )


def _save_artifact(
    run_id: int,
    stage: str,
    version: int,
    role: str,
    status: str,
    result: AssistResult,
) -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO production_artifacts(
                run_id,stage,version,role,status,content,provider,model
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                stage,
                version,
                role,
                status,
                result.content,
                result.provider,
                result.model,
            ),
        )
        return int(cur.lastrowid)


def _set_artifact_status(artifact_id: int, status: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE production_artifacts SET status=? WHERE id=?",
            (status, artifact_id),
        )


def _decision(text: str) -> str:
    first = (text or "").strip().splitlines()[:1]
    if not first:
        return "REJECT"
    normalized = first[0].strip().upper().replace("：", ":")
    if normalized == "DECISION: PASS":
        return "PASS"
    return "REJECT"


def _save_review(
    run_id: int,
    artifact_id: int,
    reviewer: str,
    category: str,
    result: AssistResult,
) -> str:
    decision = _decision(result.content)
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO production_reviews(
                run_id,artifact_id,reviewer,category,decision,content,provider,model
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                artifact_id,
                reviewer,
                category,
                decision,
                result.content,
                result.provider,
                result.model,
            ),
        )
    return decision


async def _generate(
    *,
    mode: str,
    content: str,
    instruction: str,
) -> AssistResult:
    result = await assist(mode=mode, content=content, instruction=instruction)
    if result.demo:
        raise ProductionConfigurationError(
            "生产流水线收到 demo 模型结果，已终止；该结果不会进入小说产物。"
        )
    return result


def _foundation_context(accepted: dict[str, str], brief: str) -> str:
    parts = [f"创作委托：\n{brief.strip()}"]
    labels = {
        "architecture": "已批准故事架构",
        "world": "已批准世界观/科学设定",
        "characters": "已批准人物与矛盾",
        "outline": "已批准章节大纲",
    }
    for stage in ("architecture", "world", "characters", "outline"):
        if accepted.get(stage):
            parts.append(f"{labels[stage]}：\n{accepted[stage]}")
    return "\n\n".join(parts)


async def _run_foundation_stage(
    *,
    run_id: int,
    brief: str,
    accepted: dict[str, str],
    spec: dict[str, str],
    max_attempts: int = 3,
) -> str:
    stage = spec["stage"]
    context = _foundation_context(accepted, brief)
    result = await _generate(
        mode=spec["mode"],
        content=context,
        instruction=(
            f"你是 NarrativeOS 的 {spec['role']}。"
            "只完成当前阶段，不提前写正文。输出必须能直接作为后续 Agent 的约束输入。"
        ),
    )

    version = 1
    while version <= max_attempts:
        artifact_id = _save_artifact(
            run_id, stage, version, spec["role"], "reviewing", result
        )
        review = await _generate(
            mode="check",
            content=result.content,
            instruction=(
                f"你是独立 Reviewer：{spec['reviewer']}。\n"
                f"{spec['review_instruction']}\n\n"
                "第一行必须严格输出 DECISION: PASS 或 DECISION: REJECT。"
                "如果 REJECT，后续必须列出 blocking 问题以及可执行修改要求。"
            ),
        )
        decision = _save_review(
            run_id,
            artifact_id,
            spec["reviewer"],
            stage,
            review,
        )
        if decision == "PASS":
            _set_artifact_status(artifact_id, "accepted")
            return result.content

        _set_artifact_status(artifact_id, "rejected")
        version += 1
        if version > max_attempts:
            raise ProductionStateError(
                f"{stage} stage rejected after {max_attempts} attempts"
            )
        result = await _generate(
            mode="revise",
            content=result.content,
            instruction=(
                f"你是 {spec['role']} 的 Revision Agent。"
                "根据独立 Reviewer 的打回意见重写当前阶段产物，不得绕过 blocking 问题。\n\n"
                f"Reviewer 意见：\n{review.content}\n\n"
                f"既有约束：\n{context}"
            ),
        )

    raise ProductionStateError(f"{stage} stage failed")


async def _run_chapter(
    *,
    run_id: int,
    brief: str,
    accepted: dict[str, str],
    max_attempts: int = 3,
) -> str:
    context = _foundation_context(accepted, brief)
    draft = await _generate(
        mode="draft",
        content=context,
        instruction=(
            "你是 Draft Writer。严格依据已批准的故事架构、世界规则、人物矛盾和章节大纲，"
            "只写第一章完整正文。不得擅自增加新世界规则，不得提前解释后期谜底。"
        ),
    )
    _save_artifact(run_id, "chapter-draft", 1, "draft-writer", "completed", draft)

    enriched = await _generate(
        mode="enrich",
        content=draft.content,
        instruction=(
            "你是 Scene Enricher。加强场景存在感、人物动作、气氛、情绪递进和信息承载，"
            "但不得改变已批准剧情事实与科学规则。"
        ),
    )
    _save_artifact(run_id, "chapter-enrich", 1, "scene-enricher", "completed", enriched)

    polished = await _generate(
        mode="polish",
        content=enriched.content,
        instruction=(
            "你是 Prose Editor。改善句式、节奏、对白与语言质感。"
            "禁止新增剧情、修改人物动机或改变世界规则。"
        ),
    )

    current = polished
    version = 1
    while version <= max_attempts:
        artifact_id = _save_artifact(
            run_id, "chapter-final", version, "prose-editor", "reviewing", current
        )
        async def run_reviewer(
            reviewer: str,
            category: str,
            instruction: str,
            review_content: str,
        ) -> tuple[str, str, AssistResult]:
            review = await _generate(
                mode="check",
                content=review_content,
                instruction=(
                    f"你是独立的 {reviewer}。\n{instruction}\n\n"
                    f"已批准创作约束：\n{context}\n\n"
                    "第一行必须严格输出 DECISION: PASS 或 DECISION: REJECT。"
                    "REJECT 时必须给出 blocking 问题和可执行修改要求。"
                ),
            )
            return reviewer, category, review

        review_results = await asyncio.gather(
            *(
                run_reviewer(reviewer, category, instruction, current.content)
                for reviewer, category, instruction in CHAPTER_REVIEWERS
            )
        )

        rejected_feedback: list[str] = []
        for reviewer, category, review in review_results:
            decision = _save_review(
                run_id, artifact_id, reviewer, category, review
            )
            if decision != "PASS":
                rejected_feedback.append(f"[{category}]\n{review.content}")

        if not rejected_feedback:
            _set_artifact_status(artifact_id, "accepted")
            return current.content

        _set_artifact_status(artifact_id, "rejected")
        version += 1
        if version > max_attempts:
            raise ProductionStateError(
                f"chapter rejected after {max_attempts} attempts"
            )
        current = await _generate(
            mode="revise",
            content=current.content,
            instruction=(
                "你是 Revision Agent。必须逐项解决所有 blocking 审核意见，"
                "同时保持已批准架构、科学规则、人物秘密和章节目标不变。\n\n"
                + "\n\n".join(rejected_feedback)
                + f"\n\n已批准创作约束：\n{context}"
            ),
        )

    raise ProductionStateError("chapter stage failed")


def get_production_run(run_id: int) -> dict[str, Any] | None:
    _ensure_schema()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM production_runs WHERE id=?", (run_id,)
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        artifacts = [
            dict(item)
            for item in conn.execute(
                """
                SELECT * FROM production_artifacts
                WHERE run_id=?
                ORDER BY id
                """,
                (run_id,),
            ).fetchall()
        ]
        for artifact in artifacts:
            artifact["reviews"] = [
                dict(review)
                for review in conn.execute(
                    """
                    SELECT * FROM production_reviews
                    WHERE artifact_id=?
                    ORDER BY id
                    """,
                    (artifact["id"],),
                ).fetchall()
            ]
        result["artifacts"] = artifacts
        return result


async def start_production(project_id: int, brief: str) -> dict[str, Any]:
    _ensure_schema()
    _require_real_provider()
    with connect() as conn:
        project = conn.execute("SELECT id FROM projects WHERE id=?", (project_id,)).fetchone()
        if not project:
            raise ValueError("project not found")
        cur = conn.execute(
            "INSERT INTO production_runs(project_id,brief,status) VALUES(?,?,?)",
            (project_id, brief.strip(), "running"),
        )
        run_id = int(cur.lastrowid)

    accepted: dict[str, str] = {}
    try:
        for spec in FOUNDATION_STAGES:
            accepted[spec["stage"]] = await _run_foundation_stage(
                run_id=run_id,
                brief=brief,
                accepted=accepted,
                spec=spec,
            )

        final_chapter = await _run_chapter(
            run_id=run_id,
            brief=brief,
            accepted=accepted,
        )
        with connect() as conn:
            conn.execute(
                """
                UPDATE production_runs
                SET status='awaiting_approval',
                    final_chapter=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (final_chapter, run_id),
            )
    except Exception as exc:
        with connect() as conn:
            conn.execute(
                """
                UPDATE production_runs
                SET status='failed',error=?,updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (str(exc)[:2000], run_id),
            )
        raise

    return get_production_run(run_id) or {}


def approve_production_run(
    run_id: int,
    decision: str,
    note: str = "",
) -> dict[str, Any]:
    _ensure_schema()
    with connect() as conn:
        run = conn.execute(
            "SELECT * FROM production_runs WHERE id=?",
            (run_id,),
        ).fetchone()
        if not run:
            raise ValueError("production run not found")
        if run["status"] != "awaiting_approval":
            raise ProductionStateError(
                f"production run cannot be approved while status is {run['status']}"
            )

        if decision == "rejected":
            conn.execute(
                """
                UPDATE production_runs
                SET status='rejected',error=?,updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (note[:2000], run_id),
            )
        else:
            chapter = conn.execute(
                """
                SELECT * FROM chapters
                WHERE project_id=?
                ORDER BY position,id
                LIMIT 1
                """,
                (run["project_id"],),
            ).fetchone()
            if not chapter:
                cur = conn.execute(
                    """
                    INSERT INTO chapters(project_id,title,position,content,status)
                    VALUES(?,?,?,?,?)
                    """,
                    (
                        run["project_id"],
                        "第一章",
                        1,
                        run["final_chapter"],
                        "draft",
                    ),
                )
                chapter_id = int(cur.lastrowid)
            else:
                chapter_id = int(chapter["id"])
                conn.execute(
                    """
                    UPDATE chapters
                    SET content=?,updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (run["final_chapter"], chapter_id),
                )

            conn.execute(
                """
                INSERT INTO chapter_versions(chapter_id,content,note)
                VALUES(?,?,?)
                """,
                (
                    chapter_id,
                    run["final_chapter"],
                    f"NarrativeOS production run #{run_id} approved",
                ),
            )

            accepted = conn.execute(
                """
                SELECT stage,content
                FROM production_artifacts
                WHERE run_id=? AND status='accepted'
                  AND stage IN ('architecture','world','characters','outline')
                ORDER BY id
                """,
                (run_id,),
            ).fetchall()
            for item in accepted:
                conn.execute(
                    """
                    INSERT INTO memories(
                        project_id,kind,title,content,source_type,source_ref,confirmed
                    ) VALUES(?,?,?,?,?,?,1)
                    """,
                    (
                        run["project_id"],
                        item["stage"],
                        f"Production {item['stage']}",
                        item["content"],
                        "production",
                        f"production-run:{run_id}:{item['stage']}",
                    ),
                )

            conn.execute(
                """
                UPDATE production_runs
                SET status='approved',updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (run_id,),
            )

    return get_production_run(run_id) or {}
