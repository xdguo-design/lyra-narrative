# NarrativeOS operations guide

This document covers local installation, content-repository setup, backup/recovery, and common failure recovery for the single-user local-first release.

## 1. Install and start

Requirements:

- Python 3.11+
- Git
- Chromium only when running the browser test suite

Create an environment and install dependencies:

```bash
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

Start NarrativeOS:

```bash
python -m uvicorn app.main:app --reload --port 8000
```

Open:

- Workbench: `http://127.0.0.1:8000`
- Health: `http://127.0.0.1:8000/api/health`
- API docs: `http://127.0.0.1:8000/docs`

## 2. Local data and content repository

NarrativeOS keeps workflow state in SQLite and accepted manuscript artifacts in a separate content repository.

Recommended layout:

```text
D:/WorkSpace/
├─ narrative-os/
└─ slow-world-novel/
   └─ novels/
      └─ slow-world/
         ├─ bible/
         ├─ characters/
         ├─ outline/
         ├─ chapters/
         ├─ reviews/
         └─ versions/
```

Environment:

```env
NOVEL_DB_PATH=data/novel_workbench.db
NOVEL_CONTENT_ROOT=D:/WorkSpace/slow-world-novel
```

In the workbench:

1. Open **任务**.
2. Bind the project content slug, for example `slow-world`.
3. Run **预检**.
4. Run **导入资料** to import repository world/style Markdown into Memory/Skill.
5. Create and run a writing task.
6. Only after human approval does NarrativeOS update the chapter and archive chapter/review/version files.

## 3. Content preflight

`GET /api/projects/{project_id}/content/preflight` verifies:

- `NOVEL_CONTENT_ROOT` is configured;
- the repository root exists;
- the project is linked to a slug;
- `novels/<slug>` exists and is writable;
- chapter/review/version output locations are writable;
- project bible and/or shared writing-style Markdown can be discovered.

A failed preflight must be fixed before a production import or archive run.

## 4. Backup

Back up both stores together.

### SQLite

Stop NarrativeOS before copying the SQLite file:

```text
data/novel_workbench.db
```

A backup should include the full database file, not only exported chapter text, because tasks, reviews, approvals, Memory versions, Skill versions, and content-sync history live in SQLite.

### Content repository

Commit or copy the complete `slow-world-novel` repository. Git is the preferred history for accepted manuscript artifacts.

At a production checkpoint, record both:

- SQLite backup timestamp/hash;
- content repository Git commit SHA.

This pair is the recovery point.

## 5. Restore

1. Stop NarrativeOS.
2. Restore the selected SQLite backup to `NOVEL_DB_PATH`.
3. Checkout the matching content-repository commit.
4. Start NarrativeOS.
5. Open the project and run content **预检**.
6. Verify chapter history and the most recent task/approval.
7. If SQLite says an approved task exists but content files are missing, call:
   `POST /api/tasks/{task_id}/content-sync`.

Never repair a mismatch by manually rewriting both SQLite and Git artifacts at the same time. Restore one authoritative checkpoint, then use the sync endpoint.

## 6. Failure recovery

### Writer fails

The task becomes `failed`. The original chapter is unchanged. Retry the task.

### One Reviewer fails

Other Reviewer results remain available. The failure is stored as a finding; it is not treated as a pass.

### Revision fails

The task remains reviewed and the Writer draft/Reviewer output is retained. Retry without changing the chapter.

### Approval succeeds but content sync fails

The chapter and SQLite version are already accepted. The sync record stores the error. Fix the filesystem/repository path and run the content-sync retry endpoint.

### Content repository source changes

Run **导入资料** again. Unchanged sources are ignored; changed Memory/Skill sources create a new version instead of silently overwriting history.

### Memory conflict

The Memory tab surfaces confirmed records with the same kind/title but different content. Withdraw the incorrect confirmed memory or restore a prior version before the next production run.

## 7. Validation commands

```bash
python -m compileall -q app tests
ruff check app tests
node --check app/static/app.js
pytest -q
```

For the browser suite:

```bash
python -m playwright install chromium
pytest -q tests/test_browser.py
```

CI runs the full suite including Chromium.

## 8. Production acceptance before deleting `aitest`

Do not delete the old repository until all of the following are true:

- compatibility matrix has no unexplained user-visible gap;
- current NarrativeOS CI is green;
- an old SQLite database has been upgraded without data loss;
- a real 《慢速世界》 chapter completes Writer → Reviewer → Revision → human approval;
- chapter/review/version artifacts are present under `novels/slow-world`;
- a restore/re-sync rehearsal succeeds;
- no team workflow still relies on `aitest` as comparison or fallback.
