# Model Pool Benchmark & Routing Decision — 2026-09-30

Source run: GitHub Actions `Model Pool Benchmark` run **36657505415**  
Benchmark commit: `89695055b1a7bab68d8ccf50d7ab8c27bb73e9b7`

All 11 production profiles were tested with the same smoke, fiction-writing and review tasks. KIMIK3 used its required temperature=1.0; reasoning-heavy models received larger completion budgets so empty-content false negatives were reduced.

| Profile | Smoke | Writer | Review | Decision |
|---|---:|---:|---:|---|
| AGNES | 1.8s PASS | 16.2s PASS | 11.3s PASS, 5/5 signals | Primary writer + natural/dialogue review |
| DOTS3 | 1.5s PASS | 30.8s PASS | 12.8s PASS, 5/5 | Writer fallback + language/rhythm + final fallback |
| SENSENOVA68 | 3.4s PASS | 41.4s PASS | 11.5s PASS, 5/5 | Scene/prose editor + final review primary |
| ATRIA | 9.0s PASS | 37.8s; length gate miss by 4 chars | 18.4s PASS, 5/5 | Reviewer/fallback only |
| MODELSCOPE | 2.4s PASS | 81.7s timeout | 25.8s PASS, 5/5 | Reasoning/continuity/plot review |
| GLM52 | 3.3s PASS | 96.1s PASS | 29.2s PASS, 5/5 | Slow reasoning-review fallback |
| GLM53FLASH | 2.4s PASS | 120.4s timeout | 93.3s PASS, 5/5 | Remove from critical path |
| SENSENOVA | quota 429 | 19.7s PASS | 17.7s PASS, 5/5 | Standby only until quota stable |
| DEEPSEEKV4PRO | 2.5s PASS | 429 | 429 | Standby; rate-limited |
| KIMIK3 | empty/length | 429 | 429 | Standby; rate-limited |
| XINGCHENAGI | 28.2s timeout | 81.8s timeout | 56.1s timeout | Remove from active routing |

## Production routing

- Writer: AGNES -> DOTS3 -> SENSENOVA68 -> ATRIA
- Natural reader: AGNES -> DOTS3 -> SENSENOVA68 -> ATRIA
- Reasoning reader: MODELSCOPE -> GLM52 -> DOTS3 -> AGNES
- Final review: SENSENOVA68 -> DOTS3 -> ATRIA -> AGNES
- Continuity / plot: MODELSCOPE
- Character dialogue: AGNES
- Language / rhythm: DOTS3
- Scene enrichment / prose edit: SENSENOVA68
- Revision / writer retry: DOTS3

Profiles removed from the critical path are not deleted from repository configuration; they remain available for future re-benchmarking after endpoint, quota or latency changes.
