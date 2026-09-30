# NarrativeOS Role-aware Model Routing

正式流水线不再让 Writer 与所有 Reader 共用同一模型。2026-09-30 全模型池基准测试后，默认路由按“可用性 + 任务质量 + 延迟 + 限流稳定性”重新收敛。

当前默认路由：

- Writer / Planner: AGNES -> DOTS3 -> SENSENOVA68 -> ATRIA
- Automated Natural Reader: AGNES -> DOTS3 -> SENSENOVA68 -> ATRIA
- Reasoning Reader: MODELSCOPE -> GLM52 -> DOTS3 -> AGNES
- Final Machine Review: SENSENOVA68 -> DOTS3 -> ATRIA -> AGNES

专项角色：

- blind-reader: AGNES
- blind-natural-reader: AGNES
- aesthetic-reviewer: AGNES
- blind-artifice-reader: MODELSCOPE
- cadence-character-reader: MODELSCOPE
- continuity-reviewer: MODELSCOPE
- plot-reviewer: MODELSCOPE
- character-reviewer: AGNES
- reader-gap-reviewer: MODELSCOPE
- continuity-plot-reviewer: GLM53FLASH
- character-dialogue-reviewer: AGNES
- language-rhythm-reviewer: DOTS3

当前专项深审：

- GLM53FLASH：作为 continuity-plot-reviewer 主模型，使用官方参数流式调用；深审使用 reasoning_effort=high，GLM52 作为 fallback。若官方 5 小时额度触发 429，必须在运行记录中标明“GLM53FLASH 未执行完成”，不得把 fallback 结果记为 GLM53FLASH 结果。

暂不进入关键路径：

- XINGCHENAGI：smoke / writer / review 均超时。
- DEEPSEEKV4PRO：RPM/TPM 限流。
- KIMIK3：RPM/TPM 限流，暂不做稳定生产路由。
- SENSENOVA：正文和审稿质量门通过，但同轮出现 quota 429；保留配置，不做关键路径 primary。

说明：

1. Automated Natural Reader 只是自动初筛，不冒充人工商业读者。
2. 当前与用户共同创作期间，“普通读者 / 商业阅读感 / 节奏”最终首读仍由 ChatGPT 在会话中人工执行并留下明确记录。
3. Writer 与 Reasoning Reader 默认使用不同模型，降低同模型自我脑补造成的相关性漏检。
4. Provider 发生限流或暂时失败时，按同一角色的 fallback 顺序切换。
5. 所有实际运行仍写入 agent_runs 的 provider/model 字段，可追溯某次审核到底用了哪个模型。
6. 详细数据见 `docs/test-reports/2026-09-30-model-pool-routing.md`。

A role can be overridden with:
`NARRATIVE_ROLE_<ROLE_NAME_WITH_UNDERSCORES>_PROFILE`

## Character Voice Review

`character-voice-reviewer` 是逐角色对白门禁。每个活跃角色只审自己的台词，并结合人物卡、关系、利益、压力和已建立声线判断“这个人此刻会不会这样说”。

该层与 blind Reader 分离。Character Voice Review 可以读取目标角色卡和近期章节窗口；blind readers 不读取角色卡或其他 reviewer 输出。任一通道失败都阻止对白通过。
