# Browser-compatible forms and confirmations 实施计划

> **给代理执行者：** 在本会话内逐任务执行并在每个任务后验证。任务使用 `- [x]` 勾选跟踪。

**目标：** 移除工作台所有原生 `prompt()` / `confirm()` / `alert()` 调用，用统一、可访问且能在 Codex 内置浏览器运行的表单、确认和说明对话框替代。

**架构要点：** `index.html` 提供共享 `<dialog>` 容器，`styles.css` 提供一致的表单、错误和焦点样式，`app.js` 提供 Promise 表单/确认/说明助手。各业务函数只声明字段和提交后的 API 调用，API 与工作流语义不变。

**技术栈：** FastAPI 静态页面、原生 JavaScript/CSS、Playwright；验证命令：`node --check app/static/app.js`、`python -m pytest tests/test_browser.py -q`、`python -m pytest -q`。

**关联设计文档：** `docs/specs/2026-09-30-browser-compatible-dialogs-design.md`

---

## 文件结构

- 修改 `app/static/index.html`：加入共享表单和确认 `<dialog>` 容器。
- 修改 `app/static/styles.css`：加入字段布局、错误提示、长文本框、Skill 多选和窄屏样式。
- 修改 `app/static/app.js`：加入 `requestForm` / `requestConfirm` / `requestNotice` 助手，并迁移所有原生弹窗调用。
- 修改 `tests/test_browser.py`：添加浏览器端交互回归，覆盖写作主流程和其他表单/确认类型。

## 任务 1：共享对话框和写作主流程

**涉及文件：** 上述 `index.html`、`styles.css`、`app.js`、`tests/test_browser.py`。

- [x] **步骤 1：先添加失败的浏览器回归。** 在 `tests/test_browser.py` 增加 E2E：点击“新建作品”后检查可访问名称为“新建作品”的 dialog；填写作品名称、类型和简介并提交；新建章节；编辑并保存正文；创建任务、运行 Demo pipeline、审批并验证正文与版本历史更新。为旧实现注册 Playwright 原生 dialog 自动取消处理，确保旧 `prompt()` 不会卡住测试。

- [x] **步骤 2：运行测试确认失败。** 运行 `python -m pytest tests/test_browser.py -q`。预期新用例失败：新建作品后没有应用内 dialog，触发的是浏览器原生 prompt。

- [x] **步骤 3：实现共享 dialog。** 在 `index.html` 添加一个 `<dialog>`，含标题、描述、动态字段区域、错误区域、取消和提交按钮；在 `app.js` 实现 `requestForm({ title, description, fields, submitLabel })` 与 `requestConfirm({ title, description, confirmLabel, danger })`。函数解析为字段值对象，用户取消或按 Escape 时返回 `null`。字段通过 DOM API 创建并关联 `<label>` 与错误节点；验证失败时阻止关闭并聚焦第一个无效字段。关闭后将焦点交还调用按钮。在 `styles.css` 沿用现有 `.dialog` 主题样式，增加可滚动表单区与窄屏布局。

- [x] **步骤 4：迁移写作主流程。** 将项目创建、章节创建、写作任务创建、任务批准/退回、项目/章节删除改用共享助手。项目/任务字段合并到单个表单；Skill 用已启用项的复选框列表；退回理由必填；批准备注可选；取消不提交。审批、删除和 AI 正文替换前的确认都使用 `requestConfirm`。

- [x] **步骤 5：再次运行指定用例。** 运行 `python -m pytest tests/test_browser.py -q`。预期写作 E2E 通过、`/api/chapters/{id}` 返回已批准正文且版本数增加；新建/审批过程中没有页面错误。

## 任务 2：迁移记忆、技能、人物、世界观和内容库

**涉及文件：** `app/static/app.js`、`app/static/styles.css`、`tests/test_browser.py`。

- [x] **步骤 1：添加失败回归。** 增加 Playwright 用例，打开并提交记忆表单、技能表单、人物表单、世界观表单与内容库绑定表单；验证标签、默认值、必填校验、多选技能、可选记忆确认复选框和取消返回焦点。创建一条临时 Provider，验证取消删除后仍存在，确认删除后消失。

- [x] **步骤 2：运行测试确认失败。** 运行 `python -m pytest tests/test_browser.py -q`。预期相关表单未出现应用内 dialog。

- [x] **步骤 3：迁移表单操作。** 将记忆创建、技能创建/发布新版本、人物创建、世界观创建、内容库绑定改用 `requestForm`；将 Provider 删除改用 `requestConfirm`。保持已有字段默认值和 API payload 不变；取消任何表单均不发请求。

- [x] **步骤 4：验证指定回归。** 运行 `python -m pytest tests/test_browser.py -q`。预期 CRUD 表单行为通过；临时 Provider 在取消后存在、确认后消失。

## 任务 3：迁移版本选择和剩余确认

**涉及文件：** `app/static/app.js`、`tests/test_browser.py`。

- [x] **步骤 1：添加失败回归。** 增加用例覆盖章节版本恢复、记忆版本恢复、Skill 版本恢复、AI 结果替换确认与取消；取消时数据不变，确认替换时正文变为预览结果且版本数增加。

- [x] **步骤 2：运行测试确认失败。** 运行 `python -m pytest tests/test_browser.py -q`。预期旧实现仍会触发至少一个原生 prompt/confirm。

- [x] **步骤 3：迁移余下操作。** 三种历史恢复通过下拉控件选择版本；恢复和 AI 结果替换通过 `requestConfirm` 确认。明确取消结果为不执行 API 写操作。

- [x] **步骤 4：验证剩余操作。** 运行 `python -m pytest tests/test_browser.py -q`；预期取消时数据无变化，确认时恢复/替换成功。

## 任务 4：可访问性、残留扫描和全量验证

**涉及文件：** `app/static/app.js`、`app/static/index.html`、`app/static/styles.css`、`tests/test_browser.py`。

- [x] **步骤 1：验证键盘和语义。** 在 E2E 检查 dialog 名称/描述、字段可按 label 定位、必填错误与字段关联、首个控件获得焦点、Escape 取消后焦点回到按钮，以及无效提交会聚焦第一个错误字段。

- [x] **步骤 2：扫描原生调用残留。** 运行 `rg -n '\b(prompt|confirm|alert)\s*\(' app/static`。预期没有匹配。

- [x] **步骤 3：运行检查。** 运行 `node --check app/static/app.js`、`python -m compileall -q app tests`、`ruff check app tests` 和 `python -m pytest -q`。预期命令全部退出码为 0。

- [x] **步骤 4：用 Codex 内置浏览器做最终流程验收。** 启动 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`，从空白测试数据库创建作品和章节，完成编辑、Demo 续写、任务运行与批准，确认 UI 显示已保存且刷新后正文和版本仍存在；检查浏览器 console 无异常。

## 后续修复：窄屏创作辅助面板不可见

- [x] 在 860×764 视口复现助手面板被隐藏，并新增浏览器回归用例。
- [x] 让 721–980px 保持三栏自适应；在窄面板中把助手标签排为多行网格，消除页面和标签横向溢出。
- [x] Demo/AI 生成后把结果框滚入当前可见区域。
- [x] 验证模型设置、人物管理、AI 结果均可到达；全量测试 168 项通过，页面控制台无错误。
