from __future__ import annotations

import os
import re
from pathlib import Path

from app.db import connect

_SLUG_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def content_root() -> Path | None:
    value = os.getenv("NOVEL_CONTENT_ROOT", "").strip()
    if not value:
        return None
    return Path(value).expanduser().resolve()


def validate_slug(slug: str) -> str:
    value = slug.strip()
    if not _SLUG_RE.fullmatch(value) or value in {".", ".."}:
        raise ValueError("invalid content repository slug")
    return value


def link_project(project_id: int, slug: str) -> dict:
    slug = validate_slug(slug)
    with connect() as conn:
        project = conn.execute("SELECT id FROM projects WHERE id=?", (project_id,)).fetchone()
        if not project:
            raise ValueError("project not found")
        conn.execute(
            """
            INSERT INTO project_content_links(project_id,slug)
            VALUES(?,?)
            ON CONFLICT(project_id) DO UPDATE SET
                slug=excluded.slug,
                updated_at=CURRENT_TIMESTAMP
            """,
            (project_id, slug),
        )
        row = conn.execute(
            "SELECT * FROM project_content_links WHERE project_id=?", (project_id,)
        ).fetchone()
        return dict(row)


def project_content_status(project_id: int) -> dict:
    root = content_root()
    with connect() as conn:
        link = conn.execute(
            "SELECT * FROM project_content_links WHERE project_id=?", (project_id,)
        ).fetchone()
        latest = conn.execute(
            """
            SELECT cs.*
            FROM content_syncs cs
            JOIN writing_tasks wt ON wt.id=cs.task_id
            WHERE wt.project_id=?
            ORDER BY cs.id DESC
            LIMIT 1
            """,
            (project_id,),
        ).fetchone()
    slug = link["slug"] if link else None
    project_dir = root / "novels" / slug if root is not None and slug else None
    return {
        "configured": root is not None,
        "root": str(root) if root is not None else "",
        "linked": link is not None,
        "slug": slug,
        "project_dir": str(project_dir) if project_dir is not None else "",
        "project_dir_exists": bool(project_dir and project_dir.exists()),
        "latest_sync": dict(latest) if latest else None,
    }



def _linked_project_dir(project_id: int) -> tuple[Path, str]:
    root = content_root()
    if root is None:
        raise ValueError("NOVEL_CONTENT_ROOT is not configured")
    with connect() as conn:
        link = conn.execute(
            "SELECT slug FROM project_content_links WHERE project_id=?",
            (project_id,),
        ).fetchone()
    if not link:
        raise ValueError("project has no content repository link")
    slug = validate_slug(link["slug"])
    project_dir = (root / "novels" / slug).resolve()
    _assert_within_root(project_dir, root)
    return project_dir, slug


def _source_files(project_dir: Path, root: Path) -> list[tuple[str, Path]]:
    sources: list[tuple[str, Path]] = []

    project_readme = project_dir / "README.md"
    if project_readme.is_file():
        sources.append(("project", project_readme))

    project_bible = project_dir / "bible"
    if project_bible.is_dir():
        for path in sorted(project_bible.rglob("*.md")):
            sources.append(("world", path))

    project_characters = project_dir / "characters"
    if project_characters.is_dir():
        for path in sorted(project_characters.rglob("*.md")):
            sources.append(("character", path))

    project_outline = project_dir / "outline"
    if project_outline.is_dir():
        for path in sorted(project_outline.rglob("*.md")):
            sources.append(("outline", path))

    legacy_bible = root / "bible"
    if legacy_bible.is_dir():
        for path in sorted(legacy_bible.rglob("*.md")):
            if not any(existing.resolve() == path.resolve() for _, existing in sources):
                sources.append(("world", path))

    shared_style = root / "shared" / "writing-style"
    if shared_style.is_dir():
        for path in sorted(shared_style.rglob("*.md")):
            sources.append(("skill", path))

    return sources


def preflight_content_repository(project_id: int) -> dict:
    root = content_root()
    status = project_content_status(project_id)
    result = {
        **status,
        "root_exists": bool(root and root.exists()),
        "root_writable": bool(root and root.exists() and os.access(root, os.W_OK)),
        "required_directories": {},
        "sources": [],
        "ready": False,
        "issues": [],
    }

    if root is None:
        result["issues"].append("NOVEL_CONTENT_ROOT is not configured")
        return result
    if not root.exists():
        result["issues"].append("content repository root does not exist")
        return result
    if not status["linked"]:
        result["issues"].append("project has no content repository link")
        return result

    project_dir, _ = _linked_project_dir(project_id)
    if not project_dir.exists():
        result["issues"].append("linked project directory does not exist")
        return result

    required = {}
    for name in ("chapters", "reviews", "versions"):
        path = project_dir / name
        required[name] = {
            "path": str(path),
            "exists": path.is_dir(),
            "writable": os.access(path if path.exists() else project_dir, os.W_OK),
        }
    result["required_directories"] = required

    sources = []
    for kind, path in _source_files(project_dir, root):
        sources.append(
            {
                "kind": kind,
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
            }
        )
    result["sources"] = sources

    if not sources:
        result["issues"].append("no project bible or shared writing-style Markdown found")
    if not os.access(project_dir, os.W_OK):
        result["issues"].append("linked project directory is not writable")
    if any(not item["writable"] for item in required.values()):
        result["issues"].append("one or more output directories are not writable")

    result["ready"] = not result["issues"]
    return result


def _upsert_imported_memory(
    *,
    project_id: int,
    title: str,
    content: str,
    source_ref: str,
    kind: str,
) -> tuple[int, str]:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM memories
            WHERE project_id=? AND source_type='content_repo' AND source_ref=?
            ORDER BY id
            LIMIT 1
            """,
            (project_id, source_ref),
        ).fetchone()
        if row and row["content"] == content and row["title"] == title:
            return int(row["id"]), "unchanged"

        if row:
            memory_id = int(row["id"])
            conn.execute(
                """
                UPDATE memories
                SET kind=?,title=?,content=?,confirmed=1,updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (kind, title, content, memory_id),
            )
            version = conn.execute(
                """
                SELECT COALESCE(MAX(version),0)+1 AS next_version
                FROM memory_versions
                WHERE memory_id=?
                """,
                (memory_id,),
            ).fetchone()["next_version"]
            conn.execute(
                """
                INSERT INTO memory_versions(
                    memory_id,version,kind,title,content,confirmed,note
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    memory_id,
                    version,
                    kind,
                    title,
                    content,
                    1,
                    f"content repo sync: {source_ref}",
                ),
            )
            return memory_id, "updated"

        cur = conn.execute(
            """
            INSERT INTO memories(
                project_id,kind,title,content,source_type,source_ref,confirmed
            ) VALUES(?,?,?,?,?,?,1)
            """,
            (project_id, kind, title, content, "content_repo", source_ref),
        )
        memory_id = int(cur.lastrowid)
        conn.execute(
            """
            INSERT INTO memory_versions(
                memory_id,version,kind,title,content,confirmed,note
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (memory_id, 1, kind, title, content, 1, f"content repo import: {source_ref}"),
        )
        return memory_id, "created"


def _upsert_imported_skill(
    *,
    project_id: int,
    name: str,
    content: str,
    source_ref: str,
) -> tuple[int, str]:
    skill_name = f"内容库 · {name}"
    purpose = f"从 {source_ref} 导入的共享写作规范"
    with connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM skills
            WHERE project_id=? AND name=?
            ORDER BY id
            LIMIT 1
            """,
            (project_id, skill_name),
        ).fetchone()
        if row and row["content"] == content:
            return int(row["id"]), "unchanged"

        if row:
            skill_id = int(row["id"])
            version = int(row["current_version"]) + 1
            conn.execute(
                """
                INSERT INTO skill_versions(skill_id,version,content,note)
                VALUES(?,?,?,?)
                """,
                (skill_id, version, content, f"content repo sync: {source_ref}"),
            )
            conn.execute(
                """
                UPDATE skills
                SET purpose=?,content=?,enabled=1,current_version=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (purpose, content, version, skill_id),
            )
            return skill_id, "updated"

        cur = conn.execute(
            """
            INSERT INTO skills(project_id,name,purpose,content,enabled,current_version)
            VALUES(?,?,?,?,1,1)
            """,
            (project_id, skill_name, purpose, content),
        )
        skill_id = int(cur.lastrowid)
        conn.execute(
            """
            INSERT INTO skill_versions(skill_id,version,content,note)
            VALUES(?,?,?,?)
            """,
            (skill_id, 1, content, f"content repo import: {source_ref}"),
        )
        return skill_id, "created"


def import_content_repository(project_id: int) -> dict:
    root = content_root()
    if root is None:
        raise ValueError("NOVEL_CONTENT_ROOT is not configured")
    project_dir, slug = _linked_project_dir(project_id)
    if not project_dir.exists():
        raise ValueError("linked project directory does not exist")

    imported = []
    for kind, path in _source_files(project_dir, root):
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            continue
        source_ref = str(path.relative_to(root)).replace("\\", "/")
        if kind == "skill":
            resource_id, action = _upsert_imported_skill(
                project_id=project_id,
                name=path.stem,
                content=content,
                source_ref=source_ref,
            )
            imported.append(
                {
                    "resource_type": "skill",
                    "resource_id": resource_id,
                    "source_ref": source_ref,
                    "action": action,
                }
            )
        else:
            memory_kind = {
                "project": "project",
                "world": "world",
                "character": "character",
                "outline": "outline",
            }.get(kind, "world")
            resource_id, action = _upsert_imported_memory(
                project_id=project_id,
                title=path.stem,
                content=content,
                source_ref=source_ref,
                kind=memory_kind,
            )
            imported.append(
                {
                    "resource_type": "memory",
                    "resource_id": resource_id,
                    "source_ref": source_ref,
                    "action": action,
                }
            )

    return {
        "slug": slug,
        "imported": imported,
        "counts": {
            "created": sum(item["action"] == "created" for item in imported),
            "updated": sum(item["action"] == "updated" for item in imported),
            "unchanged": sum(item["action"] == "unchanged" for item in imported),
        },
    }

def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _assert_within_root(path: Path, root: Path) -> None:
    path.resolve().relative_to(root.resolve())


def archive_task(task_id: int) -> dict:
    with connect() as conn:
        task = conn.execute("SELECT * FROM writing_tasks WHERE id=?", (task_id,)).fetchone()
        if not task:
            raise ValueError("task not found")
        if task["status"] != "approved":
            raise ValueError("task is not approved")

        root = content_root()
        if root is None:
            return {
                "status": "disabled",
                "error": "NOVEL_CONTENT_ROOT is not configured",
            }

        link = conn.execute(
            "SELECT * FROM project_content_links WHERE project_id=?",
            (task["project_id"],),
        ).fetchone()
        if not link:
            return {"status": "unlinked", "error": "project has no content repository link"}
        if task["chapter_id"] is None:
            return {"status": "skipped", "error": "task has no target chapter"}
        chapter = conn.execute(
            "SELECT * FROM chapters WHERE id=?", (task["chapter_id"],)
        ).fetchone()
        findings = conn.execute(
            "SELECT * FROM review_findings WHERE task_id=? ORDER BY id", (task_id,)
        ).fetchall()
        runs = conn.execute(
            "SELECT * FROM agent_runs WHERE task_id=? ORDER BY id", (task_id,)
        ).fetchall()

    slug = validate_slug(link["slug"])
    project_dir = (root / "novels" / slug).resolve()
    _assert_within_root(project_dir, root)

    chapter_path = project_dir / "chapters" / f"chapter-{chapter['id']:04d}.md"
    review_path = project_dir / "reviews" / f"task-{task_id:06d}.md"
    version_path = project_dir / "versions" / f"task-{task_id:06d}.md"
    for path in (chapter_path, review_path, version_path):
        _assert_within_root(path, root)

    body = task["revised_content"] or task["draft"] or chapter["content"]
    chapter_doc = f"# {chapter['title']}\n\n{body.rstrip()}\n"

    review_lines = [
        f"# Task {task_id} Review",
        "",
        f"- Goal: {task['goal']}",
        f"- Status: {task['status']}",
        "",
        "## Findings",
        "",
    ]
    if findings:
        for row in findings:
            review_lines.extend(
                [
                    f"### {row['reviewer']} · {row['category']} · {row['severity']}",
                    "",
                    row["summary"],
                    "",
                    f"建议：{row['suggestion']}" if row["suggestion"] else "",
                    "",
                ]
            )
    else:
        review_lines.extend(["本次没有记录 Reviewer finding。", ""])

    review_lines.extend(["## Agent Runs", ""])
    for row in runs:
        run_parts = [
            row["stage"],
            row["role"],
            row["status"],
            row["provider"] or "-",
            row["model"] or "-",
        ]
        review_lines.append("- " + " / ".join(run_parts))

    version_doc = "\n".join(
        [
            f"# NarrativeOS Task {task_id} Accepted Version",
            "",
            f"- Project ID: {task['project_id']}",
            f"- Chapter ID: {chapter['id']}",
            f"- Goal: {task['goal']}",
            f"- Task updated: {task['updated_at']}",
            "",
            "## Content",
            "",
            body.rstrip(),
            "",
        ]
    )

    try:
        _atomic_write(chapter_path, chapter_doc)
        _atomic_write(review_path, "\n".join(review_lines).rstrip() + "\n")
        _atomic_write(version_path, version_doc)
    except OSError as exc:
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO content_syncs(task_id,status,error)
                VALUES(?,?,?)
                """,
                (task_id, "failed", str(exc)[:2000]),
            )
        return {"status": "failed", "error": str(exc)}

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO content_syncs(
                task_id,status,chapter_path,review_path,version_path,error
            ) VALUES(?,?,?,?,?,?)
            """,
            (
                task_id,
                "completed",
                str(chapter_path),
                str(review_path),
                str(version_path),
                "",
            ),
        )

    return {
        "status": "completed",
        "chapter_path": str(chapter_path),
        "review_path": str(review_path),
        "version_path": str(version_path),
    }
