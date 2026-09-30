# Context-aware Model Routing — 2026-09-30

The model pool is no longer treated as if every model has the same context capacity.

Runtime policy:

- The current draft is always preserved in full for chapter review.
- Continuity/plot review receives the largest supporting-context budget: Reader Skill tail 6k chars + project context tail 7k chars.
- Character/dialogue review receives Reader Skill tail 4.5k chars + recent-chapter window tail 5k chars.
- Language/rhythm review receives only the current draft + Reader Skill tail 3.5k chars; full project Memory is intentionally omitted.
- Every model invocation now logs estimated input characters and a short / medium / long context tier before the provider call.
- Model availability decisions use the actual production workload, not only the short benchmark.

Reason: 2026-09-30 chapter-02 runs showed that several profiles passed short benchmark prompts but timed out under full chapter review prompts. Context size is therefore a routing dimension, separate from prose/review quality and raw latency.
