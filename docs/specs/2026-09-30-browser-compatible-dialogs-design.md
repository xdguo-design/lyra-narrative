# Browser-compatible forms and confirmations

## Problem

The workbench uses native `prompt()`, `confirm()`, and `alert()` throughout project, chapter, and supporting tools. The Codex in-app browser does not support these native dialogs consistently, so users cannot create projects, chapters, or writing tasks, approve a task, or read content-repository preflight failures from that browser.

## Decision

Replace every native `prompt()`, `confirm()`, and `alert()` call in the workbench with shared, accessible HTML `<dialog>` patterns: a form dialog, a confirmation dialog, and an acknowledgement dialog for multi-line notices. Keep the existing API endpoints and business operations unchanged.

The form dialog supports labeled text inputs, textareas, selects, checkboxes, and multi-select skill choices; required fields and defaults; submit and cancel; Escape cancellation; and returning either submitted values or an explicit cancellation result. Build fields with DOM APIs and assign user-provided strings as text/value properties so titles and content are not interpreted as markup.

Cancel or Escape aborts the current operation and never submits an approval, rejection, restore, replacement, or delete. Blank optional fields continue with their documented defaults. Required goal/title/content fields prevent submission and focus the invalid field. Approval notes remain optional; rejection reasons are required by the API.

Use one form per operation. Project, chapter, memory, skill creation/version publishing, character, world-setting, and content-repository forms collect their existing values together. The writing-task form collects its goal, optional instruction, and enabled Skills. Approval and rejection collect a note, with rejection reason required. Memory, Skill, and chapter history restoration use a version select rather than asking users to type a version number. Memory confirmation is an explicit checkbox. Delete, AI replacement, and history restore operations use a distinct confirmation dialog with the affected object and consequence named.

Dialogs have an accessible name and description. Every field has a programmatic label and associated validation message. Opening moves focus to the first useful control; closing returns focus to the invoking button. Keyboard users can navigate options and submit; validation focuses the first invalid control.

## Scope

Cover all current `prompt()`/`confirm()`/`alert()` call sites in `app/static/app.js`, including project and chapter creation/deletion, replacing AI output, writing tasks and approval/rejection, memory creation/confirmation/restoration, Skill creation/version publishing/restoration, content-repository binding and preflight notices, characters, world settings, chapter-version restoration, and provider deletion. Add reusable dialog markup to `app/static/index.html` and styles to `app/static/styles.css`.

Do not change API schemas, database behavior, workflow stages, or demo/model selection.

## Validation

- Confirm no native `prompt()`, `confirm()`, or `alert()` calls remain in the workbench.
- Verify create/cancel/submit behavior, default values, required-field validation, keyboard dismissal, focus return, error association, checkbox/skill selection, and dropdown version selection.
- In the in-app browser, create a test project and chapter, create and run a writing task, then approve and confirm the chapter version persists.
- Exercise memory confirmation, Skill publishing, AI replacement cancel and confirm (including version creation), memory/Skill/chapter restoration, repository binding, character/world-setting forms, and provider deletion cancel and confirm. Use only the newly created test project and a disposable test Provider for destructive success-path checks.
- Run the existing automated checks and inspect browser console errors.
- At 860px and other tablet widths, keep the assistant panel and all tools reachable without horizontal page or tab overflow; after AI generation, bring the result into view.
