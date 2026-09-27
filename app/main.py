from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.db import connect, init_db
from app.services.ai_service import assist
from app.services.default_skills import (
    BUILTIN_EDITOR_TRAINING_SKILL_NAME,
    BUILTIN_WRITER_TRAINING_SKILL_NAME,
)
from app.services.book_pipeline import run_book_pipeline
from app.services.continuity_service import (
    latest_story_state,
    latest_story_state_record,
)
from app.services.content_repository import (
    archive_task,
    import_content_repository,
    link_project,
    preflight_content_repository,
    project_content_status,
)
from app.services.full_novel_pipeline import run_full_novel_pipeline
from app.services.workflow_service import WorkflowStateError
from app.services.workflow_service import get_task as get_workflow_task
from app.services.writer_training_pipeline import run_writer_training
from app.services.workflow_service import run_task as execute_workflow_task

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="NarrativeOS", version="1.5.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = ""
    genre: str = ""


class ChapterCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    content: str = ""


class ChapterPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    content: str | None = None
    note: str = "自动保存"


class CharacterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    role: str = ""
    profile: str = ""
    tags: list[str] = []


class WorldNoteCreate(BaseModel):
    category: str = "设定"
    title: str = Field(min_length=1, max_length=120)
    content: str = ""


class AssistRequest(BaseModel):
    mode: str = Field(pattern="^(continue|polish|check)$")
    content: str = ""
    instruction: str = ""


class WritingTaskCreate(BaseModel):
    chapter_id: int | None = None
    goal: str = Field(min_length=1, max_length=500)
    instruction: str = ""
    skill_ids: list[int] | None = None


class ApprovalRequest(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    note: str = ""


class BookPipelineRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=2000)
    instruction: str = ""
    chapter_count: int = Field(default=8, ge=1, le=30)


class WriterTrainingRequest(BaseModel):
    source: str = ""
    transfer_brief: str = ""


class MemoryCreate(BaseModel):
    kind: str = "fact"
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1)
    source_type: str = "manual"
    source_ref: str = ""
    confirmed: bool = False


class MemoryPatch(BaseModel):
    kind: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=120)
    content: str | None = Field(default=None, min_length=1)
    confirmed: bool | None = None


class SkillCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    purpose: str = ""
    content: str = Field(min_length=1)
    enabled: bool = True


class SkillVersionCreate(BaseModel):
    content: str = Field(min_length=1)
    note: str = ""


class SkillPatch(BaseModel):
    enabled: bool


class ContentLinkCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=120)


class ProviderProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    protocol: str = ""
    base_url: str = ""
    api_key_env: str = ""
    default_model: str = ""
    enabled: bool = True
    is_default: bool = False
    options: dict[str, object] = Field(default_factory=dict)


class ProviderProfilePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    protocol: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    default_model: str | None = None
    enabled: bool | None = None
    is_default: bool | None = None
    options: dict[str, object] | None = None


PROVIDER_PROTOCOLS = {"", "openai-compatible", "anthropic", "gemini", "ollama"}


def _validate_provider_protocol(protocol: str) -> str:
    value = protocol.strip().lower()
    if value not in PROVIDER_PROTOCOLS:
        raise HTTPException(400, f"unsupported provider protocol: {protocol}")
    return value


def _provider_row(row):
    item = _row(row)
    if item is None:
        return None
    item["enabled"] = bool(item["enabled"])
    item["is_default"] = bool(item["is_default"])
    item["options"] = json.loads(item.pop("options_json") or "{}")
    return item


def _row(row):
    return dict(row) if row else None


def _require_project(conn, project_id: int):
    project = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not project:
        raise HTTPException(404, "project not found")
    return project


def _require_chapter(conn, chapter_id: int):
    chapter = conn.execute("SELECT * FROM chapters WHERE id=?", (chapter_id,)).fetchone()
    if not chapter:
        raise HTTPException(404, "chapter not found")
    return chapter


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "service": "narrative-os", "version": "1.5.0"}


@app.get("/api/providers")
def list_provider_profiles():
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM provider_profiles
            ORDER BY is_default DESC, enabled DESC, id
            """
        ).fetchall()
        return [_provider_row(row) for row in rows]


@app.post("/api/providers", status_code=201)
def create_provider_profile(payload: ProviderProfileCreate):
    name = payload.name.strip()
    protocol = _validate_provider_protocol(payload.protocol)
    if payload.is_default and (not protocol or not payload.default_model.strip()):
        raise HTTPException(
            400,
            "default provider requires a protocol and default model",
        )
    with connect() as conn:
        if conn.execute(
            "SELECT 1 FROM provider_profiles WHERE name=?",
            (name,),
        ).fetchone():
            raise HTTPException(409, "provider name already exists")
        if payload.is_default:
            conn.execute("UPDATE provider_profiles SET is_default=0")
        cur = conn.execute(
            """
            INSERT INTO provider_profiles(
                name,protocol,base_url,api_key_env,default_model,
                enabled,is_default,options_json
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                name,
                protocol,
                payload.base_url.strip(),
                payload.api_key_env.strip(),
                payload.default_model.strip(),
                int(payload.enabled),
                int(payload.is_default),
                json.dumps(payload.options, ensure_ascii=False),
            ),
        )
        return _provider_row(
            conn.execute(
                "SELECT * FROM provider_profiles WHERE id=?",
                (cur.lastrowid,),
            ).fetchone()
        )


@app.patch("/api/providers/{provider_id}")
def update_provider_profile(provider_id: int, payload: ProviderProfilePatch):
    with connect() as conn:
        current = conn.execute(
            "SELECT * FROM provider_profiles WHERE id=?",
            (provider_id,),
        ).fetchone()
        if not current:
            raise HTTPException(404, "provider profile not found")

        name = payload.name.strip() if payload.name is not None else current["name"]
        protocol = (
            _validate_provider_protocol(payload.protocol)
            if payload.protocol is not None
            else current["protocol"]
        )
        duplicate = conn.execute(
            "SELECT 1 FROM provider_profiles WHERE name=? AND id<>?",
            (name, provider_id),
        ).fetchone()
        if duplicate:
            raise HTTPException(409, "provider name already exists")

        base_url = (
            payload.base_url.strip()
            if payload.base_url is not None
            else current["base_url"]
        )
        api_key_env = (
            payload.api_key_env.strip()
            if payload.api_key_env is not None
            else current["api_key_env"]
        )
        default_model = (
            payload.default_model.strip()
            if payload.default_model is not None
            else current["default_model"]
        )
        enabled = (
            int(payload.enabled)
            if payload.enabled is not None
            else current["enabled"]
        )
        is_default = (
            int(payload.is_default)
            if payload.is_default is not None
            else current["is_default"]
        )
        options_json = (
            json.dumps(payload.options, ensure_ascii=False)
            if payload.options is not None
            else current["options_json"]
        )
        if is_default and (not protocol or not default_model):
            raise HTTPException(
                400,
                "default provider requires a protocol and default model",
            )
        if is_default:
            conn.execute(
                "UPDATE provider_profiles SET is_default=0 WHERE id<>?",
                (provider_id,),
            )
        conn.execute(
            """
            UPDATE provider_profiles
            SET name=?,protocol=?,base_url=?,api_key_env=?,default_model=?,
                enabled=?,is_default=?,options_json=?,updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (
                name,
                protocol,
                base_url,
                api_key_env,
                default_model,
                enabled,
                is_default,
                options_json,
                provider_id,
            ),
        )
        return _provider_row(
            conn.execute(
                "SELECT * FROM provider_profiles WHERE id=?",
                (provider_id,),
            ).fetchone()
        )


@app.delete("/api/providers/{provider_id}")
def delete_provider_profile(provider_id: int):
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM provider_profiles WHERE id=?",
            (provider_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "provider profile not found")
        conn.execute("DELETE FROM provider_profiles WHERE id=?", (provider_id,))
    return {"ok": True}


@app.get("/api/projects")
def list_projects():
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT p.*, COUNT(c.id) AS chapter_count,
                   COALESCE(SUM(LENGTH(c.content)), 0) AS char_count
            FROM projects p
            LEFT JOIN chapters c ON c.project_id=p.id
            GROUP BY p.id
            ORDER BY p.updated_at DESC, p.id DESC
            """
        ).fetchall()
        return [_row(row) for row in rows]


@app.post("/api/projects", status_code=201)
def create_project(payload: ProjectCreate):
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO projects(title,description,genre) VALUES(?,?,?)",
            (payload.title.strip(), payload.description.strip(), payload.genre.strip()),
        )
        project_id = cur.lastrowid
        conn.execute(
            "INSERT INTO chapters(project_id,title,position,content) VALUES(?,?,?,?)",
            (project_id, "第一章", 1, ""),
        )
        return _row(
            conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        )


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: int):
    with connect() as conn:
        _require_project(conn, project_id)
        conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
    return {"ok": True}


@app.get("/api/projects/{project_id}/chapters")
def list_chapters(project_id: int):
    with connect() as conn:
        _require_project(conn, project_id)
        rows = conn.execute(
            """
            SELECT id,project_id,title,position,status,updated_at,
                   LENGTH(content) AS char_count
            FROM chapters
            WHERE project_id=?
            ORDER BY position,id
            """,
            (project_id,),
        ).fetchall()
        return [_row(row) for row in rows]


@app.post("/api/projects/{project_id}/chapters", status_code=201)
def create_chapter(project_id: int, payload: ChapterCreate):
    with connect() as conn:
        _require_project(conn, project_id)
        position = conn.execute(
            """
            SELECT COALESCE(MAX(position),0)+1 AS next_position
            FROM chapters WHERE project_id=?
            """,
            (project_id,),
        ).fetchone()["next_position"]
        cur = conn.execute(
            "INSERT INTO chapters(project_id,title,position,content) VALUES(?,?,?,?)",
            (project_id, payload.title.strip(), position, payload.content),
        )
        chapter_id = cur.lastrowid
        conn.execute(
            "INSERT INTO chapter_versions(chapter_id,content,note) VALUES(?,?,?)",
            (chapter_id, payload.content, "创建章节"),
        )
        return _row(
            conn.execute("SELECT * FROM chapters WHERE id=?", (chapter_id,)).fetchone()
        )


@app.get("/api/chapters/{chapter_id}")
def get_chapter(chapter_id: int):
    with connect() as conn:
        return _row(_require_chapter(conn, chapter_id))


@app.patch("/api/chapters/{chapter_id}")
def update_chapter(chapter_id: int, payload: ChapterPatch):
    with connect() as conn:
        chapter = _require_chapter(conn, chapter_id)
        new_title = payload.title if payload.title is not None else chapter["title"]
        new_content = payload.content if payload.content is not None else chapter["content"]
        changed_content = new_content != chapter["content"]
        conn.execute(
            """
            UPDATE chapters
            SET title=?, content=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (new_title.strip(), new_content, chapter_id),
        )
        if changed_content:
            conn.execute(
                "INSERT INTO chapter_versions(chapter_id,content,note) VALUES(?,?,?)",
                (chapter_id, new_content, payload.note[:120]),
            )
        conn.execute(
            "UPDATE projects SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (chapter["project_id"],),
        )
        return _row(
            conn.execute("SELECT * FROM chapters WHERE id=?", (chapter_id,)).fetchone()
        )


@app.delete("/api/chapters/{chapter_id}")
def delete_chapter(chapter_id: int):
    with connect() as conn:
        _require_chapter(conn, chapter_id)
        conn.execute("DELETE FROM chapters WHERE id=?", (chapter_id,))
    return {"ok": True}


@app.get("/api/chapters/{chapter_id}/versions")
def chapter_versions(chapter_id: int):
    with connect() as conn:
        _require_chapter(conn, chapter_id)
        rows = conn.execute(
            """
            SELECT id,chapter_id,note,created_at,LENGTH(content) AS char_count
            FROM chapter_versions
            WHERE chapter_id=?
            ORDER BY id DESC
            LIMIT 50
            """,
            (chapter_id,),
        ).fetchall()
        return [_row(row) for row in rows]


@app.post("/api/chapters/{chapter_id}/versions/{version_id}/restore")
def restore_version(chapter_id: int, version_id: int):
    with connect() as conn:
        _require_chapter(conn, chapter_id)
        version = conn.execute(
            "SELECT * FROM chapter_versions WHERE id=? AND chapter_id=?",
            (version_id, chapter_id),
        ).fetchone()
        if not version:
            raise HTTPException(404, "version not found")
        conn.execute(
            "UPDATE chapters SET content=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (version["content"], chapter_id),
        )
        conn.execute(
            "INSERT INTO chapter_versions(chapter_id,content,note) VALUES(?,?,?)",
            (chapter_id, version["content"], f"恢复版本 {version_id}"),
        )
        return _row(
            conn.execute("SELECT * FROM chapters WHERE id=?", (chapter_id,)).fetchone()
        )


@app.get("/api/projects/{project_id}/characters")
def list_characters(project_id: int):
    with connect() as conn:
        _require_project(conn, project_id)
        rows = conn.execute(
            "SELECT * FROM characters WHERE project_id=? ORDER BY id",
            (project_id,),
        ).fetchall()
        result = []
        for row in rows:
            item = _row(row)
            item["tags"] = json.loads(item["tags"] or "[]")
            result.append(item)
        return result


@app.post("/api/projects/{project_id}/characters", status_code=201)
def create_character(project_id: int, payload: CharacterCreate):
    with connect() as conn:
        _require_project(conn, project_id)
        cur = conn.execute(
            """
            INSERT INTO characters(project_id,name,role,profile,tags)
            VALUES(?,?,?,?,?)
            """,
            (
                project_id,
                payload.name.strip(),
                payload.role.strip(),
                payload.profile.strip(),
                json.dumps(payload.tags, ensure_ascii=False),
            ),
        )
        row = _row(
            conn.execute("SELECT * FROM characters WHERE id=?", (cur.lastrowid,)).fetchone()
        )
        row["tags"] = json.loads(row["tags"] or "[]")
        return row


@app.get("/api/projects/{project_id}/world")
def list_world_notes(project_id: int):
    with connect() as conn:
        _require_project(conn, project_id)
        rows = conn.execute(
            "SELECT * FROM world_notes WHERE project_id=? ORDER BY id DESC",
            (project_id,),
        ).fetchall()
        return [_row(row) for row in rows]


@app.post("/api/projects/{project_id}/world", status_code=201)
def create_world_note(project_id: int, payload: WorldNoteCreate):
    with connect() as conn:
        _require_project(conn, project_id)
        cur = conn.execute(
            """
            INSERT INTO world_notes(project_id,category,title,content)
            VALUES(?,?,?,?)
            """,
            (
                project_id,
                payload.category.strip(),
                payload.title.strip(),
                payload.content.strip(),
            ),
        )
        return _row(
            conn.execute("SELECT * FROM world_notes WHERE id=?", (cur.lastrowid,)).fetchone()
        )


@app.post("/api/ai/assist")
async def ai_assist(payload: AssistRequest):
    try:
        result = await assist(
            mode=payload.mode,
            content=payload.content,
            instruction=payload.instruction,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "content": result.content,
        "provider": result.provider,
        "model": result.model,
        "demo": result.demo,
    }



@app.get("/api/projects/{project_id}/tasks")
def list_writing_tasks(project_id: int):
    with connect() as conn:
        _require_project(conn, project_id)
        rows = conn.execute(
            """
            SELECT id,project_id,chapter_id,goal,instruction,status,created_at,updated_at
            FROM writing_tasks
            WHERE project_id=?
            ORDER BY id DESC
            """,
            (project_id,),
        ).fetchall()
        return [_row(row) for row in rows]


@app.post("/api/projects/{project_id}/tasks", status_code=201)
def create_writing_task(project_id: int, payload: WritingTaskCreate):
    with connect() as conn:
        _require_project(conn, project_id)
        if payload.chapter_id is not None:
            chapter = _require_chapter(conn, payload.chapter_id)
            if chapter["project_id"] != project_id:
                raise HTTPException(400, "chapter does not belong to project")

        selection_mode = "default" if payload.skill_ids is None else "explicit"
        if payload.skill_ids is None:
            skills = conn.execute(
                """
                SELECT id,current_version
                FROM skills
                WHERE enabled=1
                  AND (project_id IS NULL OR project_id=?)
                  AND name NOT IN (?,?)
                ORDER BY project_id IS NOT NULL DESC,id
                """,
                (
                    project_id,
                    BUILTIN_WRITER_TRAINING_SKILL_NAME,
                    BUILTIN_EDITOR_TRAINING_SKILL_NAME,
                ),
            ).fetchall()
        else:
            requested_ids = list(dict.fromkeys(payload.skill_ids))
            if requested_ids:
                placeholders = ",".join("?" for _ in requested_ids)
                skills = conn.execute(
                    f"""
                    SELECT id,current_version
                    FROM skills
                    WHERE enabled=1
                      AND (project_id IS NULL OR project_id=?)
                      AND id IN ({placeholders})
                    ORDER BY id
                    """,
                    (project_id, *requested_ids),
                ).fetchall()
                found_ids = {int(row["id"]) for row in skills}
                missing = [skill_id for skill_id in requested_ids if skill_id not in found_ids]
                if missing:
                    raise HTTPException(
                        400,
                        f"invalid or disabled skill ids: {missing}",
                    )
            else:
                skills = []

        cur = conn.execute(
            """
            INSERT INTO writing_tasks(project_id,chapter_id,goal,instruction,status)
            VALUES(?,?,?,?,?)
            """,
            (
                project_id,
                payload.chapter_id,
                payload.goal.strip(),
                payload.instruction.strip(),
                "pending",
            ),
        )
        task_id = int(cur.lastrowid)
        conn.execute(
            """
            INSERT INTO writing_task_skill_policy(task_id,mode)
            VALUES(?,?)
            """,
            (task_id, selection_mode),
        )
        for skill in skills:
            conn.execute(
                """
                INSERT INTO writing_task_skills(task_id,skill_id,version)
                VALUES(?,?,?)
                """,
                (task_id, skill["id"], skill["current_version"]),
            )

    return get_workflow_task(task_id)


@app.get("/api/tasks/{task_id}")
def read_writing_task(task_id: int):
    task = get_workflow_task(task_id)
    if not task:
        raise HTTPException(404, "task not found")
    return task


@app.post("/api/tasks/{task_id}/run")
async def run_writing_task(task_id: int):
    if not get_workflow_task(task_id):
        raise HTTPException(404, "task not found")
    try:
        return await execute_workflow_task(task_id)
    except WorkflowStateError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/tasks/{task_id}/run-full-pipeline")
async def run_full_pipeline(task_id: int):
    if not get_workflow_task(task_id):
        raise HTTPException(404, "task not found")
    try:
        return await run_full_novel_pipeline(task_id)
    except WorkflowStateError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/tasks/{task_id}/train-writer")
async def train_writer(task_id: int, payload: WriterTrainingRequest):
    if not get_workflow_task(task_id):
        raise HTTPException(404, "task not found")
    try:
        return await run_writer_training(
            task_id,
            source=payload.source,
            transfer_brief=payload.transfer_brief,
        )
    except WorkflowStateError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/projects/{project_id}/run-book-pipeline")
async def run_project_book_pipeline(project_id: int, payload: BookPipelineRequest):
    with connect() as conn:
        _require_project(conn, project_id)
    try:
        return await run_book_pipeline(
            project_id=project_id,
            goal=payload.goal,
            instruction=payload.instruction,
            chapter_count=payload.chapter_count,
        )
    except WorkflowStateError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/tasks/{task_id}/approval")
def approve_writing_task(task_id: int, payload: ApprovalRequest):
    with connect() as conn:
        task = conn.execute("SELECT * FROM writing_tasks WHERE id=?", (task_id,)).fetchone()
        if not task:
            raise HTTPException(404, "task not found")
        if task["status"] != "awaiting_approval":
            raise HTTPException(
                409,
                f"task cannot be decided while status is {task['status']}",
            )

        version_id = None
        if payload.decision == "approved":
            if task["chapter_id"] is None:
                raise HTTPException(400, "task has no target chapter")
            chapter = _require_chapter(conn, task["chapter_id"])
            content = task["revised_content"] or task["draft"]
            if not content:
                raise HTTPException(409, "task has no generated content to approve")
            conn.execute(
                """
                UPDATE chapters
                SET content=?,status='writing',updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (content, chapter["id"]),
            )
            cur = conn.execute(
                """
                INSERT INTO chapter_versions(chapter_id,content,note)
                VALUES(?,?,?)
                """,
                (chapter["id"], content, f"NarrativeOS task #{task_id} approved"),
            )
            version_id = cur.lastrowid
            conn.execute(
                "UPDATE projects SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (task["project_id"],),
            )

        conn.execute(
            """
            INSERT INTO approvals(task_id,decision,note,chapter_version_id)
            VALUES(?,?,?,?)
            """,
            (task_id, payload.decision, payload.note[:500], version_id),
        )
        conn.execute(
            """
            UPDATE writing_tasks
            SET status=?,updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (payload.decision, task_id),
        )
    task_result = get_workflow_task(task_id)
    if payload.decision == "approved":
        task_result["content_sync"] = archive_task(task_id)
    return task_result


@app.get("/api/projects/{project_id}/content")
def get_project_content_status(project_id: int):
    with connect() as conn:
        _require_project(conn, project_id)
    return project_content_status(project_id)


@app.put("/api/projects/{project_id}/content")
def link_project_content(project_id: int, payload: ContentLinkCreate):
    try:
        link = link_project(project_id, payload.slug)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"link": link, "status": project_content_status(project_id)}


@app.post("/api/tasks/{task_id}/content-sync")
def retry_task_content_sync(task_id: int):
    if not get_workflow_task(task_id):
        raise HTTPException(404, "task not found")
    try:
        return archive_task(task_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/projects/{project_id}/content/preflight")
def preflight_project_content(project_id: int):
    with connect() as conn:
        _require_project(conn, project_id)
    try:
        return preflight_content_repository(project_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/projects/{project_id}/content/import")
def import_project_content(project_id: int):
    with connect() as conn:
        _require_project(conn, project_id)
    try:
        return import_content_repository(project_id)
    except (OSError, ValueError, UnicodeError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/projects/{project_id}/story-state")
def get_story_state(project_id: int):
    with connect() as conn:
        project = conn.execute(
            "SELECT id FROM projects WHERE id=?",
            (project_id,),
        ).fetchone()
    if not project:
        raise HTTPException(status_code=404, detail="project not found")

    record = latest_story_state_record(project_id)
    return {
        "snapshot": record,
        "state": latest_story_state(project_id),
    }


@app.get("/api/projects/{project_id}/story-states")
def list_story_states(project_id: int):
    with connect() as conn:
        project = conn.execute(
            "SELECT id FROM projects WHERE id=?",
            (project_id,),
        ).fetchone()
        if not project:
            raise HTTPException(status_code=404, detail="project not found")
        rows = conn.execute(
            """
            SELECT id,project_id,task_id,chapter_id,chapter_number,
                   summary,created_at,updated_at
            FROM story_state_snapshots
            WHERE project_id=?
            ORDER BY chapter_number,id
            """,
            (project_id,),
        ).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/projects/{project_id}/memories")
def list_memories(project_id: int):
    with connect() as conn:
        _require_project(conn, project_id)
        rows = conn.execute(
            """
            SELECT m.*,
                   COALESCE(
                       (SELECT MAX(mv.version) FROM memory_versions mv WHERE mv.memory_id=m.id),
                       1
                   ) AS current_version
            FROM memories m
            WHERE m.project_id=?
            ORDER BY m.confirmed DESC,m.updated_at DESC,m.id DESC
            """,
            (project_id,),
        ).fetchall()
        return [_row(row) for row in rows]


@app.get("/api/projects/{project_id}/memory-conflicts")
def list_memory_conflicts(project_id: int):
    with connect() as conn:
        _require_project(conn, project_id)
        groups = conn.execute(
            """
            SELECT kind,title,COUNT(DISTINCT content) AS variants
            FROM memories
            WHERE project_id=? AND confirmed=1
            GROUP BY kind,title
            HAVING COUNT(DISTINCT content) > 1
            ORDER BY kind,title
            """,
            (project_id,),
        ).fetchall()
        result = []
        for group in groups:
            items = conn.execute(
                """
                SELECT id,kind,title,content,source_type,source_ref,updated_at
                FROM memories
                WHERE project_id=? AND confirmed=1 AND kind=? AND title=?
                ORDER BY id
                """,
                (project_id, group["kind"], group["title"]),
            ).fetchall()
            result.append(
                {
                    "kind": group["kind"],
                    "title": group["title"],
                    "variants": group["variants"],
                    "items": [_row(item) for item in items],
                }
            )
        return result


@app.post("/api/projects/{project_id}/memories", status_code=201)
def create_memory(project_id: int, payload: MemoryCreate):
    with connect() as conn:
        _require_project(conn, project_id)
        kind = payload.kind.strip() or "fact"
        title = payload.title.strip()
        content = payload.content.strip()
        confirmed = 1 if payload.confirmed else 0
        cur = conn.execute(
            """
            INSERT INTO memories(
                project_id,kind,title,content,source_type,source_ref,confirmed
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (
                project_id,
                kind,
                title,
                content,
                payload.source_type.strip() or "manual",
                payload.source_ref.strip(),
                confirmed,
            ),
        )
        memory_id = cur.lastrowid
        conn.execute(
            """
            INSERT INTO memory_versions(
                memory_id,version,kind,title,content,confirmed,note
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (memory_id, 1, kind, title, content, confirmed, "initial"),
        )
        return _row(conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone())


@app.get("/api/memories/{memory_id}/versions")
def list_memory_versions(memory_id: int):
    with connect() as conn:
        row = conn.execute("SELECT id FROM memories WHERE id=?", (memory_id,)).fetchone()
        if not row:
            raise HTTPException(404, "memory not found")
        versions = conn.execute(
            """
            SELECT * FROM memory_versions
            WHERE memory_id=?
            ORDER BY version DESC
            """,
            (memory_id,),
        ).fetchall()
        return [_row(version) for version in versions]


@app.patch("/api/memories/{memory_id}")
def update_memory(memory_id: int, payload: MemoryPatch):
    with connect() as conn:
        row = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        if not row:
            raise HTTPException(404, "memory not found")
        kind = payload.kind.strip() if payload.kind is not None else row["kind"]
        title = payload.title.strip() if payload.title is not None else row["title"]
        content = payload.content.strip() if payload.content is not None else row["content"]
        confirmed = (
            1 if payload.confirmed else 0
            if payload.confirmed is not None
            else row["confirmed"]
        )
        conn.execute(
            """
            UPDATE memories
            SET kind=?,title=?,content=?,confirmed=?,updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (kind, title, content, confirmed, memory_id),
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
            (memory_id, version, kind, title, content, confirmed, "update"),
        )
        return _row(conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone())


@app.post("/api/memories/{memory_id}/versions/{version}/restore")
def restore_memory_version(memory_id: int, version: int):
    with connect() as conn:
        current = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        if not current:
            raise HTTPException(404, "memory not found")
        source = conn.execute(
            """
            SELECT * FROM memory_versions
            WHERE memory_id=? AND version=?
            """,
            (memory_id, version),
        ).fetchone()
        if not source:
            raise HTTPException(404, "memory version not found")
        conn.execute(
            """
            UPDATE memories
            SET kind=?,title=?,content=?,confirmed=?,updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (
                source["kind"],
                source["title"],
                source["content"],
                source["confirmed"],
                memory_id,
            ),
        )
        next_version = conn.execute(
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
                next_version,
                source["kind"],
                source["title"],
                source["content"],
                source["confirmed"],
                f"restore version {version}",
            ),
        )
        return _row(conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone())


@app.get("/api/projects/{project_id}/skills")
def list_skills(project_id: int):
    with connect() as conn:
        _require_project(conn, project_id)
        rows = conn.execute(
            """
            SELECT * FROM skills
            WHERE project_id IS NULL OR project_id=?
            ORDER BY project_id IS NOT NULL DESC,enabled DESC,id DESC
            """,
            (project_id,),
        ).fetchall()
        return [_row(row) for row in rows]


@app.post("/api/projects/{project_id}/skills", status_code=201)
def create_skill(project_id: int, payload: SkillCreate):
    with connect() as conn:
        _require_project(conn, project_id)
        cur = conn.execute(
            """
            INSERT INTO skills(project_id,name,purpose,content,enabled,current_version)
            VALUES(?,?,?,?,?,1)
            """,
            (
                project_id,
                payload.name.strip(),
                payload.purpose.strip(),
                payload.content.strip(),
                1 if payload.enabled else 0,
            ),
        )
        skill_id = cur.lastrowid
        conn.execute(
            """
            INSERT INTO skill_versions(skill_id,version,content,note)
            VALUES(?,?,?,?)
            """,
            (skill_id, 1, payload.content.strip(), "initial"),
        )
        return _row(conn.execute("SELECT * FROM skills WHERE id=?", (skill_id,)).fetchone())


@app.post("/api/skills/{skill_id}/versions", status_code=201)
def publish_skill_version(skill_id: int, payload: SkillVersionCreate):
    with connect() as conn:
        skill = conn.execute("SELECT * FROM skills WHERE id=?", (skill_id,)).fetchone()
        if not skill:
            raise HTTPException(404, "skill not found")
        version = int(skill["current_version"]) + 1
        conn.execute(
            """
            INSERT INTO skill_versions(skill_id,version,content,note)
            VALUES(?,?,?,?)
            """,
            (skill_id, version, payload.content.strip(), payload.note[:500]),
        )
        conn.execute(
            """
            UPDATE skills
            SET content=?,current_version=?,updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (payload.content.strip(), version, skill_id),
        )
        return _row(conn.execute("SELECT * FROM skills WHERE id=?", (skill_id,)).fetchone())



@app.get("/api/skills/{skill_id}/versions")
def list_skill_versions(skill_id: int):
    with connect() as conn:
        skill = conn.execute("SELECT id FROM skills WHERE id=?", (skill_id,)).fetchone()
        if not skill:
            raise HTTPException(404, "skill not found")
        rows = conn.execute(
            """
            SELECT * FROM skill_versions
            WHERE skill_id=?
            ORDER BY version DESC
            """,
            (skill_id,),
        ).fetchall()
        return [_row(row) for row in rows]


@app.patch("/api/skills/{skill_id}")
def update_skill_state(skill_id: int, payload: SkillPatch):
    with connect() as conn:
        skill = conn.execute("SELECT * FROM skills WHERE id=?", (skill_id,)).fetchone()
        if not skill:
            raise HTTPException(404, "skill not found")
        conn.execute(
            """
            UPDATE skills
            SET enabled=?,updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (1 if payload.enabled else 0, skill_id),
        )
        return _row(conn.execute("SELECT * FROM skills WHERE id=?", (skill_id,)).fetchone())


@app.post("/api/skills/{skill_id}/versions/{version}/restore")
def restore_skill_version(skill_id: int, version: int):
    with connect() as conn:
        skill = conn.execute("SELECT * FROM skills WHERE id=?", (skill_id,)).fetchone()
        if not skill:
            raise HTTPException(404, "skill not found")
        source = conn.execute(
            """
            SELECT * FROM skill_versions
            WHERE skill_id=? AND version=?
            """,
            (skill_id, version),
        ).fetchone()
        if not source:
            raise HTTPException(404, "skill version not found")
        next_version = int(skill["current_version"]) + 1
        conn.execute(
            """
            INSERT INTO skill_versions(skill_id,version,content,note)
            VALUES(?,?,?,?)
            """,
            (skill_id, next_version, source["content"], f"restore version {version}"),
        )
        conn.execute(
            """
            UPDATE skills
            SET content=?,current_version=?,updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (source["content"], next_version, skill_id),
        )
        return _row(conn.execute("SELECT * FROM skills WHERE id=?", (skill_id,)).fetchone())
