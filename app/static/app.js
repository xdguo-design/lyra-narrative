const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const state = {
  projects: [],
  projectId: null,
  chapters: [],
  chapterId: null,
  chapter: null,
  characters: [],
  world: [],
  tasks: [],
  memories: [],
  skills: [],
  providers: [],
  editingProviderId: null,
  contentStatus: null,
  selectedTaskId: null,
  aiText: "",
  aiMode: null,
  saveTimer: null,
  taskPollTimer: null,
  taskPollBusy: false,
  search: "",
  workspaceContext: null,
};


const LYRA_BRIDGE_VERSION = "1.0";
const lyraBridgeParams = new URLSearchParams(window.location.search);
const lyraHubOrigin = (() => {
  if (lyraBridgeParams.get("lyraHub") !== "1") return null;
  const raw = lyraBridgeParams.get("lyraHubOrigin");
  if (!raw) return null;
  try {
    return new URL(raw).origin;
  } catch {
    return null;
  }
})();
const lyraPendingCapabilities = new Map();

function invokeLyraCapability(capability, payload = {}) {
  if (!lyraHubOrigin || window.parent === window) {
    return Promise.reject(new Error("Lyra Hub bridge is not available"));
  }

  const requestId =
    typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `lyra-${Date.now()}-${Math.random().toString(16).slice(2)}`;

  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      lyraPendingCapabilities.delete(requestId);
      reject(new Error("Lyra Hub capability request timed out"));
    }, 15000);

    lyraPendingCapabilities.set(requestId, { resolve, reject, timer });
    window.parent.postMessage(
      {
        type: "lyra.capability.invoke",
        version: LYRA_BRIDGE_VERSION,
        requestId,
        capability,
        payload,
      },
      lyraHubOrigin,
    );
  });
}

function initLyraHubBridge() {
  if (!lyraHubOrigin || window.parent === window) return;

  window.addEventListener("message", (event) => {
    if (event.source !== window.parent || event.origin !== lyraHubOrigin) return;
    const message = event.data || {};
    if (message.version !== LYRA_BRIDGE_VERSION) return;

    if (message.type === "lyra.workspace.init") {
      const context = message.context || {};
      if (context.appId !== "lyra-narrative") return;
      state.workspaceContext = context;
      document.documentElement.dataset.lyraMode = "workspace";
      if (typeof context.locale === "string" && context.locale) {
        document.documentElement.lang = context.locale;
      }
      applyTheme(context.theme === "dark" ? "space" : "paper");
      const badge = $("#hubContextBadge");
      if (badge) {
        badge.classList.remove("hidden");
        badge.textContent = "LYRA HUB";
        badge.title = context.identity?.authenticated
          ? "已连接 Lyra Hub 身份上下文"
          : "已连接 Lyra Hub；当前为匿名平台上下文";
      }
      return;
    }

    if (message.type === "lyra.capability.result" && message.requestId) {
      const pending = lyraPendingCapabilities.get(message.requestId);
      if (!pending) return;
      clearTimeout(pending.timer);
      lyraPendingCapabilities.delete(message.requestId);
      if (message.ok) pending.resolve(message.result);
      else pending.reject(new Error(message.error || "Lyra Hub capability failed"));
    }
  });

  window.lyraHub = {
    getContext: () => state.workspaceContext,
    invokeCapability: invokeLyraCapability,
  };

  window.parent.postMessage(
    {
      type: "lyra.app.ready",
      version: LYRA_BRIDGE_VERSION,
      appId: "lyra-narrative",
    },
    lyraHubOrigin,
  );
}

const THEME_KEY = "narrativeos-theme";
const THEMES = new Set(["ink", "space", "paper", "neo"]);

function applyTheme(theme) {
  const next = THEMES.has(theme) ? theme : "space";
  document.documentElement.dataset.theme = next;
  localStorage.setItem(THEME_KEY, next);
  const selector = $("#themeSelect");
  if (selector) selector.value = next;
}

function initTheme() {
  applyTheme(localStorage.getItem(THEME_KEY) || "space");
  const selector = $("#themeSelect");
  if (selector) {
    selector.addEventListener("change", (event) => applyTheme(event.target.value));
  }
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    let message = `请求失败 ${response.status}`;
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch {
      // Keep fallback message.
    }
    throw new Error(message);
  }

  return response.status === 204 ? null : response.json();
}

function toast(message) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.add("show");
  clearTimeout(element._timer);
  element._timer = setTimeout(() => element.classList.remove("show"), 1900);
}

function escapeHtml(value = "") {
  return String(value).replace(
    /[&<>'"]/g,
    (char) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        "'": "&#39;",
        '"': "&quot;",
      })[char],
  );
}

function countText(text) {
  return (text || "").replace(/\s/g, "").length;
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString("zh-CN");
}

function statusLabel(status) {
  const labels = {
    draft: "草稿",
    writing: "写作中",
    done: "完成",
    published: "已发布",
  };
  return labels[status] || status || "草稿";
}

function setSaving(saving) {
  const element = $("#saveState");
  element.innerHTML = `<span class="status-dot"></span>${saving ? "保存中…" : "已保存"}`;
  element.classList.toggle("saving", saving);
}

function currentProject() {
  return state.projects.find((project) => project.id === state.projectId) || null;
}

function clearWorkspace() {
  state.projectId = null;
  state.chapterId = null;
  state.chapter = null;
  state.chapters = [];
  state.characters = [];
  state.world = [];
  state.tasks = [];
  state.memories = [];
  state.skills = [];
  state.contentStatus = null;
  state.selectedTaskId = null;

  $("#currentProjectName").textContent = "暂无作品";
  $("#projectTitle").textContent = "暂无作品";
  $("#projectGenre").textContent = "未分类";
  $("#projectDescription").textContent = "点击右上角“新建作品”开始。";
  $("#statChapters").textContent = "0";
  $("#statChars").textContent = "0";
  $("#statProgress").textContent = "—";
  $("#chapterList").innerHTML = '<div class="no-results">还没有章节</div>';
  $("#chapterTitle").value = "";
  $("#editor").value = "";
  $("#chapterPosition").textContent = "—";
  $("#chapterStatus").textContent = "—";
  $("#chapterUpdated").textContent = "尚未保存";
  $("#characterList").innerHTML = '<div class="no-results">还没有人物卡</div>';
  $("#worldList").innerHTML = '<div class="no-results">还没有世界设定</div>';
  $("#characterCount").textContent = "0";
  $("#worldCount").textContent = "0";
  $("#taskCount").textContent = "0";
  $("#memoryCount").textContent = "0";
  $("#skillCount").textContent = "0";
  $("#taskList").innerHTML = '<div class="no-results">还没有创作任务</div>';
  $("#memoryList").innerHTML = '<div class="no-results">还没有作品记忆</div>';
  $("#skillList").innerHTML = '<div class="no-results">还没有技能</div>';
  $("#contentRepoStatus").textContent = "未绑定";
  updateStats();
}

function renderProjectSummary() {
  const project = currentProject();
  if (!project) {
    clearWorkspace();
    return;
  }

  $("#currentProjectName").textContent = project.title;
  $("#projectTitle").textContent = project.title;
  $("#projectGenre").textContent = project.genre || "未分类";
  $("#projectDescription").textContent = project.description || "暂无作品简介。";
  $("#statChapters").textContent = formatNumber(project.chapter_count);
  $("#statChars").textContent = formatNumber(project.char_count);
  $("#statProgress").textContent = statusLabel(project.status);
}

async function loadProjects(preferredId = null) {
  const previousId = state.projectId;
  state.projects = await api("/api/projects");

  const select = $("#projectSelect");
  select.innerHTML = "";

  for (const project of state.projects) {
    const option = document.createElement("option");
    option.value = project.id;
    option.textContent = project.title;
    select.appendChild(option);
  }

  if (!state.projects.length) {
    clearWorkspace();
    return;
  }

  const candidateId =
    preferredId ||
    (state.projects.some((project) => project.id === previousId) ? previousId : null) ||
    state.projects[0].id;

  state.projectId = Number(candidateId);
  select.value = String(state.projectId);
  await loadProject(state.projectId);
}

async function refreshProjectSummary() {
  const projects = await api("/api/projects");
  state.projects = projects;
  renderProjectSummary();

  const select = $("#projectSelect");
  const knownIds = [...select.options].map((option) => Number(option.value));
  if (
    projects.length !== knownIds.length ||
    projects.some((project) => !knownIds.includes(project.id))
  ) {
    const selected = state.projectId;
    select.innerHTML = "";
    for (const project of projects) {
      const option = document.createElement("option");
      option.value = project.id;
      option.textContent = project.title;
      select.appendChild(option);
    }
    if (selected) select.value = String(selected);
  }
}

async function loadProject(projectId) {
  await flushPendingSave();

  state.projectId = Number(projectId);
  state.chapterId = null;
  state.chapter = null;
  $("#projectSelect").value = String(state.projectId);

  renderProjectSummary();

  state.chapters = await api(`/api/projects/${state.projectId}/chapters`);
  renderChapters();

  await Promise.all([
    loadCharacters(),
    loadWorld(),
    loadTasks(),
    loadMemories(),
    loadSkills(),
    loadContentStatus(),
  ]);

  if (state.chapters.length) {
    await loadChapter(state.chapters[0].id);
  } else {
    clearChapterEditor();
  }
}

function renderChapters() {
  const container = $("#chapterList");
  const query = state.search.trim().toLowerCase();

  const filtered = state.chapters.filter((chapter) =>
    chapter.title.toLowerCase().includes(query),
  );

  container.innerHTML = "";

  if (!filtered.length) {
    container.innerHTML = `<div class="no-results">${query ? "没有匹配的章节" : "还没有章节"}</div>`;
    return;
  }

  for (const chapter of filtered) {
    const realIndex = state.chapters.findIndex((item) => item.id === chapter.id);
    const button = document.createElement("button");
    button.className =
      "chapter-item" + (chapter.id === state.chapterId ? " active" : "");
    button.innerHTML = `
      <span class="chapter-index">${String(realIndex + 1).padStart(2, "0")}</span>
      <span class="chapter-copy">
        <strong>${escapeHtml(chapter.title)}</strong>
        <small>${formatNumber(chapter.char_count)} 字符 · ${statusLabel(chapter.status)}</small>
      </span>
      <span class="chapter-arrow">›</span>
    `;
    button.onclick = () => loadChapter(chapter.id);
    container.appendChild(button);
  }
}

async function loadChapter(id) {
  const chapterId = Number(id);
  if (state.chapterId && state.chapterId !== chapterId) {
    await flushPendingSave();
  }

  state.chapterId = chapterId;
  state.chapter = await api(`/api/chapters/${chapterId}`);

  $("#chapterTitle").value = state.chapter.title;
  $("#editor").value = state.chapter.content || "";

  const position = state.chapters.findIndex((chapter) => chapter.id === chapterId);
  $("#chapterPosition").textContent =
    position >= 0 ? `第 ${position + 1} 章` : "当前章节";
  $("#chapterStatus").textContent = statusLabel(state.chapter.status);
  $("#chapterUpdated").textContent = state.chapter.updated_at
    ? `最后保存：${state.chapter.updated_at}`
    : "尚未保存";

  updateStats();
  renderChapters();
  setSaving(false);
  if (window.matchMedia("(max-width: 720px)").matches) {
    closeMobileNav();
  }
}

function clearChapterEditor() {
  state.chapterId = null;
  state.chapter = null;
  $("#chapterTitle").value = "";
  $("#editor").value = "";
  $("#chapterPosition").textContent = "—";
  $("#chapterStatus").textContent = "—";
  $("#chapterUpdated").textContent = "尚未保存";
  updateStats();
}

function updateStats() {
  $("#charCount").textContent = formatNumber(countText($("#editor").value));
}

function scheduleSave() {
  if (!state.chapterId) return;
  setSaving(true);
  updateStats();
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(() => saveChapter(false), 850);
}

async function flushPendingSave() {
  if (!state.saveTimer || !state.chapterId) return;
  clearTimeout(state.saveTimer);
  state.saveTimer = null;
  await saveChapter(true);
}

async function saveChapter(silent = false) {
  if (!state.chapterId) return;

  clearTimeout(state.saveTimer);
  state.saveTimer = null;

  try {
    const chapter = await api(`/api/chapters/${state.chapterId}`, {
      method: "PATCH",
      body: JSON.stringify({
        title: $("#chapterTitle").value.trim() || "未命名章节",
        content: $("#editor").value,
        note: "自动保存",
      }),
    });

    state.chapter = chapter;
    $("#chapterUpdated").textContent = chapter.updated_at
      ? `最后保存：${chapter.updated_at}`
      : "已保存";
    setSaving(false);

    await refreshChapterList();
    await refreshProjectSummary();

    if (!silent) {
      // Autosave stays quiet; explicit Ctrl/Cmd+S shows its own toast.
    }
  } catch (error) {
    setSaving(false);
    toast(error.message);
    throw error;
  }
}

async function refreshChapterList() {
  if (!state.projectId) return;
  state.chapters = await api(`/api/projects/${state.projectId}/chapters`);
  renderChapters();
}

async function createProject() {
  const title = prompt("作品名称");
  if (!title?.trim()) return;

  const genre = prompt("作品类型（可选）", "悬疑") || "";
  const description = prompt("作品简介（可选）", "") || "";

  try {
    const project = await api("/api/projects", {
      method: "POST",
      body: JSON.stringify({
        title: title.trim(),
        genre: genre.trim(),
        description: description.trim(),
      }),
    });
    await loadProjects(project.id);
    toast("作品已创建");
  } catch (error) {
    toast(error.message);
  }
}

async function deleteCurrentProject() {
  const project = currentProject();
  if (!project) return;

  if (
    !confirm(
      `确定删除《${project.title}》吗？\n\n作品下的章节、版本、人物和世界观都会一起删除，此操作不可撤销。`,
    )
  ) {
    return;
  }

  await flushPendingSave();

  try {
    await api(`/api/projects/${project.id}`, { method: "DELETE" });
    state.projectId = null;
    state.chapterId = null;
    await loadProjects();
    toast("作品已删除");
  } catch (error) {
    toast(error.message);
  }
}

async function createChapter() {
  if (!state.projectId) {
    toast("请先新建作品");
    return;
  }

  const defaultTitle = `第${state.chapters.length + 1}章`;
  const title = prompt("章节标题", defaultTitle);
  if (!title?.trim()) return;

  try {
    const chapter = await api(`/api/projects/${state.projectId}/chapters`, {
      method: "POST",
      body: JSON.stringify({ title: title.trim() }),
    });
    await refreshChapterList();
    await refreshProjectSummary();
    await loadChapter(chapter.id);
    toast("章节已创建");
  } catch (error) {
    toast(error.message);
  }
}

async function deleteCurrentChapter() {
  if (!state.chapterId || !state.chapter) return;

  if (!confirm(`确定删除“${state.chapter.title}”吗？该章节的版本历史也会一起删除。`)) {
    return;
  }

  try {
    clearTimeout(state.saveTimer);
    state.saveTimer = null;
    await api(`/api/chapters/${state.chapterId}`, { method: "DELETE" });

    const deletedId = state.chapterId;
    state.chapterId = null;
    state.chapter = null;
    await refreshChapterList();
    await refreshProjectSummary();

    const next = state.chapters.find((chapter) => chapter.id !== deletedId);
    if (next) {
      await loadChapter(next.id);
    } else {
      clearChapterEditor();
    }

    toast("章节已删除");
  } catch (error) {
    toast(error.message);
  }
}

function setAiButtons(mode, hasText) {
  $("#insertAiBtn").disabled = !hasText || mode === "check";
  $("#replaceAiBtn").disabled = !hasText || mode === "check";
}

async function runAi(mode) {
  if (!state.chapterId) {
    toast("请先选择章节");
    return;
  }

  state.aiMode = mode;
  state.aiText = "";

  const titles = {
    continue: "续写结果",
    polish: "润色结果",
    check: "一致性检查",
  };

  $("#aiResultTitle").textContent = titles[mode] || "AI 输出";
  $("#aiModelInfo").textContent = "处理中…";
  $("#aiResult").innerHTML =
    '<div class="empty-state"><div class="empty-icon">◌</div><strong>模型正在处理</strong><p>正文不会被自动修改。</p></div>';
  setAiButtons(mode, false);

  try {
    const data = await api("/api/ai/assist", {
      method: "POST",
      body: JSON.stringify({
        mode,
        content: $("#editor").value,
        instruction: $("#aiInstruction").value,
      }),
    });

    state.aiText = data.content || "";
    $("#aiResult").textContent = state.aiText;
    $("#aiProviderBadge").textContent = (data.provider || "demo").toUpperCase();
    $("#aiModelInfo").textContent = data.model || data.provider || "未知模型";
    setAiButtons(mode, Boolean(state.aiText));

    if (data.demo) {
      toast("当前使用 AI 演示模式");
    }
  } catch (error) {
    $("#aiResult").textContent = error.message;
    $("#aiModelInfo").textContent = "请求失败";
    $("#aiProviderBadge").textContent = "ERROR";
    setAiButtons(mode, false);
    toast("AI 请求失败");
  }
}

function appendAiResult() {
  if (!state.aiText || state.aiMode === "check") return;

  const editor = $("#editor");
  editor.value = (editor.value.trimEnd() + `\n\n${state.aiText}`).trimStart();
  editor.focus();
  updateStats();
  scheduleSave();
  toast("AI 结果已追加到正文");
}

async function replaceWithAiResult() {
  if (!state.aiText || state.aiMode === "check") return;

  if (!confirm("确定用 AI 结果替换当前正文吗？当前正文会先保存到版本历史。")) {
    return;
  }

  try {
    await flushPendingSave();
    await saveChapter(true);
  } catch {
    return;
  }

  const editor = $("#editor");
  editor.value = state.aiText;
  editor.focus();
  updateStats();
  scheduleSave();
  toast("AI 结果已替换正文");
}


function workflowStatusLabel(status) {
  const labels = {
    pending: "待运行",
    running: "运行中",
    failed: "失败",
    reviewed: "已评审",
    awaiting_approval: "待确认",
    approved: "已确认",
    rejected: "已退回",
  };
  return labels[status] || status || "未知";
}

function runStatusLabel(status) {
  const labels = {
    pending: "等待",
    queued: "排队",
    running: "运行中",
    completed: "完成",
    success: "完成",
    failed: "失败",
    error: "失败",
  };
  return labels[status] || status || "未知";
}

function roleLabel(role) {
  const labels = {
    writer: "Writer · 正文生成",
    planner: "Planner · 结构规划",
    "continuity-plot-reviewer": "GLM 深审 · 连续性 / 剧情 / 证据链",
    "character-dialogue-reviewer": "人物对白审核",
    "language-rhythm-reviewer": "语言节奏审核",
    "master-reader": "Master Reviewer",
    "revision-agent": "Revision · 修订",
    "scene-enricher": "场景增强",
    "prose-editor": "文字编辑",
  };
  return labels[role] || role || "未命名 Agent";
}

function formatDurationMs(value) {
  const ms = Number(value);
  if (!Number.isFinite(ms) || ms < 0) return "";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)}s`;
  const minutes = Math.floor(ms / 60000);
  const seconds = Math.round((ms % 60000) / 1000);
  return `${minutes}m ${seconds}s`;
}

function renderLiveTaskProgress(task) {
  const runs = task.runs || [];
  const completed = runs.filter((run) => ["completed", "success"].includes(run.status)).length;
  const running = runs.filter((run) => run.status === "running").length;
  const failed = runs.filter((run) => ["failed", "error"].includes(run.status)).length;
  const terminal = ["awaiting_approval", "reviewed", "approved", "rejected"].includes(task.status);
  const percent = terminal ? 100 : runs.length ? Math.round((completed / runs.length) * 100) : 0;

  const rows = runs.length
    ? runs.map((run) => {
        const metric = run.metrics || {};
        const duration = formatDurationMs(metric.duration_ms ?? run.duration_ms);
        const model = [run.provider, run.model].filter(Boolean).join(" / ");
        const error = run.error ? `<div class="progress-error">${escapeHtml(run.error)}</div>` : "";
        return `
          <div class="progress-run status-${escapeHtml(run.status)}">
            <span class="progress-dot" aria-hidden="true"></span>
            <div class="progress-run-main">
              <strong>${escapeHtml(roleLabel(run.role))}</strong>
              <small>${escapeHtml(run.stage || "workflow")} · ${escapeHtml(runStatusLabel(run.status))}</small>
              ${model ? `<small>实际模型：${escapeHtml(model)}</small>` : ""}
              ${error}
            </div>
            <span class="progress-time">${escapeHtml(duration)}</span>
          </div>`;
      }).join("")
    : `<div class="progress-empty">${task.status === "running" ? "正在准备 Writer / Reviewer…" : "尚未启动 Agent"}</div>`;

  return `
    <div class="task-progress" data-task-progress="${task.id}">
      <div class="task-progress-head">
        <div>
          <span class="live-indicator ${task.status === "running" ? "is-live" : ""}"></span>
          <strong>${task.status === "running" ? "实时进度" : "执行进度"}</strong>
        </div>
        <span>${completed} 完成 · ${running} 运行 · ${failed} 失败</span>
      </div>
      <div class="progress-track" aria-label="任务进度">
        <span style="width:${Math.max(0, Math.min(100, percent))}%"></span>
      </div>
      <div class="progress-runs">${rows}</div>
      ${task.status === "running" ? '<p class="progress-refresh-note">自动刷新中 · 约每 1.2 秒更新</p>' : ""}
    </div>`;
}

function stopTaskPolling() {
  if (state.taskPollTimer) {
    clearTimeout(state.taskPollTimer);
    state.taskPollTimer = null;
  }
  state.taskPollBusy = false;
}

function startTaskPolling(taskId) {
  stopTaskPolling();

  const tick = async () => {
    if (state.selectedTaskId !== taskId || !$("#taskDialog").open) {
      stopTaskPolling();
      return;
    }
    if (state.taskPollBusy) {
      state.taskPollTimer = setTimeout(tick, 1200);
      return;
    }

    state.taskPollBusy = true;
    try {
      const task = await api(`/api/tasks/${taskId}`);
      renderTaskDialog(task);
      if (task.status !== "running") {
        stopTaskPolling();
        await loadTasks();
        return;
      }
    } catch {
      // Keep polling; a transient read error should not hide task progress.
    } finally {
      state.taskPollBusy = false;
    }

    state.taskPollTimer = setTimeout(tick, 1200);
  };

  state.taskPollTimer = setTimeout(tick, 350);
}

async function loadTasks() {
  if (!state.projectId) return;
  state.tasks = await api(`/api/projects/${state.projectId}/tasks`);
  $("#taskCount").textContent = String(state.tasks.length);
  const container = $("#taskList");
  container.innerHTML = "";

  if (!state.tasks.length) {
    container.innerHTML = '<div class="no-results">还没有创作任务</div>';
    return;
  }

  for (const task of state.tasks) {
    const card = document.createElement("article");
    card.className = "info-card workflow-card";
    const canRun = ["pending", "failed", "reviewed", "rejected"].includes(task.status);
    const canReview = task.status === "awaiting_approval";
    card.innerHTML = `
      <div class="info-card-head">
        <strong>#${task.id} · ${escapeHtml(task.goal)}</strong>
        <span class="status-badge status-${escapeHtml(task.status)}">${workflowStatusLabel(task.status)}</span>
      </div>
      <p>${escapeHtml(task.instruction || "无额外要求")}</p>
      <div class="card-actions">
        <button class="ghost compact" data-action="detail">详情</button>
        ${canRun ? '<button class="primary compact" data-action="run">运行</button>' : ""}
        ${canReview ? '<button class="primary compact" data-action="review">审阅确认</button>' : ""}
      </div>
    `;
    card.querySelector('[data-action="detail"]').onclick = () => openTask(task.id);
    const runButton = card.querySelector('[data-action="run"]');
    if (runButton) runButton.onclick = () => runWorkflowTask(task.id);
    const reviewButton = card.querySelector('[data-action="review"]');
    if (reviewButton) reviewButton.onclick = () => openTask(task.id);
    container.appendChild(card);
  }
}

async function createWritingTask() {
  if (!state.projectId || !state.chapterId) {
    toast("请先选择目标章节");
    return;
  }
  await flushPendingSave();

  const goal = prompt("这次创作任务要完成什么？", "继续推进当前章节");
  if (!goal?.trim()) return;
  const instruction = prompt(
    "补充要求（可选）",
    "保持当前叙述视角，不新增无关人物。",
  ) || "";

  const enabledSkills = state.skills.filter((skill) => Boolean(skill.enabled));
  let skillIds = [];
  if (enabledSkills.length) {
    const skillHelp = enabledSkills
      .map((skill) => `${skill.id} = ${skill.name} v${skill.current_version}`)
      .join("\n");
    const rawSkillIds = prompt(
      `选择本次冻结使用的 Skill ID（逗号分隔；留空表示不用）：\n\n${skillHelp}`,
      enabledSkills.map((skill) => skill.id).join(","),
    );
    if (rawSkillIds === null) return;
    skillIds = rawSkillIds.trim()
      ? rawSkillIds
          .split(/[,，]/)
          .map((value) => Number(value.trim()))
          .filter((value) => Number.isInteger(value))
      : [];
  }

  try {
    const task = await api(`/api/projects/${state.projectId}/tasks`, {
      method: "POST",
      body: JSON.stringify({
        chapter_id: state.chapterId,
        goal: goal.trim(),
        instruction: instruction.trim(),
        skill_ids: skillIds,
      }),
    });
    await loadTasks();
    toast(`任务 #${task.id} 已创建`);
  } catch (error) {
    toast(error.message);
  }
}

async function runWorkflowTask(taskId) {
  try {
    state.selectedTaskId = taskId;
    const initial = await api(`/api/tasks/${taskId}`);
    renderTaskDialog({ ...initial, status: "running" });
    if (!$("#taskDialog").open) $("#taskDialog").showModal();

    toast(`任务 #${taskId} 已启动，可实时查看进度`);
    const runPromise = api(`/api/tasks/${taskId}/run`, { method: "POST" });
    startTaskPolling(taskId);

    const task = await runPromise;
    stopTaskPolling();
    renderTaskDialog(task);
    await loadTasks();
  } catch (error) {
    stopTaskPolling();
    await loadTasks();
    try {
      const task = await api(`/api/tasks/${taskId}`);
      renderTaskDialog(task);
    } catch {
      // Keep the original execution error as the primary user-facing message.
    }
    toast(error.message);
  }
}

function renderTaskDialog(task) {
  const body = $("#taskDialogBody");
  const findings = task.findings || [];
  const runs = task.runs || [];
  const selectedSkills = task.skills || [];
  $("#taskDialogTitle").textContent = `任务 #${task.id} · ${workflowStatusLabel(task.status)}`;
  body.innerHTML = `
    <section class="task-section">
      <span class="eyebrow">Goal</span>
      <strong>${escapeHtml(task.goal)}</strong>
      <p>${escapeHtml(task.instruction || "无额外要求")}</p>
      <p>
        ${selectedSkills.length
          ? selectedSkills
              .map((skill) => `Skill: ${escapeHtml(skill.name)} v${skill.version}`)
              .join("<br>")
          : "本任务未选择 Skill"}
      </p>
    </section>
    <section class="task-section">
      <span class="eyebrow">Live Workflow</span>
      ${renderLiveTaskProgress(task)}
    </section>
    <section class="task-section">
      <span class="eyebrow">Writer Draft</span>
      <pre>${escapeHtml(task.draft || "尚未生成")}</pre>
    </section>
    <section class="task-section">
      <span class="eyebrow">Reviewer Findings</span>
      <div class="finding-list">
        ${findings.length
          ? findings
              .map(
                (item) => `
                  <article class="finding-item">
                    <div class="info-card-head">
                      <strong>${escapeHtml(item.reviewer)}</strong>
                      <span class="status-badge">${escapeHtml(item.severity)}</span>
                    </div>
                    <p>${escapeHtml(item.summary)}</p>
                    ${item.suggestion ? `<p>建议：${escapeHtml(item.suggestion)}</p>` : ""}
                    ${item.location?.excerpt
                      ? `<blockquote class="finding-excerpt">原文：${escapeHtml(item.location.excerpt)}${Number.isInteger(item.location.start_offset) ? ` · @${item.location.start_offset}-${item.location.end_offset}` : ""}</blockquote>`
                      : ""}
                  </article>`,
              )
              .join("")
          : '<div class="no-results">暂无 Reviewer 结果</div>'}
      </div>
    </section>
    <section class="task-section">
      <span class="eyebrow">Revision</span>
      <pre>${escapeHtml(task.revised_content || "尚未生成修订稿")}</pre>
    </section>
    <section class="task-section task-run-summary">
      <span class="eyebrow">Runs</span>
      <p>${runs
        .map((run) => {
          const metric = run.metrics;
          const suffix = metric
            ? ` · ${escapeHtml(metric.prompt_version)} · ${metric.duration_ms}ms`
            : "";
          return `${escapeHtml(run.stage)} · ${escapeHtml(run.role)} · ${escapeHtml(run.status)}${suffix}`;
        })
        .join("<br>") || "暂无运行记录"}</p>
    </section>
  `;
  const canApprove = task.status === "awaiting_approval";
  $("#approveTaskBtn").disabled = !canApprove;
  $("#rejectTaskBtn").disabled = !canApprove;
}

async function openTask(taskId) {
  try {
    const task = await api(`/api/tasks/${taskId}`);
    state.selectedTaskId = taskId;
    renderTaskDialog(task);
    $("#taskDialog").showModal();
    if (task.status === "running") startTaskPolling(taskId);
  } catch (error) {
    toast(error.message);
  }
}

async function decideTask(decision) {
  if (!state.selectedTaskId) return;
  const note = prompt(decision === "approved" ? "确认备注（可选）" : "退回原因（可选）", "") || "";

  try {
    const task = await api(`/api/tasks/${state.selectedTaskId}/approval`, {
      method: "POST",
      body: JSON.stringify({ decision, note }),
    });
    $("#taskDialog").close();
    await Promise.all([loadTasks(), refreshChapterList(), refreshProjectSummary(), loadContentStatus()]);
    if (state.chapterId) await loadChapter(state.chapterId);
    const sync = task.content_sync;
    if (decision === "approved" && sync?.status === "completed") {
      toast("已确认并写入章节，内容库归档完成");
    } else if (decision === "approved" && sync && sync.status !== "completed") {
      toast(`正文已确认；内容库同步：${sync.status}`);
    } else {
      toast("任务已退回，原正文未改动");
    }
  } catch (error) {
    toast(error.message);
  }
}

async function loadMemories() {
  if (!state.projectId) return;
  const [memories, conflicts] = await Promise.all([
    api(`/api/projects/${state.projectId}/memories`),
    api(`/api/projects/${state.projectId}/memory-conflicts`),
  ]);
  state.memories = memories;
  $("#memoryCount").textContent = String(state.memories.length);
  const container = $("#memoryList");
  container.innerHTML = "";

  if (conflicts.length) {
    const warning = document.createElement("article");
    warning.className = "info-card conflict-card";
    warning.innerHTML = `
      <div class="info-card-head">
        <strong>发现 ${conflicts.length} 组记忆冲突</strong>
        <span class="status-badge status-failed">需处理</span>
      </div>
      <p>${conflicts
        .map((item) => `${escapeHtml(item.kind)} · ${escapeHtml(item.title)}（${item.variants} 个版本）`)
        .join("<br>")}</p>
      <p>请撤销错误记忆的“已确认”状态，Reviewer 将只使用仍被确认的事实。</p>
    `;
    container.appendChild(warning);
  }

  if (!state.memories.length) {
    container.insertAdjacentHTML("beforeend", '<div class="no-results">还没有作品记忆</div>');
    return;
  }

  for (const memory of state.memories) {
    const card = document.createElement("article");
    card.className = "info-card";
    card.innerHTML = `
      <div class="info-card-head">
        <strong>${escapeHtml(memory.title)}</strong>
        <span class="status-badge ${memory.confirmed ? "status-approved" : "status-pending"}">
          ${memory.confirmed ? "已确认" : "候选"} · v${memory.current_version || 1}
        </span>
      </div>
      <p>${escapeHtml(memory.content)}</p>
      <div class="tag-row"><span class="tag">${escapeHtml(memory.kind)}</span></div>
      <div class="card-actions">
        <button class="ghost compact" data-action="history">版本</button>
        <button class="ghost compact" data-action="confirm">
          ${memory.confirmed ? "撤销确认" : "确认记忆"}
        </button>
      </div>
    `;
    card.querySelector('[data-action="confirm"]').onclick = () =>
      setMemoryConfirmed(memory.id, !memory.confirmed);
    card.querySelector('[data-action="history"]').onclick = () =>
      restoreMemoryVersion(memory);
    container.appendChild(card);
  }
}

async function createMemory() {
  if (!state.projectId) return;
  const title = prompt("记忆标题");
  if (!title?.trim()) return;
  const kind = prompt("类型", "fact") || "fact";
  const content = prompt("记忆内容");
  if (!content?.trim()) return;
  const confirmed = confirm("是否立即确认这条记忆？\n\n确认后会进入 Writer / Reviewer 上下文。");

  try {
    await api(`/api/projects/${state.projectId}/memories`, {
      method: "POST",
      body: JSON.stringify({
        title: title.trim(),
        kind: kind.trim() || "fact",
        content: content.trim(),
        confirmed,
      }),
    });
    await loadMemories();
    toast("作品记忆已创建");
  } catch (error) {
    toast(error.message);
  }
}

async function setMemoryConfirmed(memoryId, confirmed) {
  try {
    await api(`/api/memories/${memoryId}`, {
      method: "PATCH",
      body: JSON.stringify({ confirmed }),
    });
    await loadMemories();
    toast(confirmed ? "记忆已确认" : "记忆已撤回为候选");
  } catch (error) {
    toast(error.message);
  }
}

async function restoreMemoryVersion(memory) {
  try {
    const versions = await api(`/api/memories/${memory.id}/versions`);
    if (!versions.length) {
      toast("没有可恢复版本");
      return;
    }
    const summary = versions
      .map((item) => `v${item.version} · ${item.note || "版本"} · ${item.content.slice(0, 28)}`)
      .join("\n");
    const selected = prompt(
      `选择要恢复的版本号：\n\n${summary}`,
      String(versions[0].version),
    );
    if (!selected?.trim()) return;
    const version = Number(selected);
    if (!Number.isInteger(version)) {
      toast("版本号无效");
      return;
    }
    await api(`/api/memories/${memory.id}/versions/${version}/restore`, {
      method: "POST",
    });
    await loadMemories();
    toast(`记忆已恢复到 v${version} 的内容，并生成新版本`);
  } catch (error) {
    toast(error.message);
  }
}

async function loadSkills() {
  if (!state.projectId) return;
  state.skills = await api(`/api/projects/${state.projectId}/skills`);
  $("#skillCount").textContent = String(state.skills.length);
  const container = $("#skillList");
  container.innerHTML = "";

  if (!state.skills.length) {
    container.innerHTML = '<div class="no-results">还没有技能</div>';
    return;
  }

  for (const skill of state.skills) {
    const card = document.createElement("article");
    card.className = "info-card";
    card.innerHTML = `
      <div class="info-card-head">
        <strong>${escapeHtml(skill.name)}</strong>
        <span class="status-badge ${skill.enabled ? "status-approved" : "status-pending"}">
          ${skill.enabled ? "启用" : "停用"} · v${skill.current_version}
        </span>
      </div>
      <p>${escapeHtml(skill.purpose || skill.content)}</p>
      <div class="card-actions">
        <button class="ghost compact" data-action="toggle">${skill.enabled ? "停用" : "启用"}</button>
        <button class="ghost compact" data-action="restore">历史</button>
        <button class="ghost compact" data-action="publish">新版本</button>
      </div>
    `;
    card.querySelector('[data-action="toggle"]').onclick = () =>
      setSkillEnabled(skill, !skill.enabled);
    card.querySelector('[data-action="restore"]').onclick = () =>
      restoreSkillVersion(skill);
    card.querySelector('[data-action="publish"]').onclick = () =>
      publishSkillVersion(skill);
    container.appendChild(card);
  }
}

async function createSkill() {
  if (!state.projectId) return;
  const name = prompt("技能名称");
  if (!name?.trim()) return;
  const purpose = prompt("技能用途（可选）", "") || "";
  const content = prompt("技能正文 / 执行规则");
  if (!content?.trim()) return;

  try {
    await api(`/api/projects/${state.projectId}/skills`, {
      method: "POST",
      body: JSON.stringify({
        name: name.trim(),
        purpose: purpose.trim(),
        content: content.trim(),
      }),
    });
    await loadSkills();
    toast("技能已创建");
  } catch (error) {
    toast(error.message);
  }
}

async function setSkillEnabled(skill, enabled) {
  try {
    await api(`/api/skills/${skill.id}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    });
    await loadSkills();
    toast(enabled ? "技能已启用" : "技能已停用");
  } catch (error) {
    toast(error.message);
  }
}

async function publishSkillVersion(skill) {
  const next = prompt(`发布 ${skill.name} 的新版本`, skill.content || "");
  if (!next?.trim() || next.trim() === skill.content) return;
  const note = prompt("版本说明（可选）", "") || "";

  try {
    await api(`/api/skills/${skill.id}/versions`, {
      method: "POST",
      body: JSON.stringify({ content: next.trim(), note: note.trim() }),
    });
    await loadSkills();
    toast("技能新版本已发布");
  } catch (error) {
    toast(error.message);
  }
}

async function restoreSkillVersion(skill) {
  try {
    const versions = await api(`/api/skills/${skill.id}/versions`);
    if (!versions.length) {
      toast("没有可恢复版本");
      return;
    }
    const summary = versions
      .map((item) => `v${item.version} · ${item.note || "版本"} · ${item.content.slice(0, 28)}`)
      .join("\n");
    const selected = prompt(
      `选择要恢复的版本号：\n\n${summary}`,
      String(versions[0].version),
    );
    if (!selected?.trim()) return;
    const version = Number(selected);
    if (!Number.isInteger(version)) {
      toast("版本号无效");
      return;
    }
    await api(`/api/skills/${skill.id}/versions/${version}/restore`, {
      method: "POST",
    });
    await loadSkills();
    toast(`技能已恢复 v${version} 内容，并发布为新版本`);
  } catch (error) {
    toast(error.message);
  }
}

async function loadContentStatus() {
  if (!state.projectId) return;
  try {
    state.contentStatus = await api(`/api/projects/${state.projectId}/content`);
    const element = $("#contentRepoStatus");
    if (!state.contentStatus.linked) {
      element.textContent = "未绑定";
    } else if (!state.contentStatus.configured) {
      element.textContent = `${state.contentStatus.slug} · 未配置路径`;
    } else {
      element.textContent = `${state.contentStatus.slug} · 已连接`;
    }
  } catch (error) {
    $("#contentRepoStatus").textContent = "状态读取失败";
  }
}

async function linkContentRepository() {
  if (!state.projectId) return;
  const current = state.contentStatus?.slug || "";
  const slug = prompt("作品库目录 slug", current || "slow-world");
  if (!slug?.trim()) return;

  try {
    await api(`/api/projects/${state.projectId}/content`, {
      method: "PUT",
      body: JSON.stringify({ slug: slug.trim() }),
    });
    await loadContentStatus();
    toast("作品内容库已绑定");
  } catch (error) {
    toast(error.message);
  }
}

async function preflightContentRepository() {
  if (!state.projectId) return;

  try {
    const result = await api(
      `/api/projects/${state.projectId}/content/preflight`,
    );
    const element = $("#contentRepoStatus");
    if (result.ready) {
      element.textContent = `${result.slug} · 预检通过 · ${result.sources.length} 份资料`;
      toast("内容库预检通过");
    } else {
      element.textContent = `${result.slug || "未绑定"} · 预检未通过`;
      alert(
        ["内容库预检未通过：", "", ...(result.issues || [])]
          .filter(Boolean)
          .join("\n"),
      );
    }
  } catch (error) {
    toast(error.message);
  }
}

async function importContentRepository() {
  if (!state.projectId) return;

  try {
    const preflight = await api(
      `/api/projects/${state.projectId}/content/preflight`,
    );
    if (!preflight.ready) {
      alert(
        ["暂不能导入内容库：", "", ...(preflight.issues || [])]
          .filter(Boolean)
          .join("\n"),
      );
      return;
    }

    const result = await api(
      `/api/projects/${state.projectId}/content/import`,
      { method: "POST" },
    );
    await Promise.all([loadMemories(), loadSkills(), loadContentStatus()]);
    const counts = result.counts || {};
    toast(
      `内容库资料已同步：新建 ${counts.created || 0}，更新 ${counts.updated || 0}，未变 ${counts.unchanged || 0}`,
    );
  } catch (error) {
    toast(error.message);
  }
}

async function loadCharacters() {
  if (!state.projectId) return;

  state.characters = await api(`/api/projects/${state.projectId}/characters`);
  $("#characterCount").textContent = String(state.characters.length);

  const container = $("#characterList");
  container.innerHTML = "";

  if (!state.characters.length) {
    container.innerHTML = '<div class="no-results">还没有人物卡</div>';
    return;
  }

  for (const character of state.characters) {
    const card = document.createElement("article");
    card.className = "info-card";
    card.innerHTML = `
      <div class="info-card-head">
        <strong>${escapeHtml(character.name)}</strong>
        <span class="role">${escapeHtml(character.role || "未设定")}</span>
      </div>
      <p>${escapeHtml(character.profile || "暂无简介")}</p>
      <div class="tag-row">
        ${(character.tags || [])
          .map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`)
          .join("")}
      </div>
    `;
    container.appendChild(card);
  }
}

async function createCharacter() {
  if (!state.projectId) return;

  const name = prompt("人物名");
  if (!name?.trim()) return;

  const role = prompt("角色定位（可选）", "主角") || "";
  const profile = prompt("人物简介（可选）", "") || "";
  const rawTags = prompt("标签（用逗号分隔，可选）", "") || "";
  const tags = rawTags
    .split(/[,，]/)
    .map((tag) => tag.trim())
    .filter(Boolean);

  try {
    await api(`/api/projects/${state.projectId}/characters`, {
      method: "POST",
      body: JSON.stringify({
        name: name.trim(),
        role: role.trim(),
        profile: profile.trim(),
        tags,
      }),
    });
    await loadCharacters();
    toast("人物卡已创建");
  } catch (error) {
    toast(error.message);
  }
}

async function loadWorld() {
  if (!state.projectId) return;

  state.world = await api(`/api/projects/${state.projectId}/world`);
  $("#worldCount").textContent = String(state.world.length);

  const container = $("#worldList");
  container.innerHTML = "";

  if (!state.world.length) {
    container.innerHTML = '<div class="no-results">还没有世界设定</div>';
    return;
  }

  for (const note of state.world) {
    const card = document.createElement("article");
    card.className = "info-card";
    card.innerHTML = `
      <div class="info-card-head">
        <strong>${escapeHtml(note.title)}</strong>
        <span class="role">${escapeHtml(note.category || "设定")}</span>
      </div>
      <p>${escapeHtml(note.content || "暂无内容")}</p>
    `;
    container.appendChild(card);
  }
}

async function createWorldNote() {
  if (!state.projectId) return;

  const title = prompt("设定名称");
  if (!title?.trim()) return;

  const category = prompt("分类", "地点") || "设定";
  const content = prompt("设定内容", "") || "";

  try {
    await api(`/api/projects/${state.projectId}/world`, {
      method: "POST",
      body: JSON.stringify({
        title: title.trim(),
        category: category.trim() || "设定",
        content: content.trim(),
      }),
    });
    await loadWorld();
    toast("世界设定已创建");
  } catch (error) {
    toast(error.message);
  }
}

async function showHistory() {
  if (!state.chapterId) {
    toast("请先选择章节");
    return;
  }

  await flushPendingSave();

  const rows = await api(`/api/chapters/${state.chapterId}/versions`);
  const container = $("#historyList");
  container.innerHTML = "";

  if (!rows.length) {
    container.innerHTML = '<div class="no-results">还没有历史版本</div>';
  }

  for (const version of rows) {
    const row = document.createElement("div");
    row.className = "history-item";
    row.innerHTML = `
      <div>
        <strong>${escapeHtml(version.note || "历史版本")}</strong>
        <small>${version.created_at} · ${formatNumber(version.char_count)} 字符</small>
      </div>
      <button class="ghost compact">恢复</button>
    `;

    row.querySelector("button").onclick = async () => {
      if (!confirm("恢复这个版本？当前内容仍会保留在版本历史中。")) return;

      const chapter = await api(
        `/api/chapters/${state.chapterId}/versions/${version.id}/restore`,
        { method: "POST" },
      );

      state.chapter = chapter;
      $("#editor").value = chapter.content || "";
      updateStats();
      $("#historyDialog").close();
      await refreshChapterList();
      await refreshProjectSummary();
      toast("版本已恢复");
    };

    container.appendChild(row);
  }

  $("#historyDialog").showModal();
}

function toggleMobileNav() {
  const enabled = document.body.classList.toggle("mobile-nav-open");
  $("#mobileNavBtn").textContent = enabled ? "×" : "☰";
}

function closeMobileNav() {
  document.body.classList.remove("mobile-nav-open");
  $("#mobileNavBtn").textContent = "☰";
}

function toggleFocusMode() {
  const enabled = document.body.classList.toggle("focus-mode");
  $("#focusBtn").textContent = enabled ? "▣ 退出专注" : "◫ 专注模式";
  toast(enabled ? "已进入专注模式" : "已退出专注模式");
}

const PROVIDER_PROTOCOL_LABELS = {
  "openai-compatible": "OpenAI Compatible",
  anthropic: "Anthropic Messages",
  gemini: "Gemini GenerateContent",
  ollama: "Ollama Chat",
};

function resetProviderEditor() {
  state.editingProviderId = null;
  $("#providerName").value = "";
  $("#providerProtocol").value = "";
  $("#providerBaseUrl").value = "";
  $("#providerModel").value = "";
  $("#providerKeyEnv").value = "";
  $("#providerEnabled").checked = true;
  $("#providerDefault").checked = false;
  $("#providerProtocolFields").classList.add("hidden");
  $("#providerEditor").classList.add("hidden");
}

function syncProviderProtocolFields() {
  const hasProtocol = Boolean($("#providerProtocol").value);
  $("#providerProtocolFields").classList.toggle("hidden", !hasProtocol);
}

async function loadProviders() {
  state.providers = await api("/api/providers");
  renderProviders();
}

function renderProviders() {
  $("#providerCount").textContent = String(state.providers.length);
  const container = $("#providerList");
  container.innerHTML = "";

  if (!state.providers.length) {
    container.innerHTML =
      '<div class="no-results">还没有 Provider。名称由你自己定义，协议可以稍后再选。</div>';
    return;
  }

  for (const provider of state.providers) {
    const card = document.createElement("div");
    card.className = "provider-card";
    const protocolLabel =
      PROVIDER_PROTOCOL_LABELS[provider.protocol] ||
      (provider.protocol ? provider.protocol : "未选择协议");
    const runtimeText = provider.protocol
      ? protocolLabel + (provider.default_model ? " · " + escapeHtml(provider.default_model) : "")
      : "未选择协议 · 不进入运行链路";

    card.innerHTML = [
      '<div class="provider-card-head"><div><strong>',
      escapeHtml(provider.name),
      '</strong><small>',
      runtimeText,
      '</small></div><div class="provider-badges">',
      provider.is_default ? '<span class="mini-badge">默认</span>' : "",
      provider.enabled ? "" : '<span class="mini-badge muted">停用</span>',
      '</div></div><div class="provider-card-meta"><span>',
      provider.base_url ? escapeHtml(provider.base_url) : "默认协议地址",
      '</span><span>',
      provider.api_key_env ? "Key: " + escapeHtml(provider.api_key_env) : "未配置 Key 环境变量",
      '</span></div><div class="provider-card-actions">',
      '<button class="ghost compact" data-action="edit">编辑</button>',
      provider.is_default ? "" : '<button class="ghost compact" data-action="default">设为默认</button>',
      '<button class="ghost danger compact" data-action="delete">删除</button>',
      '</div>',
    ].join("");

    card.querySelector('[data-action="edit"]').onclick = () => editProvider(provider);
    const defaultButton = card.querySelector('[data-action="default"]');
    if (defaultButton) defaultButton.onclick = () => setDefaultProvider(provider);
    card.querySelector('[data-action="delete"]').onclick = () => deleteProvider(provider);
    container.appendChild(card);
  }
}

function editProvider(provider) {
  state.editingProviderId = provider.id;
  $("#providerName").value = provider.name || "";
  $("#providerProtocol").value = provider.protocol || "";
  $("#providerBaseUrl").value = provider.base_url || "";
  $("#providerModel").value = provider.default_model || "";
  $("#providerKeyEnv").value = provider.api_key_env || "";
  $("#providerEnabled").checked = Boolean(provider.enabled);
  $("#providerDefault").checked = Boolean(provider.is_default);
  $("#providerEditor").classList.remove("hidden");
  syncProviderProtocolFields();
}

function newProvider() {
  resetProviderEditor();
  $("#providerEditor").classList.remove("hidden");
  $("#providerName").focus();
}

async function saveProvider() {
  const name = $("#providerName").value.trim();
  if (!name) {
    toast("请先填写 Provider 名称");
    return;
  }

  const protocol = $("#providerProtocol").value;
  const payload = {
    name,
    protocol,
    base_url: protocol ? $("#providerBaseUrl").value.trim() : "",
    default_model: protocol ? $("#providerModel").value.trim() : "",
    api_key_env: protocol ? $("#providerKeyEnv").value.trim() : "",
    enabled: $("#providerEnabled").checked,
    is_default: protocol ? $("#providerDefault").checked : false,
  };

  try {
    const path = state.editingProviderId
      ? "/api/providers/" + state.editingProviderId
      : "/api/providers";
    await api(path, {
      method: state.editingProviderId ? "PATCH" : "POST",
      body: JSON.stringify(payload),
    });
    resetProviderEditor();
    await loadProviders();
    toast("Provider 已保存");
  } catch (error) {
    toast(error.message);
  }
}

async function setDefaultProvider(provider) {
  if (!provider.protocol) {
    toast("请先选择协议并完成连接配置");
    return;
  }
  try {
    await api("/api/providers/" + provider.id, {
      method: "PATCH",
      body: JSON.stringify({ is_default: true }),
    });
    await loadProviders();
    toast("已将“" + provider.name + "”设为默认");
  } catch (error) {
    toast(error.message);
  }
}

async function deleteProvider(provider) {
  if (!confirm("确定删除 Provider“" + provider.name + "”吗？")) return;
  try {
    await api("/api/providers/" + provider.id, { method: "DELETE" });
    if (state.editingProviderId === provider.id) resetProviderEditor();
    await loadProviders();
    toast("Provider 已删除");
  } catch (error) {
    toast(error.message);
  }
}

function switchTab(button) {
  $$(".tab").forEach((tab) => tab.classList.toggle("active", tab === button));
  $$(".tab-pane").forEach((pane) =>
    pane.classList.toggle("active", pane.id === `tab-${button.dataset.tab}`),
  );
}

function bind() {
  $("#projectSelect").onchange = (event) => loadProject(event.target.value);
  $("#chapterSearch").addEventListener("input", (event) => {
    state.search = event.target.value || "";
    renderChapters();
  });

  $("#editor").addEventListener("input", scheduleSave);
  $("#chapterTitle").addEventListener("input", scheduleSave);

  $("#newProjectBtn").onclick = createProject;
  $("#deleteProjectBtn").onclick = deleteCurrentProject;
  $("#addChapterBtn").onclick = createChapter;
  $("#deleteChapterBtn").onclick = deleteCurrentChapter;
  $("#focusBtn").onclick = toggleFocusMode;
  $("#mobileNavBtn").onclick = toggleMobileNav;

  $$("[data-ai]").forEach((button) => {
    button.onclick = () => runAi(button.dataset.ai);
  });

  $("#insertAiBtn").onclick = appendAiResult;
  $("#replaceAiBtn").onclick = replaceWithAiResult;

  $$(".tab").forEach((button) => {
    button.onclick = () => switchTab(button);
  });

  $("#newTaskBtn").onclick = createWritingTask;
  $("#addMemoryBtn").onclick = createMemory;
  $("#addSkillBtn").onclick = createSkill;
  $("#linkContentRepoBtn").onclick = linkContentRepository;
  $("#preflightContentRepoBtn").onclick = preflightContentRepository;
  $("#importContentRepoBtn").onclick = importContentRepository;
  $("#approveTaskBtn").onclick = () => decideTask("approved");
  $("#rejectTaskBtn").onclick = () => decideTask("rejected");
  $("#closeTaskBtn").onclick = () => $("#taskDialog").close();
  $("#taskDialog").addEventListener("close", stopTaskPolling);

  $("#addCharacterBtn").onclick = createCharacter;
  $("#addWorldBtn").onclick = createWorldNote;

  $("#newProviderBtn").onclick = newProvider;
  $("#saveProviderBtn").onclick = saveProvider;
  $("#cancelProviderBtn").onclick = resetProviderEditor;
  $("#providerProtocol").onchange = syncProviderProtocolFields;

  $("#historyBtn").onclick = showHistory;
  $("#closeHistoryBtn").onclick = () => $("#historyDialog").close();

  document.addEventListener("keydown", async (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      try {
        await saveChapter(true);
        toast("已保存");
      } catch {
        // saveChapter already reports the error.
      }
    }

    if (event.key === "Escape" && document.body.classList.contains("focus-mode")) {
      toggleFocusMode();
    }
    if (event.key === "Escape" && document.body.classList.contains("mobile-nav-open")) {
      closeMobileNav();
    }
  });

  window.addEventListener("beforeunload", (event) => {
    if (state.saveTimer) {
      event.preventDefault();
    }
  });
}

initTheme();
initLyraHubBridge();
bind();
Promise.all([loadProjects(), loadProviders()]).catch((error) => {
  clearWorkspace();
  toast(error.message);
});
