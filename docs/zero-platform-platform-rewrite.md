# 《零点站台》平台重写

这次重写只认 NarrativeOS 运行记录，不接受聊天中直接生成的正文作为正式产物。

## 固定模型

所有 Agent 统一使用 OpenAI GPT-5.6 Sol：

- provider: `openai`
- model: `gpt-5.6-sol`
- reasoning effort: `high`
- API key environment name: `OPENAI_API_KEY`

## 整书流程

1. Story Architect：整本故事架构
2. World Builder：科学假设、装置、事故、规则与边界
3. Character Designer：人物秘密、错误、利益冲突与关系钉子
4. Plot Planner：冻结 8 章整卷大纲
5. 每章顺序执行 Writer → Scene Enricher → Prose Editor
6. 五个 Reviewer 独立审核：continuity / plot / character / world-science / style
7. Revision Agent 修订
8. 第二轮五审；仍有 blocking 时再次重写并第三轮复审
9. 所有候选章保持未批准状态，等待人工终审

旧版《零点站台》正文不作为 Writer 的输入答案，只保留标题和核心故事前提。

## 运行

本地：

```bash
export OPENAI_API_KEY=...
python scripts/run_zero_platform_rewrite.py
```

GitHub Actions：

运行 `Zero Platform NarrativeOS Rewrite`。仓库必须先配置 Actions Secret：
`OPENAI_API_KEY`。

输出 artifact `zero-platform-platform-rewrite`，其中包括：

- `planning.md`
- `planning-task.json`
- `chapter-0001.md` ... `chapter-0008.md`
- 每章完整 Task / AgentRun / ReviewFinding JSON
- `manuscript-candidate.md`
- `manifest.json`

只有 manifest 中的 Provider/Model、AgentRun 和 Reviewer 记录齐全，才算平台正式产出。
