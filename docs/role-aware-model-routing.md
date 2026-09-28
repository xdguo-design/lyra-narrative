# NarrativeOS Role-aware Model Routing

正式流水线不再让 Writer 与所有 Reader 共用同一模型。

当前默认路由：

- Writer / Planner / Revision: ATRIA -> AGNES -> KIMIK3
- Automated Natural Reader: GLM52 -> SENSENOVA68 -> AGNES
- Reasoning Reader: DEEPSEEKV4PRO -> MODELSCOPE -> GLM52
- Final Machine Review: SENSENOVA -> DEEPSEEKV4PRO -> AGNES

说明：

1. Automated Natural Reader 只是自动初筛，不冒充人工商业读者。
2. 当前与用户共同创作期间，“普通读者 / 商业阅读感 / 节奏”最终首读由 ChatGPT 在会话中人工执行并留下明确记录。
3. Writer 与 Reasoning Reader 默认使用不同模型，降低同模型自我脑补造成的相关性漏检。
4. Provider 发生限流或暂时失败时，按同一角色的 fallback 顺序切换。
5. 所有实际运行仍写入 agent_runs 的 provider/model 字段，可追溯某次审核到底用了哪个模型。


## Specialist distribution

Default specialist primaries are intentionally different:

- blind-reader: GLM52
- blind-natural-reader: SENSENOVA68
- aesthetic-reviewer: AGNES
- blind-artifice-reader: DEEPSEEKV4PRO
- cadence-character-reader: MODELSCOPE
- continuity-reviewer: MODELSCOPE
- plot-reviewer: DEEPSEEKV4PRO
- character-reviewer: GLM52
- reader-gap-reviewer: DEEPSEEKV4PRO

A role can be overridden with:
NARRATIVE_ROLE_<ROLE_NAME_WITH_UNDERSCORES>_PROFILE
