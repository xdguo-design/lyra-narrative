from __future__ import annotations

import os

os.environ["NOVEL_DB_PATH"] = "/tmp/novel-workbench-test.db"
os.environ["NOVEL_SEED_DEMO"] = "0"
os.environ["NOVEL_AI_KIND"] = "demo"

from fastapi.testclient import TestClient

from app.db import db_path
from app.main import app


def setup_function():
    path = db_path()
    if path.exists():
        path.unlink()


def test_project_chapter_and_ai_flow():
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["ok"] is True

        project = client.post("/api/projects", json={"title": "测试小说", "genre": "悬疑"})
        assert project.status_code == 201
        project_id = project.json()["id"]

        chapters = client.get(f"/api/projects/{project_id}/chapters").json()
        assert len(chapters) == 1
        chapter_id = chapters[0]["id"]

        saved = client.patch(
            f"/api/chapters/{chapter_id}",
            json={"title": "第一章", "content": "雨夜。电话响了。", "note": "测试保存"},
        )
        assert saved.status_code == 200
        assert saved.json()["content"] == "雨夜。电话响了。"

        versions = client.get(f"/api/chapters/{chapter_id}/versions").json()
        assert versions and versions[0]["note"] == "测试保存"

        ai = client.post(
            "/api/ai/assist",
            json={"mode": "continue", "content": "雨夜。电话响了。"},
        )
        assert ai.status_code == 200
        assert ai.json()["demo"] is True
        assert ai.json()["content"]


def test_character_and_world_note_flow():
    with TestClient(app) as client:
        project_id = client.post("/api/projects", json={"title": "设定测试"}).json()["id"]
        character = client.post(
            f"/api/projects/{project_id}/characters",
            json={
                "name": "阿岚",
                "role": "主角",
                "profile": "记者",
                "tags": ["敏锐"],
            },
        )
        assert character.status_code == 201
        assert character.json()["tags"] == ["敏锐"]

        note = client.post(
            f"/api/projects/{project_id}/world",
            json={"category": "地点", "title": "旧城", "content": "终年多雾"},
        )
        assert note.status_code == 201
        assert client.get(f"/api/projects/{project_id}/world").json()[0]["title"] == "旧城"


def test_workbench_page_is_served():
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "NarrativeOS" in response.text
        assert 'id="chapterList"' in response.text
        assert 'id="editor"' in response.text
        assert 'id="aiResult"' in response.text
        assert 'id="themeSelect"' in response.text
        assert 'id="tab-tasks"' in response.text
        assert 'id="tab-memory"' in response.text
        assert 'id="tab-skills"' in response.text
        assert 'id="tab-providers"' in response.text
        assert 'id="providerProtocol"' in response.text
        assert 'id="taskDialog"' in response.text



def test_writer_reviewer_revision_requires_approval_before_chapter_change():
    with TestClient(app) as client:
        project_id = client.post(
            "/api/projects", json={"title": "工作流测试", "genre": "科幻"}
        ).json()["id"]
        chapter_id = client.get(f"/api/projects/{project_id}/chapters").json()[0]["id"]
        original = "门外的雨停了。"
        client.patch(
            f"/api/chapters/{chapter_id}",
            json={"content": original, "note": "工作流基线"},
        )

        memory = client.post(
            f"/api/projects/{project_id}/memories",
            json={
                "kind": "rule",
                "title": "天气规则",
                "content": "本章发生在雨停之后。",
                "confirmed": True,
            },
        )
        assert memory.status_code == 201

        skill = client.post(
            f"/api/projects/{project_id}/skills",
            json={
                "name": "克制续写",
                "purpose": "保持既有事实",
                "content": "不新增无关人物，不改变已确认时间线。",
            },
        )
        assert skill.status_code == 201

        task = client.post(
            f"/api/projects/{project_id}/tasks",
            json={
                "chapter_id": chapter_id,
                "goal": "继续推进门外异响的悬念",
                "instruction": "第三人称。",
            },
        )
        assert task.status_code == 201
        task_id = task.json()["id"]

        run = client.post(f"/api/tasks/{task_id}/run")
        assert run.status_code == 200
        body = run.json()
        assert body["status"] == "awaiting_approval"
        assert body["draft"]
        assert body["revised_content"]
        assert original in body["draft"]
        assert original in body["revised_content"]
        assert len(body["runs"]) == 5
        assert len(body["findings"]) == 3
        assert all(run["metrics"] is not None for run in body["runs"])
        assert {run["metrics"]["prompt_version"] for run in body["runs"]} == {
            "draft-v1",
            "review-v1",
            "revision-v1",
        }

        unchanged = client.get(f"/api/chapters/{chapter_id}").json()
        assert unchanged["content"] == original

        approval = client.post(
            f"/api/tasks/{task_id}/approval",
            json={"decision": "approved", "note": "人工确认"},
        )
        assert approval.status_code == 200
        assert approval.json()["status"] == "approved"

        changed = client.get(f"/api/chapters/{chapter_id}").json()
        assert changed["content"] == body["revised_content"]
        versions = client.get(f"/api/chapters/{chapter_id}/versions").json()
        assert any(f"NarrativeOS task #{task_id} approved" == item["note"] for item in versions)


def test_memory_project_isolation_and_skill_versioning():
    with TestClient(app) as client:
        p1 = client.post("/api/projects", json={"title": "作品甲"}).json()["id"]
        p2 = client.post("/api/projects", json={"title": "作品乙"}).json()["id"]

        memory = client.post(
            f"/api/projects/{p1}/memories",
            json={"kind": "character", "title": "阿岚", "content": "左手有伤。"},
        ).json()
        client.patch(f"/api/memories/{memory['id']}", json={"confirmed": True})

        p1_memories = client.get(f"/api/projects/{p1}/memories").json()
        p2_memories = client.get(f"/api/projects/{p2}/memories").json()
        assert len(p1_memories) == 1
        assert p1_memories[0]["confirmed"] == 1
        assert p2_memories == []

        skill = client.post(
            f"/api/projects/{p1}/skills",
            json={"name": "审稿规则", "content": "先检查时间线。"},
        ).json()
        published = client.post(
            f"/api/skills/{skill['id']}/versions",
            json={"content": "先检查时间线，再检查称谓。", "note": "补充称谓"},
        )
        assert published.status_code == 201
        assert published.json()["current_version"] == 2
        assert published.json()["content"] == "先检查时间线，再检查称谓。"



def test_content_repository_archives_approved_task():
    import tempfile
    from pathlib import Path

    previous = os.environ.get("NOVEL_CONTENT_ROOT")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["NOVEL_CONTENT_ROOT"] = tmp
        try:
            with TestClient(app) as client:
                project_id = client.post(
                    "/api/projects", json={"title": "慢速世界"}
                ).json()["id"]
                chapter_id = client.get(
                    f"/api/projects/{project_id}/chapters"
                ).json()[0]["id"]

                linked = client.put(
                    f"/api/projects/{project_id}/content",
                    json={"slug": "slow-world"},
                )
                assert linked.status_code == 200
                assert linked.json()["status"]["linked"] is True

                task_id = client.post(
                    f"/api/projects/{project_id}/tasks",
                    json={
                        "chapter_id": chapter_id,
                        "goal": "验证内容库归档",
                        "instruction": "保持原有事实。",
                    },
                ).json()["id"]
                assert client.post(f"/api/tasks/{task_id}/run").status_code == 200

                approved = client.post(
                    f"/api/tasks/{task_id}/approval",
                    json={"decision": "approved", "note": "归档验收"},
                )
                assert approved.status_code == 200
                sync = approved.json()["content_sync"]
                assert sync["status"] == "completed"

                root = Path(tmp) / "novels" / "slow-world"
                assert (root / "chapters" / f"chapter-{chapter_id:04d}.md").exists()
                assert (root / "reviews" / f"task-{task_id:06d}.md").exists()
                assert (root / "versions" / f"task-{task_id:06d}.md").exists()
        finally:
            if previous is None:
                os.environ.pop("NOVEL_CONTENT_ROOT", None)
            else:
                os.environ["NOVEL_CONTENT_ROOT"] = previous



def test_legacy_sqlite_schema_upgrades_additively_without_losing_content():
    import sqlite3
    import tempfile
    from pathlib import Path

    from app.db import init_db

    previous_path = os.environ.get("NOVEL_DB_PATH")
    previous_seed = os.environ.get("NOVEL_SEED_DEMO")

    with tempfile.TemporaryDirectory() as tmp:
        legacy_path = Path(tmp) / "legacy.db"
        conn = sqlite3.connect(legacy_path)
        conn.executescript(
            """
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                genre TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE chapters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                content TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE chapter_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chapter_id INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
                content TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '自动保存',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE characters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT '',
                profile TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE world_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                category TEXT NOT NULL DEFAULT '设定',
                title TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            INSERT INTO projects(id,title,description,genre,status)
            VALUES(1,'旧作品','保留测试','悬疑','draft');
            INSERT INTO chapters(id,project_id,title,position,content,status)
            VALUES(1,1,'旧章节',1,'不能丢失的正文','draft');
            INSERT INTO chapter_versions(id,chapter_id,content,note)
            VALUES(1,1,'不能丢失的正文','旧版本');
            INSERT INTO characters(id,project_id,name,role,profile,tags)
            VALUES(1,1,'旧人物','主角','旧档案','["旧标签"]');
            INSERT INTO world_notes(id,project_id,category,title,content)
            VALUES(1,1,'规则','旧规则','不能丢失的设定');
            """
        )
        conn.commit()
        conn.close()

        os.environ["NOVEL_DB_PATH"] = str(legacy_path)
        os.environ["NOVEL_SEED_DEMO"] = "0"
        try:
            init_db()
            conn = sqlite3.connect(legacy_path)
            conn.row_factory = sqlite3.Row
            assert conn.execute("SELECT content FROM chapters WHERE id=1").fetchone()["content"] == "不能丢失的正文"
            assert conn.execute("SELECT note FROM chapter_versions WHERE id=1").fetchone()["note"] == "旧版本"
            assert conn.execute("SELECT name FROM characters WHERE id=1").fetchone()["name"] == "旧人物"
            assert conn.execute("SELECT content FROM world_notes WHERE id=1").fetchone()["content"] == "不能丢失的设定"

            tables = {
                row["name"]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            assert {
                "writing_tasks",
                "agent_runs",
                "review_findings",
                "approvals",
                "memories",
                "skills",
                "skill_versions",
                "project_content_links",
                "content_syncs",
            }.issubset(tables)
            conn.close()
        finally:
            if previous_path is None:
                os.environ.pop("NOVEL_DB_PATH", None)
            else:
                os.environ["NOVEL_DB_PATH"] = previous_path
            if previous_seed is None:
                os.environ.pop("NOVEL_SEED_DEMO", None)
            else:
                os.environ["NOVEL_SEED_DEMO"] = previous_seed



def test_memory_conflicts_history_restore_and_agent_resource_trace():
    with TestClient(app) as client:
        project_id = client.post("/api/projects", json={"title": "追溯测试"}).json()["id"]
        chapter_id = client.get(f"/api/projects/{project_id}/chapters").json()[0]["id"]

        first = client.post(
            f"/api/projects/{project_id}/memories",
            json={
                "kind": "character",
                "title": "林渡",
                "content": "左手有旧伤。",
                "confirmed": True,
            },
        ).json()
        client.post(
            f"/api/projects/{project_id}/memories",
            json={
                "kind": "character",
                "title": "林渡",
                "content": "左手从未受伤。",
                "confirmed": True,
            },
        )

        conflicts = client.get(
            f"/api/projects/{project_id}/memory-conflicts"
        ).json()
        assert len(conflicts) == 1
        assert conflicts[0]["title"] == "林渡"
        assert conflicts[0]["variants"] == 2

        changed = client.patch(
            f"/api/memories/{first['id']}",
            json={"content": "右手有旧伤。"},
        )
        assert changed.status_code == 200
        versions = client.get(f"/api/memories/{first['id']}/versions").json()
        assert [item["version"] for item in versions[:2]] == [2, 1]

        restored = client.post(
            f"/api/memories/{first['id']}/versions/1/restore"
        )
        assert restored.status_code == 200
        assert restored.json()["content"] == "左手有旧伤。"
        versions = client.get(f"/api/memories/{first['id']}/versions").json()
        assert versions[0]["version"] == 3

        skill = client.post(
            f"/api/projects/{project_id}/skills",
            json={
                "name": "连续性优先",
                "purpose": "先保护已确认事实",
                "content": "任何修订先核对人物状态。",
            },
        ).json()

        task_id = client.post(
            f"/api/projects/{project_id}/tasks",
            json={
                "chapter_id": chapter_id,
                "goal": "继续一小段",
                "instruction": "不要改人物伤势。",
            },
        ).json()["id"]
        task = client.post(f"/api/tasks/{task_id}/run").json()
        assert task["runs"]
        resources = task["runs"][0]["resources"]
        assert any(
            item["resource_type"] == "memory"
            and item["resource_id"] == first["id"]
            and item["version"] == 3
            for item in resources
        )
        assert any(
            item["resource_type"] == "skill"
            and item["resource_id"] == skill["id"]
            and item["version"] == 1
            for item in resources
        )


def test_skill_disable_history_and_restore():
    with TestClient(app) as client:
        project_id = client.post("/api/projects", json={"title": "技能回滚"}).json()["id"]
        skill = client.post(
            f"/api/projects/{project_id}/skills",
            json={"name": "节奏", "content": "短句少用。"},
        ).json()

        client.post(
            f"/api/skills/{skill['id']}/versions",
            json={"content": "长短句交替。", "note": "v2"},
        )
        versions = client.get(f"/api/skills/{skill['id']}/versions").json()
        assert [item["version"] for item in versions[:2]] == [2, 1]

        disabled = client.patch(
            f"/api/skills/{skill['id']}",
            json={"enabled": False},
        )
        assert disabled.status_code == 200
        assert disabled.json()["enabled"] == 0

        restored = client.post(
            f"/api/skills/{skill['id']}/versions/1/restore"
        )
        assert restored.status_code == 200
        assert restored.json()["current_version"] == 3
        assert restored.json()["content"] == "短句少用。"



def test_content_repository_preflight_and_idempotent_source_import():
    import tempfile
    from pathlib import Path

    previous = os.environ.get("NOVEL_CONTENT_ROOT")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_dir = root / "novels" / "slow-world"
        project_dir.mkdir(parents=True)
        (project_dir / "README.md").write_text(
            "# 慢速世界\n\n正式作品说明。\n",
            encoding="utf-8",
        )
        legacy_bible = root / "bible"
        legacy_bible.mkdir()
        world_file = legacy_bible / "world.md"
        world_file.write_text(
            "# 世界观\n\n2041年，灰雾降临。\n",
            encoding="utf-8",
        )
        style_dir = root / "shared" / "writing-style"
        style_dir.mkdir(parents=True)
        style_file = style_dir / "README.md"
        style_file.write_text(
            "# 写作规范\n\n保持人物连续性。\n",
            encoding="utf-8",
        )

        os.environ["NOVEL_CONTENT_ROOT"] = str(root)
        try:
            with TestClient(app) as client:
                project_id = client.post(
                    "/api/projects",
                    json={"title": "慢速世界"},
                ).json()["id"]
                client.put(
                    f"/api/projects/{project_id}/content",
                    json={"slug": "slow-world"},
                )

                preflight = client.get(
                    f"/api/projects/{project_id}/content/preflight"
                )
                assert preflight.status_code == 200
                assert preflight.json()["ready"] is True
                source_paths = {
                    item["path"] for item in preflight.json()["sources"]
                }
                assert "novels/slow-world/README.md" in source_paths
                assert "bible/world.md" in source_paths
                assert "shared/writing-style/README.md" in source_paths

                first = client.post(
                    f"/api/projects/{project_id}/content/import"
                )
                assert first.status_code == 200
                assert first.json()["counts"]["created"] == 3

                memories = client.get(
                    f"/api/projects/{project_id}/memories"
                ).json()
                skills = client.get(
                    f"/api/projects/{project_id}/skills"
                ).json()
                assert len(memories) == 2
                assert all(item["confirmed"] == 1 for item in memories)
                assert len(skills) == 1
                assert skills[0]["enabled"] == 1

                second = client.post(
                    f"/api/projects/{project_id}/content/import"
                )
                assert second.status_code == 200
                assert second.json()["counts"]["unchanged"] == 3

                world_file.write_text(
                    "# 世界观\n\n2041年，灰雾降临，灰塔出现。\n",
                    encoding="utf-8",
                )
                third = client.post(
                    f"/api/projects/{project_id}/content/import"
                )
                assert third.status_code == 200
                assert third.json()["counts"]["updated"] == 1

                updated_world = next(
                    item
                    for item in client.get(
                        f"/api/projects/{project_id}/memories"
                    ).json()
                    if item["source_ref"] == "bible/world.md"
                )
                versions = client.get(
                    f"/api/memories/{updated_world['id']}/versions"
                ).json()
                assert versions[0]["version"] == 2
        finally:
            if previous is None:
                os.environ.pop("NOVEL_CONTENT_ROOT", None)
            else:
                os.environ["NOVEL_CONTENT_ROOT"] = previous



def test_workflow_state_guards_prevent_duplicate_approval_and_unapproved_archive():
    with TestClient(app) as client:
        project_id = client.post(
            "/api/projects",
            json={"title": "状态机测试"},
        ).json()["id"]
        chapter_id = client.get(
            f"/api/projects/{project_id}/chapters"
        ).json()[0]["id"]

        task_id = client.post(
            f"/api/projects/{project_id}/tasks",
            json={
                "chapter_id": chapter_id,
                "goal": "验证状态保护",
            },
        ).json()["id"]

        premature_sync = client.post(f"/api/tasks/{task_id}/content-sync")
        assert premature_sync.status_code == 409

        premature_approval = client.post(
            f"/api/tasks/{task_id}/approval",
            json={"decision": "approved"},
        )
        assert premature_approval.status_code == 409

        run = client.post(f"/api/tasks/{task_id}/run")
        assert run.status_code == 200
        assert run.json()["status"] == "awaiting_approval"

        rerun_while_waiting = client.post(f"/api/tasks/{task_id}/run")
        assert rerun_while_waiting.status_code == 409

        approved = client.post(
            f"/api/tasks/{task_id}/approval",
            json={"decision": "approved"},
        )
        assert approved.status_code == 200

        duplicate = client.post(
            f"/api/tasks/{task_id}/approval",
            json={"decision": "approved"},
        )
        assert duplicate.status_code == 409

        rerun_approved = client.post(f"/api/tasks/{task_id}/run")
        assert rerun_approved.status_code == 409



def test_task_skill_selection_freezes_versions_and_supports_explicit_none():
    with TestClient(app) as client:
        project_id = client.post(
            "/api/projects",
            json={"title": "Skill 冻结测试"},
        ).json()["id"]
        chapter_id = client.get(
            f"/api/projects/{project_id}/chapters"
        ).json()[0]["id"]

        skill_a = client.post(
            f"/api/projects/{project_id}/skills",
            json={"name": "Skill A", "content": "规则 A v1"},
        ).json()
        skill_b = client.post(
            f"/api/projects/{project_id}/skills",
            json={"name": "Skill B", "content": "规则 B v1"},
        ).json()

        task = client.post(
            f"/api/projects/{project_id}/tasks",
            json={
                "chapter_id": chapter_id,
                "goal": "只使用 A",
                "skill_ids": [skill_a["id"]],
            },
        ).json()
        assert [(item["id"], item["version"]) for item in task["skills"]] == [
            (skill_a["id"], 1)
        ]

        client.post(
            f"/api/skills/{skill_a['id']}/versions",
            json={"content": "规则 A v2", "note": "升级"},
        )
        client.patch(
            f"/api/skills/{skill_b['id']}",
            json={"enabled": False},
        )

        frozen = client.get(f"/api/tasks/{task['id']}").json()
        assert frozen["skills"][0]["version"] == 1
        assert frozen["skills"][0]["content"] == "规则 A v1"

        run = client.post(f"/api/tasks/{task['id']}/run").json()
        first_run_skills = [
            item
            for item in run["runs"][0]["resources"]
            if item["resource_type"] == "skill"
        ]
        assert len(first_run_skills) == 1
        assert first_run_skills[0]["resource_id"] == skill_a["id"]
        assert first_run_skills[0]["version"] == 1
        assert first_run_skills[0]["content"] == "规则 A v1"

        no_skill_task = client.post(
            f"/api/projects/{project_id}/tasks",
            json={
                "chapter_id": chapter_id,
                "goal": "明确不用 Skill",
                "skill_ids": [],
            },
        ).json()
        assert no_skill_task["skills"] == []

        no_skill_run = client.post(
            f"/api/tasks/{no_skill_task['id']}/run"
        ).json()
        assert not any(
            item["resource_type"] == "skill"
            for item in no_skill_run["runs"][0]["resources"]
        )



def test_structured_reviewer_findings_locate_exact_source_excerpt():
    from app.services.workflow_service import _parse_review_output

    draft = "胡朔推开门。走廊尽头传来金属碰撞。他停住脚步。"
    output = """严重性: blocking
片段: 走廊尽头传来金属碰撞
问题: 声音来源与前文设定冲突。
建议: 明确声音来自已出现的房间。
---
严重性: suggestion
片段: NONE
问题: 结尾节奏可以更紧。
建议: 删除一句解释。"""

    findings = _parse_review_output(output, draft)
    assert len(findings) == 2
    assert findings[0]["severity"] == "blocking"
    assert findings[0]["excerpt"] == "走廊尽头传来金属碰撞"
    assert findings[0]["start_offset"] == draft.index("走廊尽头传来金属碰撞")
    assert findings[0]["end_offset"] == findings[0]["start_offset"] + len(
        "走廊尽头传来金属碰撞"
    )
    assert findings[1]["excerpt"] == ""
    assert findings[1]["start_offset"] is None



def test_zero_platform_full_production_acceptance_flow():
    import tempfile
    from pathlib import Path

    previous = os.environ.get("NOVEL_CONTENT_ROOT")
    seed_chapter = """临江市的雨从晚上十点开始下，到午夜时已经细得像雾。

林桥把检修车停在青屿站封闭入口外，平板上的曲线还亮着。

00:06。十八点二千瓦。

一条已经断开市政运营系统七年的地铁支线，正在稳定用电。

七年前，林桥的妹妹林夏最后一次给他发消息：哥，我到终点站了。

他刷开检修门往下走。站厅里没有脚印，只有两条像行李箱轮子留下的平行细痕。

00:07，隧道深处亮起车灯。

一班没有线路编号的银灰色列车停在废弃站台。

第一节车厢里，失踪七年的林夏隔着车窗看着他。

倒计时还剩六秒。

她抬手贴住玻璃。

“哥，你怎么还没上车？”
"""

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_dir = root / "novels" / "zero-platform"
        (project_dir / "bible").mkdir(parents=True)
        (project_dir / "characters").mkdir()
        (project_dir / "outline").mkdir()
        (project_dir / "chapters").mkdir()
        (project_dir / "reviews").mkdir()
        (project_dir / "versions").mkdir()
        style_dir = root / "shared" / "writing-style"
        style_dir.mkdir(parents=True)

        (project_dir / "README.md").write_text(
            "# 零点站台\n\n都市悬疑 / 时间异常。\n",
            encoding="utf-8",
        )
        (project_dir / "bible" / "world.md").write_text(
            "# 世界观\n\n每天 00:07，停运七年的青屿站会出现一班只停 47 秒的列车。\n",
            encoding="utf-8",
        )
        (project_dir / "characters" / "lin-qiao.md").write_text(
            "# 林桥\n\n34 岁，供电检修工程师。右手虎口有旧烧伤。妹妹林夏于七年前失踪。\n",
            encoding="utf-8",
        )
        (project_dir / "outline" / "volume-01.md").write_text(
            "# 第一卷\n\n林桥调查青屿站异常用电，并发现妹妹活在另一条人生分支中。\n",
            encoding="utf-8",
        )
        (style_dir / "README.md").write_text(
            "# 写作规范\n\n保持第三人称限知；少解释，多用可观察细节推进悬疑。\n",
            encoding="utf-8",
        )

        os.environ["NOVEL_CONTENT_ROOT"] = str(root)
        try:
            with TestClient(app) as client:
                project_id = client.post(
                    "/api/projects",
                    json={
                        "title": "零点站台",
                        "genre": "都市悬疑 / 轻科幻",
                        "description": "NarrativeOS 全链路验收小说",
                    },
                ).json()["id"]
                chapter_id = client.get(
                    f"/api/projects/{project_id}/chapters"
                ).json()[0]["id"]

                baseline = client.patch(
                    f"/api/chapters/{chapter_id}",
                    json={
                        "title": "第一章 七年前停运的站",
                        "content": seed_chapter,
                        "note": "零点站台验收初稿",
                    },
                )
                assert baseline.status_code == 200

                linked = client.put(
                    f"/api/projects/{project_id}/content",
                    json={"slug": "zero-platform"},
                )
                assert linked.status_code == 200

                preflight = client.get(
                    f"/api/projects/{project_id}/content/preflight"
                )
                assert preflight.status_code == 200
                assert preflight.json()["ready"] is True
                source_kinds = {item["kind"] for item in preflight.json()["sources"]}
                assert {"project", "world", "character", "outline", "skill"}.issubset(
                    source_kinds
                )

                imported = client.post(
                    f"/api/projects/{project_id}/content/import"
                )
                assert imported.status_code == 200
                assert imported.json()["counts"]["created"] == 5

                memories = client.get(
                    f"/api/projects/{project_id}/memories"
                ).json()
                skills = client.get(
                    f"/api/projects/{project_id}/skills"
                ).json()
                assert {item["kind"] for item in memories} == {
                    "project",
                    "world",
                    "character",
                    "outline",
                }
                assert len(skills) == 1
                skill_id = skills[0]["id"]

                task = client.post(
                    f"/api/projects/{project_id}/tasks",
                    json={
                        "chapter_id": chapter_id,
                        "goal": "从林夏出现后继续推进悬念，但不解释零点列车真相。",
                        "instruction": "保持第三人称限知，不新增核心人物。",
                        "skill_ids": [skill_id],
                    },
                )
                assert task.status_code == 201
                task_id = task.json()["id"]
                assert task.json()["skills"][0]["version"] == 1

                run = client.post(f"/api/tasks/{task_id}/run")
                assert run.status_code == 200
                body = run.json()
                assert body["status"] == "awaiting_approval"
                assert body["draft"]
                assert body["revised_content"]
                assert len(body["runs"]) == 5
                assert len(body["findings"]) == 3
                assert all(item["metrics"] is not None for item in body["runs"])
                assert all(
                    any(
                        resource["resource_type"] == "skill"
                        and resource["resource_id"] == skill_id
                        and resource["version"] == 1
                        for resource in agent_run["resources"]
                    )
                    for agent_run in body["runs"]
                )

                before_approval = client.get(
                    f"/api/chapters/{chapter_id}"
                ).json()
                assert before_approval["content"] == seed_chapter

                approved = client.post(
                    f"/api/tasks/{task_id}/approval",
                    json={
                        "decision": "approved",
                        "note": "零点站台全链路验收通过",
                    },
                )
                assert approved.status_code == 200
                approved_body = approved.json()
                assert approved_body["status"] == "approved"
                assert approved_body["content_sync"]["status"] == "completed"

                accepted_content = client.get(
                    f"/api/chapters/{chapter_id}"
                ).json()["content"]
                assert accepted_content == body["revised_content"]
                assert seed_chapter.strip() in accepted_content
                assert accepted_content.strip() != seed_chapter.strip()

                chapter_file = (
                    project_dir / "chapters" / f"chapter-{chapter_id:04d}.md"
                )
                review_file = (
                    project_dir / "reviews" / f"task-{task_id:06d}.md"
                )
                version_file = (
                    project_dir / "versions" / f"task-{task_id:06d}.md"
                )
                assert chapter_file.exists()
                assert review_file.exists()
                assert version_file.exists()
                assert accepted_content in chapter_file.read_text(encoding="utf-8")
                assert "Agent Runs" in review_file.read_text(encoding="utf-8")
                assert accepted_content in version_file.read_text(encoding="utf-8")

                versions = client.get(
                    f"/api/chapters/{chapter_id}/versions"
                ).json()
                baseline_version = next(
                    item
                    for item in versions
                    if item["note"] == "零点站台验收初稿"
                )
                accepted_version = next(
                    item
                    for item in versions
                    if item["note"] == f"NarrativeOS task #{task_id} approved"
                )

                restored_baseline = client.post(
                    f"/api/chapters/{chapter_id}/versions/{baseline_version['id']}/restore"
                )
                assert restored_baseline.status_code == 200
                assert restored_baseline.json()["content"] == seed_chapter

                restored_accepted = client.post(
                    f"/api/chapters/{chapter_id}/versions/{accepted_version['id']}/restore"
                )
                assert restored_accepted.status_code == 200
                assert restored_accepted.json()["content"] == accepted_content

                chapter_file.unlink()
                review_file.unlink()
                version_file.unlink()
                resync = client.post(f"/api/tasks/{task_id}/content-sync")
                assert resync.status_code == 200
                assert resync.json()["status"] == "completed"
                assert chapter_file.exists()
                assert review_file.exists()
                assert version_file.exists()

            with TestClient(app) as restarted:
                persisted_task = restarted.get(f"/api/tasks/{task_id}")
                assert persisted_task.status_code == 200
                assert persisted_task.json()["status"] == "approved"
                persisted_chapter = restarted.get(
                    f"/api/chapters/{chapter_id}"
                )
                assert persisted_chapter.status_code == 200
                assert persisted_chapter.json()["content"] == accepted_content
        finally:
            if previous is None:
                os.environ.pop("NOVEL_CONTENT_ROOT", None)
            else:
                os.environ["NOVEL_CONTENT_ROOT"] = previous


def test_full_novel_pipeline_rejects_demo_provider():
    previous = os.environ.get("NOVEL_AI_KIND")
    os.environ["NOVEL_AI_KIND"] = "demo"
    try:
        with TestClient(app) as client:
            project_id = client.post(
                "/api/projects",
                json={"title": "完整流水线测试", "genre": "科幻"},
            ).json()["id"]
            chapter_id = client.get(
                f"/api/projects/{project_id}/chapters"
            ).json()[0]["id"]
            task = client.post(
                f"/api/projects/{project_id}/tasks",
                json={
                    "chapter_id": chapter_id,
                    "goal": "从架构开始生成第一章",
                    "instruction": "必须经过完整创作流水线。",
                },
            )
            assert task.status_code == 201
            response = client.post(
                f"/api/tasks/{task.json()['id']}/run-full-pipeline"
            )
            assert response.status_code == 409
            assert "real AI provider" in response.json()["detail"]
    finally:
        if previous is None:
            os.environ.pop("NOVEL_AI_KIND", None)
        else:
            os.environ["NOVEL_AI_KIND"] = previous


def test_book_pipeline_rejects_demo_provider():
    previous = os.environ.get("NOVEL_AI_KIND")
    os.environ["NOVEL_AI_KIND"] = "demo"
    try:
        with TestClient(app) as client:
            project_id = client.post(
                "/api/projects",
                json={"title": "整书流水线测试", "genre": "科幻"},
            ).json()["id"]
            response = client.post(
                f"/api/projects/{project_id}/run-book-pipeline",
                json={
                    "goal": "从架构开始写一部完整小说",
                    "instruction": "必须走冻结规划与逐章审核。",
                    "chapter_count": 8,
                },
            )
            assert response.status_code == 409
            assert "real AI provider" in response.json()["detail"]
    finally:
        if previous is None:
            os.environ.pop("NOVEL_AI_KIND", None)
        else:
            os.environ["NOVEL_AI_KIND"] = previous


def test_provider_profile_name_is_custom_and_protocol_is_optional():
    with TestClient(app) as client:
        created = client.post(
            "/api/providers",
            json={
                "name": "主写作",
                "protocol": "",
                "enabled": True,
            },
        )
        assert created.status_code == 201
        body = created.json()
        assert body["name"] == "主写作"
        assert body["protocol"] == ""
        assert body["is_default"] is False

        incomplete_default = client.patch(
            f"/api/providers/{body['id']}",
            json={"is_default": True},
        )
        assert incomplete_default.status_code == 400

        configured = client.patch(
            f"/api/providers/{body['id']}",
            json={
                "protocol": "openai-compatible",
                "base_url": "https://example.invalid/v1",
                "api_key_env": "WRITER_MODEL_KEY",
                "default_model": "writer-model",
                "is_default": True,
            },
        )
        assert configured.status_code == 200
        configured_body = configured.json()
        assert configured_body["name"] == "主写作"
        assert configured_body["protocol"] == "openai-compatible"
        assert configured_body["api_key_env"] == "WRITER_MODEL_KEY"
        assert configured_body["is_default"] is True


def test_provider_default_switches_between_user_named_instances():
    with TestClient(app) as client:
        writer = client.post(
            "/api/providers",
            json={
                "name": "主写作",
                "protocol": "openai-compatible",
                "default_model": "writer-model",
                "is_default": True,
            },
        ).json()
        reviewer = client.post(
            "/api/providers",
            json={
                "name": "科学审稿",
                "protocol": "anthropic",
                "default_model": "review-model",
                "is_default": True,
            },
        )
        assert reviewer.status_code == 201

        rows = client.get("/api/providers").json()
        by_name = {item["name"]: item for item in rows}
        assert by_name["主写作"]["is_default"] is False
        assert by_name["科学审稿"]["is_default"] is True

        duplicate = client.post(
            "/api/providers",
            json={"name": "主写作"},
        )
        assert duplicate.status_code == 409

        invalid = client.post(
            "/api/providers",
            json={"name": "错误协议", "protocol": "kimi"},
        )
        assert invalid.status_code == 400

        deleted = client.delete(f"/api/providers/{writer['id']}")
        assert deleted.status_code == 200
