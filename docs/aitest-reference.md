# Novel Workbench

> 一个面向长篇小说创作的本地优先 AI 写作工作台。  
> 重点不是“让 AI 一键生成整本小说”，而是把 **作品、章节、正文、版本、人物、世界观、AI 辅助** 放在同一个可持续写作环境里。

![CI](https://github.com/xdguo-design/aitest/actions/workflows/ci.yml/badge.svg)

## 1. 项目定位

Novel Workbench 适合需要长期维护一部长篇作品的人使用。

它解决的核心问题不是单次生成，而是：

- 一部长篇小说有几十到几百章，正文必须能稳定保存；
- 人物、地点、规则、时间线会越来越多，需要持续维护；
- AI 可以辅助续写、润色和检查，但不能替代作品本身的数据管理；
- 模型供应商可能变化，因此 AI 层不能写死到某一家；
- 本地写作必须在没有 API Key 的情况下仍然可用。

当前项目采用 **FastAPI + SQLite + 原生 HTML/CSS/JavaScript**，没有 Node.js 构建依赖，下载后即可本地启动。

---

## 2. 当前能力

### 作品管理

- 新建多部小说；
- 在工作台中快速切换作品；
- 显示类型、章节数、总字符数；
- 删除不再需要的作品；
- 首次启动自动生成一部示例小说《雾城档案》，方便直接体验。

### 章节管理

- 新建章节；
- 章节列表快速切换；
- 章节搜索；
- 删除章节；
- 自动保存章节标题与正文；
- 显示当前章节字符数；
- 显示最后更新时间；
- 支持 Ctrl / Cmd + S 主动保存。

### 正文编辑

- 纸张式沉浸编辑区；
- 自动保存；
- 当前章节字数实时统计；
- 专注写作模式；
- 工作台三栏布局：
  - 左：作品与章节；
  - 中：正文；
  - 右：AI / 人物 / 世界观。

### 版本历史

正文发生变化时自动生成历史版本。

可用于：

- 找回误删内容；
- 比较修改前后；
- 恢复某次旧版本；
- 保留写作过程中的阶段性结果。

当前最多读取最近 50 个版本。

### 人物卡

每个作品可独立维护人物：

- 姓名；
- 角色定位；
- 简介；
- 标签。

人物卡与作品绑定，不会跨作品混用。

### 世界观

支持记录：

- 地点；
- 势力；
- 组织；
- 规则；
- 道具；
- 能力体系；
- 历史事件；
- 其他设定。

### AI 助手

当前内置三类操作：

1. **续写**：根据当前正文延续内容；
2. **润色**：在不改变核心事实的情况下改善表达；
3. **一致性检查**：检查人物、时间线、地点、道具和因果冲突。

AI 结果先进入右侧结果区，不会自动覆盖正文。

用户可以明确选择：

- 追加到正文；
- 替换正文；
- 仅查看检查结果。

这样可以避免模型输出直接破坏原稿。

---

## 3. 工作台页面

启动后访问：

```text
http://127.0.0.1:8000
```

工作台结构：

```text
┌──────────────────────────────────────────────────────────────────────┐
│ Novel Workbench       当前作品 / 保存状态 / 专注模式 / 新建作品     │
├──────────────────┬──────────────────────────────┬────────────────────┤
│                  │                              │                    │
│ 作品信息         │ 章节标题                     │ AI 助手            │
│ 章节统计         │                              │ 人物卡             │
│ 章节搜索         │        正文编辑器            │ 世界观             │
│                  │                              │                    │
│ 章节列表         │                              │ AI 输出结果        │
│                  │                              │                    │
├──────────────────┴──────────────────────────────┴────────────────────┤
│ 快捷键 / 字符数 / 更新时间                                          │
└──────────────────────────────────────────────────────────────────────┘
```

### 左侧：作品与章节

左侧负责结构管理，不放正文。

包含：

- 当前作品选择；
- 作品类型；
- 章节数量；
- 总字符数；
- 作品简介；
- 章节搜索；
- 新建章节；
- 删除当前作品；
- 章节列表。

### 中间：写作区

中间只关注正文。

包含：

- 当前章节标题；
- 当前章节字符数；
- 版本历史；
- 删除章节；
- 正文编辑器；
- 自动保存状态；
- 最后更新时间；
- 专注模式。

### 右侧：创作辅助区

右侧分为三个 Tab：

#### AI 助手

- 续写；
- 润色；
- 一致性检查；
- 自定义补充要求；
- Provider / Model 状态；
- AI 输出预览；
- 追加或替换正文。

#### 人物

- 人物卡列表；
- 人物身份；
- 简介；
- 标签；
- 新建人物。

#### 世界观

- 分类；
- 标题；
- 设定正文；
- 新建设定。

---

## 4. 技术架构

```text
Browser
  │
  ├─ app/static/index.html
  ├─ app/static/styles.css
  └─ app/static/app.js
  │
  ▼
FastAPI
  │
  ├─ REST API
  ├─ Static Files
  ├─ AI Assist Service
  └─ SQLite Persistence
  │
  ├───────────────┐
  ▼               ▼
SQLite         AI Provider Layer
                  │
                  ├─ Gemini Native
                  ├─ Anthropic Native
                  ├─ OpenAI Compatible
                  ├─ DeepSeek
                  ├─ Ollama
                  ├─ vLLM
                  └─ freellm-gateway
```

### 为什么当前不使用前端构建框架

这一阶段目标是让仓库：

- clone 后能直接运行；
- 不要求 Node.js；
- 不要求 npm install；
- 不引入前后端两个开发服务；
- 方便快速验证小说工作流。

后续如果需要复杂组件系统、协作编辑、富文本节点、拖拽大纲等能力，可以再迁移到 React / Next.js，而 API 和数据库层可以继续复用。

---

## 5. 项目目录

```text
aitest/
├─ app/
│  ├─ __init__.py
│  ├─ main.py                 # FastAPI 入口、REST API
│  ├─ db.py                   # SQLite schema、连接、演示数据
│  │
│  ├─ ai/
│  │  └─ providers/           # 可插拔模型 Provider
│  │
│  ├─ services/
│  │  └─ ai_service.py        # 小说 AI 辅助业务逻辑
│  │
│  └─ static/
│     ├─ index.html           # 工作台页面结构
│     ├─ styles.css           # 工作台视觉与响应式布局
│     └─ app.js               # 页面交互、API 调用、自动保存
│
├─ data/                      # 本地 SQLite 数据目录
├─ docs/
│  ├─ ARCHITECTURE.md
│  └─ PROVIDERS.md
├─ tests/
│  ├─ test_api.py
│  └─ test_provider_registry.py
├─ .github/workflows/ci.yml
├─ .env.example
├─ pytest.ini
├─ requirements.txt
├─ requirements-dev.txt
├─ Makefile
└─ README.md
```

---

## 6. 环境要求

推荐：

- Python 3.11+
- Git
- Windows 10/11、macOS 或 Linux

不需要：

- Node.js
- npm
- Docker
- PostgreSQL
- Redis
- API Key（只使用写作功能时）

---

## 7. 本地安装

### 7.1 克隆项目

```bash
git clone https://github.com/xdguo-design/aitest.git
cd aitest
```

### 7.2 创建虚拟环境

```bash
python -m venv .venv
```

### Windows PowerShell

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

### macOS / Linux

```bash
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

启动后打开：

- 工作台：`http://127.0.0.1:8000`
- OpenAPI / Swagger：`http://127.0.0.1:8000/docs`
- Health：`http://127.0.0.1:8000/api/health`

---

## 8. 数据存储

默认数据库：

```text
data/novel_workbench.db
```

SQLite 会在首次启动时自动创建。

默认情况下，空数据库会自动写入示例小说：

```text
《雾城档案》
├─ 第一章 雨夜来客
├─ 第二章 消失的门牌
└─ 第三章 黑伞
```

同时会生成：

- 示例人物；
- 示例世界观；
- 初始章节版本。

### 禁用演示数据

在 `.env` 中：

```env
NOVEL_SEED_DEMO=0
```

### 修改数据库位置

```env
NOVEL_DB_PATH=D:/NovelData/novel.db
```

或 macOS/Linux：

```env
NOVEL_DB_PATH=/home/user/novel-data/novel.db
```

---

## 9. AI Provider 配置

不配置 AI 时，工作台仍然完整可用。

默认：

```env
NOVEL_AI_KIND=demo
```

这时 AI 按钮会返回明确标记的演示结果，用于验证页面流程。

### 9.1 配置方式

复制：

```bash
cp .env.example .env
```

Windows 也可以手动复制：

```powershell
Copy-Item .env.example .env
```

### 9.2 freellm-gateway 示例

```env
NOVEL_AI_KIND=freellm-gateway
NOVEL_AI_MODEL=your-model-alias
NOVEL_AI_BASE_URL=http://127.0.0.1:3000/v1
NOVEL_AI_API_KEY_ENV=FREELLM_GATEWAY_API_KEY
```

真实 Key 放在系统环境变量：

```powershell
$env:FREELLM_GATEWAY_API_KEY="your-key"
```

### 9.3 OpenAI-compatible 示例

```env
NOVEL_AI_KIND=openai-compatible
NOVEL_AI_MODEL=your-model
NOVEL_AI_BASE_URL=https://your-endpoint.example/v1
NOVEL_AI_API_KEY_ENV=MODEL_API_KEY
```

### 安全原则

仓库只保存：

- Provider 类型；
- Model 名称；
- Base URL；
- API Key 的环境变量名称。

不会把真实 Key 存进 SQLite，也不应该提交到 Git。

---

## 10. 数据模型

当前 SQLite 包含五类核心数据。

### projects

作品。

主要字段：

- title
- description
- genre
- status
- created_at
- updated_at

### chapters

章节正文。

主要字段：

- project_id
- title
- position
- content
- status
- created_at
- updated_at

### chapter_versions

章节历史版本。

主要字段：

- chapter_id
- content
- note
- created_at

### characters

人物。

主要字段：

- project_id
- name
- role
- profile
- tags

### world_notes

世界观。

主要字段：

- project_id
- category
- title
- content

---

## 11. API 概览

### 系统

```text
GET /api/health
```

### 作品

```text
GET    /api/projects
POST   /api/projects
DELETE /api/projects/{project_id}
```

### 章节

```text
GET    /api/projects/{project_id}/chapters
POST   /api/projects/{project_id}/chapters
GET    /api/chapters/{chapter_id}
PATCH  /api/chapters/{chapter_id}
DELETE /api/chapters/{chapter_id}
```

### 版本

```text
GET  /api/chapters/{chapter_id}/versions
POST /api/chapters/{chapter_id}/versions/{version_id}/restore
```

### 人物

```text
GET  /api/projects/{project_id}/characters
POST /api/projects/{project_id}/characters
```

### 世界观

```text
GET  /api/projects/{project_id}/world
POST /api/projects/{project_id}/world
```

### AI

```text
POST /api/ai/assist
```

请求示例：

```json
{
  "mode": "continue",
  "content": "当前章节正文",
  "instruction": "保持第三人称，不增加新人物"
}
```

---

## 12. 自动保存策略

当前页面采用防抖自动保存：

```text
用户输入
   │
   ▼
等待约 850ms
   │
   ├─ 用户继续输入 → 重新计时
   │
   └─ 用户停止输入 → PATCH chapter
                         │
                         ├─ 更新正文
                         └─ 正文变化时新增 version
```

因此不会每敲一个字就创建数据库版本。

---

## 13. 快捷键

| 快捷键 | 功能 |
|---|---|
| Ctrl + S | Windows / Linux 主动保存 |
| Cmd + S | macOS 主动保存 |
| 专注模式按钮 | 隐藏左右栏，只保留正文 |

---

## 14. 开发与测试

安装开发依赖：

```bash
pip install -r requirements-dev.txt
```

运行测试：

```bash
pytest -q
```

运行 lint：

```bash
ruff check app tests
```

完整检查：

```bash
make check
```

GitHub Actions 在以下场景自动运行：

- push 到 `main`
- Pull Request

CI 当前检查：

1. 安装 Python；
2. 安装依赖；
3. Python compileall；
4. Ruff；
5. Node.js 静态语法检查 `app/static/app.js`；
6. Pytest。

---

## 15. 常见问题

### Q1：为什么第一次打开已经有小说？

这是演示数据，用于验证工作台。

设置：

```env
NOVEL_SEED_DEMO=0
```

并删除已有数据库后，即可空库启动。

### Q2：AI 按钮为什么提示演示模式？

因为还没有配置真实 Provider。

编辑 `.env`：

```env
NOVEL_AI_KIND=...
NOVEL_AI_MODEL=...
```

### Q3：不使用 AI 能不能正常写小说？

可以。

作品、章节、版本、人物、世界观都不依赖 AI。

### Q4：正文存在哪里？

默认：

```text
data/novel_workbench.db
```

### Q5：可以备份吗？

可以直接备份 SQLite 文件。

推荐在关闭程序后复制：

```text
data/novel_workbench.db
```

### Q6：会不会把我的正文发送给模型？

只有用户点击 AI 操作时，当前实现才会调用已配置的 Provider。

普通编辑与保存只写本地 SQLite。

---

## 16. 当前边界

当前版本已经可用于单机小说创作，但还没有实现：

- 登录与多用户；
- 云同步；
- 多设备同步；
- 实时协作；
- 拖拽调整章节顺序；
- 人物关系图；
- 时间线图；
- 大纲卡片；
- RAG / 向量检索；
- 全书一致性批量扫描；
- AI 任务队列；
- 富文本编辑器；
- EPUB / DOCX 导出。

这些属于后续演进能力，不影响当前本地工作台使用。

---

## 17. 推荐后续路线

### v1.5

- 大纲管理；
- 章节拖拽排序；
- 人物编辑 / 删除；
- 世界观编辑 / 删除；
- Markdown / TXT 导入导出；
- 写作目标与每日字数。

### v1.6

- 长篇上下文检索；
- 人物关系；
- 时间线；
- 冲突扫描；
- 章节摘要自动维护。

### v2

- PostgreSQL；
- 登录与多用户；
- 云同步；
- 任务队列；
- 协作；
- 全书知识库；
- 多 Agent 创作流程。

---

## 18. License / 使用说明

当前仓库为项目开发仓库。正式对外发布前建议补充明确的 LICENSE、隐私说明和 AI Provider 数据处理说明。

