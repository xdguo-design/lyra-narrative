# Chapter 02 Live Model Routing Report — 2026-09-30

This report records real chapter-generation load, not only short synthetic benchmark results.

## Key conclusion

Context capacity is now a first-class routing dimension. A model may be usable for short prompts and still be unsuitable for a full chapter + Reader Skill + project context review.

## Live runs

### Run 36658953669 / attempt 20

- AGNES writer part 1: 22.778s — success.
- AGNES writer part 2: 15.039s — success.
- AGNES character/dialogue review: 49.002s — success.
- MODELSCOPE continuity/plot: 62.549s — ProviderError / read-timeout class, fallback.
- DOTS3 continuity fallback: 59.649s — ProviderError / read-timeout class, fallback.
- AGNES continuity fallback: 60.040s — read timeout, final failure.
- DOTS3 language/rhythm: 60.319s — ProviderError / read-timeout class, fallback.
- ATRIA language fallback: 61.095s — read timeout, final failure.
- Candidate: 2736 chars, hard gate 0, but automated review had blocking findings.

### Run 36659492089 / attempt 21

- AGNES writer: 13.833s + 14.285s — success.
- AGNES character/dialogue review: 45.137s — success.
- MODELSCOPE continuity/plot: 91.071s — timeout, fallback.
- DOTS3 continuity fallback: 52.502s — ProviderError, fallback.
- AGNES continuity fallback: 41.235s — success.
- DOTS3 language/rhythm: 52.369s — ProviderError, fallback.
- ATRIA language fallback: 91.020s — timeout, final failure.
- Candidate: 2533 chars; hard gate caught length, missing death-message wording and missing explicit weight-anomaly wording.

### Run 36660026809 / attempt 22

- AGNES writer: 17.240s + 14.523s — success.
- AGNES character/dialogue review: 1.918s — success.
- GLM52 continuity/plot, full review load: 84.321s — success.
- SENSENOVA68 language/rhythm: 41.406s — empty content, finish_reason=length, total_tokens=38233.
- AGNES language fallback: 79.232s — success.
- Candidate: 2178 chars; hard gate failed length only.

### Run 36660443173 / attempt 23

Prompt-size logging was enabled.

- AGNES writer part 1: 9472 input chars / medium — 15.382s, success.
- AGNES writer part 2: 8660 input chars / medium — 10.518s, success.
- AGNES length-repair: 2043 input chars / short — 22.216s, success, but output became shorter; the repair strategy itself is therefore defective.
- GLM52 continuity/plot: 15410 input chars / long — 69.227s, empty content, finish_reason=length, total_tokens=14061; fallback.
- AGNES continuity fallback: same long workload — 44.877s, success.
- AGNES character/dialogue: 14865 input chars / long — 2.078s, success.
- SENSENOVA68 language/rhythm: 5986 input chars / short — 43.949s, empty content, finish_reason=length, total_tokens=8973; fallback.
- AGNES language fallback: same short workload — 38.112s, success.
- Candidate: 1671 chars; unusable because length repair shortened rather than expanded.

## Current availability by workload

| Profile | Short task | Medium writing | Long chapter review | Current use |
|---|---|---|---|---|
| AGNES | stable | stable | stable, latency varies | primary writer and reliable review fallback |
| GLM52 | usable | not primary | conditional; 1 success / 1 empty-length in live runs | continuity specialist with AGNES fallback |
| MODELSCOPE | benchmark review good | not recommended | timed out in full review | short/medium reasoning review only until retested |
| DOTS3 | benchmark good | writer fallback | repeated ProviderError/timeouts in full review | writing fallback / short review only |
| ATRIA | benchmark review good | fallback only | full review timeout | short review / standby |
| SENSENOVA68 | benchmark good | usable writer/editor | empty-length even on compact review prompt | writing/editor role; review disabled pending response-token tuning |
| GLM53FLASH | smoke good | long writing timeout | very slow | off critical path |
| XINGCHENAGI | unstable/timeouts | unstable | unstable | inactive |
| DEEPSEEKV4PRO | rate limited | rate limited | rate limited | standby |
| KIMIK3 | rate limited / response issue | rate limited | rate limited | standby |
| SENSENOVA | quota instability | content quality acceptable | quota instability | standby |

## Routing rule

Do not equate “model quality” with “context capacity”. Route by:

1. task role;
2. actual input-context tier;
3. measured latency/failure mode at that tier;
4. then prose/review quality.

The pipeline now emits `input_chars` and `context_tier=short|medium|long` before provider calls and budgets reviewer support context by role.


### Run 36661383153 / attempt 25

Three-scene generation was introduced to reduce per-call constraint load.

- AGNES scene 1 writer: 9626 input chars / medium — 7.669s, success.
- AGNES scene 2 writer: 8260 input chars / medium — 22.520s, success.
- AGNES scene 3 writer: 8362 input chars / medium — 10.109s, success.
- AGNES continuity/plot: 15990 input chars / long — 63.478s, success.
- AGNES character/dialogue: 15445 input chars / long — 8.571s, success.
- AGNES language/rhythm: 6566 input chars / medium — 28.363s, success.
- Candidate: 2251 chars; only deterministic hard-gate failure was length.
- Provider routing was stable in this run; remaining blockers are now primarily **writer instruction adherence / scene logic / target length**, not provider availability.

Operational conclusion: for this chapter, AGNES is the verified long-context review model. Model diversity should come from context-appropriate specialist tasks and the external controller blind reader, not by forcing short-context profiles into long review prompts.
