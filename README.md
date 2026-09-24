# NarrativeOS

AI-native storytelling operating system.

## Local runnable baseline

The first migration brings the working novel workbench from `xdguo-design/aitest`
into this repository. NarrativeOS currently runs as a local-first FastAPI app
with SQLite and a static browser UI. Writer/Reviewer orchestration, Memory,
Skill, themes, and the separate manuscript content-repository adapter are now runnable.

### Start

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
make run
```

Open `http://127.0.0.1:8000`. The API health check is at
`http://127.0.0.1:8000/api/health`; interactive API docs are at
`http://127.0.0.1:8000/docs`.

No model key is required for local editing. AI actions use a clearly marked
demo fallback until a provider is configured. See [provider configuration](docs/PROVIDERS.md).

### Current capabilities

- Multiple novel projects and chapter organization
- Chapter editing with autosave, snapshots, and version restore
- Writer → multi-Reviewer → Revision → human approval workflow
- Versioned project Memory with confirmation, conflict detection, and rollback
- Versioned Skills with enable/disable and rollback
- Content-repository preflight, world/style import, accepted chapter/review/version archive, and retry
- Character cards and project-specific world notes
- AI continue, polish, and consistency-check actions
- Pluggable Gemini, Anthropic, OpenAI-compatible, Ollama, and gateway providers
- Four switchable themes and mobile chapter navigation
- SQLite persistence plus API and Chromium browser tests in CI

The exact source inventory and remaining migration work are tracked in
[the migration checklist](docs/aitest-migration.md). `aitest` remains the
source of truth until it is no longer needed for comparison or fallback. See
the [remaining feature roadmap](docs/remaining-features-roadmap.md).

## Vision

NarrativeOS is a production workflow platform for long-form fiction creation.

It separates:

- AI writing agents
- review agents
- skill memory
- world building
- character consistency
- version management

## Core Workflow

```
Creative Task
    ↓
Writer Agent
    ↓
Reviewer Agents
    ↓
Revision Agent
    ↓
Final Version
    ↓
Skill Update
```

## Modules

- Agent Workflow
- Skill Library
- Character Engine
- World Engine
- Review Pipeline
- Version System

## First Test Project

Slow World (`slow-world-novel`)

A post-apocalyptic time ability novel used to validate the complete AI writing workflow.
