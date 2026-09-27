from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.services.default_skills import BUILTIN_SKILLS


def db_path() -> Path:
    default_path = (
        "/tmp/novel_workbench.db"
        if os.getenv("VERCEL")
        else "data/novel_workbench.db"
    )
    configured = os.getenv("NOVEL_DB_PATH", default_path)
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


def _ensure_builtin_skills(conn: sqlite3.Connection) -> None:
    for builtin in BUILTIN_SKILLS:
        skill = conn.execute(
            """
            SELECT id,current_version,content
            FROM skills
            WHERE project_id IS NULL AND name=?
            ORDER BY id
            LIMIT 1
            """,
            (builtin["name"],),
        ).fetchone()
        if skill is None:
            cur = conn.execute(
                """
                INSERT INTO skills(
                    project_id,name,purpose,content,enabled,current_version
                ) VALUES(NULL,?,?,?,?,?)
                """,
                (
                    builtin["name"],
                    builtin["purpose"],
                    builtin["content"],
                    1,
                    builtin["version"],
                ),
            )
            conn.execute(
                """
                INSERT INTO skill_versions(skill_id,version,content,note)
                VALUES(?,?,?,?)
                """,
                (
                    cur.lastrowid,
                    builtin["version"],
                    builtin["content"],
                    builtin["note"],
                ),
            )
            continue

        if int(skill["current_version"]) < int(builtin["version"]):
            conn.execute(
                """
                INSERT INTO skill_versions(skill_id,version,content,note)
                VALUES(?,?,?,?)
                """,
                (
                    skill["id"],
                    builtin["version"],
                    builtin["content"],
                    builtin["note"] + " upgrade",
                ),
            )
            conn.execute(
                """
                UPDATE skills
                SET purpose=?,content=?,enabled=1,current_version=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    builtin["purpose"],
                    builtin["content"],
                    builtin["version"],
                    skill["id"],
                ),
            )


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