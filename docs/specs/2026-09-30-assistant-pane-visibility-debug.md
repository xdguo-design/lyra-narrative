## 调试记录：窄屏下模型、人物和 AI 输出不可见

### 1) 问题陈述

- **期望行为：** 工作台窄窗口中仍可打开模型配置、人物管理和 AI 输出。
- **实际行为：** Codex 内置浏览器宽 860px 时，右侧助手面板完全消失；输出区域也可能只露出一部分。
- **错误信息/日志：** 无 JavaScript 错误；样式计算结果为 `.assistant { display: none }`。
- **是否可稳定复现：** 是，视口宽度处于 721–980px 时稳定复现。
- **最近改动：** 之前的窄屏断点设置；与共享表单改动无关。

### 2) 假设清单

1. **断点隐藏助手（高）：** 721–980px 的媒体查询显式设置 `.assistant { display: none }`，窄手机断点又重新显示它。
2. **三栏最小宽度溢出（中）：** 981–1180px 的固定最小栏宽总和大于视口，导致标签被横向裁切。
3. **对话框样式污染主布局（低）：** 新增弹窗 CSS 改变了助手显示状态。

**验证优先级：** 先读 `.assistant` 的 computed style 和边界尺寸，因为页面已稳定显示 860px 宽。

### 3) 最小复现

- **最小触发路径：** 以 860×764 打开工作台。
- **复现命令：** `python -m pytest tests/test_browser.py::test_assistant_tools_remain_accessible_at_tablet_width -q`
- **预期失败表现：** `.assistant` 预期可见，旧样式实际隐藏。

### 4) 定位过程（证据链）

- 观察 1：视口为 860×764，助手的计算样式为 `display:none`，边界宽高均为 0。
- 实验 1：新增 860px 浏览器回归 → 失败，报 `.assistant` 实际 hidden。
- 观察 2：981–1180px 原三栏最小宽度为 244+500+320=1064px；860px 标签问题是面板隐藏，而较宽窗口还存在横向溢出。
- 观察 3：解除隐藏后，AI 输出框底部坐标为 829px，视口高度为 764px，输出框只显示一部分。
- 实验 2：断点改为自适应三栏、标签改为四列网格后，面板及模型/人物入口可见且横向溢出为 0。
- 实验 3：新增生成后输出框边界断言 → 自动滚动前失败（底部 829px）。
- **收敛结论：** 样式根因位于 `app/static/styles.css:1147`；输出视口问题由 AI 生成后没有定位结果框导致，见 `app/static/app.js:863`。

### 5) 修复方案对比

- **方案 A：** 在 721–980px 隐藏其他栏并加助手开关；优点是内容单栏，缺点是增加额外交互且编辑时离开正文。
- **方案 B：** 维持三栏并压缩列宽、将助手标签换行；优点是配置、人物和输出持续可见，用户无需切换页面模式。
- **推荐：** 采用方案 B；生成后自动滚动到结果框。

### 6) 修复与验证

- **修复点：** `app/static/styles.css:1128` 用比例列宽替代固定最小宽度；`app/static/styles.css:1147` 在平板断点保持助手可见并排列多行标签。`app/static/app.js:863` 生成成功后滚动到 AI 输出。
- **验证命令：**
  - `python -m pytest tests/test_browser.py::test_assistant_tools_remain_accessible_at_tablet_width -q` → `1 passed`。
  - `python -m pytest -q` → `168 passed, 1 warning`。
  - `ruff check app tests` → `All checks passed!`。
  - `python -m compileall -q app tests`、`node --check app/static/app.js`、原生弹窗残留扫描 → 通过/无匹配。
- **回归测试：** 新增 860×764 用例，检查助手可见、页面与标签无横向溢出、运行续写后输出框完整处于视口，并可进入模型与人物面板。
