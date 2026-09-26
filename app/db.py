from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def db_path() -> Path:
    configured = os.getenv("NOVEL_DB_PATH", "data/novel_workbench.db")
    path = Path(configured)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _seed_demo(conn: sqlite3.Connection) -> None:
    if os.getenv("NOVEL_SEED_DEMO", "1") in {"0", "false", "False"}:
        return
    count = conn.execute("SELECT COUNT(*) AS n FROM projects").fetchone()["n"]
    if count:
        return
    cursor = conn.execute(
        "INSERT INTO projects(title, description, genre, status) VALUES(?,?,?,?)",
        (
            "雾城档案",
            "用于体验工作台的示例长篇。你可以直接改写、删除或新建自己的作品。",
            "悬疑",
            "draft",
        ),
    )
    project_id = cursor.lastrowid
    demo_chapters = [
        (
            "第一章 雨夜来客",
            1,
            "雨从凌晨开始下。旧城区的路灯被水汽裹住，只剩一圈昏黄。\n\n林渡推开值班室的门时，桌上的电话刚好响起。电话那头没有人说话，只有很轻的呼吸声，以及远处反复三次的钟声。\n\n他看了一眼墙上的钟：02:17。",
        ),
        (
            "第二章 消失的门牌",
            2,
            "天亮以后，林渡去了电话里留下的地址。巷子还在，楼也在，唯独应该出现的七码门牌像从来没有存在过。",
        ),
        (
            "第三章 黑伞",
            3,
            "监控里，凌晨两点十六分，一个撑黑伞的人停在巷口。镜头只拍到半张脸。",
        ),
    ]
    for title, position, content in demo_chapters:
        cur = conn.execute(
            "INSERT INTO chapters(project_id,title,position,content,status) VALUES(?,?,?,?,?)",
            (project_id, title, position, content, "draft"),
        )
        chapter_id = cur.lastrowid
        conn.execute(
            "INSERT INTO chapter_versions(chapter_id,content,note) VALUES(?,?,?)",
            (chapter_id, content, "初始版本"),
        )
    conn.execute(
        "INSERT INTO characters(project_id,name,role,profile,tags) VALUES(?,?,?,?,?)",
        (
            project_id,
            "林渡",
            "主角",
            "旧城区调查员，习惯记录异常时间点。",
            json.dumps(["谨慎", "观察力强"], ensure_ascii=False),
        ),
    )
    conn.execute(
        "INSERT INTO world_notes(project_id,category,title,content) VALUES(?,?,?,?)",
        (project_id, "规则", "雾城钟声", "凌晨两点以后出现的三次钟声与失踪事件有关。"),
    )


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                genre TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS chapters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                content TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS chapter_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chapter_id INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
                content TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '自动保存',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS characters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT '',
                profile TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS world_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                category TEXT NOT NULL DEFAULT '设定',
                title TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS writing_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                chapter_id INTEGER REFERENCES chapters(id) ON DELETE SET NULL,
                goal TEXT NOT NULL,
                instruction TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                draft TEXT NOT NULL DEFAULT '',
                revised_content TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS agent_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL REFERENCES writing_tasks(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                stage TEXT NOT NULL,
                status TEXT NOT NULL,
                input_excerpt TEXT NOT NULL DEFAULT '',
                output TEXT NOT NULL DEFAULT '',
                provider TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS review_findings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL REFERENCES writing_tasks(id) ON DELETE CASCADE,
                reviewer TEXT NOT NULL,
                category TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'suggestion',
                summary TEXT NOT NULL,
                suggestion TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS approvals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL REFERENCES writing_tasks(id) ON DELETE CASCADE,
                decision TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                chapter_version_id INTEGER REFERENCES chapter_versions(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                kind TEXT NOT NULL DEFAULT 'fact',
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                source_type TEXT NOT NULL DEFAULT 'manual',
                source_ref TEXT NOT NULL DEFAULT '',
                confirmed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_memories_project_kind
            ON memories(project_id, kind, confirmed);

            CREATE TABLE IF NOT EXISTS skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                purpose TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                current_version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS skill_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
                version INTEGER NOT NULL,
                content TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(skill_id, version)
            );

            CREATE TABLE IF NOT EXISTS project_content_links (
                project_id INTEGER PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
                slug TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS content_syncs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL REFERENCES writing_tasks(id) ON DELETE CASCADE,
                status TEXT NOT NULL,
                chapter_path TEXT NOT NULL DEFAULT '',
                review_path TEXT NOT NULL DEFAULT '',
                version_path TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS memory_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id INTEGER NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
                version INTEGER NOT NULL,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                confirmed INTEGER NOT NULL DEFAULT 0,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(memory_id, version)
            );

            CREATE TABLE IF NOT EXISTS agent_run_resources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
                resource_type TEXT NOT NULL,
                resource_id INTEGER NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                title TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_agent_run_resources_run
            ON agent_run_resources(run_id, resource_type);

            CREATE TABLE IF NOT EXISTS writing_task_skills (
                task_id INTEGER NOT NULL REFERENCES writing_tasks(id) ON DELETE CASCADE,
                skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
                version INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(task_id, skill_id)
            );

            CREATE INDEX IF NOT EXISTS idx_writing_task_skills_task
            ON writing_task_skills(task_id);

            CREATE TABLE IF NOT EXISTS writing_task_skill_policy (
                task_id INTEGER PRIMARY KEY REFERENCES writing_tasks(id) ON DELETE CASCADE,
                mode TEXT NOT NULL DEFAULT 'default',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS review_finding_refs (
                finding_id INTEGER PRIMARY KEY REFERENCES review_findings(id) ON DELETE CASCADE,
                excerpt TEXT NOT NULL DEFAULT '',
                start_offset INTEGER,
                end_offset INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS agent_run_metrics (
                run_id INTEGER PRIMARY KEY REFERENCES agent_runs(id) ON DELETE CASCADE,
                prompt_version TEXT NOT NULL DEFAULT '',
                duration_ms INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS provider_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                protocol TEXT NOT NULL DEFAULT '',
                base_url TEXT NOT NULL DEFAULT '',
                api_key_env TEXT NOT NULL DEFAULT '',
                default_model TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                is_default INTEGER NOT NULL DEFAULT 0,
                options_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_provider_profiles_default
            ON provider_profiles(is_default, enabled);

            CREATE TABLE IF NOT EXISTS story_state_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                task_id INTEGER NOT NULL UNIQUE REFERENCES writing_tasks(id) ON DELETE CASCADE,
                chapter_id INTEGER REFERENCES chapters(id) ON DELETE SET NULL,
                chapter_number INTEGER NOT NULL,
                state_json TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_story_state_project_chapter
            ON story_state_snapshots(project_id, chapter_number DESC, id DESC);
            """
        )
        _seed_demo(conn)
