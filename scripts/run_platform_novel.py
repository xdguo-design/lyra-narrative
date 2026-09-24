from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from app.db import connect, init_db
from app.services.production_pipeline import get_production_run, start_production


OUTPUT_DIR = Path("artifacts/platform-zero-platform")
BRIEF = """
创作一部完整的都市悬疑/科幻小说《零点站台》，本次先按正式生产流程完成前置设计并产出第一章，作为平台真实验收。

初始创意只有这些：
- 时间：2036 年。
- 地点：临江市，已经停运七年的地铁四号线旧终点站“青屿站”。
- 每天 00:07，废弃站台会出现一列不在运营系统中的银灰色列车。
- 主人公林桥在车里看到失踪七年的妹妹林夏。
- 目标篇幅：中篇，约 8 章。

硬约束：
1. 科幻机制必须能自洽解释，尽量由一个核心科学假设推导现象，禁止“软件 bug 直接制造宇宙”这类无桥梁设定。
2. 人物不能全是好人。主要人物必须有欲望、秘密、错误选择、利益冲突和可能伤害他人的行为。
3. 反派/对立者不能只是功能性坏人，也不能靠最后突然洗白解决冲突。
4. 中段禁止用连续对白倾倒世界观；科学信息尽量通过调查、设备、事故、行动和代价显露。
5. 氛围要求冷峻、压迫、克制，场景与语言必须托住悬疑。
6. 先完成故事架构，再完成世界观/科学设定，再完成人物与核心矛盾，再完成章节大纲；每阶段必须经过独立 Reviewer。
7. Reviewer 打回必须由 Revision Agent 重写并重新审核。
8. 正文先写第一章；Draft 后必须经过 Scene Enricher、Prose Editor，以及连续性、剧情、人物、世界/科学、文风五个独立 Reviewer。
9. 未经人工批准，不得写入正式章节。
""".strip()


def create_project() -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO projects(title,genre,status)
            VALUES(?,?,?)
            """,
            ("零点站台·平台生产版", "都市悬疑 / 科幻", "active"),
        )
        return int(cur.lastrowid)


def latest_run(project_id: int):
    with connect() as conn:
        row = conn.execute(
            """
            SELECT id FROM production_runs
            WHERE project_id=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (project_id,),
        ).fetchone()
    return get_production_run(int(row["id"])) if row else None


def write_outputs(run: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "run.json").write_text(
        json.dumps(run, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# 《零点站台》NarrativeOS 平台真实生产记录",
        "",
        f"- Run ID: {run.get('id')}",
        f"- Status: {run.get('status')}",
        "- 产物来源：NarrativeOS production pipeline",
        f"- 模型运行：{os.getenv('NOVEL_AI_KIND', 'unknown')} / {os.getenv('NOVEL_AI_MODEL', 'unknown')}（GitHub Actions runner 本地运行）",
        "- 注意：这是平台流水线产物，不是聊天助手手写正文。",
        "",
        "## 创作委托",
        "",
        run.get("brief", ""),
        "",
    ]

    for artifact in run.get("artifacts", []):
        lines.extend(
            [
                "---",
                "",
                f"## {artifact['stage']} v{artifact['version']} · {artifact['role']}",
                "",
                f"状态：**{artifact['status']}**",
                "",
                artifact["content"],
                "",
            ]
        )
        reviews = artifact.get("reviews") or []
        if reviews:
            lines.extend(["### Reviewer", ""])
            for review in reviews:
                lines.extend(
                    [
                        f"#### {review['category']} · {review['reviewer']} · {review['decision']}",
                        "",
                        review["content"],
                        "",
                    ]
                )

    if run.get("final_chapter"):
        lines.extend(
            [
                "---",
                "",
                "# 待人工审批正文",
                "",
                run["final_chapter"],
                "",
            ]
        )

    if run.get("error"):
        lines.extend(["---", "", "## 运行错误", "", run["error"], ""])

    (OUTPUT_DIR / "production-record.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    accepted = {}
    for artifact in run.get("artifacts", []):
        if artifact["status"] == "accepted":
            accepted[artifact["stage"]] = artifact["content"]
    for stage in ("architecture", "world", "characters", "outline"):
        if stage in accepted:
            (OUTPUT_DIR / f"{stage}.md").write_text(accepted[stage], encoding="utf-8")
    if run.get("final_chapter"):
        (OUTPUT_DIR / "chapter-0001-awaiting-approval.md").write_text(
            run["final_chapter"],
            encoding="utf-8",
        )


async def main() -> int:
    init_db()
    project_id = create_project()
    try:
        run = await start_production(project_id, BRIEF)
    except Exception as exc:
        run = latest_run(project_id)
        if run is None:
            raise
        run["runner_exception"] = repr(exc)
        write_outputs(run)
        print(json.dumps(
            {
                "run_id": run["id"],
                "status": run["status"],
                "error": run.get("error"),
            },
            ensure_ascii=False,
        ))
        return 1

    write_outputs(run)
    print(json.dumps(
        {
            "run_id": run["id"],
            "status": run["status"],
            "artifact_count": len(run.get("artifacts", [])),
            "final_chapter_chars": len(run.get("final_chapter", "")),
        },
        ensure_ascii=False,
    ))
    return 0 if run["status"] == "awaiting_approval" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
