# Controller → Master Reader Handoff

NarrativeOS supports a fourth review lane performed by the external controller model.

## Isolation rule

The controller switches roles only after the chapter candidate is frozen. During the blind read it receives:

- current chapter candidate;
- a short tail of the previous chapter;
- a compact reader task contract.

It must **not** receive automated Reviewer outputs, review findings, model routing logs, or revision suggestions before producing its own review.

## Why

The controller has broad orchestration context. Reusing all of that context during review would contaminate the independent-reader signal. The handoff therefore creates a smaller reader packet and treats the controller as a fresh reader for that stage.

## Merge order

1. Writer freezes candidate.
2. Three automated Reviewer lanes run independently.
3. Controller reads `master-reader-packet.md` blindly.
4. Only after the controller review is complete are all four reviews merged.
5. P0/P1 findings are repaired as one batch.
6. Recheck repeats the same independence rule.

The controller review is not a provider fallback. It is an independent fourth opinion.
