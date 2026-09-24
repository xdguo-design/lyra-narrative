# NarrativeOS 全链路验收：零点站台

日期：2026-09-23

## 验收作品

为避免污染《慢速世界》正式创作内容，本轮按产品负责人要求新建独立验收小说《零点站台》，内容保存在 `xdguo-design/slow-world-novel/novels/zero-platform/`。

作品包含：

- 项目说明
- 世界观
- 人物：林桥
- 第一卷章纲
- 第一章《七年前停运的站》

## 验收链路

自动化验收使用与《零点站台》相同的数据结构，在隔离的临时 content repository checkout 中执行：

1. 创建 NarrativeOS 项目和第一章初稿。
2. 绑定 `zero-platform` slug。
3. Content repository preflight。
4. 导入 project / world / character / outline 到 Memory。
5. 导入 writing-style 到 Skill。
6. 创建 WritingTask，并冻结指定 Skill v1。
7. Writer 基于完整原章续写。
8. Continuity Reviewer。
9. Plot Reviewer。
10. Style Reviewer。
11. Revision Agent。
12. 确认人工审批前原正文未变化。
13. 人工批准。
14. 生成正式章节版本。
15. 归档 `chapters / reviews / versions`。
16. 恢复到审批前版本。
17. 再恢复到审批版本。
18. 删除归档文件后执行 content-sync 重试。
19. 确认三类归档文件被重新创建。
20. 重启应用，确认任务仍为 approved、章节正文仍为最终内容。

## 本轮发现并修复的 P0 问题

完整正文验收发现 Writer 使用 `continue` 时返回的是“新增续写段”，而工作流曾把该段直接当作整章 draft。

后果：人工批准后可能用续写段覆盖原章节。

修复后：

- 原章节正文始终保留；
- Writer 续写只追加到现有正文；
- Reviewer 和 Revision 接收完整章节草稿；
- 自动化测试明确断言原正文必须仍存在于 draft 和 revised content 中。

## 内容库能力补齐

《零点站台》还暴露了旧导入器只读取 world/project 与 shared writing-style 的问题。

本轮扩展后可读取：

- project README → project Memory
- `bible/**/*.md` → world Memory
- `characters/**/*.md` → character Memory
- `outline/**/*.md` → outline Memory
- `shared/writing-style/**/*.md` → Skill

导入仍保持幂等；源文件变化才产生新的 Memory / Skill 版本。

## CI 结果

GitHub Actions Run #72：

- Python compileall：通过
- Ruff：通过
- JavaScript syntax：通过
- Chromium Playwright：通过
- pytest：**18 passed / 0 failed**
- 第三方依赖 warning：1 条，不影响功能

## 结论

NarrativeOS 的迁移、旧数据兼容、核心创作工作流、Memory、Skill、内容库读写、恢复/重同步、桌面与移动浏览器验收均已达到当前本地优先单人创作 MVP 的合并标准。

`aitest` 已完成源代码漂移核对，不再承担新功能来源职责。

本轮自动化验收使用隔离临时 checkout，避免测试过程直接污染 Git 内容仓库；真实《零点站台》内容已经单独存放在 `slow-world-novel`，与平台代码保持隔离。
