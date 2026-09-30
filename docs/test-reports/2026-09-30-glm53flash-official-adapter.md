# GLM-5.3-Flash 官方适配专项测试 — 2026-09-30

## 结论

GLM-5.3-Flash 官方接口可用于 NarrativeOS。适配器已按官方聊天场景参数调整，并通过短响应、约 3000 字正文和整章连续性审稿三类真实调用。

## 适配参数

- temperature: 1.0
- top_p: 0.95
- thinking.type: enabled
- thinking.clear_thinking: true
- stream: true
- tool_stream: true
- reasoning_effort:
  - short_response: low
  - writer_3000_chars: low
  - whole_chapter_continuity_review: high

## 实测

来源：GitHub Actions run 36668437590，commit 16be7891a9f78babc8f0f58ae695a987e598573a。

| 场景 | 结果 | 耗时 | 输出 | 备注 |
|---|---|---:|---:|---|
| 短响应 | PASS | 1.719s | 2 汉字 | finish_reason=stop |
| 约 3000 字正文 | PASS | 88.362s | 3502 总字符 / 2826 汉字 | 达到 2800–3300 汉字目标区间；以“马二死了。”收尾 |
| 整章连续性审稿 | PASS | 571.610s | 2277 总字符 / 1661 汉字 | 对 3502 字符完整章节审稿，识别出 3 个 P0 和多项 P1/P2 |

## 关键观察

1. 之前把长写作放在 high/max 推理强度会大量消耗 reasoning token，导致正文输出预算被吃掉；写作改用 low 后，正文输出稳定。
2. 连续性审稿使用 high 能给出具体证据链问题，但延迟很高，本轮约 9.5 分钟。
3. GLM-5.3-Flash 更适合放回“深度连续性 / 剧情逻辑审稿”角色；若作为主写，需要接受约 1–2 分钟级单章生成延迟。
4. 原 benchmark 以 `endswith("马二死了。")` 判定章尾，模型输出中文闭引号时会误判；已修正为接受可选闭引号。

## 可用性结论

- API/鉴权：可用
- 流式输出：可用
- 3000 字级正文：可用
- 整章连续性审稿：可用
- 生产定位：优先作为深度连续性 Reviewer；可作为写作备用，不建议替代 AGNES 的低延迟主写位置
