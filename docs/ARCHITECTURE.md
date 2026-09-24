# Architecture

NarrativeOS is a local-first long-form fiction workflow system. Platform state lives in SQLite; accepted manuscript artifacts stay in a separate content repository.

```text
Browser workbench
  ├─ Project / chapter tree
  ├─ Long-form editor + autosave + versions
  ├─ Writer / Reviewer / Revision tasks
  ├─ Memory Engine
  ├─ Skill Engine
  ├─ Characters / world notes
  ├─ Content repository controls
  └─ Theme + mobile navigation
          │
          ▼
FastAPI (app.main)
  ├─ SQLite persistence (app.db)
  ├─ Workflow service
  ├─ AI assist service
  ├─ Content repository adapter
  └─ Provider abstraction
          │
          ├─ Gemini native
          ├─ Anthropic native
          ├─ OpenAI-compatible / DeepSeek / vLLM
          ├─ Ollama
          └─ freellm-gateway
```

## Workflow safety

A writing task persists Writer output and independent Reviewer findings before any chapter mutation. Revision output is staged. Only an explicit human approval updates the chapter and creates the accepted SQLite version.

Agent runs snapshot the Memory and Skill versions used for that run so later edits do not rewrite historical provenance.

## Memory and skills

Confirmed project Memory enters Agent context; candidate Memory does not. Memory has version history, restore, project isolation, and deterministic same-title conflict detection.

Skills are project-scoped in the MVP, versioned, enable/disable capable, and restorable. Every Agent run records the exact Skill version used.

## Content repository boundary

`NOVEL_CONTENT_ROOT` points to a separate checkout such as `slow-world-novel`.

NarrativeOS can:

- preflight the linked project directory;
- read project/world Markdown and shared writing-style Markdown;
- import world/project sources into confirmed Memory;
- import writing-style sources into versioned Skills;
- archive an approved chapter plus review and accepted-version documents;
- retry a failed archive without rerunning the creative task.

The platform repository never stores the manuscript itself.

## Local-first behavior

- SQLite is created automatically under `data/` unless `NOVEL_DB_PATH` is set.
- Demo data is seeded only when the database is empty and `NOVEL_SEED_DEMO=1`.
- No API key is required for editing or Demo workflow validation.
- Provider key values are not stored in SQLite.
- Existing baseline SQLite tables are upgraded additively; destructive schema changes require a separate reversible migration.

See `docs/OPERATIONS.md` for backup, restore, and failure recovery.
