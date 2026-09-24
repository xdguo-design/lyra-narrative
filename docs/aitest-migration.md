# aitest → NarrativeOS migration

## Source and safety gate

- Source: `xdguo-design/aitest`, branch `main`.
- Destination: `xdguo-design/narrative-os`, branch `main` baseline.
- The source is private and remains unchanged. It may be deleted once it is no
  longer needed for migration comparison or fallback, after the validation
  gates in the roadmap pass.
- Novel manuscripts belong in the separate `slow-world-novel` repository.

## Compatibility baseline copied

The initial local migration copied 28 files from `aitest`, preserving the
existing platform docs and README:

- FastAPI app and REST API (`app/main.py`)
- SQLite schema, initialization, and persistence (`app/db.py`)
- AI service and provider abstraction (`app/ai`, `app/services`)
- Existing browser workbench (`app/static`)
- Environment example, dependencies, Makefile, and CI (`.env.example`,
  `requirements*.txt`, `Makefile`, `.github/workflows/ci.yml`)
- API and provider tests (`tests`)
- Provider and implementation docs (`docs/ARCHITECTURE.md`,
  `docs/PROVIDERS.md`)
- Original source README retained as `docs/aitest-reference.md` for feature and
  setup comparison.

## Validation completed

- Python bytecode compilation: passed.
- Ruff: passed.
- Browser JavaScript syntax check: passed.
- Chromium Playwright workbench acceptance: passed.
- pytest: current full suite passes in GitHub Actions.
- Legacy five-table SQLite additive upgrade/data-preservation test: passed.
- Writer/Reviewer/Revision approval safety tests: passed.
- Memory conflict/version/rollback and Skill audit/version/rollback tests: passed.
- Content repository write, preflight, and idempotent import tests: passed.

## Deletion gate result

The production acceptance gate is complete using the dedicated acceptance novel 《零点站台》, created after the product owner explicitly requested a new novel for the final test instead of using 《慢速世界》.

The full acceptance covers content preflight/import, frozen Skill versions, Writer → 3 Reviewers → Revision → human approval, archive output, version restore, content-sync recovery, application restart recovery, and CI.

The acceptance test found and fixed a P0 truncation bug where Writer `continue` output could replace the whole chapter. The regression test now requires the original chapter to remain in both the task draft and final revised content.

See `docs/acceptance-zero-platform.md`.


## Source drift check

Verified on 2026-09-23:

- `xdguo-design/aitest@main` is still at `b8c243ff860c0985268f8a4e2269a5d1373dcf9f`.
- Its latest commit predates this migration and no new source features were added during the NarrativeOS work.
- Unmodified migrated provider files retain identical Git blob SHAs in both repositories.
- NarrativeOS has intentionally diverged only where it adds workflow, Memory, Skill, content-repository, theme/mobile, tests, and updated documentation.

Therefore `aitest` is no longer needed for ongoing feature-drift comparison or workflow fallback. The dedicated 《零点站台》 production-style acceptance has passed.
