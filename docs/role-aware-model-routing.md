# NarrativeOS Role-aware Model Routing

正式流水线不再让 Writer 与所有 Reader 共用同一模型。

当前默认路由：

- Writer / Planner / Revision: SENSENOVA -> AGNES
- Automated Natural Reader: AGNES -> SENSENOVA -> MODELSCOPE
- Reasoning Reader: MODELSCOPE -> AGNES -> SENSENOVA
- Final Machine Review: SENSENOVA -> AGNES -> MODELSCOPE

说明：

1. Automated Natural Reader 只是自动初筛，不冒充人工商业读者。
2. 当前与用户共同创作期间，“普通读者 / 商业阅读感 / 节奏”最终首读由 ChatGPT 在会话中人工执行并留下明确记录。
3. Writer 与 Reasoning Reader 默认使用不同模型，降低同模型自我脑补造成的相关性漏检。
4. Provider 发生限流或暂时失败时，按同一角色的 fallback 顺序切换。
5. 所有实际运行仍写入 agent_runs 的 provider/model 字段，可追溯某次审核到底用了哪个模型。


## Specialist distribution

Default specialist primaries are intentionally different:

- blind-reader: AGNES
- blind-natural-reader: AGNES
- aesthetic-reviewer: AGNES
- blind-artifice-reader: MODELSCOPE
- cadence-character-reader: MODELSCOPE
- continuity-reviewer: MODELSCOPE
- plot-reviewer: MODELSCOPE
- character-reviewer: AGNES
- reader-gap-reviewer: MODELSCOPE

A role can be overridden with:
NARRATIVE_ROLE_<ROLE_NAME_WITH_UNDERSCORES>_PROFILE


## Character Voice Review

`character-voice-reviewer` is a card-aware dialogue gate that runs for each structured character whose name appears in the current draft. Each active character reviews only their own spoken lines, line by line, and answers one core question: would I actually say this here, given my identity, relationship, interests, pressure, and established voice?

This layer is intentionally separate from blind Reader v11. Character Voice Review may read the target character card and recent chapter window; blind readers still receive no character cards or reviewer outputs. A failure in either channel blocks dialogue approval.

Character reviewers run in parallel, use the natural-reader routing bucket, and log under stages such as `character-voice-r1-<character_id>`. The default profile is AGNES with the normal natural-reader fallback chain.
