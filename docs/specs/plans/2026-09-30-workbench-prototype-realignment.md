# NarrativeOS 原型工作台重整实施计划

> **给代理执行者：** 任务使用 `- [ ]` 勾选跟踪；本会话按顺序执行，并遵循 `tdd-master` 的 RED→GREEN→REFACTOR 节奏。

**目标：** 将工作台默认界面重整为原型中的全局导航、中央真实任务流视图和章节上下文布局，同时保留现有写作、模型、人物、Skill 与审批能力。

**非目标（Out of Scope）：** 新增场景规划、专项编辑、评审角色 DAG 阶段；修改任务、Provider 或人物 API/schema；补充人物卡编辑/删除 API；把 AI 结果或未审批修订自动写入正文。

**架构要点：** 页面以单页工作区状态在任务流、AI 编辑、评审、角色知识库、资料/设定、模型与技能、设置之间切换。工作流视图只从已有项目任务列表和任务详情/run 记录构造节点与连线，节点选择进入现有详情和审批流程。现有编辑器仍负责章节正文保存，AI 输出保留可见预览及明确的追加/替换操作；不增加服务器端页面路由或数据库迁移。

**技术栈/运行方式：** FastAPI 静态页面、原生 JavaScript/CSS、Playwright 浏览器测试。验证命令：`python -m pytest tests/test_browser.py -q`、`python -m pytest -q`、`node --check app/static/app.js`、`ruff check app tests`。服务命令：`python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`。

**关联设计文档：** `docs/specs/2026-09-30-workbench-prototype-realignment-design.md`（用户已批准）。

---

## 文件变更清单

- 修改：
  - `tests/test_browser.py`：增加默认任务流/全局导航断言，调整依赖旧标签布局的测试，并覆盖模型、人物与 AI 输出在新工作区中的可见路径。
  - `app/static/index.html`：将固定三栏骨架改为左侧全局工作区导航、中央工作区容器、右侧章节上下文容器；保留既有表单、确认、任务详情和历史对话框。
  - `app/static/app.js`：实现工作区选择、任务/Agent Run DAG 渲染和节点详情打开；把现有编辑、模型、人物、Skills 等区块接入工作区导航；确保 AI 结果可见并保留原有追加/替换及自动保存行为。
  - `app/static/styles.css`：实现桌面三栏原型布局、节点/图例/章节信息样式，以及平板、手机的导航收纳与工作区自适应。
- 不改：
  - `app/main.py`、`app/services/workflow_service.py`、数据库 schema：复用已有 API 和真实 Agent Run 数据。

## 行为清单

- [ ] 首次加载默认进入任务流工作区，显示全局导航、中央任务流和当前章节上下文。
- [ ] 有真实任务时，每个任务可选择查看详情；详情/run 的真实状态、角色、阶段、模型、错误与待审批操作可达。
- [ ] 无任务时显示明确空状态和新建任务操作，不生成假 DAG 节点。
- [ ] 从全局导航能进入 AI 编辑、角色知识库、模型配置与 Skill 等当前已实现功能。
- [ ] AI 生成后输出完整可见，原稿不自动变化；追加和替换仍按原操作执行。
- [ ] 桌面、平板、390px 手机宽度均没有横向页面溢出；移动端可展开工作区导航。
- [ ] 原有正文自动保存、Provider CRUD/默认选择、人物卡创建、任务审批和历史流程保持通过。

## 任务 1：先锁定原型主工作区和全局导航行为

**涉及文件：**
- 修改：`tests/test_browser.py`
- 修改：`app/static/index.html`
- 修改：`app/static/app.js`
- 修改：`app/static/styles.css`

- [ ] **步骤 1：编写一个端到端失败测试**

在 `tests/test_browser.py` 增加：

```python
def test_workbench_opens_task_flow_with_global_navigation(live_server: str) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 960})
        page.goto(live_server, wait_until="networkidle")

        expect(page.locator("body")).to_have_attribute("data-workspace", "workflow")
        expect(page.get_by_role("navigation", name="工作区导航")).to_be_visible()
        expect(page.locator("#workflowBoard")).to_be_visible()
        expect(page.locator("#chapterContext")).to_be_visible()
        expect(page.get_by_role("button", name="模型与技能")).to_be_visible()

        page.get_by_role("button", name="模型与技能").click()
        expect(page.locator("#providerList")).to_be_visible()
        expect(page.get_by_role("button", name="角色知识库")).to_be_visible()
        page.get_by_role("button", name="角色知识库").click()
        expect(page.locator("#characterList")).to_be_visible()

        browser.close()
```

- [ ] **步骤 2：运行并确认因新工作区尚不存在而失败**
  - 运行：`python -m pytest tests/test_browser.py::test_workbench_opens_task_flow_with_global_navigation -q`
  - 预期：断言 `body[data-workspace="workflow"]` 失败；测试服务应正常启动且不能因 import、fixture 或浏览器错误失败。

- [ ] **步骤 3：最小实现工作区骨架和导航状态**
  - 在 `index.html` 提供具有 `aria-label="工作区导航"` 的 `<nav>`、`#workflowBoard`、`#chapterContext` 和导航按钮。
  - 在 `app.js` 通过 `data-workspace` 设置当前工作区；点击导航时只显示对应工作区，并调用现有对应数据加载函数。
  - 在 `styles.css` 以 `minmax(0, 1fr)` 构建左导航/中工作区/右上下文三列；添加选中态及窄屏导航收纳规则。
  - 保留现有 `#editor`、`#providerList`、`#characterList`、表单和对话框 DOM id，避免破坏已有事件绑定和回归测试。

- [ ] **步骤 4：运行目标浏览器测试确认通过**
  - 运行：`python -m pytest tests/test_browser.py::test_workbench_opens_task_flow_with_global_navigation -q`
  - 预期：`1 passed`。

## 任务 2：用现有任务和 Agent Run 构造真实 DAG

**涉及文件：**
- 修改：`tests/test_browser.py`
- 修改：`app/static/index.html`
- 修改：`app/static/app.js`
- 修改：`app/static/styles.css`

- [ ] **步骤 1：编写真实任务节点行为测试**

扩展一个独立浏览器测试：先通过页面创建写作任务、运行 Demo 工作流，再检查任务与真实 Run 节点，选择任务节点后详情对话框可见。

```python
def test_task_flow_renders_persisted_task_and_run_nodes(live_server: str) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 960})
        page.goto(live_server, wait_until="networkidle")
        page.locator("#newTaskBtn").click()
        dialog = page.get_by_role("dialog", name="新建写作任务")
        dialog.get_by_label("任务目标").fill("浏览器原型回归写作任务")
        dialog.get_by_role("button", name="创建任务").click()
        task = page.locator("[data-task-node]").filter(has_text="浏览器原型回归写作任务")
        expect(task).to_be_visible()
        task.get_by_role("button", name="运行").click()
        expect(page.locator("[data-run-node]").first).to_be_visible(timeout=15000)
        expect(page.locator("#workflowLegend")).to_be_visible()
        task.get_by_role("button", name="详情").click()
        expect(page.locator("#taskDialog")).to_be_visible()
        browser.close()
```

- [ ] **步骤 2：确认测试在未实现节点映射时失败**
  - 运行：`python -m pytest tests/test_browser.py::test_task_flow_renders_persisted_task_and_run_nodes -q`
  - 预期：失败在 `[data-task-node]` 不存在；FastAPI、Demo Provider 和浏览器均应正常。

- [ ] **步骤 3：读取已有 API 并绘制对应节点**
  - 从 `/api/projects/{project_id}/tasks` 读取任务节点；创建任务后刷新画布。
  - 点击任务“运行”沿用 `runWorkflowTask(task.id)`；点击“详情”沿用 `openTask(task.id)`。
  - 从 `/api/tasks/{task_id}` 的 `runs` 读取执行记录；将每条真实记录显示为 `data-run-node`，并以实际 role、stage、status、provider/model、duration/error 构造详情。轮询期间同步画布状态。
  - 对暂无任务和暂无 runs 的状态显示空态，不从原型截图补造 Planner、专项编辑或评审节点。
  - 使用 SVG 或语义 DOM 连线展示已知执行顺序；响应式超宽流程可水平滚动画布，不能扩宽整个页面。

- [ ] **步骤 4：运行目标测试确认真实数据映射通过**
  - 运行：`python -m pytest tests/test_browser.py::test_task_flow_renders_persisted_task_and_run_nodes -q`
  - 预期：`1 passed`，Demo 任务至少渲染一个真实 Run 节点，节点详情和图例均可见。

## 任务 3：打通 AI 输出、人物与模型工作区，完成响应式回归

**涉及文件：**
- 修改：`tests/test_browser.py`
- 修改：`app/static/index.html`
- 修改：`app/static/app.js`
- 修改：`app/static/styles.css`

- [ ] **步骤 1：先添加 AI 输出可见行为断言**
  - 在已有 AI 浏览器测试中从全局导航进入“AI 编辑”，生成 Demo 续写后断言结果容器可见、包含“演示续写”，并且“追加到正文末尾”和“用结果替换正文”按钮可见且可用。
  - 更新现有 `test_workbench_theme_autosave_and_mobile_navigation`、`test_assistant_tools_remain_accessible_at_tablet_width`、`test_memory_skill_character_world_and_repository_forms`、`test_provider_and_ai_replace_confirmations_are_cancellable` 中依赖旧 `[data-tab]` 的选择器为对应全局工作区导航选择器。

- [ ] **步骤 2：运行并确认 AI 编辑新入口断言失败**
  - 运行：`python -m pytest tests/test_browser.py::test_assistant_tools_remain_accessible_at_tablet_width -q`
  - 预期：失败于旧入口不可访问或新工作区可见行为缺失；服务和浏览器启动无异常。

- [ ] **步骤 3：接入现有功能并完成 UI 样式**
  - 将 AI 编辑、角色知识库、模型 Provider、Skills、Memory、世界设定与任务/评审工作区关联到左导航。
  - 将当前章节标题、状态、字数、已生成 AI 输出摘要/完整结果和追加/替换按钮渲染到右侧上下文区域；没有结果时显示可访问空态。
  - AI 编辑保留正文编辑器和历史版本；生成结果后滚动/聚焦到可见结果，并将结果操作同步到右侧卡片，避免在两个可编辑副本间造成状态分叉。
  - 人物工作区继续显示人物列表并通过现有 `createCharacter()` 创建；不添加编辑/删除按钮。
  - Provider 工作区继续使用原有 `loadProviders()`、表单及新增/编辑/默认/删除处理。
  - 更新键盘焦点、aria-current/aria-selected、移动端 nav 开关、主题、专注模式行为；旧 tab 容器不再作为唯一到达路径。

- [ ] **步骤 4：验证关键浏览器切片和整套回归**
  - 运行：`python -m pytest tests/test_browser.py -q`
  - 预期：浏览器测试全部通过；报告 `passed` 数量与本次实际执行一致。
  - 运行：`node --check app/static/app.js`
  - 预期：无输出，退出码 0。
  - 运行：`ruff check app tests`
  - 预期：`All checks passed!`
  - 运行：`python -m pytest -q`
  - 预期：全套通过，无失败。
  - 运行：`git diff --check`
  - 预期：无 whitespace error。

## 质量门控

- [ ] 每个行为先运行对应失败的浏览器测试，再写对应生产代码。
- [ ] 不改 `app/main.py`、数据库或 Provider/人物 API；如实现时发现现有 API 无法满足已批准交互，先更新规格并暂停代码。
- [ ] 运行测试使用临时 SQLite；不清理或改写已有 `data/`、`books/`、`.env` 内容。
- [ ] 代码改完后启动或复用 `127.0.0.1:8000` 服务，并通过浏览器实际完成章节写作与 AI 结果追加/替换检查。
- [ ] 提交前检查 `git status --short`，保留工作区已有且与本功能无关的变更；不擅自提交。
