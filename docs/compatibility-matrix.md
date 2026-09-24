# aitest → NarrativeOS compatibility matrix

> Baseline source: `xdguo-design/aitest` / `docs/aitest-reference.md`.
> Destination branch: `migration/aitest-baseline`.
> Rule: every user-visible source behavior must be kept, explicitly upgraded, or explicitly removed. No silent removal.

| Area | Source behavior | Disposition | NarrativeOS result | Automated coverage |
|---|---|---|---|---|
| Projects | Create multiple novels | Keep | `POST /api/projects` | `test_project_chapter_and_ai_flow` |
| Projects | Switch novels | Keep | Browser project selector | workbench smoke + API tests |
| Projects | Show genre/chapter/character counts | Keep | Existing summary card | API/workbench smoke |
| Projects | Delete a novel and dependent data | Keep | FK cascade retained | existing API behavior |
| Demo | Seed demo novel on first boot | Keep | `NOVEL_SEED_DEMO` retained | baseline tests |
| Chapters | Create chapter | Keep | Existing API/UI | `test_project_chapter_and_ai_flow` |
| Chapters | Switch/search/delete chapter | Keep | Existing UI/API | workbench smoke |
| Editor | Edit title/body | Keep | Existing editor | API tests |
| Editor | 850 ms autosave | Keep | Existing browser logic | JS syntax + workbench smoke |
| Editor | Ctrl/Cmd+S | Keep | Existing shortcut | JS syntax |
| Editor | Character count | Keep | Existing UI | workbench smoke |
| Editor | Focus mode | Keep | Existing UI | JS syntax |
| Versions | Snapshot on body change | Keep | Existing `chapter_versions` | `test_project_chapter_and_ai_flow` |
| Versions | Show recent history | Keep | Existing dialog | workbench smoke |
| Versions | Restore previous version | Keep | Existing restore endpoint | baseline API tests |
| Characters | Project-scoped character cards | Keep | Existing API/UI | `test_character_and_world_note_flow` |
| World | Project-scoped world notes | Keep | Existing API/UI | `test_character_and_world_note_flow` |
| AI | Continue / polish / consistency check | Keep | Existing `/api/ai/assist` | `test_project_chapter_and_ai_flow` |
| AI safety | Preview before append/replace | Keep | Existing result panel | workbench smoke |
| Provider | Demo fallback without API key | Keep + harden | Demo polish now returns original content instead of destructive placeholder text | workflow tests |
| Provider | Pluggable Gemini/Anthropic/OpenAI-compatible/Ollama/gateway | Keep | Provider registry unchanged | `test_provider_registry.py` |
| Persistence | SQLite local-first | Keep | Existing path/config retained | all API tests |
| Legacy DB | Existing five-table database remains readable | Upgrade | New NarrativeOS tables are additive; old content is preserved | `test_legacy_sqlite_schema_upgrades_additively_without_losing_content` |
| UI | Three-column workbench | Keep | Existing layout retained | workbench smoke |
| Responsive | Narrow-screen layout | Keep + upgrade | Existing responsive rules retained; new tabs are horizontally scrollable | static/JS checks |
| Themes | Single visual theme | Upgrade | Four switchable themes: 墨白 / 深空 / 纸页 / Neo Pop; preference persists locally | workbench smoke + JS check |
| Workflow | One-shot AI buttons only | Upgrade | Persistent Writer → 3 Reviewers → Revision → human approval task flow | `test_writer_reviewer_revision_requires_approval_before_chapter_change` |
| Workflow safety | N/A | New | Original chapter is unchanged until explicit approval | same workflow test |
| Memory | Character/world notes only | Upgrade | Structured project memory with candidate/confirmed state; only confirmed memory enters Agent context | memory isolation test |
| Skills | N/A | New | Project-scoped, versioned skills used in task context | skill versioning test |
| Content repo | Manuscript mixed with app/local DB only | Upgrade | Separate local checkout integration via `NOVEL_CONTENT_ROOT`; project/world/character/outline/style import plus approved chapter/review/version archive | `test_content_repository_archives_approved_task`, `test_zero_platform_full_production_acceptance_flow` |

## Explicitly not removed

No user-visible capability from the baseline has been intentionally removed in this migration slice.

## Browser verification status

Chromium Playwright acceptance now runs in CI and covers the desktop workbench, four-theme persistence, editor autosave/reload, task/Memory/Skill surfaces, content-repository controls, mobile chapter navigation, mobile assistant visibility, horizontal overflow, and page JavaScript errors.

The remaining manual production check is intentionally provider/content dependent: run a real 《慢速世界》 chapter with the configured production Provider, inspect the Reviewer locations and approval diff, then verify repository archive and recovery.

## Data migration rule

NarrativeOS currently uses additive SQLite schema creation only. The migration must not rename/drop the original `projects`, `chapters`, `chapter_versions`, `characters`, or `world_notes` tables without a dedicated reversible migration.
