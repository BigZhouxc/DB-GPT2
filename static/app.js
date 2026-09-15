/**
 * 智能问数 Agent — 前端应用 v3
 * 参照 DB-GPT 卡片式设计，简化模式选择，修复问答路由
 */

const API_BASE = "";
const State = {
  currentPage: "ask",
  sidebarCollapsed: false,
  health: {},
  chatHistory: [],
  isStreaming: true,
  selectedModel: "",
  // 模式：根据选中的工具自动推断
  //   - 选了数据源 → react_agent（NL2SQL+执行）
  //   - 选了知识库 → knowledge_agent（知识检索）
  //   - 都没选 → chat_normal（纯对话）
  selectedDatasource: "",
  selectedKnowledge: "",
  selectedSkill: "",
  selectedConnectors: [],   // MCP 连接器 ID 列表（多选）
  attachedFiles: [],        // 会话附件（已上传文件: {file_id,name}）
  datasourceList: [],
  knowledgeSpaces: [],
  skillList: [],
  modelList: [],
  connectorList: [],
  conversationList: [],
  currentSessionId: "",
};

// ==========================================================================
// API 封装
// ==========================================================================
async function api(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body) opts.body = JSON.stringify(body);
  const resp = await fetch(API_BASE + path, opts);
  const data = await resp.json();
  if (!resp.ok && !data.ok) throw new Error(data.detail || JSON.stringify(data));
  return data;
}

async function apiStream(path, body, onChunk) {
  const resp = await fetch(API_BASE + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop();
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        const text = line.slice(6);
        if (text === "[DONE]") return;
        onChunk(text);
      }
    }
  }
}

async function apiStreamSSE(path, body, onData, signal) {
  const opts = { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  if (signal) opts.signal = signal;
  const resp = await fetch(API_BASE + path, opts);
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop();
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        const text = line.slice(6).trim();
        if (!text || text === "[DONE]") continue;
        try { onData(JSON.parse(text)); } catch { onData({ type: "text", content: text }); }
      }
    }
  }
}

// ==========================================================================
// Toast
// ==========================================================================
function toast(msg, type = "info") {
  const c = document.getElementById("toast-container");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = msg;
  c.appendChild(el);
  setTimeout(() => { el.style.animation = "slide-in 0.3s ease reverse"; setTimeout(() => el.remove(), 300); }, 3000);
}

// ==========================================================================
// 路由
// ==========================================================================
const PAGES = {
  ask: { title: "智能问答", subtitle: "数据对话 / 知识库 / 纯对话", icon: "fa-comments" },
  apps: { title: "我的应用", subtitle: "应用管理 / 一键对话", icon: "fa-cube" },
  datasources: { title: "数据源管理", subtitle: "数据库连接管理", icon: "fa-database" },
  knowledge: { title: "知识库管理", subtitle: "知识空间 / 文档", icon: "fa-book" },
  skills: { title: "技能管理", subtitle: "查看 / 上传技能", icon: "fa-wand-magic-sparkles" },
  prompts: { title: "提示词管理", subtitle: "查看 / 创建 / 删除提示词", icon: "fa-pen-nib" },
  models: { title: "模型管理", subtitle: "模型类型 / 启停", icon: "fa-brain" },
  connectors: { title: "MCP 连接器", subtitle: "连接器管理", icon: "fa-plug" },
  conversations: { title: "会话历史", subtitle: "对话历史", icon: "fa-clock-rotate-left" },
};

function navigate(page) {
  // 切走前：保存当前活跃会话快照（不中止 SSE）
  if (State.currentPage === "ask" && page !== "ask") {
    _saveActiveSession();
  }

  // 点击「智能问答」tab 时：总是新建空白会话
  // 活跃会话在后台继续运行（SSE 不中断），用户通过侧边栏切回
  // 从应用新建会话的逻辑也走这里（只是带上数据源/知识库）
  if (page === "ask") {
    // 先保存当前活跃会话（parking 移走 DOM 节点，不中止 SSE）
    _saveActiveSession();
    // 退出应用模式（清除应用锁定，但不影响活跃会话）
    if (_currentAppCode) {
      _currentAppCode = null;
      _currentAppConfig = null;
      const indicator = document.getElementById("app-indicator");
      if (indicator) indicator.style.display = "none";
    }
    // 无条件新建空白会话：清空 State，显示欢迎页
    State.currentSessionId = "";
    _currentConvUid = null;
    State.selectedDatasource = "";
    State.selectedKnowledge = "";
    State.selectedSkill = "";
    State.selectedConnectors = [];
    State.attachedFiles = [];
    State.chatHistory = [];
    _currentActiveConvUid = null;
    _currentViewingConvUid = null; // ★ 新建空白会话，不高亮任何项
    document.getElementById("ask-chat").style.display = "none";
    document.getElementById("ask-welcome").style.display = "flex";
    document.getElementById("chat-messages").innerHTML = "";
    // ★ 清空输入框
    const chatInput = document.getElementById("chat-input");
    if (chatInput) { chatInput.value = ""; chatInput.style.height = "auto"; }
    const heroInput = document.getElementById("hero-input");
    if (heroInput) { heroInput.value = ""; heroInput.style.height = "auto"; }
    // 恢复工具栏可点击
    lockAppToolbar({ database_name: "", knowledge_space: "" });
    syncToolLabels();
    _renderActiveSessions();
    loadRecentSessions();
    // 不 return，继续走下面的 navigate 通用逻辑（切换页面显示）
  }
  State.currentPage = page;
  document.querySelectorAll(".nav-item").forEach(el => el.classList.toggle("active", el.dataset.page === page));
  const cfg = PAGES[page] || {};
  document.getElementById("topbar-title").textContent = cfg.title || page;
  document.getElementById("topbar-subtitle").textContent = cfg.subtitle || "";
  document.querySelectorAll(".page-content").forEach(el => el.classList.add("content-hidden"));
  const target = document.getElementById("page-" + page);
  if (target) {
    target.classList.remove("content-hidden");
    if (page === "datasources") loadDatasources();
    else if (page === "apps") loadApps();
    else if (page === "knowledge") loadKnowledge();
    else if (page === "skills") loadSkills();
    else if (page === "prompts") loadPrompts();
    else if (page === "models") loadModels();
    else if (page === "connectors") loadConnectors();
    else if (page === "conversations") loadConversations();
  }
}

// ==========================================================================
// 问答页 — 工具栏下拉菜单（数据源 / 知识库 / 技能 / MCP 连接器）
// ==========================================================================
// prefix: "" = 欢迎页下拉（dropdown-*），"chat-" = 对话下拉（chat-dropdown-*）
function dropdownItems(type) {
  if (type === "db") return State.datasourceList.map(ds => ({ value: ds.db_name, label: ds.db_name, tag: ds.db_type }));
  if (type === "kb") return State.knowledgeSpaces.map(sp => ({ value: sp.name, label: sp.name, tag: "知识库" }));
  if (type === "skill") return State.skillList.map(s => ({ value: s.name, label: s.name, tag: "技能" }));
  if (type === "conn") return State.connectorList.map(c => ({ value: c.id, label: c.name, tag: c.type || "MCP" }));
  return [];
}

function isToolSelected(type, value) {
  if (type === "db") return State.selectedDatasource === value;
  if (type === "kb") return State.selectedKnowledge === value;
  if (type === "skill") return State.selectedSkill === value;
  if (type === "conn") return State.selectedConnectors.includes(value);
  return false;
}

function dropdownListId(type, prefix) {
  return (prefix || "") + "dropdown-" + type + "-list";
}

function renderDropdown(type, prefix) {
  prefix = prefix || "";
  const list = document.getElementById(dropdownListId(type, prefix));
  if (!list) return;
  const items = dropdownItems(type);
  if (items.length === 0) {
    list.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text-tertiary);font-size:13px">暂无可用项</div>';
    return;
  }
  list.innerHTML = items.map(item => {
    const selected = isToolSelected(type, item.value);
    const safeVal = String(item.value).replace(/'/g, "\\'").replace(/\"/g, "&quot;");
    const safeLabel = String(item.label).replace(/'/g, "\\'");
    return `<div class="tool-dropdown-item ${selected ? 'selected' : ''}" onclick="selectTool('${type}','${safeVal}','${safeLabel}','${prefix}')">
      <span>${escapeHtml(item.label)}</span>
      <span class="tag tag-blue">${escapeHtml(item.tag)}</span>
    </div>`;
  }).join("");
}

function filterDropdown(type, keyword) {
  // type 形如 "db"/"kb"/"skill"/"conn"（欢迎页）或 "chat-skill"/"chat-conn"（对话）
  const listId = type.startsWith("chat-")
    ? "chat-dropdown-" + type.slice(5) + "-list"
    : "dropdown-" + type + "-list";
  const items = document.querySelectorAll(`#${listId} .tool-dropdown-item`);
  items.forEach(el => {
    const text = el.textContent.toLowerCase();
    el.style.display = text.includes(keyword.toLowerCase()) ? "" : "none";
  });
}

function dropdownElId(type, prefix) {
  return (prefix || "") + "dropdown-" + type;
}

function selectTool(type, value, label, prefix) {
  prefix = prefix || "";
  if (type === "db") {
    State.selectedDatasource = State.selectedDatasource === value ? "" : value;
    syncButton("tool-db", State.selectedDatasource || "数据源", "tool-db-label", State.selectedDatasource, "chat-tool-db", "chat-tool-db-label");
  } else if (type === "kb") {
    State.selectedKnowledge = State.selectedKnowledge === value ? "" : value;
    syncButton("tool-kb", label, "tool-kb-label", State.selectedKnowledge, "chat-tool-kb", "chat-tool-kb-label");
  } else if (type === "skill") {
    State.selectedSkill = State.selectedSkill === value ? "" : value;
    syncButton("tool-skill", label, "tool-skill-label", State.selectedSkill, "chat-tool-skill", "chat-tool-skill-label");
  } else if (type === "conn") {
    const idx = State.selectedConnectors.indexOf(value);
    if (idx >= 0) State.selectedConnectors.splice(idx, 1);
    else State.selectedConnectors.push(value);
    const text = State.selectedConnectors.length ? `连接器 (${State.selectedConnectors.length})` : "连接器";
    syncButton("tool-conn", text, "tool-conn-label", State.selectedConnectors.length, "chat-tool-conn", "chat-tool-conn-label");
  }
  const dd = document.getElementById(dropdownElId(type, prefix));
  if (dd) dd.style.display = "none";
  updateChatContextDisplay();
  renderDropdown(type, prefix);
  renderDropdown(type, "chat-");
}

// 同步按钮文本与高亮（支持 hero 与 chat 两处同名按钮）
function syncButton(btnId, text, labelId, activeVal, btnId2, labelId2) {
  const b1 = document.getElementById(btnId);
  if (b1) b1.classList.toggle("active", !!activeVal);
  if (labelId) { const l = document.getElementById(labelId); if (l) l.textContent = text; }
  if (btnId2) { const b2 = document.getElementById(btnId2); if (b2) b2.classList.toggle("active", !!activeVal); }
  if (labelId2) { const l2 = document.getElementById(labelId2); if (l2) l2.textContent = text; }
}

function toggleToolMenu(type) {
  const dd = document.getElementById("dropdown-" + type);
  const others = ["db", "kb", "skill", "conn"].filter(t => t !== type);
  others.forEach(t => { const o = document.getElementById("dropdown-" + t); if (o) o.style.display = "none"; });
  if (dd.style.display === "none") {
    renderDropdown(type, "");
    dd.style.display = "block";
  } else {
    dd.style.display = "none";
  }
}

function toggleChatToolMenu(type) {
  const dd = document.getElementById("chat-dropdown-" + type);
  const others = ["db", "kb", "skill", "conn"].filter(t => t !== type);
  others.forEach(t => { const o = document.getElementById("chat-dropdown-" + t); if (o) o.style.display = "none"; });
  if (dd.style.display === "none") {
    renderDropdown(type, "chat-");
    dd.style.display = "block";
  } else {
    dd.style.display = "none";
  }
}

function updateChatContextDisplay() {
  const el = document.getElementById("chat-context-display");
  if (!el) return;
  let parts = [];
  if (State.selectedDatasource) parts.push(`📊 ${State.selectedDatasource}`);
  if (State.selectedKnowledge) parts.push(`📚 ${State.selectedKnowledge}`);
  if (State.selectedSkill) parts.push(`🧩 ${State.selectedSkill}`);
  if (State.selectedConnectors.length) parts.push(`🔌 ${State.selectedConnectors.length} 个连接器`);
  el.textContent = parts.join(" | ");
}

// 推荐示例
function useExample(question, sourceType, sourceValue) {
  State.selectedDatasource = "";
  State.selectedKnowledge = "";
  if (sourceType === "db") {
    State.selectedDatasource = sourceValue;
    document.getElementById("tool-db-label").textContent = sourceValue;
    document.getElementById("tool-db").classList.add("active");
  }
  document.getElementById("hero-input").value = question;
  autoResize(document.getElementById("hero-input"));
}

// ==========================================================================
// 会话附件（本地文件）—— 上传到 DB-GPT session_file，供 react-agent 使用
// ==========================================================================
async function handleFileSelect(input) {
  const files = Array.from(input.files || []);
  input.value = "";
  if (!files.length) return;
  if (!State.currentSessionId) {
    try {
      const r = await fetch(API_BASE + "/conversations/new", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) });
      const d = await r.json();
      if (d.ok && d.conversation && d.conversation.data) State.currentSessionId = d.conversation.data.conv_uid;
    } catch { /* 忽略：仍可上传 */ }
  }
  const form = new FormData();
  if (State.currentSessionId) form.append("session_id", State.currentSessionId);
  files.forEach(f => form.append("files", f));
  toast(`正在上传 ${files.length} 个文件...`, "info");
  try {
    const resp = await fetch(API_BASE + "/files/upload", { method: "POST", body: form });
    const data = await resp.json();
    if (!resp.ok || !data.ok) throw new Error(data.detail || JSON.stringify(data));
    (data.files || []).forEach(f => {
      if (f.file_id) State.attachedFiles.push({ file_id: f.file_id, name: f.name || "file" });
    });
    renderAttachedFiles();
    updateChatContextDisplay();
    toast(`已上传 ${data.files.length} 个文件`, "success");
  } catch (err) {
    toast("上传失败: " + err.message, "error");
  }
}

function renderAttachedFiles() {
  // 同时渲染到欢迎页和对话输入区两处
  const targets = ["hero-attached-files", "attached-files"]
    .map(id => document.getElementById(id))
    .filter(Boolean);
  if (!targets.length) return;
  if (!State.attachedFiles.length) {
    targets.forEach(box => { box.style.display = "none"; box.innerHTML = ""; });
    return;
  }
  const html = State.attachedFiles.map(f =>
    `<span class="file-chip" title="${escapeHtml(f.name)}">📎 ${escapeHtml(f.name)}
      <i class="fa-solid fa-xmark" onclick="removeAttachedFile('${f.file_id}')"></i></span>`
  ).join("");
  targets.forEach(box => { box.style.display = "flex"; box.innerHTML = html; });
}

function removeAttachedFile(fileId) {
  State.attachedFiles = State.attachedFiles.filter(f => f.file_id !== fileId);
  // 同步删除服务端会话文件（忽略失败）
  fetch(API_BASE + "/files/" + fileId, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: State.currentSessionId ? JSON.stringify({ session_id: State.currentSessionId }) : undefined,
  }).catch(() => {});
  renderAttachedFiles();
  updateChatContextDisplay();
}

// ==========================================================================
// 问答核心逻辑
// ==========================================================================
function inferMode() {
  // 优先数据源：react_agent（NL2SQL）或 react_agent_both（DB+知识库）
  if (State.selectedDatasource) {
    if (State.selectedKnowledge) return "react_agent_both";
    return "react_agent";
  }
  // 纯知识库
  if (State.selectedKnowledge) return "knowledge_agent";
  // 技能 / MCP 连接器 / 附件 → 走 ReAct Agent（工具 + 文件上下文）
  if (State.selectedSkill || State.selectedConnectors.length || State.attachedFiles.length) return "react_agent";
  return "chat_normal";
}

function getModeLabel() {
  const m = inferMode();
  if (m === "react_agent_both") return "智能Agent (数据库+知识库)";
  if (m === "react_agent") return "智能Agent (NL2SQL / 技能 / 工具)";
  if (m === "knowledge_agent") return "知识库Agent";
  return "纯对话";
}

function autoResize(textarea) {
  textarea.style.height = "auto";
  textarea.style.height = Math.min(textarea.scrollHeight, 200) + "px";
}

function handleChatKey(e) {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendQuestion(); }
}

// 从欢迎页输入框发送 — Enter 发送 / Shift+Enter 换行
function handleHeroKey(e) {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendFromHero(); }
}

// 从欢迎页发送
function sendFromHero() {
  const input = document.getElementById("hero-input");
  const question = input.value.trim();
  if (!question) return;
  // ★ 清空 hero 输入框
  input.value = "";
  input.style.height = "auto";
  // 切换到对话视图
  document.getElementById("ask-welcome").style.display = "none";
  document.getElementById("ask-chat").style.display = "flex";
  document.getElementById("chat-mode-info").textContent = `模式: ${getModeLabel()}`;
  updateChatContextDisplay();
  // 直接发送，sendQuestion 中的安全网会延迟创建会话
  sendQuestion(question);
}

function clearChat() {
  State.chatHistory = [];
  State.currentSessionId = "";
  document.getElementById("ask-chat").style.display = "none";
  document.getElementById("ask-welcome").style.display = "flex";
  document.getElementById("chat-messages").innerHTML = "";
}

async function newChatSession() {
  // 先保存当前活跃会话（如果有）
  _saveActiveSession();
  // 把当前会话状态设为 inactive（已结束）
  const oldUid = _currentConvUid || State.currentSessionId;
  if (oldUid) {
    fetch(API_BASE + "/conversations/set-status", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ conv_uid: oldUid, status: "inactive" }),
    }).catch(() => {});
  }
  // 如果在应用模式，新建应用会话（保留 app 配置，清空对话区）
  if (_currentAppCode) {
    await newAppSession();
    return;
  }
  // 非应用模式：回到空白首页
  State.currentSessionId = "";
  _currentConvUid = null;
  _currentActiveConvUid = null;
  _currentViewingConvUid = null; // ★ 新建会话，不高亮任何项
  State.chatHistory = [];
  State.selectedDatasource = "";
  State.selectedKnowledge = "";
  State.selectedSkill = "";
  State.selectedConnectors = [];
  State.attachedFiles = [];
  document.getElementById("ask-chat").style.display = "none";
  document.getElementById("ask-welcome").style.display = "flex";
  document.getElementById("chat-messages").innerHTML = "";
  // ★ 清空输入框
  const chatInput = document.getElementById("chat-input");
  if (chatInput) { chatInput.value = ""; chatInput.style.height = "auto"; }
  const heroInput = document.getElementById("hero-input");
  if (heroInput) { heroInput.value = ""; heroInput.style.height = "auto"; }
  // 恢复工具栏可点击
  lockAppToolbar({ database_name: "", knowledge_space: "" });
  syncToolLabels();
  _renderActiveSessions();
  loadRecentSessions();
  toast("已新建会话", "info");
}

// 同步工具栏下拉标签到当前 State
function syncToolLabels() {
  const dbLabel = document.getElementById("tool-db-label");
  if (dbLabel) dbLabel.textContent = State.selectedDatasource ? State.selectedDatasource : "数据源";
  const kbLabel = document.getElementById("tool-kb-label");
  if (kbLabel) kbLabel.textContent = State.selectedKnowledge ? State.selectedKnowledge : "知识库";
  const chatDbLabel = document.getElementById("chat-tool-db-label");
  if (chatDbLabel) chatDbLabel.textContent = State.selectedDatasource ? State.selectedDatasource : "数据源";
  const chatKbLabel = document.getElementById("chat-tool-kb-label");
  if (chatKbLabel) chatKbLabel.textContent = State.selectedKnowledge ? State.selectedKnowledge : "知识库";
}

function appendMessage(role, text) {
  const container = document.getElementById("chat-messages");
  const avatar = role === "user" ? "&#128100;" : "&#129302;";
  const roleName = role === "user" ? "我" : "Assistant";
  const escaped = role === "user" ? escapeHtml(text) : text;
  const msgEl = document.createElement("div");
  msgEl.className = `msg msg-${role}`;
  msgEl.innerHTML = `<div class="msg-avatar">${avatar}</div><div class="msg-content"><div class="msg-role">${roleName}</div><div class="msg-text" id="msg-${Date.now()}">${escaped}</div></div>`;
  container.appendChild(msgEl);
  container.scrollTop = container.scrollHeight;
  return msgEl.querySelector(".msg-text");
}

function escapeHtml(text) { const d = document.createElement("div"); d.textContent = text; return d.innerHTML; }

async function sendQuestion(presetQuestion) {
  const input = document.getElementById("chat-input");
  const question = (presetQuestion || input.value || "").trim();
  if (!question) return;

  if (presetQuestion) {
    appendMessage("user", question);
  } else {
    appendMessage("user", question);
    input.value = "";
    input.style.height = "auto";
  }

  // ★ 先切 UI（非阻塞），让用户立即看到反馈
  const mode = inferMode();
  const sendBtn = document.getElementById("chat-send-btn");
  const stopBtn = document.getElementById("chat-stop-btn");
  if (sendBtn) sendBtn.disabled = true;
  if (sendBtn) sendBtn.style.display = "none";
  if (stopBtn) stopBtn.style.display = "flex";

  // 延迟创建会话（参考 Hermes createBackendSessionForSend）
  // 只有首次发送时才创建后端会话，后续复用同一会话 ID
  // ★ 改为 await 但在 UI 变化之后执行，减少用户感知延迟
  if (!State.currentSessionId && !_currentConvUid) {
    try {
      const body = {
        datasource_name: State.selectedDatasource || "",
        knowledge_space_name: State.selectedKnowledge || "",
      };
      if (_currentAppCode && _currentAppConfig?.resources?.prompt_template) {
        body.prompt_code = _currentAppConfig.resources.prompt_template;
      }
      const resp = await fetch(API_BASE + "/conversations/new", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body),
      });
      const data = await resp.json();
      if (data.ok && data.conversation) {
        const inner = data.conversation.data || data.conversation;
        State.currentSessionId = inner.conv_uid || "";
        _currentConvUid = inner.conv_uid || "";
        _currentActiveConvUid = inner.conv_uid;
        _currentViewingConvUid = inner.conv_uid;
        // 新会话设为 active（进行中）— fire-and-forget
        fetch(API_BASE + "/conversations/set-status", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({ conv_uid: inner.conv_uid, status: "active" }),
        }).catch(() => {});
        _ensureSessionState(inner.conv_uid);
      }
    } catch {}
  }

  _getAbortController(); // 确保当前会话有独立的 AbortController
  // ★ 在发送时捕获当前会话 UID，整个 SSE 生命周期使用此值（防止用户切换会话后 UID 漂移）
  const sessionUid = _currentConvUid || State.currentSessionId;
  if (sessionUid) _setSessionWorking(sessionUid, true);
  _renderActiveSessions();
  loadRecentSessions(); // ★ 立即刷新"最近会话"列表，把该会话从最近会话中移除（避免延迟）

  const common = {
    session: _currentAppCode ? (_currentConvUid || "") : (State.currentSessionId || ""),
    temperature: mode === "chat_normal" ? 0.2 : 0.6,
    max_new_tokens: 4000,
  };
  // 构建 react-agent 请求：携带 数据源 / 知识库 / 技能 / MCP连接器 / 附件文件
  const reactBody = Object.assign({}, common, {
    question,
    chat_param: State.selectedDatasource,
    knowledge_space: State.selectedKnowledge || "",
    skill_name: State.selectedSkill || "",
    connector_ids: State.selectedConnectors,
    file_ids: State.attachedFiles.map(f => f.file_id),
    prompt_code: (_currentAppCode && _currentAppConfig?.resources?.prompt_template) || null,
    model_name: (_currentAppCode && _currentAppConfig?.resources?.model) || document.getElementById("hero-model")?.value || null,
  });
  const kbParam = mode === "knowledge_agent" ? State.selectedKnowledge : "";

  const aiTextEl = appendMessage("ai", '<div class="typing-indicator"><span></span><span></span><span></span></div>');

  try {
    if (mode === "react_agent" || mode === "react_agent_both") {
      await sendReactAgent(reactBody, aiTextEl);
    } else if (mode === "knowledge_agent") {
      await sendKnowledgeAgent({
        question,
        chat_param: kbParam,
        file_ids: State.attachedFiles.map(f => f.file_id),
        session: State.currentSessionId || "",
      }, aiTextEl);
    } else {
      // 纯对话走 /ask/stream（SDK chat_stream），获得真正的逐字流式输出
      await sendSimpleStream({
        question,
        session: State.currentSessionId || "",
        temperature: 0.2,
        max_new_tokens: 4000,
      }, aiTextEl);
    }
  } catch (err) {
    aiTextEl.innerHTML = `<span style="color:var(--danger)">请求失败: ${escapeHtml(err.message)}</span>`;
  }

  // SSE 完成：清理当前会话的 AbortController，切换按钮
  // ★ 使用捕获的 sessionUid 而非 _currentConvUid（防止用户切换会话后 UID 漂移）
  const convKey = sessionUid || "_default";
  delete _abortControllers[convKey];
  if (sessionUid) {
    _setSessionWorking(sessionUid, false);
    // ★ set-status 改为 fire-and-forget（不 await），先刷新 UI 再后台写状态
    fetch(API_BASE + "/conversations/set-status", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ conv_uid: sessionUid, status: "inactive" }),
    }).catch(() => {});
  }
  // 只有当当前显示的会话 == sessionUid 时才切换按钮（用户可能已切到其他会话）
  if (_currentActiveConvUid === sessionUid) {
    if (sendBtn) sendBtn.disabled = false;
    if (sendBtn) sendBtn.style.display = "flex";
    if (stopBtn) stopBtn.style.display = "none";
  }
  // ★ SSE 完成后不清空聊天界面，只更新侧边栏列表位置（进行中 → 最近会话）
  // 不调用 _saveActiveSession()（那会把 DOM 移到 parking，导致界面清空）
  _renderActiveSessions();
  // ★ 立即刷新"最近会话"列表（前端 _workingSessionIds 已更新，无需等后端 status 写入）
  loadRecentSessions();
  if (input) input.focus();
}

// 停止正在进行的请求
async function stopQuestion() {
  const convKey = _currentConvUid || State.currentSessionId || "_default";
  if (_abortControllers[convKey]) {
    _abortControllers[convKey].abort();
    delete _abortControllers[convKey];
  }
  const stoppedUid = _currentConvUid || State.currentSessionId;
  if (stoppedUid) {
    _setSessionWorking(stoppedUid, false);
    // ★ set-status 改为 fire-and-forget（不 await），先刷新 UI
    fetch(API_BASE + "/conversations/set-status", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ conv_uid: stoppedUid, status: "inactive" }),
    }).catch(() => {});
  }
  const sendBtn = document.getElementById("chat-send-btn");
  const stopBtn = document.getElementById("chat-stop-btn");
  if (sendBtn) { sendBtn.disabled = false; sendBtn.style.display = "flex"; }
  if (stopBtn) stopBtn.style.display = "none";
  _renderActiveSessions();
  // ★ 立即刷新"最近会话"列表
  loadRecentSessions();
  toast("已停止", "info");
}
const AGENT_STAGES = ["解析问题", "检索 / 生成", "执行 / 调用", "汇总回答"];

function buildAgentProgress(progressEl) {
  if (!progressEl) return;
  const id = progressEl.id;
  progressEl.innerHTML = AGENT_STAGES.map((name, i) =>
    `<div class="agent-stage" id="${id}-s${i}" data-idx="${i}">
       <span class="agent-stage-dot"></span><span>${name}</span>
     </div>`
  ).join("") + `<span class="agent-budget" id="${id}-budget" style="display:none"></span>`;
}

function setAgentStage(progressEl, stageIdx, budget) {
  if (!progressEl) return;
  const id = progressEl.id;
  for (let i = 0; i < AGENT_STAGES.length; i++) {
    const el = document.getElementById(`${id}-s${i}`);
    if (!el) continue;
    const done = i < stageIdx, active = i === stageIdx;
    el.classList.toggle("done", done);
    el.classList.toggle("active", active);
  }
  const budgetEl = document.getElementById(`${id}-budget`);
  if (budgetEl) {
    if (budget != null) {
      budgetEl.style.display = "inline-block";
      budgetEl.textContent = `上下文预算 ${Math.round(budget * 100)}%`;
    } else if (stageIdx >= AGENT_STAGES.length) {
      budgetEl.style.display = "none";
    }
  }
}

// 渲染 final 事件中的引用（citations）
function renderCitations(containerEl, citations) {
  if (!containerEl || !Array.isArray(citations) || !citations.length) return;
  containerEl.innerHTML += `<div class="react-citations"><div class="react-citations-title">📚 参考来源</div>` +
    citations.map((c, i) =>
      `<div class="react-citation"><span class="react-citation-idx">[${i + 1}]</span>
         <span class="react-citation-src">${escapeHtml(c.sourceName || c.source_name || c.path || "来源")}</span>
         <span class="react-citation-excerpt">${escapeHtml((c.excerpt || "").slice(0, 120))}</span></div>`
    ).join("") + `</div>`;
}

// ==========================================================================
// React Agent 流式渲染
// ==========================================================================
async function sendReactAgent(body, aiTextEl) {
  // 使用唯一前缀避免多消息间的 ID 冲突
  const uid = Date.now() + "-" + Math.random().toString(36).slice(2, 8);
  aiTextEl.innerHTML = `<div class="agent-progress" id="agent-progress-${uid}"></div><div class="react-steps" id="react-steps-${uid}"></div><div id="react-final-${uid}"></div>`;
  const progressEl = aiTextEl.querySelector(`#agent-progress-${uid}`);
  buildAgentProgress(progressEl);
  setAgentStage(progressEl, 0);
  const stepsContainer = aiTextEl.querySelector(`#react-steps-${uid}`);
  const finalContainer = aiTextEl.querySelector(`#react-final-${uid}`);
  let currentStepId = null;
  let stepCount = 0;
  let stepEls = {};  // stepId → { wrapper, bodyEl, badgeEl, actionEl, rawContent: "" }

  await apiStreamSSE("/ask/react-agent", body, (data) => {
    if (!data) return;
    const type = data.type;

    if (type === "context.status") {
      setAgentStage(progressEl, 0, data.ratio != null ? data.ratio : null);
      return;
    }
    if (type === "step.start") {
      const stepId = data.id || `step-${stepCount}`;
      currentStepId = stepId;
      // 工具类型判断：数据源选择/数据表选择有特殊渲染
      const toolType = data.tool_type || "";
      const toolName = data.tool_name || data.title || data.detail || (toolType === "datasource_select" ? "数据源选择" : toolType === "table_select" ? "数据表选择" : "思考中");
      if (!stepEls[stepId]) {
        stepCount++;
        const stepEl = document.createElement("div");
        stepEl.className = "react-step" + (toolType ? " tool-step" : "");
        stepEl.innerHTML = `<div class="react-step-header" onclick="toggleReactStep('${uid}-${stepId}')">
          <span class="react-step-badge">${stepCount}</span>
          <span class="react-step-action">${escapeHtml(toolName)}</span>
          <span class="react-step-toggle"><i class="fa-solid fa-chevron-down"></i></span>
        </div><div class="react-step-body" id="react-body-${uid}-${stepId}"><div class="react-step-loading">等待数据...</div></div>`;
        stepsContainer.appendChild(stepEl);
        stepEls[stepId] = {
          wrapper: stepEl,
          bodyEl: stepEl.querySelector(`#react-body-${uid}-${stepId}`),
          badgeEl: stepEl.querySelector(".react-step-badge"),
          actionEl: stepEl.querySelector(".react-step-action"),
          rawContent: "",
          _pendingRender: false,
          toolType: toolType,
        };
      } else {
        const entry = stepEls[stepId];
        entry.toolType = toolType;
        if (entry.actionEl && (data.title || data.detail || toolName)) {
          entry.actionEl.textContent = toolName;
        }
      }
      scrollChatBottom();
    } else if (type === "step.meta") {
      const stepId = data.id || currentStepId || `step-${stepCount}`;
      currentStepId = stepId;
      setAgentStage(progressEl, 1);
      const entry = stepEls[stepId];
      if (entry && entry.bodyEl) {
        const bodyEl = entry.bodyEl;
        bodyEl.innerHTML = "";

        // ========== 工具定制化渲染 ==========
        if (data.tool_type === "datasource_select" || entry.toolType === "datasource_select") {
          const result = data.result || {};
          let html = "";
          if (data.thought) html += `<div class="react-step-thought-full">💭 ${escapeHtml(data.thought)}</div>`;
          html += `<div class="tool-result-card tool-ds-card">
            <span class="tool-label">已选择数据源</span>
            <span class="tool-value tool-ds-name">${escapeHtml(result.datasource || "未选择")}</span>`;
          if (result.reason) html += `<div class="tool-reason">${escapeHtml(result.reason)}</div>`;
          if (result.fallback) html += `<div class="tool-badge-fallback">自动兜底</div>`;
          html += `</div>`;
          bodyEl.innerHTML = html;
          scrollChatBottom();
          return;
        }

        if (data.tool_type === "table_select" || entry.toolType === "table_select") {
          const result = data.result || {};
          let html = "";
          if (data.thought) html += `<div class="react-step-thought-full">💭 ${escapeHtml(data.thought)}</div>`;
          html += `<div class="tool-result-card tool-tbl-card">
            <span class="tool-label">已选择数据表</span>`;
          if (result.tables && result.tables.length > 0) {
            html += `<div class="tool-tables">`;
            result.tables.forEach(t => {
              html += `<span class="tool-table-tag">${escapeHtml(t)}</span>`;
            });
            html += `</div>`;
            // 显示选中字段
            if (result.fields) {
              let fieldsHtml = "";
              for (const [tbl, cols] of Object.entries(result.fields)) {
                if (cols && cols.length > 0) {
                  fieldsHtml += `<div class="tool-fields-row"><span class="tool-fields-tbl">${escapeHtml(tbl)}</span><span class="tool-fields-cols">${escapeHtml(cols.join(", "))}</span></div>`;
                }
              }
              if (fieldsHtml) html += `<div class="tool-fields">${fieldsHtml}</div>`;
            }
          } else {
            html += `<div class="tool-empty">未选择数据表</div>`;
          }
          if (result.reason) html += `<div class="tool-reason">${escapeHtml(result.reason)}</div>`;
          if (result.fallback) html += `<div class="tool-badge-fallback">自动兜底</div>`;
          html += `</div>`;
          bodyEl.innerHTML = html;
          scrollChatBottom();
          return;
        }

        // ========== 默认渲染（DB-GPT react-agent 原生步骤） ==========
        let content = "";
        if (data.thought) content += `<div class="react-step-thought-full">💭 ${escapeHtml(data.thought)}</div>`;
        if (data.action) content += `<div class="react-step-action-label">🔧 动作: <code>${escapeHtml(data.action)}</code></div>`;
        if (data.action_input) {
          try {
            const ai = JSON.parse(data.action_input);
            if (ai.sql) content += `<div class="react-step-sql">${escapeHtml(ai.sql)}</div>`;
          } catch {
            content += `<div class="react-step-sql">${escapeHtml(data.action_input)}</div>`;
          }
        }
        if (content) bodyEl.innerHTML = content;
      }
    } else if (type === "step.chunk" || type === "step.output") {
      const stepId = data.id || currentStepId || `step-${stepCount}`;
      const entry = stepEls[stepId];
      setAgentStage(progressEl, 2);
      if (entry && entry.bodyEl && data.content) {
        const loading = entry.bodyEl.querySelector(".react-step-loading");
        if (loading) loading.remove();
        entry.rawContent += data.content;
        // ★ 节流：用 rAF + 脏标记，避免每个 chunk 都全量 renderMarkdown
        if (!entry._pendingRender) {
          entry._pendingRender = true;
          requestAnimationFrame(() => {
            entry._pendingRender = false;
            const metaNodes = entry.bodyEl.querySelectorAll(".react-step-thought-full, .react-step-action-label, .react-step-sql");
            let metaHtml = "";
            metaNodes.forEach(n => { metaHtml += n.outerHTML; });
            entry.bodyEl.innerHTML = metaHtml + renderMarkdown(entry.rawContent);
            scrollChatBottom();
          });
        }
      }
    } else if (type === "step.done") {
      const stepId = data.id || currentStepId || `step-${stepCount}`;
      const entry = stepEls[stepId];
      if (entry && entry.badgeEl) {
        entry.badgeEl.classList.add("done");
        if (data.status === "failed") {
          entry.badgeEl.classList.add("failed");
          if (entry.actionEl && !entry.actionEl.textContent.includes("失败"))
            entry.actionEl.textContent += " (失败)";
        }
      }
    } else if (type === "final") {
      setAgentStage(progressEl, 3);
      if (data.content) {
        // 如果当前步骤的 rawContent 为空或包含错误信息，用 final 内容替换
        const currentEntry = stepEls[currentStepId];
        if (currentEntry && currentEntry.bodyEl) {
          // 移除"等待数据..."占位符
          const loadingPlaceholder = currentEntry.bodyEl.querySelector(".react-step-loading");
          if (loadingPlaceholder) {
            loadingPlaceholder.remove();
          }
          
          // 检查 rawContent 是否为空或包含错误信息
          const isError = !currentEntry.rawContent || 
                          currentEntry.rawContent.trim() === "" ||
                          currentEntry.rawContent.includes("No correct response found") ||
                          currentEntry.rawContent.includes("execute failed");
          
          if (isError) {
            currentEntry.rawContent = data.content;
          }
          
          // 保留 meta 阶段插入的 thought/action/sql（如果存在）
          const metaNodes = currentEntry.bodyEl.querySelectorAll(".react-step-thought-full, .react-step-action-label, .react-step-sql");
          let metaHtml = "";
          metaNodes.forEach(n => { metaHtml += n.outerHTML; });
          
          // 渲染内容到思考区域
          currentEntry.bodyEl.innerHTML = metaHtml + renderMarkdown(currentEntry.rawContent);
        }
        // 同时在 finalContainer 也显示（保持兼容性）
        finalContainer.innerHTML = `<div class="react-final">${renderMarkdown(data.content)}</div>`;
      }
      renderCitations(finalContainer, data.citations);
      scrollChatBottom();
    } else if (type === "error") {
      finalContainer.innerHTML = `<div class="react-error">⚠️ ${escapeHtml(data.message || "未知错误")}</div>`;
    } else if (type === "done") {
      // 流结束 —— 兜底确保进度条走到最后一步
      setAgentStage(progressEl, 3);
    }
  }, _currentSignal());
  Object.values(stepEls).forEach(entry => {
    if (entry.bodyEl && entry.bodyEl.querySelector(".react-step-loading")) {
      entry.bodyEl.querySelector(".react-step-loading").textContent = "无输出";
    }
  });
  // 兜底：确保进度条完成
  setAgentStage(progressEl, 3);
  // 兜底：若完全没有内容，避免空白的回答气泡
  const hasOutput = finalContainer.innerHTML.trim() !== "" || Object.keys(stepEls).length > 0;
  if (!hasOutput) {
    finalContainer.innerHTML = '<div class="react-error">⚠️ 未收到有效响应，请检查 DB-GPT 服务是否可用，或换个问法重试。</div>';
  }
}

// ==========================================================================
// 纯对话流式渲染（走 /ask/stream，SDK chat_stream 逐字 delta）
// ==========================================================================
async function sendSimpleStream(body, aiTextEl) {
  // 简洁 UI：打字机指示器 → 逐字累积渲染
  aiTextEl.innerHTML = '<div class="typing-indicator"><span></span><span></span><span></span></div>';
  let rawContent = "";
  // ★ 节流：用 rAF + 脏标记，避免每个 chunk 都全量 renderMarkdown
  let _pendingRender = false;
  let _finalRender = false;
  function _scheduleRender() {
    if (_pendingRender) return;
    _pendingRender = true;
    requestAnimationFrame(() => {
      _pendingRender = false;
      aiTextEl.innerHTML = renderMarkdown(rawContent);
      if (!_finalRender) scrollChatBottom();
    });
  }

  await apiStreamSSE("/ask/stream", body, (data) => {
    if (!data) return;
    const type = data.type;

    if (type === "chunk") {
      if (data.content) {
        const typing = aiTextEl.querySelector(".typing-indicator");
        if (typing) typing.remove();
        rawContent += data.content;
        _scheduleRender(); // ★ 节流渲染
      }
    } else if (type === "done") {
      const typing = aiTextEl.querySelector(".typing-indicator");
      if (typing) typing.remove();
      // ★ 最终渲染（确保完整内容显示）
      _finalRender = true;
      aiTextEl.innerHTML = renderMarkdown(rawContent);
      if (!rawContent.trim()) {
        aiTextEl.innerHTML = '<div class="react-error">⚠️ 未收到有效响应</div>';
      }
    } else if (type === "error") {
      const typing = aiTextEl.querySelector(".typing-indicator");
      if (typing) typing.remove();
      aiTextEl.innerHTML = `<div class="react-error">⚠️ ${escapeHtml(data.message || "未知错误")}</div>`;
    }
  }, _currentSignal());
}

// ==========================================================================
// Knowledge Agent 流式渲染
// ==========================================================================
async function sendKnowledgeAgent(body, aiTextEl) {
  const uid = Date.now() + "-" + Math.random().toString(36).slice(2, 8);
  aiTextEl.innerHTML = `<div class="agent-progress" id="agent-progress-${uid}"></div><div class="react-steps" id="react-steps-${uid}"></div><div id="react-final-${uid}"></div>`;
  const progressEl = aiTextEl.querySelector(`#agent-progress-${uid}`);
  buildAgentProgress(progressEl);
  setAgentStage(progressEl, 0);
  const stepsContainer = aiTextEl.querySelector(`#react-steps-${uid}`);
  const finalContainer = aiTextEl.querySelector(`#react-final-${uid}`);
  let currentStepId = null;
  let stepCount = 0;
  let finalContent = "";
  let stepEls = {};  // stepId → { wrapper, bodyEl, rawContent: "" }

  await apiStreamSSE("/ask/knowledge-agent", body, (data) => {
    if (!data) return;
    const type = data.type;

    if (type === "context.status") {
      setAgentStage(progressEl, 0, data.ratio != null ? data.ratio : null);
      return;
    }
    if (type === "step.start" || (!type && data.retrieval)) {
      const stepId = data.id || `step-${stepCount}`;
      currentStepId = stepId;
      if (!stepEls[stepId]) {
        stepCount++;
        const stepEl = document.createElement("div");
        stepEl.className = "react-step";
        stepEl.innerHTML = `<div class="react-step-header" onclick="toggleReactStep('${uid}-${stepId}')">
          <span class="react-step-badge">${stepCount}</span>
          <span class="react-step-action">${escapeHtml(data.title || data.detail || "知识检索中")}</span>
          <span class="react-step-toggle"><i class="fa-solid fa-chevron-down"></i></span>
        </div><div class="react-step-body" id="react-body-${uid}-${stepId}"><div class="react-step-loading">检索中...</div></div>`;
        stepsContainer.appendChild(stepEl);
        stepEls[stepId] = {
          wrapper: stepEl,
          bodyEl: stepEl.querySelector(`#react-body-${uid}-${stepId}`),
          rawContent: "",
        };
      }
      scrollChatBottom();
    } else if (type === "step.chunk" || type === "server.chunk" || type === "step.output" || (!type && data.content)) {
      const content = data.content;
      setAgentStage(progressEl, 2);
      if (content) {
        const stepId = data.id || currentStepId;
        if (stepId && type && type.startsWith("step")) {
          const entry = stepEls[stepId];
          if (entry && entry.bodyEl) {
            const loading = entry.bodyEl.querySelector(".react-step-loading");
            if (loading) loading.remove();
            // 累积全文后整体渲染
            entry.rawContent += content;
            entry.bodyEl.innerHTML = renderMarkdown(entry.rawContent);
          }
        } else {
          finalContent += content;
          finalContainer.innerHTML = `<div class="react-final">${renderMarkdown(finalContent)}</div>`;
        }
      }
      scrollChatBottom();
    } else if (type === "final" || type === "server.final") {
      setAgentStage(progressEl, 3);
      if (data.content) {
        finalContent = data.content;
        finalContainer.innerHTML = `<div class="react-final">${renderMarkdown(data.content)}</div>`;
      }
      renderCitations(finalContainer, data.citations);
      scrollChatBottom();
    } else if (type === "step.done") {
      const stepId = data.id || currentStepId || `step-${stepCount}`;
      const entry = stepEls[stepId];
      if (entry && entry.bodyEl && entry.bodyEl.querySelector(".react-step-loading")) {
        entry.bodyEl.querySelector(".react-step-loading").textContent = "无输出";
      }
    } else if (type === "error") {
      finalContainer.innerHTML = `<div class="react-error">⚠️ ${escapeHtml(data.message || "未知错误")}</div>`;
    }
  });

  // 流结束后清理
  Object.values(stepEls).forEach(entry => {
    if (entry.bodyEl && entry.bodyEl.querySelector(".react-step-loading")) {
      entry.bodyEl.querySelector(".react-step-loading").textContent = "无输出";
    }
  });
  // 兜底：确保进度条完成
  setAgentStage(progressEl, 3);
  // 兜底：若完全没有内容，避免空白的回答气泡
  const hasOutput = finalContainer.innerHTML.trim() !== "" || Object.keys(stepEls).length > 0;
  if (!hasOutput) {
    finalContainer.innerHTML = '<div class="react-error">⚠️ 未收到有效响应，请检查 DB-GPT 服务是否可用，或换个问法重试。</div>';
  }
}

function toggleReactStep(fullId) {
  // fullId 格式为 "uid-stepId"，需要找到对应的 body 元素
  const body = document.getElementById(`react-body-${fullId}`);
  if (body) body.classList.toggle("hidden");
}

function scrollChatBottom() {
  const container = document.getElementById("chat-messages");
  if (container) container.scrollTop = container.scrollHeight;
}

// ==========================================================================
// Markdown 渲染器（轻量级，支持表格/列表/代码块/加粗/标题/链接）
// 使用占位符保护代码块和表格内容不被后续正则误伤
// ==========================================================================
function renderMarkdown(md) {
  if (!md) return "";
  const placeholders = [];

  // 保护 HTML 实体（避免在后面的处理中被二次转义）
  // 先抽取代码块和表格，替换为占位符，最后还原

  // 1. 代码块 ```...```
  md = md.replace(/```(\w*)\n?([\s\S]*?)```/g, (m, lang, code) => {
    const idx = placeholders.length;
    placeholders.push(`<pre class="md-code-block"><code>${escapeHtml(code.trim())}</code></pre>`);
    return `\u0000CODE${idx}\u0000`;
  });

  // 2. 行内代码 `code`
  md = md.replace(/`([^`\n]+)`/g, (m, code) => {
    const idx = placeholders.length;
    placeholders.push(`<code class="md-inline-code">${escapeHtml(code)}</code>`);
    return `\u0000CODE${idx}\u0000`;
  });

  // 3. 表格（| header | ... | 和 | --- | ... |）
  md = md.replace(/(?:^|\n)(\|.+\|)\n(\|[\s\-:|]+\|)\n((?:\|.+\|\n?)+)/g, (m, headerRow, sep, bodyRows) => {
    const headers = headerRow.split("|").map(h => h.trim()).filter(h => h !== "");
    let tableHtml = '<table class="md-table"><thead><tr>';
    headers.forEach(h => { tableHtml += `<th>${escapeHtml(h)}</th>`; });
    tableHtml += "</tr></thead><tbody>";
    bodyRows.trim().split("\n").forEach(row => {
      const cells = row.split("|").map(c => c.trim()).filter(c => c !== "");
      if (cells.length > 0) {
        tableHtml += "<tr>";
        cells.forEach(c => { tableHtml += `<td>${escapeHtml(c)}</td>`; });
        tableHtml += "</tr>";
      }
    });
    tableHtml += "</tbody></table>";
    const idx = placeholders.length;
    placeholders.push(tableHtml);
    return `\n\u0000CODE${idx}\u0000\n`;
  });

  // 4. 标题 #### / ### / ## / #
  md = md.replace(/^#### (.+)$/gm, '<h4 class="md-h4">$1</h4>');
  md = md.replace(/^### (.+)$/gm, '<h3 class="md-h3">$1</h3>');
  md = md.replace(/^## (.+)$/gm, '<h2 class="md-h2">$1</h2>');
  md = md.replace(/^# (.+)$/gm, '<h1 class="md-h1">$1</h1>');

  // 4b. 水平线 --- / ***
  md = md.replace(/^(-{3,}|\*{3,}|_{3,})\s*$/gm, '<hr class="md-hr">');

  // 4c. 块引用 >
  md = md.replace(/^&gt; (.+)$/gm, '<blockquote class="md-quote">$1</blockquote>');
  md = md.replace(/^> (.+)$/gm, '<blockquote class="md-quote">$1</blockquote>');

  // 5. 有序列表 1. 2. 3. （支持缩进嵌套）
  md = md.replace(/(?:^|\n)((?:[ \t]*\d+\.\s.+\n?)+)/g, (m, block) => {
    const lines = block.trim().split("\n").filter(l => /^\s*\d+\.\s/.test(l));
    let listHtml = '<ol class="md-ol">';
    for (const item of lines) {
      const text = item.replace(/^\s*\d+\.\s*/, "").trim();
      const processedText = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
      listHtml += `<li>${processedText}</li>`;
    }
    listHtml += "</ol>";
    return "\n" + listHtml + "\n";
  });

  // 6. 无序列表 - / * （支持缩进嵌套）
  md = md.replace(/(?:^|\n)((?:[ \t]*[-*]\s.+[ \t]*\n?)+)/g, (m, block) => {
    const lines = block.trim().split("\n").filter(l => /^\s*[-*]\s/.test(l));
    let listHtml = '<ul class="md-ul">';
    let prevIndent = -1;
    for (const item of lines) {
      const indent = (item.match(/^([ \t]*)/) || [""])[0].length;
      const text = item.replace(/^\s*[-*]\s*/, "").trim();
      const processedText = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
      if (indent > prevIndent && prevIndent >= 0) {
        listHtml += `<ul class="md-ul"><li>${processedText}</li>`;
      } else if (indent < prevIndent) {
        listHtml += `</li></ul></li><li>${processedText}</li>`;
      } else {
        listHtml += `<li>${processedText}</li>`;
      }
      prevIndent = indent;
    }
    listHtml += "</ul>";
    return "\n" + listHtml + "\n";
  });

  // 7. 加粗 **text**
  md = md.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

  // 8. 斜体 *text* (避免匹配已处理的加粗)
  md = md.replace(/(?<!\*)\*(?!\*)([^*]+)\*(?!\*)/g, '<em>$1</em>');

  // 9. 链接 [text](url)
  md = md.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');

  // 10. 换行（非块级元素后的单换行）
  md = md.replace(/\n/g, "<br>");

  // 清理多余 br（块级元素前后的 br）
  md = md.replace(/<br>(<\/?(?:h[1-6]|ol|ul|li|table|thead|tbody|tr|th|td|pre|div|blockquote|hr)>)/g, "$1");
  md = md.replace(/(<\/(?:h[1-6]|ol|ul|li|table|thead|tbody|tr|th|td|pre|div|blockquote|hr)>)(<br>)/g, "$1");

  // 还原占位符（代码块 / 行内代码 / 表格）
  md = md.replace(/\u0000CODE(\d+)\u0000/g, (m, idx) => placeholders[parseInt(idx)] || "");

  return md;
}

// 兼容旧函数名
function renderMarkdownTable(md) { return renderMarkdown(md); }

// ==========================================================================
// 数据源管理
// ==========================================================================
async function loadDatasources() {
  const container = document.getElementById("ds-list");
  if (!container) return;
  container.innerHTML = `<div style="text-align:center;padding:40px"><div class="loading-spinner"></div></div>`;
  try {
    const data = await api("GET", "/datasources");
    State.datasourceList = data.datasources || [];
    const badge = document.getElementById("badge-ds");
    if (badge) badge.textContent = State.datasourceList.length || "";

    let html = `<div class="stat-grid">
      <div class="stat-card"><div class="stat-icon">🗄️</div><div class="stat-label">数据源总数</div><div class="stat-value">${State.datasourceList.length}</div></div>
      <div class="stat-card"><div class="stat-icon">🔧</div><div class="stat-label">类型数</div><div class="stat-value">${new Set(State.datasourceList.map(d => d.db_type)).size}</div></div>
    </div>`;
    html += `<div class="card"><div class="card-header"><span class="card-title">数据源列表</span></div><div class="card-body">`;
    if (State.datasourceList.length === 0) {
      html += `<div class="empty-state"><div class="empty-state-icon">🗄️</div><div class="empty-state-text">暂无数据源，点击"添加数据源"创建</div></div>`;
    } else {
      html += `<div class="table-wrapper"><table class="data-table"><thead><tr><th>ID</th><th>类型</th><th>名称</th><th>主机</th><th>端口</th><th>备注</th><th>操作</th></tr></thead><tbody>`;
      State.datasourceList.forEach(ds => {
        html += `<tr><td>${ds.id}</td><td><span class="tag tag-blue">${escapeHtml(ds.db_type)}</span></td><td><strong>${escapeHtml(ds.db_name)}</strong></td><td>${escapeHtml(ds.db_host || "-")}</td><td>${ds.db_port || "-"}</td><td>${escapeHtml(ds.comment || "-")}</td><td><button class="btn btn-sm" onclick="testConnection(${ds.id})">测试</button> <button class="btn btn-sm" onclick="showSchemaModal(${ds.id})">编辑注释</button> <button class="btn btn-sm btn-danger" onclick="deleteDatasource(${ds.id})">删除</button></td></tr>`;
      });
      html += `</tbody></table></div>`;
    }
    html += `</div></div>`;
    container.innerHTML = html;
  } catch (e) {
    container.innerHTML = `<div class="empty-state"><div class="empty-state-text" style="color:var(--danger)">加载失败: ${escapeHtml(e.message)}</div></div>`;
  }
}

async function testConnection(id) {
  toast("正在测试连接...", "info");
  try {
    const ds = State.datasourceList.find(d => d.id == id);
    const result = await api("POST", "/datasources/test-connection", {
      db_type: ds.db_type, db_name: ds.db_name, db_host: ds.db_host,
      db_port: ds.db_port, db_user: ds.db_user, db_path: ds.db_path || "",
      db_pwd: "", datasource_id: String(ds.id),
    });
    toast(result.connected ? "连接成功" : "连接失败", result.connected ? "success" : "error");
  } catch (e) { toast("测试失败: " + e.message, "error"); }
}

async function deleteDatasource(id) {
  if (!confirm("确认删除此数据源？")) return;
  try { await api("DELETE", `/datasources/${id}`); toast("已删除", "success"); loadDatasources(); }
  catch (e) { toast("删除失败: " + e.message, "error"); }
}

// ==========================================================================
// Schema & Comment 编辑（表注释 + 列注释）
// ==========================================================================
let _schemaData = null;  // 当前编辑的 schema 数据

async function showSchemaModal(dsId) {
  const ds = State.datasourceList.find(d => d.id == dsId);
  if (!ds) { toast("数据源不存在", "error"); return; }

  openModal(`编辑注释 — ${ds.db_name} (${ds.db_type})`,
    `<div id="schema-loading" style="text-align:center;padding:40px"><div class="loading-spinner"></div><p>正在加载表结构...</p></div>`,
    [
      { class: "btn btn-sm", action: "closeModalDirect()", text: "取消" },
      { class: "btn btn-primary btn-sm", action: `saveSchemaComments(${dsId})`, text: "保存全部" },
    ]
  );

  try {
    const data = await api("GET", `/datasources/${dsId}/schema`);
    _schemaData = data.schema;
    renderSchemaEditor(data.schema, ds.db_type);
  } catch (e) {
    document.getElementById("modal-body").innerHTML =
      `<div class="empty-state"><div class="empty-state-text" style="color:var(--danger)">加载失败: ${escapeHtml(e.message)}</div></div>`;
  }
}

function renderSchemaEditor(schema, dbType) {
  const isMysql = dbType === "mysql";
  let html = "";

  if (schema.tables.length === 0) {
    html = `<div class="empty-state"><div class="empty-state-text">数据库中没有表</div></div>`;
    document.getElementById("modal-body").innerHTML = html;
    return;
  }

  schema.tables.forEach((table, ti) => {
    html += `<div class="schema-table-card">`;
    html += `<div class="schema-table-header" onclick="toggleSchemaTable(${ti})">
      <span class="schema-table-name">📋 ${escapeHtml(table.table_name)}</span>
      <span class="schema-table-cols">${table.columns.length} 列</span>
      <span class="react-step-toggle"><i class="fa-solid fa-chevron-down"></i></span>
    </div>`;
    html += `<div class="schema-table-body" id="schema-table-${ti}">`;

    // 表注释
    html += `<div class="schema-field-row">
      <label class="schema-label">表注释</label>
      <input class="input schema-table-comment" data-table-idx="${ti}" value="${escapeAttr(table.table_comment || "")}"
        placeholder="${isMysql ? "输入表注释..." : "SQLite 不支持表注释"}" ${isMysql ? "" : "disabled"}>
    </div>`;

    // 列表格
    html += `<div class="table-wrapper"><table class="data-table schema-col-table">
      <thead><tr><th>列名</th><th>类型</th><th>主键</th><th>注释</th></tr></thead><tbody>`;
    table.columns.forEach((col, ci) => {
      const pkBadge = col.is_primary_key ? '<span class="tag tag-green">PK</span>' : '<span style="color:var(--text-tertiary)">-</span>';
      html += `<tr>
        <td><code>${escapeHtml(col.name)}</code></td>
        <td>${escapeHtml(col.type)}</td>
        <td style="text-align:center">${pkBadge}</td>
        <td><input class="input schema-col-comment" data-table-idx="${ti}" data-col-idx="${ci}"
          value="${escapeAttr(col.comment || "")}" placeholder="${isMysql ? "输入列注释..." : "SQLite 不支持列注释"}" ${isMysql ? "" : "disabled"}></td>
      </tr>`;
    });
    html += `</tbody></table></div>`;

    // DDL 预览（折叠）
    html += `<details class="schema-ddl-details"><summary>查看 DDL</summary><pre class="schema-ddl-pre">${escapeHtml(table.ddl)}</pre></details>`;

    html += `</div></div>`;
  });

  html += `<div style="padding:8px 0;color:var(--text-tertiary);font-size:12px">
    ${isMysql ? "✅ MySQL：修改注释后立即生效，下次问答时模型自动看到新注释。" : "⚠️ SQLite 不支持表/列注释。"}
  </div>`;

  document.getElementById("modal-body").innerHTML = html;
  // SQLite 禁用保存按钮
  const saveBtn = document.querySelector("#modal-footer .btn-primary");
  if (saveBtn) saveBtn.disabled = !isMysql;
}

function toggleSchemaTable(idx) {
  const body = document.getElementById(`schema-table-${idx}`);
  if (body) body.classList.toggle("hidden");
}

async function saveSchemaComments(dsId) {
  if (!_schemaData) return;
  const isMysql = _schemaData.db_type === "mysql";
  if (!isMysql) { toast("SQLite 不支持注释修改", "error"); return; }

  // 收集表注释变更
  const tableComments = [];
  const columnComments = [];

  _schemaData.tables.forEach((table, ti) => {
    const tableInput = document.querySelector(`.schema-table-comment[data-table-idx="${ti}"]`);
    if (tableInput) {
      const newComment = tableInput.value;
      if (newComment !== (table.table_comment || "")) {
        tableComments.push({ table_name: table.table_name, comment: newComment });
      }
    }

    table.columns.forEach((col, ci) => {
      const colInput = document.querySelector(`.schema-col-comment[data-table-idx="${ti}"][data-col-idx="${ci}"]`);
      if (colInput) {
        const newComment = colInput.value;
        if (newComment !== (col.comment || "")) {
          columnComments.push({ table_name: table.table_name, column_name: col.name, comment: newComment });
        }
      }
    });
  });

  const total = tableComments.length + columnComments.length;
  if (total === 0) { toast("没有变更", "info"); return; }

  toast(`正在保存 ${total} 项变更...`, "info");
  let okCount = 0, failCount = 0;

  try {
    // 批量修改表注释
    if (tableComments.length > 0) {
      const res = await api("PUT", `/datasources/${dsId}/schema/tables`, { comments: tableComments });
      (res.results || []).forEach(r => { if (r.ok) okCount++; else failCount++; });
    }
    // 批量修改列注释
    if (columnComments.length > 0) {
      const res = await api("PUT", `/datasources/${dsId}/schema/columns`, { comments: columnComments });
      (res.results || []).forEach(r => { if (r.ok) okCount++; else failCount++; });
    }

    if (failCount === 0) {
      toast(`保存成功：${okCount} 项已更新`, "success");
    } else {
      toast(`部分成功：${okCount} 成功，${failCount} 失败`, "info");
    }
    closeModalDirect();
  } catch (e) {
    toast("保存失败: " + e.message, "error");
  }
}

function escapeAttr(text) { return String(text || "").replace(/"/g, "&quot;").replace(/'/g, "&#39;"); }

function showAddDsModal() {
  openModal("添加数据源", `
    <div class="form-field"><label>数据库类型</label><select class="select" id="ds-type" onchange="toggleDsFields()"><option value="mysql">MySQL</option><option value="sqlite">SQLite</option><option value="duckdb">DuckDB</option><option value="postgresql">PostgreSQL</option></select></div>
    <div class="form-field"><label>数据库名 *</label><input class="input" id="ds-name" placeholder="如 chase_book"></div>
    <div id="ds-mysql-fields">
      <div class="form-field"><label>主机地址</label><input class="input" id="ds-host" placeholder="如 127.0.0.1" value="127.0.0.1"></div>
      <div class="form-row">
        <div class="form-field form-field-half"><label>端口</label><input class="input" id="ds-port" type="number" placeholder="如 3306" value="3306"></div>
        <div class="form-field form-field-half"><label>用户名</label><input class="input" id="ds-user" placeholder="如 root" value="root"></div>
      </div>
      <div class="form-field"><label>密码</label><input class="input" id="ds-pwd" type="password"></div>
    </div>
    <div id="ds-sqlite-fields" style="display:none">
      <div class="form-field"><label>文件路径</label><input class="input" id="ds-path" placeholder="如 /app/pilot/examples/example.db"></div>
    </div>
    <div class="form-field"><label>数据库备注</label><input class="input" id="ds-comment" placeholder="可选，如：双11电商数据"></div>
    <div class="form-hint">💡 测试连接成功后，可在下方为表和列添加中文注释（仅 MySQL）</div>
    <div id="ds-schema-area" style="display:none;margin-top:12px">
      <div style="border-top:1px solid var(--border-color);padding-top:12px">
        <div style="font-weight:600;font-size:13px;margin-bottom:8px">📋 表/列注释编辑</div>
        <div id="ds-schema-list"></div>
      </div>
    </div>
  `, [
    { text: "取消", class: "btn", action: "closeModalDirect()" },
    { text: "测试连接", class: "btn", action: "testConnectionFromModal()" },
    { text: "创建", class: "btn btn-primary", action: "createDatasource()" },
  ]);
}

function toggleDsFields() {
  const type = document.getElementById("ds-type").value;
  document.getElementById("ds-mysql-fields").style.display = type === "sqlite" ? "none" : "";
  document.getElementById("ds-sqlite-fields").style.display = type === "sqlite" ? "" : "none";
}

function _getDsFormParams() {
  const type = document.getElementById("ds-type").value;
  return {
    db_type: type,
    db_name: document.getElementById("ds-name").value,
    db_host: document.getElementById("ds-host") ? document.getElementById("ds-host").value : "",
    db_port: document.getElementById("ds-port") ? parseInt(document.getElementById("ds-port").value) || 0 : 0,
    db_user: document.getElementById("ds-user") ? document.getElementById("ds-user").value : "",
    db_pwd: document.getElementById("ds-pwd") ? document.getElementById("ds-pwd").value : "",
    db_path: document.getElementById("ds-path") ? document.getElementById("ds-path").value : "",
  };
}

async function testConnectionFromModal() {
  const body = _getDsFormParams();
  if (!body.db_name) { toast("数据库名不能为空", "error"); return; }
  toast("正在测试连接...", "info");
  try {
    const result = await api("POST", "/datasources/test-connection", body);
    if (result.connected) {
      toast("连接成功", "success");
      // 连接成功后预览 schema（仅 MySQL）
      if (body.db_type === "mysql") {
        await _loadSchemaPreview(body);
      }
    } else {
      toast("连接失败", "error");
    }
  } catch (e) { toast("测试失败: " + e.message, "error"); }
}

async function _loadSchemaPreview(body) {
  try {
    const data = await api("POST", "/datasources/schema-preview", body);
    _schemaData = data.schema;
    document.getElementById("ds-schema-area").style.display = "";
    _renderAddDsSchemaEditor(data.schema);
  } catch (e) {
    document.getElementById("ds-schema-area").style.display = "none";
    toast("预览表结构失败: " + e.message, "info");
  }
}

function _renderAddDsSchemaEditor(schema) {
  let html = "";
  schema.tables.forEach((table, ti) => {
    html += `<div class="schema-table-card">`;
    html += `<div class="schema-table-header" onclick="toggleSchemaTable('add-${ti}')">
      <span class="schema-table-name">📋 ${escapeHtml(table.table_name)}</span>
      <span class="schema-table-cols">${table.columns.length} 列</span>
      <span class="react-step-toggle"><i class="fa-solid fa-chevron-down"></i></span>
    </div>`;
    html += `<div class="schema-table-body" id="schema-table-add-${ti}">`;
    html += `<div class="schema-field-row">
      <label class="schema-label">表注释</label>
      <input class="input schema-table-comment" data-table-idx="${ti}" value="${escapeAttr(table.table_comment || "")}" placeholder="输入表注释...">
    </div>`;
    html += `<div class="table-wrapper"><table class="data-table schema-col-table">
      <thead><tr><th>列名</th><th>类型</th><th>主键</th><th>注释</th></tr></thead><tbody>`;
    table.columns.forEach((col, ci) => {
      const pkBadge = col.is_primary_key ? '<span class="tag tag-green">PK</span>' : '<span style="color:var(--text-tertiary)">-</span>';
      html += `<tr>
        <td><code>${escapeHtml(col.name)}</code></td>
        <td>${escapeHtml(col.type)}</td>
        <td style="text-align:center">${pkBadge}</td>
        <td><input class="input schema-col-comment" data-table-idx="${ti}" data-col-idx="${ci}"
          value="${escapeAttr(col.comment || "")}" placeholder="输入列注释..."></td>
      </tr>`;
    });
    html += `</tbody></table></div>`;
    html += `</div></div>`;
  });
  document.getElementById("ds-schema-list").innerHTML = html;
}

async function createDatasource() {
  const body = _getDsFormParams();
  body.comment = document.getElementById("ds-comment").value;
  if (!body.db_name) { toast("数据库名不能为空", "error"); return; }
  try {
    // 1. 创建数据源
    await api("POST", "/datasources", body);
    toast("数据源创建成功", "success");

    // 2. 如果有 schema 编辑数据（MySQL），找到新数据源并保存注释
    if (_schemaData && _schemaData.db_type === "mysql") {
      // 刷新列表获取新数据源 ID
      await loadDatasources();
      const newDs = State.datasourceList.find(d => d.db_name === body.db_name);
      if (newDs) {
        await _saveSchemaCommentsFromModal(newDs.id);
      }
    }
    closeModalDirect();
    await loadDatasources();
  } catch (e) { toast("创建失败: " + e.message, "error"); }
}

async function _saveSchemaCommentsFromModal(dsId) {
  if (!_schemaData) return;
  const tableComments = [];
  const columnComments = [];

  _schemaData.tables.forEach((table, ti) => {
    const tableInput = document.querySelector(`#ds-schema-list .schema-table-comment[data-table-idx="${ti}"]`);
    if (tableInput) {
      const newComment = tableInput.value;
      if (newComment !== (table.table_comment || "")) {
        tableComments.push({ table_name: table.table_name, comment: newComment });
      }
    }
    table.columns.forEach((col, ci) => {
      const colInput = document.querySelector(`#ds-schema-list .schema-col-comment[data-table-idx="${ti}"][data-col-idx="${ci}"]`);
      if (colInput) {
        const newComment = colInput.value;
        if (newComment !== (col.comment || "")) {
          columnComments.push({ table_name: table.table_name, column_name: col.name, comment: newComment });
        }
      }
    });
  });

  const total = tableComments.length + columnComments.length;
  if (total === 0) return;
  try {
    if (tableComments.length > 0) {
      await api("PUT", `/datasources/${dsId}/schema/tables`, { comments: tableComments });
    }
    if (columnComments.length > 0) {
      await api("PUT", `/datasources/${dsId}/schema/columns`, { comments: columnComments });
    }
    toast(`已保存 ${total} 项注释`, "success");
  } catch (e) {
    toast("注释保存失败: " + e.message, "info");
  }
}

// ==========================================================================
// 知识库管理
// ==========================================================================
async function loadKnowledge() {
  const container = document.getElementById("kb-list");
  if (!container) return;
  container.innerHTML = `<div style="text-align:center;padding:40px"><div class="loading-spinner"></div></div>`;
  try {
    const [spacesResp, docsResp] = await Promise.all([api("GET", "/knowledge/spaces"), api("GET", "/knowledge/documents")]);
    State.knowledgeSpaces = spacesResp.spaces || [];
    const docs = docsResp.documents || [];

    let html = `<div class="stat-grid">
      <div class="stat-card"><div class="stat-icon">📚</div><div class="stat-label">知识空间</div><div class="stat-value">${State.knowledgeSpaces.length}</div></div>
      <div class="stat-card"><div class="stat-icon">📄</div><div class="stat-label">文档总数</div><div class="stat-value">${docs.length}</div></div>
    </div>`;
    html += `<div class="card"><div class="card-header"><span class="card-title">知识空间</span></div><div class="card-body">`;
    if (State.knowledgeSpaces.length === 0) {
      html += `<div class="empty-state"><div class="empty-state-icon">📚</div><div class="empty-state-text">暂无知识空间</div></div>`;
    } else {
      html += `<div class="table-wrapper"><table class="data-table"><thead><tr><th>ID</th><th>名称</th><th>向量类型</th><th>描述</th><th>所有者</th><th>操作</th></tr></thead><tbody>`;
      State.knowledgeSpaces.forEach(sp => {
        html += `<tr><td>${sp.id}</td><td><strong>${escapeHtml(sp.name)}</strong></td><td><span class="tag tag-purple">${escapeHtml(sp.vector_type || "-")}</span></td><td>${escapeHtml(sp.desc || "-")}</td><td>${escapeHtml(sp.owner || "-")}</td><td><button class="btn btn-sm btn-danger" onclick="deleteSpace(${sp.id})">删除</button></td></tr>`;
      });
      html += `</tbody></table></div>`;
    }
    html += `</div></div>`;

    html += `<div class="card" style="margin-top:16px"><div class="card-header"><span class="card-title">文档列表</span></div><div class="card-body">`;
    if (docs.length === 0) html += `<div class="empty-state"><div class="empty-state-text">暂无文档</div></div>`;
    else {
      html += `<div class="table-wrapper"><table class="data-table"><thead><tr><th>ID</th><th>名称</th><th>类型</th><th>来源</th><th>预览</th></tr></thead><tbody>`;
      docs.forEach(d => { html += `<tr><td>${d.id}</td><td><strong>${escapeHtml(d.doc_name)}</strong></td><td><span class="tag tag-blue">${escapeHtml(d.doc_type)}</span></td><td>${escapeHtml(d.doc_source || "-")}</td><td style="max-width:200px;overflow:hidden;text-overflow:ellipsis">${escapeHtml((d.content || "").slice(0, 80))}...</td></tr>`; });
      html += `</tbody></table></div>`;
    }
    html += `</div></div>`;
    container.innerHTML = html;
  } catch (e) {
    container.innerHTML = `<div class="empty-state"><div class="empty-state-text" style="color:var(--danger)">加载失败: ${escapeHtml(e.message)}</div></div>`;
  }
}

function showAddKbModal() {
  openModal("创建知识空间", `
    <div class="form-field"><label>空间名称 *</label><input class="input" id="kb-name" placeholder="如 my_knowledge"></div>
    <div class="form-field"><label>向量类型</label><input class="input" id="kb-vector" placeholder="如 ChromaDefault (可选)"></div>
    <div class="form-field"><label>描述</label><input class="input" id="kb-desc" placeholder="可选"></div>
    <div class="form-field"><label>所有者</label><input class="input" id="kb-owner" placeholder="可选"></div>
  `, [
    { text: "取消", class: "btn", action: "closeModalDirect()" },
    { text: "创建", class: "btn btn-primary", action: "createSpace()" },
  ]);
}

async function createSpace() {
  const body = {
    name: document.getElementById("kb-name").value,
    vector_type: document.getElementById("kb-vector").value || "",
    desc: document.getElementById("kb-desc").value,
    owner: document.getElementById("kb-owner").value,
  };
  if (!body.name) { toast("空间名称不能为空", "error"); return; }
  try {
    await api("POST", "/knowledge/spaces", body);
    toast("知识空间创建成功", "success");
    closeModalDirect();
    loadKnowledge();
  } catch (e) { toast("创建失败: " + e.message, "error"); }
}

async function deleteSpace(id) {
  if (!confirm("确认删除此知识空间？")) return;
  try { await api("DELETE", `/knowledge/spaces/${id}`); toast("已删除", "success"); loadKnowledge(); }
  catch (e) { toast("删除失败: " + e.message, "error"); }
}

// 上传本地文件到知识库空间（参考 DB-GPT 文档上传弹窗设计）
function showUploadDocModal() {
  const spaces = State.knowledgeSpaces || [];
  const opts = spaces.map(s => `<option value="${escapeAttr(s.id)}">${escapeHtml(s.name)}</option>`).join("");
  const modelOpts = (State.modelList || []).map(m => `<option value="${escapeAttr(m.model_name)}">${escapeHtml(m.model_name)}</option>`).join("");
  openModal("上传文档到知识库", `
    <div class="upload-section">
      <div class="upload-section-title">📋 基本信息</div>
      <div class="form-field"><label>目标空间 *</label>
        ${spaces.length ? `<select class="select" id="up-space">${opts}</select>`
          : '<input class="input" id="up-space" placeholder="空间 ID 或名称">'}
      </div>
      <div class="form-field"><label>文档名（可选，缺省取文件名）</label>
        <input class="input" id="up-name" placeholder="可选"></div>
      <div class="form-field"><label>文档类型</label>
        <select class="select" id="up-type">
          <option value="document">自动识别</option>
          <option value="txt">txt</option>
          <option value="markdown">markdown</option>
          <option value="csv">csv</option>
          <option value="pdf">pdf</option>
          <option value="html">html</option>
          <option value="json">json</option>
          <option value="pptx">pptx</option>
          <option value="docx">docx</option>
          <option value="excel">excel</option>
        </select></div>
    </div>

    <div class="upload-section">
      <div class="upload-section-title">📁 文件来源</div>
      <div class="form-field"><label>选择本地文件（与文本二选一）</label>
        <input type="file" id="up-file" class="input"></div>
      <div class="form-field"><label>或直接粘贴文本内容</label>
        <textarea id="up-content" class="textarea" placeholder="文件与文本二选一"></textarea></div>
    </div>

    <div class="upload-section">
      <div class="upload-section-title">⚙️ 分块与向量化设置</div>
      <div class="form-field"><label>分块策略</label>
        <select class="select" id="up-chunk-strategy" onchange="toggleChunkParams()">
          <option value="Automatic" selected>自动（推荐）</option>
          <option value="CHUNK_BY_SIZE">按大小分块</option>
          <option value="CHUNK_BY_PAGE">按页分块</option>
          <option value="CHUNK_BY_PARAGRAPH">按段落分块</option>
          <option value="CHUNK_BY_SEPARATOR">按分隔符分块</option>
          <option value="CHUNK_BY_MARKDOWN_HEADER">按 Markdown 标题分块</option>
        </select>
        <div class="form-hint" id="up-strategy-hint">自动根据文档类型选择最佳分块策略</div>
      </div>
      <div class="form-row" id="up-chunk-params" style="display:none;">
        <div class="form-field form-field-half"><label>分块大小</label>
          <input class="input" id="up-chunk-size" type="number" value="512" min="100" max="4096"></div>
        <div class="form-field form-field-half"><label>分块重叠</label>
          <input class="input" id="up-chunk-overlap" type="number" value="50" min="0" max="500"></div>
      </div>
      <div class="form-field" id="up-separator-field" style="display:none;">
        <label>分隔符</label>
        <input class="input" id="up-separator" value="\\n">
      </div>
      <div class="form-field"><label>摘要模型（可选）</label>
        <select class="select" id="up-model">
          <option value="">默认</option>
          ${modelOpts}
        </select>
      </div>
    </div>
  `, [
    { text: "取消", class: "btn", action: "closeModalDirect()" },
    { text: "上传并同步", class: "btn btn-primary", action: "uploadKnowledgeDoc()" },
  ]);
}

// 切换分块参数显示（Automatic 时隐藏高级参数）
function toggleChunkParams() {
  const strategy = document.getElementById("up-chunk-strategy").value;
  const isAuto = strategy === "Automatic";
  const paramsEl = document.getElementById("up-chunk-params");
  const sepEl = document.getElementById("up-separator-field");
  const hintEl = document.getElementById("up-strategy-hint");
  if (paramsEl) paramsEl.style.display = isAuto ? "none" : "";
  if (sepEl) sepEl.style.display = (strategy === "CHUNK_BY_SEPARATOR" || strategy === "CHUNK_BY_PARAGRAPH") ? "" : "none";
  if (hintEl) {
    const hints = {
      "Automatic": "自动根据文档类型选择最佳分块策略",
      "CHUNK_BY_SIZE": "按固定大小分块，适合通用文本",
      "CHUNK_BY_PAGE": "按页分块，适合 PDF / Word",
      "CHUNK_BY_PARAGRAPH": "按段落分块，需指定分隔符",
      "CHUNK_BY_SEPARATOR": "按分隔符分块，需指定分隔符",
      "CHUNK_BY_MARKDOWN_HEADER": "按 Markdown 标题分块，适合文档",
    };
    hintEl.textContent = hints[strategy] || "";
  }
}

async function uploadKnowledgeDoc() {
  const spaceId = document.getElementById("up-space").value.trim();
  const docType = document.getElementById("up-type").value;
  const docName = document.getElementById("up-name").value.trim();
  const content = document.getElementById("up-content").value;
  const fileInput = document.getElementById("up-file");
  const file = fileInput && fileInput.files && fileInput.files[0];
  if (!spaceId) { toast("请选择目标空间", "error"); return; }
  if (!file && !content) { toast("请选择文件或输入文本内容", "error"); return; }

  const chunkStrategy = document.getElementById("up-chunk-strategy").value;
  const chunkSize = parseInt(document.getElementById("up-chunk-size")?.value || "512");
  const chunkOverlap = parseInt(document.getElementById("up-chunk-overlap")?.value || "50");
  const separator = document.getElementById("up-separator")?.value || "\\n";
  const modelName = document.getElementById("up-model").value || "";

  const form = new FormData();
  form.append("space_id", spaceId);
  form.append("doc_type", docType);
  form.append("chunk_strategy", chunkStrategy);
  form.append("chunk_size", chunkSize);
  form.append("chunk_overlap", chunkOverlap);
  form.append("separator", separator);
  if (modelName) form.append("model_name", modelName);
  form.append("auto_sync", "true");
  if (docName) form.append("doc_name", docName);
  if (file) form.append("doc_file", file);
  if (content) form.append("content", content);

  toast("正在上传并同步...", "info");
  try {
    const resp = await fetch(API_BASE + "/knowledge/documents/upload", { method: "POST", body: form });
    const data = await resp.json();
    if (!resp.ok || !data.ok) throw new Error(data.detail || JSON.stringify(data));
    const syncStatus = data.sync_status || "unknown";
    if (syncStatus === "syncing") {
      toast("文档上传成功，正在向量化同步中", "success");
    } else if (syncStatus.startsWith("failed")) {
      toast("文档已上传，但同步失败: " + syncStatus, "warning");
    } else {
      toast("文档上传成功", "success");
    }
    closeModalDirect();
    loadKnowledge();
  } catch (err) {
    toast("上传失败: " + err.message, "error");
  }
}

// ==========================================================================
// 技能管理
// ==========================================================================
async function loadSkills() {
  const container = document.getElementById("skill-list");
  if (!container) return;
  container.innerHTML = `<div style="text-align:center;padding:40px"><div class="loading-spinner"></div></div>`;
  try {
    const data = await api("GET", "/ask/skills");
    State.skillList = data.skills || [];
    let html = `<div class="stat-grid">
      <div class="stat-card"><div class="stat-icon">🧩</div><div class="stat-label">技能总数</div><div class="stat-value">${State.skillList.length}</div></div>
    </div>`;
    html += `<div class="card"><div class="card-header"><span class="card-title">技能列表</span></div><div class="card-body">`;
    if (State.skillList.length === 0) {
      html += `<div class="empty-state"><div class="empty-state-icon">🧩</div><div class="empty-state-text">暂无技能</div></div>`;
    } else {
      html += `<div class="table-wrapper"><table class="data-table"><thead><tr><th>名称</th><th>类型</th><th>版本</th><th>描述</th><th>来源</th><th>操作</th></tr></thead><tbody>`;
      State.skillList.forEach(s => {
        const desc = (s.description || "").slice(0, 60);
        html += `<tr>
          <td><strong>${escapeHtml(s.name)}</strong></td>
          <td><span class="tag tag-purple">${escapeHtml(s.skill_type || "-")}</span></td>
          <td>${escapeHtml(s.version || "-")}</td>
          <td style="max-width:300px">${escapeHtml(desc)}</td>
          <td><span class="tag ${s.type === 'official' ? 'tag-blue' : 'tag-green'}">${escapeHtml(s.type || "-")}</span></td>
          <td><button class="btn btn-sm" onclick="viewSkillDetail('${escapeAttr(s.name)}','${escapeAttr(s.file_path)}')">查看</button></td>
        </tr>`;
      });
      html += `</tbody></table></div>`;
    }
    html += `</div></div>`;
    container.innerHTML = html;
  } catch (e) {
    container.innerHTML = `<div class="empty-state"><div class="empty-state-text" style="color:var(--danger)">加载失败: ${escapeHtml(e.message)}</div></div>`;
  }
}

function viewSkillDetail(name, filePath) {
  openModal(`技能详情: ${name}`, `<div id="skill-detail-body" style="text-align:center;padding:40px"><div class="loading-spinner"></div></div>`, [
    { text: "关闭", class: "btn", action: "closeModalDirect()" },
  ]);
  // 异步加载详情
  (async () => {
    try {
      const resp = await fetch(API_BASE + `/ask/skills/detail?skill_name=${encodeURIComponent(name)}&file_path=${encodeURIComponent(filePath)}`);
      const data = await resp.json();
      const body = document.getElementById("skill-detail-body");
      if (!body) return;
      if (!data.ok || !data.detail) {
        body.innerHTML = `<div class="empty-state-text" style="color:var(--danger)">加载失败: ${escapeHtml(data.error || "未知错误")}</div>`;
        return;
      }
      const d = data.detail;
      let html = "";
      if (d.metadata) {
        html += `<div class="card" style="margin-bottom:12px"><div class="card-body">`;
        const m = d.metadata;
        if (m.name) html += `<div><strong>名称:</strong> ${escapeHtml(m.name)}</div>`;
        if (m.description) html += `<div style="margin-top:4px"><strong>描述:</strong> ${escapeHtml(m.description)}</div>`;
        if (m.author) html += `<div style="margin-top:4px"><strong>作者:</strong> ${escapeHtml(m.author)}</div>`;
        if (m.version) html += `<div style="margin-top:4px"><strong>版本:</strong> ${escapeHtml(m.version)}</div>`;
        if (m.skill_type) html += `<div style="margin-top:4px"><strong>类型:</strong> ${escapeHtml(m.skill_type)}</div>`;
        html += `</div></div>`;
      }
      if (d.instructions) {
        html += `<div class="card"><div class="card-header"><span class="card-title">SKILL.md 内容</span></div>`;
        html += `<div class="card-body"><pre class="md-code-block" style="max-height:400px;overflow-y:auto"><code>${escapeHtml(d.instructions)}</code></pre></div></div>`;
      }
      body.innerHTML = html;
    } catch (err) {
      const body = document.getElementById("skill-detail-body");
      if (body) body.innerHTML = `<div class="empty-state-text" style="color:var(--danger)">加载失败: ${escapeHtml(err.message)}</div>`;
    }
  })();
}

function showUploadSkillModal() {
  openModal("上传技能", `
    <div class="form-field"><label>选择技能包（.zip / .skill / 单文件）</label>
      <input type="file" id="skill-upload-file" class="input"></div>
    <div class="form-field"><label>或从 GitHub 导入（URL）</label>
      <input class="input" id="skill-github-url" placeholder="https://github.com/..."></div>
  `, [
    { text: "取消", class: "btn", action: "closeModalDirect()" },
    { text: "上传", class: "btn btn-primary", action: "uploadSkill()" },
  ]);
}

async function uploadSkill() {
  const fileInput = document.getElementById("skill-upload-file");
  const file = fileInput && fileInput.files && fileInput.files[0];
  if (!file) { toast("请选择技能包文件", "error"); return; }
  const form = new FormData();
  form.append("file", file);
  toast("正在上传...", "info");
  try {
    const resp = await fetch(API_BASE + "/ask/skills/upload", { method: "POST", body: form });
    const data = await resp.json();
    if (!resp.ok || !data.ok) throw new Error(data.error || JSON.stringify(data));
    toast("技能上传成功", "success");
    closeModalDirect();
    loadSkills();
  } catch (err) {
    toast("上传失败: " + err.message, "error");
  }
}

// ==========================================================================
// 提示词管理
// ==========================================================================
async function loadPrompts() {
  const container = document.getElementById("prompt-list");
  if (!container) return;
  container.innerHTML = `<div style="text-align:center;padding:40px"><div class="loading-spinner"></div></div>`;
  try {
    const data = await api("POST", "/prompts/list", { page: 1, page_size: 100 });
    const prompts = data.prompts || [];
    let html = `<div class="stat-grid">
      <div class="stat-card"><div class="stat-icon">✏️</div><div class="stat-label">提示词总数</div><div class="stat-value">${Array.isArray(prompts) ? prompts.length : 0}</div></div>
    </div>`;
    html += `<div class="card"><div class="card-header"><span class="card-title">提示词列表</span></div><div class="card-body">`;
    if (!Array.isArray(prompts) || prompts.length === 0) {
      html += `<div class="empty-state"><div class="empty-state-icon">✏️</div><div class="empty-state-text">暂无提示词</div></div>`;
    } else {
      html += `<div class="table-wrapper"><table class="data-table"><thead><tr><th>名称</th><th>类型</th><th>场景</th><th>内容预览</th><th>操作</th></tr></thead><tbody>`;
      prompts.forEach(p => {
        const content = (p.content || "").slice(0, 80);
        html += `<tr>
          <td><strong>${escapeHtml(p.prompt_name || p.name || "-")}</strong></td>
          <td><span class="tag tag-blue">${escapeHtml(p.prompt_type || "-")}</span></td>
          <td>${escapeHtml(p.scene || "-")}</td>
          <td style="max-width:250px;overflow:hidden;text-overflow:ellipsis">${escapeHtml(content)}</td>
          <td>
            <button class="btn btn-sm" onclick="viewPrompt('${escapeAttr(p.prompt_name || p.name)}')">查看</button>
            <button class="btn btn-sm btn-danger" onclick="deletePrompt('${escapeAttr(p.prompt_name || p.name)}')">删除</button>
          </td>
        </tr>`;
      });
      html += `</tbody></table></div>`;
    }
    html += `</div></div>`;
    container.innerHTML = html;
  } catch (e) {
    container.innerHTML = `<div class="empty-state"><div class="empty-state-text" style="color:var(--danger)">加载失败: ${escapeHtml(e.message)}</div></div>`;
  }
}

function viewPrompt(name) {
  openModal(`提示词: ${name}`, `<div id="prompt-detail-body" style="text-align:center;padding:40px"><div class="loading-spinner"></div></div>`, [
    { text: "关闭", class: "btn", action: "closeModalDirect()" },
  ]);
  (async () => {
    try {
      const data = await api("POST", "/prompts/list", { page: 1, page_size: 100 });
      const body = document.getElementById("prompt-detail-body");
      if (!body) return;
      const prompts = data.prompts || [];
      const p = prompts.find(x => (x.prompt_name || x.name) === name);
      if (!p) { body.innerHTML = '<div class="empty-state-text">未找到</div>'; return; }
      body.innerHTML = `
        <div class="form-field"><label>名称</label><div style="padding:4px 0">${escapeHtml(p.prompt_name || p.name || "-")}</div></div>
        <div class="form-field"><label>类型</label><div style="padding:4px 0">${escapeHtml(p.prompt_type || "-")}</div></div>
        <div class="form-field"><label>场景</label><div style="padding:4px 0">${escapeHtml(p.scene || "-")} / ${escapeHtml(p.sub_scene || "-")}</div></div>
        <div class="form-field"><label>内容</label><pre class="md-code-block" style="max-height:300px;overflow-y:auto"><code>${escapeHtml(p.content || "")}</code></pre></div>`;
    } catch (err) {
      const body = document.getElementById("prompt-detail-body");
      if (body) body.innerHTML = `<div class="empty-state-text" style="color:var(--danger)">加载失败: ${escapeHtml(err.message)}</div>`;
    }
  })();
}

function showAddPromptModal() {
  openModal("新建提示词", `
    <div class="form-field"><label>名称 *</label><input class="input" id="pt-name" placeholder="如 my_prompt"></div>
    <div class="form-field"><label>内容 *</label><textarea class="textarea" id="pt-content" rows="8" placeholder="输入提示词内容...&#10;&#10;该内容会作为业务约束/上下文追加到默认 system prompt 中（非替换），ReAct 格式约束保持不变。&#10;例如：你是电视收视率分析助手，始终用中文回答并附带数据来源表名。"></textarea></div>
    <div class="form-hint">💡 此提示词会追加到默认 system prompt 的「Please Solve this task:」之前，作为额外约束。不影响 ReAct 格式。</div>
  `, [
    { text: "取消", class: "btn", action: "closeModalDirect()" },
    { text: "创建", class: "btn btn-primary", action: "createPrompt()" },
  ]);
}

async function createPrompt() {
  const body = {
    prompt_name: document.getElementById("pt-name").value,
    content: document.getElementById("pt-content").value,
    prompt_type: "common",
  };
  if (!body.prompt_name || !body.content) { toast("名称和内容不能为空", "error"); return; }
  try {
    await api("POST", "/prompts/add", body);
    toast("提示词创建成功", "success");
    closeModalDirect();
    loadPrompts();
  } catch (e) { toast("创建失败: " + e.message, "error"); }
}

async function deletePrompt(name) {
  if (!confirm(`确认删除提示词「${name}」？`)) return;
  try {
    await api("POST", "/prompts/delete", { prompt_name: name });
    toast("已删除", "success");
    loadPrompts();
  } catch (e) { toast("删除失败: " + e.message, "error"); }
}

// ==========================================================================
// 模型管理
// ==========================================================================
async function loadModels() {
  const container = document.getElementById("model-list");
  if (!container) return;
  container.innerHTML = `<div style="text-align:center;padding:40px"><div class="loading-spinner"></div></div>`;
  try {
    const [typesResp, listResp] = await Promise.all([api("GET", "/models/model-types"), api("GET", "/models/list")]);
    const types = typesResp.model_types || [];
    State.modelList = listResp.models || [];

    // 提取去重的 worker_type 列表（llm / text2vec / reranker 等）
    const workerTypes = [...new Set(types.map(t => t.worker_type).filter(Boolean))].sort();

    let html = `<div class="stat-grid">
      <div class="stat-card"><div class="stat-icon">🧠</div><div class="stat-label">模型类型</div><div class="stat-value">${workerTypes.length}</div></div>
      <div class="stat-card"><div class="stat-icon">⚡</div><div class="stat-label">运行中模型</div><div class="stat-value">${State.modelList.length}</div></div>
      <div class="stat-card"><div class="stat-icon">📦</div><div class="stat-label">可注册规格</div><div class="stat-value">${types.length}</div></div>
    </div>`;
    html += `<div class="card"><div class="card-header"><span class="card-title">运行中的模型</span><button class="btn btn-sm btn-primary" style="margin-left:auto" onclick="showStartModelModal()">+ 添加模型</button></div><div class="card-body">`;
    if (State.modelList.length === 0) html += `<div class="empty-state"><div class="empty-state-text">暂无运行中的模型，点击「添加模型」启动一个</div></div>`;
    else {
      html += `<div class="table-wrapper"><table class="data-table"><thead><tr><th>模型名</th><th>类型</th><th>主机</th><th>端口</th><th>状态</th><th>操作</th></tr></thead><tbody>`;
      State.modelList.forEach(m => {
        const healthy = m.healthy !== false;
        const wt = escapeAttr(m.worker_type || m.model_type || "llm");
        const h = escapeAttr(m.host || "127.0.0.1");
        const p = m.port || 5670;
        html += `<tr><td><strong>${escapeHtml(m.model_name)}</strong></td><td><span class="tag tag-blue">${escapeHtml(m.model_type || m.worker_type || "-")}</span></td><td>${escapeHtml(m.host || "-")}</td><td>${m.port || "-"}</td><td>${healthy ? '<span class="tag tag-green">健康</span>' : '<span class="tag tag-red\">异常</span>'}</td><td style="white-space:nowrap"><button class="btn btn-sm btn-primary" onclick="showEditModelModal('${escapeAttr(m.model_name)}','${wt}','${h}',${p})">编辑</button> <button class="btn btn-sm" style="background:var(--bg-info);color:var(--text-info);border:0.5px solid var(--color-border-info)" onclick="testModel('${escapeAttr(m.model_name)}','${wt}','${h}',${p})">测试</button> <button class="btn btn-sm btn-danger" onclick="deleteModel('${escapeAttr(m.model_name)}','${wt}','${h}',${p})">删除</button></td></tr>`;
      });
      html += `</tbody></table></div>`;
    }
    html += `</div></div>`;
    container.innerHTML = html;
  } catch (e) {
    container.innerHTML = `<div class="empty-state"><div class="empty-state-text" style="color:var(--danger)">加载失败: ${escapeHtml(e.message)}</div></div>`;
  }
}

// 构建模型类型下拉选项 HTML
function _buildWorkerTypeOptions(selected) {
  // 从已缓存的 model-types 中提取去重的 worker_type
  let wts = ["llm", "text2vec", "reranker"];
  // 如果有缓存的 types 数据，用实际的
  return wts.map(wt => `<option value="${wt}"${wt === selected ? ' selected' : ''}>${wt}</option>`).join('');
}

function showStartModelModal() {
  const opts = _buildWorkerTypeOptions("llm");
  openModal("添加模型", `
    <div class="form-field"><label>模型名称 *</label><input class="input" id="m-name" placeholder="如 TS-MOMA/DeepSeek-V4-Flash"></div>
    <div class="form-field"><label>模型类型 *</label><select class="select" id="m-type">${opts}</select></div>
    <div class="form-field"><label>提供者 *</label><select class="select" id="m-provider"><option value="proxy/openai" selected>proxy/openai（远程API调用）</option><option value="huggingface">huggingface（本地HF模型）</option><option value="vllm">vllm（本地vLLM推理）</option><option value="llama.cpp">llama.cpp（本地CPU推理）</option><option value="llama_cpp_server">llama_cpp_server（本地llama服务）</option></select></div>
    <div class="form-field"><label>API 地址</label><input class="input" id="m-apibase" placeholder="如 https://api.openai.com/v1（留空则用服务端默认）"></div>
    <div class="form-field"><label>API Key</label><input class="input" id="m-apikey" type="password" placeholder="API Key（留空则用服务端默认）"></div>
    <div class="form-field"><label>主机</label><input class="input" id="m-host" placeholder="可选，默认 127.0.0.1"></div>
    <div class="form-field"><label>端口</label><input class="input" id="m-port" type="number" placeholder="可选，默认 5670"></div>
  `, [
    { text: "取消", class: "btn", action: "closeModalDirect()" },
    { text: "添加", class: "btn btn-primary", action: "startModel()" },
  ]);
}

async function startModel() {
  const body = { model_name: document.getElementById("m-name").value, model_type: document.getElementById("m-type").value };
  const host = document.getElementById("m-host").value; if (host) body.host = host;
  const port = document.getElementById("m-port").value; if (port) body.port = parseInt(port);
  const provider = document.getElementById("m-provider").value; if (provider) body.provider = provider;
  const apiBase = document.getElementById("m-apibase").value; if (apiBase) body.api_base = apiBase;
  const apiKey = document.getElementById("m-apikey").value; if (apiKey) body.api_key = apiKey;
  if (!body.model_name || !body.model_type) { toast("模型名和类型不能为空", "error"); return; }
  try {
    await api("POST", "/models/start", body);
    toast("模型添加成功", "success");
    closeModalDirect();
    loadModels();
  } catch (e) { toast("添加失败: " + e.message, "error"); }
}

async function stopModel(name, type) {
  // 已废弃：删除模型会自动停止实例，不再单独提供停止功能
  toast("停止功能已移除，请使用删除按钮", "info");
}

function showEditModelModal(name, workerType, host, port) {
  const opts = _buildWorkerTypeOptions(workerType);
  openModal("编辑模型", `
    <div class="form-field"><label>模型名称 *</label><input class="input" id="edit-m-name" value="${escapeAttr(name)}" placeholder="模型名称"></div>
    <div class="form-field"><label>模型类型 *</label><select class="select" id="edit-m-wtype">${opts}</select></div>
    <div class="form-field"><label>提供者</label><select class="select" id="edit-m-provider"><option value="proxy/openai" selected>proxy/openai（远程API调用）</option><option value="huggingface">huggingface（本地HF模型）</option><option value="vllm">vllm（本地vLLM推理）</option><option value="llama.cpp">llama.cpp（本地CPU推理）</option><option value="llama_cpp_server">llama_cpp_server（本地llama服务）</option></select></div>
    <div class="form-field"><label>API 地址</label><input class="input" id="edit-m-apibase" placeholder="如 https://api.openai.com/v1（留空则用已有配置）"></div>
    <div class="form-field"><label>API Key</label><input class="input" id="edit-m-apikey" type="password" placeholder="输入新 Key 覆盖（留空则保留原值）"></div>
    <div class="form-field"><label>主机</label><input class="input" id="edit-m-host" value="${escapeAttr(host)}" placeholder="主机地址"></div>
    <div class="form-field"><label>端口</label><input class="input" id="edit-m-port" type="number" value="${port}" placeholder="端口"></div>
    <div style="margin-top:8px;padding:8px;background:var(--bg-secondary);border-radius:6px;font-size:13px;color:var(--text-secondary)">提示：编辑会停止当前模型实例，用新配置重新启动。仅对 DB 中有记录的模型有效。</div>
  `, [
    { text: "取消", class: "btn", action: "closeModalDirect()" },
    { text: "测试连通性", class: "btn", style: "background:var(--bg-info);color:var(--text-info);border:0.5px solid var(--color-border-info)", action: "testModelFromEdit()" },
    { text: "保存", class: "btn btn-primary", action: "editModel()" },
  ]);
}

async function editModel() {
  const body = {
    model_name: document.getElementById("edit-m-name").value,
    worker_type: document.getElementById("edit-m-wtype").value || "llm",
    host: document.getElementById("edit-m-host").value || "127.0.0.1",
    port: parseInt(document.getElementById("edit-m-port").value) || 5670,
    model_type: document.getElementById("edit-m-wtype").value || "llm",
  };
  if (!body.model_name) { toast("模型名不能为空", "error"); return; }
  const provider = document.getElementById("edit-m-provider").value; if (provider) body.provider = provider;
  const apiBase = document.getElementById("edit-m-apibase").value; if (apiBase) body.api_base = apiBase;
  const apiKey = document.getElementById("edit-m-apikey").value; if (apiKey) body.api_key = apiKey;
  try {
    await api("PUT", "/models/edit", body);
    toast("模型更新请求已发送", "success");
    closeModalDirect();
    loadModels();
  } catch (e) { toast("编辑失败: " + e.message, "error"); }
}

async function deleteModel(name, workerType, host, port) {
  if (!confirm(`确认删除模型 ${name}？\n\n此操作将：\n1. 停止运行中的实例\n2. 从数据库中删除该模型记录\n\n此操作不可逆！`)) return;
  try {
    await api("DELETE", "/models/delete", { model_name: name, worker_type: workerType, host: host, port: port });
    toast("模型已删除", "success");
    loadModels();
  } catch (e) { toast("删除失败: " + e.message, "error"); }
}

async function testModel(name, workerType, host, port) {
  toast(`正在测试 ${name} 连通性...`, "info");
  try {
    const data = await api("POST", "/models/test", { model_name: name, worker_type: workerType, host: host, port: port });
    toast(data.message || "连通正常", "success");
  } catch (e) { toast("连通性测试失败: " + e.message, "error"); }
}

async function testModelFromEdit() {
  const name = document.getElementById("edit-m-name").value;
  const wt = document.getElementById("edit-m-wtype").value || "llm";
  const host = document.getElementById("edit-m-host").value || "127.0.0.1";
  const port = parseInt(document.getElementById("edit-m-port").value) || 5670;
  if (!name) { toast("请先填写模型名称", "error"); return; }
  toast(`正在测试 ${name} 连通性...`, "info");
  try {
    const data = await api("POST", "/models/test", { model_name: name, worker_type: wt, host: host, port: port });
    toast(data.message || "连通正常", "success");
  } catch (e) { toast("连通性测试失败: " + e.message, "error"); }
}

// ==========================================================================
// 连接器
// ==========================================================================
async function loadConnectors() {
  const container = document.getElementById("conn-list");
  if (!container) return;
  container.innerHTML = `<div style="text-align:center;padding:40px"><div class="loading-spinner"></div></div>`;
  try {
    const [typesResp, listResp] = await Promise.all([api("GET", "/connectors/types"), api("GET", "/connectors")]);
    const types = typesResp.types || [];
    State.connectorList = listResp.connectors || [];
    let html = `<div class="stat-grid">
      <div class="stat-card"><div class="stat-icon">🔌</div><div class="stat-label">连接器类型</div><div class="stat-value">${types.length}</div></div>
      <div class="stat-card"><div class="stat-icon">🔗</div><div class="stat-label">已配置</div><div class="stat-value">${State.connectorList.length}</div></div>
    </div><div class="card"><div class="card-header"><span class="card-title">连接器列表</span></div><div class="card-body">`;
    if (State.connectorList.length === 0) html += `<div class="empty-state"><div class="empty-state-text">暂无连接器</div></div>`;
    else {
      html += `<div class="table-wrapper"><table class="data-table"><thead><tr><th>ID</th><th>类型</th><th>名称</th><th>操作</th></tr></thead><tbody>`;
      State.connectorList.forEach(c => { html += `<tr><td>${c.id || "-"}</td><td><span class="tag tag-blue">${escapeHtml(c.type || "-")}</span></td><td><strong>${escapeHtml(c.name || "-")}</strong></td><td><button class="btn btn-sm" onclick="testConnector('${escapeAttr(c.id)}')">测试</button></td></tr>`; });
      html += `</tbody></table></div>`;
    }
    container.innerHTML = html + `</div></div>`;
  } catch (e) { container.innerHTML = `<div class="empty-state"><div class="empty-state-text" style="color:var(--danger)">加载失败: ${escapeHtml(e.message)}</div></div>`; }
}

async function testConnector(id) {
  toast("正在测试...", "info");
  try { await api("POST", `/connectors/${id}/test`); toast("测试成功", "success"); }
  catch (e) { toast("测试失败: " + e.message, "error"); }
}

// ==========================================================================
// 会话历史
// ==========================================================================
async function loadConversations() {
  const container = document.getElementById("conv-list");
  if (!container) return;
  container.innerHTML = `<div style="text-align:center;padding:40px"><div class="loading-spinner"></div></div>`;
  try {
    const data = await api("GET", "/conversations/list");
    const convs = Array.isArray(data.conversations) ? data.conversations : [];
    let html = `<div class="card"><div class="card-header"><span class="card-title">会话列表 (${convs.length})</span></div><div class="card-body">`;
    if (convs.length === 0) html += `<div class="empty-state"><div class="empty-state-text">暂无会话</div></div>`;
    else {
      html += `<div class="table-wrapper"><table class="data-table"><thead><tr><th>会话摘要</th><th>创建时间</th><th>操作</th></tr></thead><tbody>`;
      convs.forEach(c => {
        const uid = c.conv_uid || c.con_uid || "";
        const summary = _cleanSummary(c.summary || c.title || uid);
        const created = c.gmt_created || c.create_time || "";
        html += `<tr><td>${escapeHtml(summary)}</td><td>${escapeHtml(created)}</td><td><button class="btn btn-sm" onclick="resumeConversation('${uid}')">恢复对话</button> <button class="btn btn-sm btn-danger" onclick="deleteConversation('${uid}', this)">删除</button></td></tr>`;
      });
      html += `</tbody></table></div>`;
    }
    container.innerHTML = html + `</div></div>`;
  } catch (e) { container.innerHTML = `<div class="empty-state"><div class="empty-state-text" style="color:var(--danger)">加载失败: ${escapeHtml(e.message)}</div></div>`; }
}

// 删除会话
async function deleteConversation(convUid, btn) {
  if (!convUid) return;
  if (!confirm("确定删除该会话？删除后不可恢复。")) return;
  try {
    await api("POST", "/conversations/delete", { con_uid: convUid });
    toast("已删除会话", "success");
    // 刷新列表 + 侧边栏
    loadConversations();
    loadRecentSessions();
  } catch (e) { toast("删除失败: " + e.message, "error"); }
}

// 从会话历史页面/侧边栏恢复对话
// 核心原则：数据源/知识库只从 chat_history 绑定信息读取，不从 App 配置覆盖
async function resumeConversation(convUid) {
  if (!convUid) { toast("会话 ID 为空", "error"); return; }

  // ★ 先保存当前活跃会话（不覆盖，不丢失）
  _saveActiveSession();

  // ★ 第1步：清空所有状态，防止上一个会话污染
  State.selectedDatasource = "";
  State.selectedKnowledge = "";
  State.selectedSkill = "";
  State.selectedConnectors = [];
  State.attachedFiles = [];
  State.currentSessionId = convUid;
  _currentConvUid = convUid;

  // ★ 第2步：切换到问答页（不走 navigate 避免触发 exitAppChat）
  _switchToAskPage();

  // ★ 第3步：清空对话区
  document.getElementById("chat-messages").innerHTML = "";
  toast("正在加载历史消息...", "info");

  try {
    // ★ 第4步：并行加载历史消息 + 绑定信息
    const [msgData, bindingData] = await Promise.all([
      api("GET", `/conversations/messages/history?con_uid=${convUid}`),
      api("GET", `/conversations/${convUid}/binding`).catch(() => ({ binding: {} })),
    ]);

    // 解析消息
    let msgs = msgData.messages;
    if (msgs && !Array.isArray(msgs)) msgs = msgs["data"] || [];
    msgs = Array.isArray(msgs) ? msgs : [];

    // 解析绑定信息（只从数据库读，不用 App 配置覆盖）
    const binding = bindingData.binding || {};
    let dbName = "";
    let kbName = binding.knowledge_space || "";
    // 数据源名称从 datasource_id 解析
    if (binding.datasource_id) {
      try {
        const dsData = await api("GET", "/datasources");
        const dsList = dsData.datasources || [];
        const found = dsList.find(d => d.id === binding.datasource_id);
        if (found) dbName = found.db_name || "";
      } catch {}
    }

    // ★ 第5步：设置 State（只从绑定信息来）
    if (dbName) State.selectedDatasource = dbName;
    if (kbName) State.selectedKnowledge = kbName;
    // 恢复的会话始终锁定只读（不管有没有绑定）
    lockAppToolbar({ database_name: dbName, knowledge_space: kbName, lockAlways: true });
    syncToolLabels();

    // ★ 第6步：根据后端实时 status 切换终止/发送按钮
    const convStatus = binding.status || "inactive";
    _updateSendStopButtons(convStatus === "active");

    // ★ 第7步：渲染历史消息（只渲染一次）
    _renderHistoryMessages(msgs);

    // ★ 第8步：注册到状态缓存 + 设置 currentActive
    _ensureSessionState(convUid);
    _currentActiveConvUid = convUid;
    _currentViewingConvUid = convUid; // ★ 用于"最近会话"高亮
    const st = _sessionStateMap.get(convUid);
    if (st) {
      st.appCode = _currentAppCode;
      st.appConfig = _currentAppConfig;
      st.state = {
        currentSessionId: State.currentSessionId,
        selectedDatasource: State.selectedDatasource,
        selectedKnowledge: State.selectedKnowledge,
        selectedSkill: State.selectedSkill,
        selectedConnectors: [...State.selectedConnectors],
        attachedFiles: [...State.attachedFiles],
      };
      st.scrollTop = document.getElementById("chat-messages")?.scrollTop || 0;
    }
    _renderActiveSessions();
    loadRecentSessions(); // ★ 刷新"最近会话"列表高亮

    if (msgs.length === 0) toast("该会话无历史消息", "info");
    else toast(`已恢复会话 (${msgs.length} 条消息)`, "success");
  } catch (e) { toast("加载历史消息失败: " + e.message, "error"); }
}

// 切换到问答页（不走 navigate 避免触发 exitAppChat/state 清理）
function _switchToAskPage() {
  State.currentPage = "ask";
  document.querySelectorAll(".nav-item").forEach(el => el.classList.toggle("active", el.dataset.page === "ask"));
  document.getElementById("topbar-title").textContent = PAGES.ask.title;
  document.getElementById("topbar-subtitle").textContent = PAGES.ask.subtitle;
  document.querySelectorAll(".page-content").forEach(el => el.classList.add("content-hidden"));
  const askPage = document.getElementById("page-ask");
  if (askPage) askPage.classList.remove("content-hidden");
  document.getElementById("ask-welcome").style.display = "none";
  document.getElementById("ask-chat").style.display = "flex";
}

// 根据会话运行状态切换发送/终止按钮
// isRunning=true → 显示终止按钮；isRunning=false → 显示发送按钮
function _updateSendStopButtons(isRunning) {
  const sendBtn = document.getElementById("chat-send-btn");
  const stopBtn = document.getElementById("chat-stop-btn");
  if (isRunning) {
    if (sendBtn) { sendBtn.disabled = true; sendBtn.style.display = "none"; }
    if (stopBtn) { stopBtn.style.display = "flex"; stopBtn.disabled = false; }
  } else {
    if (sendBtn) { sendBtn.disabled = false; sendBtn.style.display = "flex"; }
    if (stopBtn) { stopBtn.style.display = "none"; stopBtn.disabled = true; }
  }
}

// 渲染历史消息（统一函数，避免重复逻辑）
// DB-GPT 消息格式：
//   纯对话：每轮 human + ai + view（view 是 ai 的副本）
//   ReAct Agent：每轮 human + view（只有 view，无 ai，content 是 JSON 含 final_content）
// 策略：顺序遍历，渲染 human；回答优先 ai，没有 ai 才用 view（避免纯对话重复）
function _renderHistoryMessages(msgs) {
  const container = document.getElementById("chat-messages");
  if (!container) return;
  container.innerHTML = "";
  let lastRole = null;
  for (const m of msgs) {
    const role = m.role || m.type;
    const content = m.context || m.content || "";
    if (role === "human") {
      const cleanContent = content.replace(/^\[Database:\s*[^\]]+\]\s*/, "");
      appendMessage("user", cleanContent);
      lastRole = "human";
    } else if (role === "ai") {
      appendMessage("ai", renderMarkdown(content));
      lastRole = "ai";
    } else if (role === "view") {
      // view 是 ai 的副本——如果上一条已渲染了 ai，跳过
      if (lastRole === "ai") continue;
      // ReAct Agent 的 view（JSON 含 final_content），提取后渲染
      let displayContent = content;
      try {
        if (content.startsWith("{")) {
          const parsed = JSON.parse(content);
          if (parsed.final_content) displayContent = parsed.final_content;
        }
      } catch {}
      appendMessage("ai", renderMarkdown(displayContent));
      lastRole = "view";
    }
  }
}

// 锁定应用工具栏（数据源/知识库只读）。
// lockAlways=true 时无论有没有绑定都锁定（用于恢复的历史会话）
// lockAlways=false 或未传时：有绑定才锁定，无绑定恢复可点击（用于应用模式新建会话）
function lockAppToolbar(res) {
  const hasDb = !!res.database_name;
  const hasKb = !!res.knowledge_space;
  const lockAlways = res.lockAlways === true;
  const shouldLock = hasDb || hasKb || lockAlways;
  ["chat-tool-db", "chat-tool-kb"].forEach(id => {
    const btn = document.getElementById(id);
    if (btn) {
      if (shouldLock) {
        btn.style.opacity = "0.5"; btn.style.pointerEvents = "none"; btn.title = "会话已锁定，不可修改";
      } else {
        btn.style.opacity = ""; btn.style.pointerEvents = ""; btn.title = "";
      }
    }
  });
  const dbLabel = document.getElementById("chat-tool-db-label");
  if (dbLabel) dbLabel.textContent = res.database_name || (lockAlways ? "未绑定" : "数据源");
  const kbLabel = document.getElementById("chat-tool-kb-label");
  if (kbLabel) kbLabel.textContent = res.knowledge_space || (lockAlways ? "未绑定" : "知识库");
}

// ==========================================================================
// 模态框
// ==========================================================================
function openModal(title, bodyHtml, buttons) {
  document.getElementById("modal-title").textContent = title;
  document.getElementById("modal-body").innerHTML = bodyHtml;
  document.getElementById("modal-footer").innerHTML = buttons.map(b => `<button class="${b.class}"${b.style ? ` style="${b.style}"` : ''} onclick="${b.action}">${b.text}</button>`).join("");
  document.getElementById("modal-overlay").style.display = "flex";
}

function closeModal(e) { if (e.target.id === "modal-overlay") closeModalDirect(); }
function closeModalDirect() { document.getElementById("modal-overlay").style.display = "none"; }

// ==========================================================================
// 健康检查
// ==========================================================================
async function checkHealth() {
  try {
    const data = await api("GET", "/health");
    State.health = data;
    const footer = document.querySelector(".sidebar-footer");
    if (footer) footer.innerHTML = `<span class="status-dot ${data.status !== 'ok' ? 'offline' : ''}"></span>${data.status === "ok" ? "服务正常" : "服务异常"} · ${data.model || ""}`;
  } catch {
    const footer = document.querySelector(".sidebar-footer");
    if (footer) footer.innerHTML = `<span class="status-dot offline"></span>服务异常`;
  }
}

// ==========================================================================
// 工具
// ==========================================================================
function escapeAttr(text) { return String(text).replace(/'/g, "\\'").replace(/"/g, "&quot;"); }
function toggleSidebar() { document.querySelector(".sidebar").classList.toggle("sidebar-collapsed"); }

// 点击外部关闭下拉（覆盖欢迎页 + 对话工具栏的所有选择器）
document.addEventListener("click", (e) => {
  const pairs = [
    ["#tool-db", "#dropdown-db"], ["#tool-kb", "#dropdown-kb"],
    ["#tool-skill", "#dropdown-skill"], ["#tool-conn", "#dropdown-conn"],
    ["#chat-tool-db", "#chat-dropdown-db"], ["#chat-tool-kb", "#chat-dropdown-kb"],
    ["#chat-tool-skill", "#chat-dropdown-skill"], ["#chat-tool-conn", "#chat-dropdown-conn"],
  ];
  pairs.forEach(([btnSel, ddSel]) => {
    if (e.target.closest(btnSel) || e.target.closest(ddSel)) return;
    const dd = document.querySelector(ddSel);
    if (dd) dd.style.display = "none";
  });
  // 附件文件选择框点击不关闭
  if (e.target.closest("#chat-tool-attach") || e.target.closest("#file-input") ||
      e.target.closest("#tool-attach") || e.target.closest("#hero-file-input")) return;
});

// ==========================================================================
// 初始化
// ==========================================================================
async function preloadData() {
  try {
    const [dsResp, kbResp, modelResp, skillResp, connResp, promptResp] = await Promise.allSettled([
      api("GET", "/datasources"),
      api("GET", "/knowledge/spaces"),
      api("GET", "/models/list"),
      api("GET", "/ask/skills"),
      api("GET", "/connectors"),
      api("POST", "/prompts/list", { page: 1, page_size: 100 }),
    ]);
    if (dsResp.status === "fulfilled") State.datasourceList = dsResp.value.datasources || [];
    if (kbResp.status === "fulfilled") State.knowledgeSpaces = kbResp.value.spaces || [];
    if (skillResp.status === "fulfilled") State.skillList = skillResp.value.skills || [];
    if (connResp.status === "fulfilled") State.connectorList = connResp.value.connectors || [];
    if (promptResp.status === "fulfilled") {
      const prompts = promptResp.value.prompts;
      State.promptList = Array.isArray(prompts) ? prompts : (prompts && prompts.data ? prompts.data : []);
    }
    if (modelResp.status === "fulfilled") {
      State.modelList = modelResp.value.models || [];
      const sel = document.getElementById("hero-model");
      if (sel) {
        let html = '<option value="">默认模型</option>';
        State.modelList.forEach(m => { html += `<option value="${m.model_name}">${m.model_name}</option>`; });
        sel.innerHTML = html;
      }
    }
  } catch {}
}

function initApp() {
  checkHealth();
  setInterval(checkHealth, 30000);
  preloadData();
  loadRecentSessions();
  setInterval(loadRecentSessions, 30000);
  // 心跳：每 5s 清理已结束但状态未更新的会话
  setInterval(_heartbeat, 5000);
}

// 心跳：检查 _workingSessionIds 中是否有会话已不在 _abortControllers 中（SSE 已结束）
function _heartbeat() {
  if (_workingSessionIds.size === 0) return;
  let changed = false;
  for (const uid of [..._workingSessionIds]) {
    if (!_abortControllers[uid]) {
      // SSE 已结束但 working 状态未清理
      _workingSessionIds.delete(uid);
      changed = true;
    }
  }
  if (changed) _renderActiveSessions();
}

// 解析时间字符串为时间戳（支持 "2024-01-01 12:00:00" 等格式）
function _parseTime(t) {
  if (!t) return 0;
  if (typeof t === "number") return t;
  const d = new Date(t.replace(/-/g, "/"));
  return isNaN(d.getTime()) ? 0 : d.getTime();
}

// 清洗会话摘要：去除数据源/知识库等附加信息，只保留用户提问内容
function _cleanSummary(summary) {
  if (!summary) return "";
  let s = String(summary).trim();
  // 去除常见的附加信息模式：
  // "[Database: xxx] 问题内容" → "问题内容"  （react-agent user_input 前缀）
  // "数据源: xxx | 知识库: yyy | 问题内容" → "问题内容"
  // "【数据源:xxx】问题内容" → "问题内容"
  // "数据库:xxx 知识库:yyy 问题内容" → "问题内容"
  // 去除 [Database: xxx] [Knowledge: yyy] 等前缀（可能多个连排）
  while (/^\[(database|datasource|data\s*source|knowledge|知识库|数据源|数据库)[:：]\s*[^\]]*\]\s*/i.test(s)) {
    s = s.replace(/^\[(database|datasource|data\s*source|knowledge|知识库|数据源|数据库)[:：]\s*[^\]]*\]\s*/i, "");
  }
  s = s.replace(/^【[^】]*】\s*/, "");
  s = s.replace(/^数据源[:：]\s*\S+\s*[|｜]\s*/i, "");
  s = s.replace(/^知识库[:：]\s*\S+\s*[|｜]\s*/i, "");
  s = s.replace(/^[|｜]\s*数据源[:：]\s*\S+\s*[|｜]\s*/i, "");
  s = s.replace(/^[|｜]\s*知识库[:：]\s*\S+\s*[|｜]\s*/i, "");
  // 去除前缀中的 "数据源:xxx" "知识库:yyy" 等
  const parts = s.split(/[|｜]/).map(p => p.trim());
  const filtered = parts.filter(p => {
    if (/^(数据源|数据库|知识库|knowledge|datasource|data\s*source)[:：]/i.test(p)) return false;
    if (/^(技能|skill)[:：]/i.test(p)) return false;
    if (/^(连接器|connector)[:：]/i.test(p)) return false;
    return true;
  });
  s = filtered.join(" ").trim();
  if (!s) s = String(summary).trim();
  return s;
}

// 加载会话列表——"进行中"由 _workingSessionIds 驱动，"最近会话"由后端 inactive 列表驱动
async function loadRecentSessions() {
  try {
    const data = await api("GET", "/conversations/list");
    let convs = data.conversations || [];
    if (!Array.isArray(convs)) convs = convs.data || [];

    // 只渲染"最近会话"（status != active 且不在进行中列表），按最后消息时间排序取前 5
    const inactiveConvs = convs.filter(c => c.status !== "active" && !_workingSessionIds.has(c.conv_uid))
      .sort((a, b) => {
        const ta = _parseTime(a.last_message_time) || _parseTime(a.gmt_created) || 0;
        const tb = _parseTime(b.last_message_time) || _parseTime(b.gmt_created) || 0;
        return tb - ta;
      })
      .slice(0, 5);

    // "进行中"区域完全由 _workingSessionIds 驱动（不依赖后端 status）
    _renderActiveSessions();

    // 渲染"最近会话"
    const recentContainer = document.getElementById("recent-session-list");
    const recentWrapper = document.getElementById("sidebar-recent-sessions");
    if (!recentContainer || !recentWrapper) return;
    if (inactiveConvs.length === 0) { recentWrapper.style.display = "none"; return; }
    recentWrapper.style.display = "block";
    recentContainer.innerHTML = inactiveConvs.map(c => {
      const uid = c.conv_uid || "";
      const rawSummary = c.summary || c.title || uid.slice(0, 12);
      const summary = _cleanSummary(rawSummary);
      const truncated = summary.length > 20 ? summary.slice(0, 20) + "\u2026" : summary;
      // ★ 用 _currentViewingConvUid 而非 _currentActiveConvUid 判断高亮
      const isSelected = uid === _currentViewingConvUid;
      const isPinned = _pinnedSessionIds.includes(uid);
      return `<div class="recent-session-item" onclick="resumeConversation('${uid}')" title="${escapeHtml(summary)}" style="padding:6px 8px;cursor:pointer;border-radius:4px;font-size:12px;color:var(--text-secondary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;${isSelected ? "background:var(--accent-dim);color:var(--accent);" : ""}">
      ${isPinned ? '<i class="fa-solid fa-thumbtack" style="margin-right:4px;color:var(--amber);font-size:10px;"></i>' : ''}${escapeHtml(truncated)}
    </div>`;
    }).join("");
  } catch {}
}

// ==========================================================================
// 应用管理（类 Dify 模式：App=配置模板，对话=独立会话）
// ==========================================================================
let _currentAppCode = null;
let _currentAppConfig = null;  // {database_name, knowledge_space, model, recommend_questions}
let _currentConvUid = null;    // 当前会话 ID
let _abortControllers = {};     // convUid → AbortController，支持多会话并行 SSE
let _sessionStateMap = new Map(); // convUid → {state, appCode, appConfig, scrollTop}
let _workingSessionIds = new Set(); // 运行中的会话 ID 集合
let _pinnedSessionIds = [];    // 置顶会话 ID 列表
let _currentActiveConvUid = null; // 当前显示的活跃会话 convUid（用于"进行中"高亮）
let _currentViewingConvUid = null; // 当前正在查看的会话 convUid（用于"最近会话"高亮，跨两个列表）

// === Parking Lot 容器（隐藏 DOM，存放切走的会话消息节点） ===
let _parkingLot = null;
function _getParkingLot() {
  if (!_parkingLot) {
    _parkingLot = document.createElement("div");
    _parkingLot.id = "chat-parking-lot";
    _parkingLot.style.display = "none";
    document.body.appendChild(_parkingLot);
  }
  return _parkingLot;
}

// 获取当前会话的 AbortController（不存在则新建）
function _getAbortController() {
  const key = _currentConvUid || State.currentSessionId || "_default";
  if (!_abortControllers[key]) {
    _abortControllers[key] = new AbortController();
  }
  return _abortControllers[key];
}

// 获取当前会话的 AbortController 的 signal
function _currentSignal() {
  return _getAbortController().signal;
}

// 创建/获取会话状态缓存
function _ensureSessionState(convUid) {
  if (!convUid) return null;
  if (!_sessionStateMap.has(convUid)) {
    _sessionStateMap.set(convUid, {
      convUid,
      state: {
        currentSessionId: "",
        selectedDatasource: "",
        selectedKnowledge: "",
        selectedSkill: "",
        selectedConnectors: [],
        attachedFiles: [],
      },
      appCode: null,
      appConfig: null,
      scrollTop: 0,
    });
  }
  return _sessionStateMap.get(convUid);
}

// 设置会话工作状态
function _setSessionWorking(convUid, working) {
  if (!convUid) return;
  if (working) {
    _workingSessionIds.add(convUid);
  } else {
    _workingSessionIds.delete(convUid);
  }
}

// === Parking Lot 核心：把当前 chat-messages 的子节点移到 parking 容器 ===
function _parkCurrentSession() {
  const convUid = _currentConvUid || State.currentSessionId;
  if (!convUid) return;
  const chatContainer = document.getElementById("chat-messages");
  if (!chatContainer || chatContainer.children.length === 0) return;

  // 为该会话创建一个专属 parking slot（如果不存在）
  let slot = _getParkingLot().querySelector(`[data-park-for="${convUid}"]`);
  if (!slot) {
    slot = document.createElement("div");
    slot.setAttribute("data-park-for", convUid);
    _getParkingLot().appendChild(slot);
  }
  // 移动所有子节点到 parking slot（DOM 移动，不销毁，SSE 回调引用仍有效）
  while (chatContainer.firstChild) {
    slot.appendChild(chatContainer.firstChild);
  }
  // 保存 scrollTop
  const st = _sessionStateMap.get(convUid);
  if (st) st.scrollTop = chatContainer.scrollTop;
}

// === Parking Lot 恢复：把 parking slot 的节点移回 chat-messages ===
function _unparkSession(convUid) {
  const chatContainer = document.getElementById("chat-messages");
  if (!chatContainer) return;
  // 先清空当前容器（但不清 parking — 有可能是新建空白）
  chatContainer.innerHTML = "";
  const slot = _getParkingLot().querySelector(`[data-park-for="${convUid}"]`);
  if (slot) {
    while (slot.firstChild) {
      chatContainer.appendChild(slot.firstChild);
    }
    slot.remove();
  }
  const st = _sessionStateMap.get(convUid);
  if (st) chatContainer.scrollTop = st.scrollTop || 0;
}

// === 移除会话的 parking slot ===
function _removeParkingSlot(convUid) {
  const slot = _getParkingLot().querySelector(`[data-park-for="${convUid}"]`);
  if (slot) slot.remove();
}

// === 清理 parking lot 中已无缓存且非运行中的会话 ===
function _cleanupParking() {
  const slots = _getParkingLot().querySelectorAll("[data-park-for]");
  slots.forEach(slot => {
    const uid = slot.getAttribute("data-park-for");
    if (!_sessionStateMap.has(uid) && !_workingSessionIds.has(uid)) {
      slot.remove();
    }
  });
}

// ==========================================================================
// 活跃会话管理（侧边栏"进行中的会话"）
// ==========================================================================

// 保存当前对话到状态缓存 + parking lot
function _saveActiveSession() {
  const chatContainer = document.getElementById("chat-messages");
  const isChatVisible = document.getElementById("ask-chat")?.style.display === "flex";
  const convUid = _currentConvUid || State.currentSessionId;
  if (!isChatVisible || !convUid || !chatContainer) return;

  // 用 Parking Lot 移动 DOM 节点（不序列化为字符串）
  _parkCurrentSession();

  // 保存状态快照
  const snapshot = {
    convUid,
    appCode: _currentAppCode,
    appConfig: _currentAppConfig,
    state: {
      currentSessionId: State.currentSessionId,
      selectedDatasource: State.selectedDatasource,
      selectedKnowledge: State.selectedKnowledge,
      selectedSkill: State.selectedSkill,
      selectedConnectors: [...State.selectedConnectors],
      attachedFiles: [...State.attachedFiles],
    },
  };
  const existing = _sessionStateMap.get(convUid) || {};
  _sessionStateMap.set(convUid, Object.assign(existing, snapshot));
  _currentActiveConvUid = convUid;
  _renderActiveSessions();
}

// 渲染侧边栏分组列表
function _renderActiveSessions() {
  const activeContainer = document.getElementById("active-session-list");
  const activeWrapper = document.getElementById("sidebar-active-sessions");
  if (activeContainer && activeWrapper) {
    const workingUids = [..._workingSessionIds];
    if (workingUids.length === 0) {
      activeWrapper.style.display = "none";
    } else {
      activeWrapper.style.display = "block";
      activeContainer.innerHTML = workingUids.map(uid => {
        const s = _sessionStateMap.get(uid);
        let summary = uid.slice(0, 12);
        // 从 parking slot 中提取第一条用户消息作为摘要
        try {
          const slot = _getParkingLot().querySelector(`[data-park-for="${uid}"]`);
          const chatEl = slot || document.getElementById("chat-messages");
          if (chatEl) {
            const firstUser = chatEl.querySelector(".msg-user .msg-text");
            if (firstUser) summary = firstUser.textContent.slice(0, 25);
          }
        } catch {}
        summary = _cleanSummary(summary);
        const truncated = summary.length > 20 ? summary.slice(0, 20) + "\u2026" : summary;
        const isActive = uid === _currentViewingConvUid;
        return `<div class="active-session-item" onclick="switchToActiveSession('${uid}')" title="${escapeHtml(summary)}" style="padding:6px 8px;cursor:pointer;border-radius:4px;font-size:12px;color:var(--text-secondary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;${isActive ? "background:var(--accent-dim);color:var(--accent);" : ""}">
      <span style="color:var(--teal)">\u25CF</span> ${escapeHtml(truncated)}
      <i class="fa-solid fa-xmark" onclick="closeActiveSession('${uid}', event)" style="float:right;color:var(--text-tertiary);cursor:pointer;font-size:11px;margin-left:4px;" title="关闭"></i>
    </div>`;
      }).join("");
    }
  }
}

// 切换到指定活跃会话（按 convUid）
function switchToActiveSession(convUid) {
  const s = _sessionStateMap.get(convUid);
  if (!s) {
    // 缓存未命中，从后端恢复
    resumeConversation(convUid);
    return;
  }

  // 先保存当前会话（parking 移走 DOM 节点）
  if (_currentActiveConvUid && _currentActiveConvUid !== convUid) {
    _saveActiveSession();
  }

  // 恢复目标会话状态
  _currentAppCode = s.appCode;
  _currentAppConfig = s.appConfig;
  _currentConvUid = s.convUid;
  State.currentSessionId = s.state.currentSessionId || s.convUid;
  State.selectedDatasource = s.state.selectedDatasource || "";
  State.selectedKnowledge = s.state.selectedKnowledge || "";
  State.selectedSkill = s.state.selectedSkill || "";
  State.selectedConnectors = s.state.selectedConnectors || [];
  State.attachedFiles = s.state.attachedFiles || [];

  _currentActiveConvUid = convUid;
  _currentViewingConvUid = convUid; // ★ 用于跨列表高亮
  _switchToAskPage();
  _unparkSession(convUid);

  // 恢复工具栏
  if (_currentAppCode && _currentAppConfig) {
    lockAppToolbar(_currentAppConfig.resources || {});
    _showAppIndicator();
  } else {
    const hasDs = !!State.selectedDatasource;
    const hasKb = !!State.selectedKnowledge;
    if (hasDs || hasKb) {
      lockAppToolbar({ database_name: State.selectedDatasource, knowledge_space: State.selectedKnowledge, lockAlways: true });
    } else {
      lockAppToolbar({ database_name: "", knowledge_space: "" });
    }
  }
  syncToolLabels();
  updateChatContextDisplay();
  scrollChatBottom();
  _renderActiveSessions();
  loadRecentSessions(); // ★ 刷新"最近会话"列表高亮

  // 根据 AbortController 是否存在决定终止/发送按钮
  const isStreaming = !!_abortControllers[convUid];
  _updateSendStopButtons(isStreaming);
}

// 关闭活跃会话（从缓存移除 + 清理 parking）
function closeActiveSession(convUid, event) {
  if (event) event.stopPropagation();
  if (!convUid || !_sessionStateMap.has(convUid)) return;
  const wasCurrent = convUid === _currentActiveConvUid;

  // 中止该会话的 SSE（如果在运行）
  if (_abortControllers[convUid]) {
    _abortControllers[convUid].abort();
    delete _abortControllers[convUid];
  }
  _sessionStateMap.delete(convUid);
  _workingSessionIds.delete(convUid);
  _removeParkingSlot(convUid);
  _pinnedSessionIds = _pinnedSessionIds.filter(id => id !== convUid);

  if (wasCurrent) {
    _currentActiveConvUid = null;
    _currentViewingConvUid = null;
    if (_workingSessionIds.size > 0) {
      switchToActiveSession([..._workingSessionIds][0]);
    } else {
      navigate("ask");
    }
  }
  _renderActiveSessions();
}

// 显示应用指示器
function _showAppIndicator() {
  const indicator = document.getElementById("app-indicator");
  if (indicator && _currentAppConfig) {
    const res = _currentAppConfig.resources || {};
    const parts = [`📦 ${_currentAppConfig.app_name}`];
    if (res.database_name) parts.push(`📊 ${res.database_name} (已锁定)`);
    if (res.knowledge_space) parts.push(`📚 ${res.knowledge_space} (已锁定)`);
    indicator.innerHTML = parts.join(" | ") +
      ` <button class="btn btn-sm" style="margin-left:8px" onclick="newAppSession()">新建会话</button>` +
      ` <button class="btn btn-sm" onclick="showAppHistory()">历史会话</button>` +
      ` <button class="btn btn-sm" onclick="exitAppChat()">退出应用</button>`;
    indicator.style.display = "block";
  }
}

async function loadApps() {
  const container = document.getElementById("app-list");
  if (!container) return;
  container.innerHTML = `<div style="text-align:center;padding:40px"><div class="loading-spinner"></div></div>`;
  try {
    const data = await api("GET", "/apps");
    const apps = data.apps || [];
    let html = `<div class="stat-grid">
      <div class="stat-card"><div class="stat-icon">📦</div><div class="stat-label">应用总数</div><div class="stat-value">${apps.length}</div></div>
    </div>`;
    if (apps.length === 0) {
      html += `<div class="empty-state"><div class="empty-state-icon">📦</div><div class="empty-state-text">暂无应用，点击"创建应用"开始</div></div>`;
    } else {
      html += `<div class="app-card-grid">`;
      for (const a of apps) {
        let badges = "";
        try {
          const detail = await api("GET", `/apps/${a.app_code}`);
          const res = detail.app.resources || {};
          const parts = [];
          if (res.database_name) parts.push(`<span class="app-badge">📊 ${escapeHtml(res.database_name)}</span>`);
          if (res.knowledge_space) parts.push(`<span class="app-badge">📚 ${escapeHtml(res.knowledge_space)}</span>`);
          if (res.model) parts.push(`<span class="app-badge">🤖 ${escapeHtml(res.model)}</span>`);
          badges = parts.join(" ");
        } catch {}
        html += `<div class="app-card">
          <div class="app-card-header">
            <span class="app-card-icon">📦</span>
            <span class="app-card-name">${escapeHtml(a.app_name || "")}</span>
          </div>
          <div class="app-card-desc">${escapeHtml(a.app_describe || "无描述")}</div>
          <div class="app-card-badges">${badges}</div>
          <div class="app-card-actions">
            <button class="btn btn-sm btn-primary" onclick="enterAppChat('${a.app_code}','${escapeAttr(a.app_name)}')">进入对话</button>
            <button class="btn btn-sm" onclick="editAppConfig('${a.app_code}')">编辑</button>
            <button class="btn btn-sm" onclick="showAppDetail('${a.app_code}')">详情</button>
            <button class="btn btn-sm btn-danger" onclick="deleteApp('${a.app_code}','${escapeAttr(a.app_name)}')">删除</button>
          </div>
        </div>`;
      }
      html += `</div>`;
    }
    container.innerHTML = html;
  } catch (e) {
    container.innerHTML = `<div class="empty-state"><div class="empty-state-text" style="color:var(--danger)">加载失败: ${escapeHtml(e.message)}</div></div>`;
  }
}

async function showCreateAppModal() {
  const dsOptions = State.datasourceList.map(d => `<option value="${escapeAttr(d.db_name)}">${escapeHtml(d.db_name)} (${escapeHtml(d.db_type)})</option>`).join("");
  const kbOptions = (State.knowledgeSpaces || []).map(k => {
    const name = typeof k === "string" ? k : (k.name || k.space_name || "");
    return `<option value="${escapeAttr(name)}">${escapeHtml(name)}</option>`;
  }).join("");
  const modelOptions = (State.modelList || []).map(m => `<option value="${escapeAttr(m.model_name)}">${escapeHtml(m.model_name)}</option>`).join("");
  // 直接获取提示词列表（不依赖 preloadData 缓存）
  let promptOptions = "";
  try {
    const pdata = await api("POST", "/prompts/list", { page: 1, page_size: 100 });
    let prompts = pdata.prompts || [];
    if (!Array.isArray(prompts) && prompts.data) prompts = prompts.data;
    promptOptions = prompts.map(p => {
      const name = p.prompt_name || p.name || "";
      const code = p.prompt_code || p.id || name;
      return `<option value="${escapeAttr(code)}">${escapeHtml(name)}</option>`;
    }).join("");
  } catch {}

  openModal("创建应用", `
    <div class="form-field"><label>应用名称 *</label><input class="input" id="app-name" placeholder="如：双11电商分析助手"></div>
    <div class="form-field"><label>应用描述</label><input class="input" id="app-describe" placeholder="如：基于chase_double11的电商数据分析"></div>
    <div class="form-field" style="display:none;"><label>对话模式</label><select class="select" id="app-team-mode">
      <option value="chat_react_agent" selected>ReAct Agent（默认）</option>
    </select></div>
    <div class="form-field"><label>📊 绑定数据源（创建后不可变）</label><select class="select" id="app-database"><option value="">不绑定</option>${dsOptions}</select></div>
    <div class="form-field"><label>📚 绑定知识库（创建后不可变）</label><select class="select" id="app-knowledge"><option value="">不绑定</option>${kbOptions}</select></div>
    <div class="form-field"><label>模型</label><select class="select" id="app-model">${modelOptions || '<option value="TS/GLM-5.2">TS/GLM-5.2</option>'}</select></div>
    <div class="form-field"><label>📝 自定义提示词</label><select class="select" id="app-prompt"><option value="">不添加</option>${promptOptions}</select>
    <div class="form-hint" style="margin-top:4px">💡 选中的提示词会<strong>追加</strong>到默认 system prompt 的「Please Solve this task:」之前，作为业务约束/上下文补充。ReAct 格式约束保持不变。</div></div>
    <div class="form-row">
      <div class="form-field form-field-half"><label>温度</label><input class="input" id="app-temperature" type="number" step="0.1" value="0.6"></div>
      <div class="form-field form-field-half"><label>最大 token</label><input class="input" id="app-max-tokens" type="number" value="4000"></div>
    </div>
    <div class="form-field"><label>推荐问题（每行一个）</label><textarea class="input" id="app-questions" rows="3" placeholder="双十一有哪些商家参与活动&#10;哪个平台影响力最大"></textarea></div>
    <div class="form-hint">💡 应用创建后，数据源和知识库不可修改。对话中仍可调整技能、MCP 连接器和上传文件。</div>
  `, [
    { text: "取消", class: "btn", action: "closeModalDirect()" },
    { text: "创建", class: "btn btn-primary", action: "createApp()" },
  ]);
}

async function createApp() {
  const name = document.getElementById("app-name").value;
  if (!name) { toast("应用名称不能为空", "error"); return; }
  const questions = document.getElementById("app-questions").value.split("\n").map(s => s.trim()).filter(s => s);
  const body = {
    app_name: name,
    app_describe: document.getElementById("app-describe").value,
    team_mode: document.getElementById("app-team-mode").value,  // 字段名兼容后端
    chat_mode: document.getElementById("app-team-mode").value,
    database_name: document.getElementById("app-database").value,
    knowledge_space: document.getElementById("app-knowledge").value,
    model: document.getElementById("app-model").value,
    prompt_template: document.getElementById("app-prompt").value,
    temperature: parseFloat(document.getElementById("app-temperature").value) || 0.6,
    max_new_tokens: parseInt(document.getElementById("app-max-tokens").value) || 4000,
    recommend_questions: questions,
  };
  try {
    await api("POST", "/apps", body);
    toast("应用创建成功", "success");
    closeModalDirect();
    loadApps();
  } catch (e) { toast("创建失败: " + e.message, "error"); }
}

async function showAppDetail(appCode) {
  try {
    const data = await api("GET", `/apps/${appCode}`);
    const app = data.app;
    const res = app.resources || {};
    openModal(`应用详情 — ${app.app_name}`, `
      <div class="form-field"><label>应用名称</label><div class="form-readonly">${escapeHtml(app.app_name || "")}</div></div>
      <div class="form-field"><label>描述</label><div class="form-readonly">${escapeHtml(app.app_describe || "无")}</div></div>
      <div class="form-field"><label>Agent 模式</label><div class="form-readonly">${escapeHtml(app.team_mode || "single_agent")}</div></div>
      <div class="form-field"><label>📊 数据源（已绑定）</label><div class="form-readonly">${escapeHtml(res.database_name || "未绑定")}</div></div>
      <div class="form-field"><label>📚 知识库（已绑定）</label><div class="form-readonly">${escapeHtml(res.knowledge_space || "未绑定")}</div></div>
      <div class="form-field"><label>🤖 模型</label><div class="form-readonly">${escapeHtml(res.model || "默认")}</div></div>
      <div class="form-field"><label>推荐问题</label><div class="form-readonly">${(app.recommend_questions || []).map(q => `• ${escapeHtml(q)}`).join("<br>") || "无"}</div></div>
      <div class="form-hint">💡 数据源和知识库已绑定，不可修改。对话中可调整技能、MCP 和文件。</div>
    `, [{ text: "关闭", class: "btn", action: "closeModalDirect()" }]);
  } catch (e) { toast("获取详情失败: " + e.message, "error"); }
}

async function deleteApp(appCode, appName) {
  if (!confirm(`确认删除应用「${appName}」？`)) return;
  try { await api("DELETE", `/apps/${appCode}`); toast("已删除", "success"); loadApps(); }
  catch (e) { toast("删除失败: " + e.message, "error"); }
}

// 编辑应用配置（chat_mode/模型/推荐问题可改，数据源/知识库只读）
async function editAppConfig(appCode) {
  try {
    const data = await api("GET", `/apps/${appCode}`);
    const app = data.app;
    const res = app.resources || {};
    const modelOptions = (State.modelList || []).map(m => `<option value="${escapeAttr(m.model_name)}" ${m.model_name === res.model ? "selected" : ""}>${escapeHtml(m.model_name)}</option>`).join("");
    // 直接获取提示词列表
    let promptOptions = "";
    try {
      const pdata = await api("POST", "/prompts/list", { page: 1, page_size: 100 });
      let prompts = pdata.prompts || [];
      if (!Array.isArray(prompts) && prompts.data) prompts = prompts.data;
      promptOptions = prompts.map(p => {
        const name = p.prompt_name || p.name || "";
        const code = p.prompt_code || p.id || name;
        return `<option value="${escapeAttr(code)}" ${code === res.prompt_template ? "selected" : ""}>${escapeHtml(name)}</option>`;
      }).join("");
    } catch {}
    const dsOptions = State.datasourceList.map(d => `<option value="${escapeAttr(d.db_name)}" ${d.db_name === res.database_name ? "selected" : ""}>${escapeHtml(d.db_name)}</option>`).join("");
    const kbOptions = (State.knowledgeSpaces || []).map(k => {
      const name = typeof k === "string" ? k : (k.name || k.space_name || "");
      return `<option value="${escapeAttr(name)}" ${name === res.knowledge_space ? "selected" : ""}>${escapeHtml(name)}</option>`;
    }).join("");

    openModal(`编辑应用 — ${app.app_name}`, `
      <div class="form-field"><label>应用名称</label><input class="input" id="edit-app-name" value="${escapeAttr(app.app_name || "")}"></div>
      <div class="form-field"><label>应用描述</label><input class="input" id="edit-app-describe" value="${escapeAttr(app.app_describe || "")}"></div>
      <div class="form-field" style="display:none;"><label>对话模式</label><select class="select" id="edit-app-chat-mode">
        <option value="chat_react_agent" selected>ReAct Agent（默认）</option>
      </select></div>
      <div class="form-field"><label>📊 数据源</label><select class="select" id="edit-app-database"><option value="">不绑定</option>${dsOptions}</select></div>
      <div class="form-field"><label>📚 知识库</label><select class="select" id="edit-app-knowledge"><option value="">不绑定</option>${kbOptions}</select></div>
      <div class="form-field"><label>模型</label><select class="select" id="edit-app-model">${modelOptions || '<option value="TS/GLM-5.2">TS/GLM-5.2</option>'}</select></div>
      <div class="form-field"><label>📝 自定义提示词</label><select class="select" id="edit-app-prompt"><option value="">不添加</option>${promptOptions}</select>
      <div class="form-hint" style="margin-top:4px">💡 追加到默认 system prompt 的「Please Solve this task:」之前，作为业务约束/上下文。ReAct 格式约束保持不变。</div></div>
      <div class="form-field"><label>推荐问题（每行一个）</label><textarea class="input" id="edit-app-questions" rows="3">${(app.recommend_questions || []).join("\n")}</textarea></div>
      <div class="form-hint">💡 可修改数据源、知识库、对话模式、模型和推荐问题。</div>
    `, [
      { text: "取消", class: "btn", action: "closeModalDirect()" },
      { text: "保存", class: "btn btn-primary", action: `submitEditAppConfig('${appCode}')` },
    ]);
  } catch (e) { toast("获取详情失败: " + e.message, "error"); }
}

async function submitEditAppConfig(appCode) {
  const body = {
    app_name: document.getElementById("edit-app-name").value,
    app_describe: document.getElementById("edit-app-describe").value,
    chat_mode: document.getElementById("edit-app-chat-mode").value,
    database_name: document.getElementById("edit-app-database").value,
    knowledge_space: document.getElementById("edit-app-knowledge").value,
    model: document.getElementById("edit-app-model").value,
    prompt_template: document.getElementById("edit-app-prompt").value,
    temperature: 0.6,
    max_new_tokens: 4000,
    recommend_questions: document.getElementById("edit-app-questions").value.split("\n").map(s => s.trim()).filter(s => s),
  };
  try {
    await api("POST", `/apps/${appCode}/edit`, body);
    toast("修改成功", "success");
    closeModalDirect();
    loadApps();
  } catch (e) { toast("修改失败: " + e.message, "error"); }
}

// 进入应用对话模式 —— 与点击"智能问答"逻辑一致，只是带上数据源/知识库
async function enterAppChat(appCode, appName) {
  // 先保存当前活跃会话（parking 移走 DOM）
  _saveActiveSession();
  _currentConvUid = null; // 新会话，等用户输入第一个问题后才创建
  let appConfig = null;
  let res = {};
  try {
    const data = await api("GET", `/apps/${appCode}`);
    appConfig = data.app;
    res = appConfig.resources || {};
  } catch (e) {}
  // ★ 从应用进入：直接显示聊天界面（不走 navigate("ask")，因为那样会显示空白欢迎页）
  State.currentSessionId = "";
  _currentConvUid = null;
  _currentActiveConvUid = null;
  _currentViewingConvUid = null;
  State.selectedDatasource = "";
  State.selectedKnowledge = "";
  State.selectedSkill = "";
  State.selectedConnectors = [];
  State.attachedFiles = [];
  State.chatHistory = [];
  // 切换到问答页面
  State.currentPage = "ask";
  document.querySelectorAll(".nav-item").forEach(el => el.classList.toggle("active", el.dataset.page === "ask"));
  document.getElementById("topbar-title").textContent = PAGES.ask.title;
  document.getElementById("topbar-subtitle").textContent = PAGES.ask.subtitle;
  document.querySelectorAll(".page-content").forEach(el => el.classList.add("content-hidden"));
  const askPage = document.getElementById("page-ask");
  if (askPage) askPage.classList.remove("content-hidden");
  // ★ 直接显示聊天界面（不是欢迎页）
  document.getElementById("ask-welcome").style.display = "none";
  document.getElementById("ask-chat").style.display = "flex";
  document.getElementById("chat-messages").innerHTML = "";
  document.getElementById("chat-mode-info").textContent = `模式: ${getModeLabel()}`;
  // 清空输入框
  const chatInput = document.getElementById("chat-input");
  if (chatInput) { chatInput.value = ""; chatInput.style.height = "auto"; }
  const heroInput = document.getElementById("hero-input");
  if (heroInput) { heroInput.value = ""; heroInput.style.height = "auto"; }
  // 设置应用模式
  _currentAppCode = appCode;
  _currentAppConfig = appConfig;
  if (res.database_name) State.selectedDatasource = res.database_name;
  if (res.knowledge_space) State.selectedKnowledge = res.knowledge_space;
  // 应用模式下锁定数据源/知识库按钮（不可改）
  lockAppToolbar(res);
  updateChatContextDisplay();
  // 显示应用指示器
  const indicator = document.getElementById("app-indicator");
  if (indicator && appConfig) {
    const res2 = appConfig.resources || {};
    const parts = [`📦 ${appConfig.app_name}`];
    if (res2.database_name) parts.push(`📊 ${res2.database_name} (已锁定)`);
    if (res2.knowledge_space) parts.push(`📚 ${res2.knowledge_space} (已锁定)`);
    indicator.innerHTML = parts.join(" | ") +
      ` <button class="btn btn-sm" style="margin-left:8px" onclick="newAppSession()">新建会话</button>` +
      ` <button class="btn btn-sm" onclick="showAppHistory()">历史会话</button>` +
      ` <button class="btn btn-sm" onclick="exitAppChat()">退出应用</button>`;
    indicator.style.display = "block";
  }
  syncToolLabels();
  _renderActiveSessions();
  toast(`已进入应用: ${appName}，数据源/知识库已锁定`, "info");
}

function exitAppChat() {
  _currentAppCode = null;
  _currentAppConfig = null;
  _currentConvUid = null;
  State.currentSessionId = "";
  _currentActiveConvUid = null;  // 清除活跃会话索引
  _currentViewingConvUid = null;
  // 清理 State 中应用锁定的选择
  State.selectedDatasource = "";
  State.selectedKnowledge = "";
  const indicator = document.getElementById("app-indicator");
  if (indicator) indicator.style.display = "none";
  // 回到空白首页
  const welcome = document.getElementById("ask-welcome");
  const chat = document.getElementById("ask-chat");
  if (welcome) welcome.style.display = "flex";
  if (chat) chat.style.display = "none";
  document.getElementById("chat-messages").innerHTML = "";
  // ★ 清空输入框
  const chatInput = document.getElementById("chat-input");
  if (chatInput) { chatInput.value = ""; chatInput.style.height = "auto"; }
  const heroInput = document.getElementById("hero-input");
  if (heroInput) { heroInput.value = ""; heroInput.style.height = "auto"; }
  // 恢复工具栏按钮可点击
  ["chat-tool-db", "chat-tool-kb"].forEach(id => {
    const btn = document.getElementById(id);
    if (btn) { btn.style.opacity = ""; btn.style.pointerEvents = ""; btn.title = ""; }
  });
  // 恢复按钮标签
  syncToolLabels();
  toast("已退出应用模式", "info");
}

async function newAppSession() {
  // 真正创建一个新的 DB-GPT 会话，传入绑定的数据源/知识库/prompt_code
  try {
    const res = _currentAppConfig?.resources || {};
    const body = {
      datasource_name: res.database_name || "",
      knowledge_space_name: res.knowledge_space || "",
      prompt_code: res.prompt_template || "",
    };
    const resp = await fetch(API_BASE + "/conversations/new", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await resp.json();
    if (data.ok && data.conversation && data.conversation.data) {
      _currentConvUid = data.conversation.data.conv_uid;
    } else {
      _currentConvUid = "";
    }
  } catch {
    _currentConvUid = "";
  }
  // 清空对话区，留在对话界面
  const container = document.getElementById("chat-messages");
  if (container) container.innerHTML = "";
  // ★ 清空输入框
  const chatInput = document.getElementById("chat-input");
  if (chatInput) { chatInput.value = ""; chatInput.style.height = "auto"; }
  const heroInput = document.getElementById("hero-input");
  if (heroInput) { heroInput.value = ""; heroInput.style.height = "auto"; }
  toast("已新建会话", "success");
}

async function showAppHistory() {
  if (!_currentAppCode) return;
  try {
    const data = await api("GET", `/apps/${_currentAppCode}/sessions`);
    const sessions = data.sessions || [];
    if (sessions.length === 0) {
      toast("暂无历史会话", "info");
      return;
    }
    openModal("历史会话", `
      <div class="table-wrapper"><table class="data-table">
        <thead><tr><th>会话摘要</th><th>时间</th><th>操作</th></tr></thead>
        <tbody>
          ${sessions.map(s => `<tr>
            <td>${escapeHtml(_cleanSummary(s.summary) || s.conv_uid)}</td>
            <td>${escapeHtml(s.gmt_created || "")}</td>
            <td><button class="btn btn-sm" onclick="resumeAppSession('${s.conv_uid}','${escapeAttr(s.summary || "")}')">恢复</button></td>
          </tr>`).join("")}
        </tbody>
      </table></div>
    `, [{ text: "关闭", class: "btn", action: "closeModalDirect()" }]);
  } catch (e) { toast("获取历史失败: " + e.message, "error"); }
}

async function resumeAppSession(convUid, summary) {
  _currentConvUid = convUid;
  closeModalDirect();
  toast(`正在恢复会话: ${summary}`, "info");

  // ★ 清空状态，防止污染
  State.selectedDatasource = "";
  State.selectedKnowledge = "";

  // ★ 并行加载消息 + 绑定信息
  try {
    const [msgData, bindingData] = await Promise.all([
      api("GET", `/conversations/messages/history?con_uid=${convUid}`),
      api("GET", `/conversations/${convUid}/binding`).catch(() => ({ binding: {} })),
    ]);

    let msgs = msgData.messages || [];
    if (!Array.isArray(msgs)) msgs = msgs["data"] || [];

    // 从绑定信息读取（不用 App 配置覆盖）
    const binding = bindingData.binding || {};
    let dbName = "";
    let kbName = binding.knowledge_space || "";
    if (binding.datasource_id) {
      try {
        const dsData = await api("GET", "/datasources");
        const dsList = dsData.datasources || [];
        const found = dsList.find(d => d.id === binding.datasource_id);
        if (found) dbName = found.db_name || "";
      } catch {}
    }

    if (dbName) State.selectedDatasource = dbName;
    if (kbName) State.selectedKnowledge = kbName;
    // 恢复的会话始终锁定
    lockAppToolbar({ database_name: dbName, knowledge_space: kbName, lockAlways: true });
    syncToolLabels();

    // 根据后端实时 status 切换终止/发送按钮
    const convStatus = binding.status || "inactive";
    _updateSendStopButtons(convStatus === "active");

    // 渲染消息（统一函数）
    _renderHistoryMessages(msgs);

    // 注册到状态缓存
    _ensureSessionState(convUid);
    _currentActiveConvUid = convUid;
    _currentViewingConvUid = convUid;
    const st = _sessionStateMap.get(convUid);
    if (st) {
      st.appCode = _currentAppCode;
      st.appConfig = _currentAppConfig;
      st.state = {
        currentSessionId: State.currentSessionId,
        selectedDatasource: State.selectedDatasource,
        selectedKnowledge: State.selectedKnowledge,
        selectedSkill: State.selectedSkill,
        selectedConnectors: [...State.selectedConnectors],
        attachedFiles: [...State.attachedFiles],
      };
    }
    _renderActiveSessions();
    loadRecentSessions(); // ★ 刷新"最近会话"列表高亮
  } catch (e) { toast("加载历史消息失败: " + e.message, "error"); }
}

// 应用模式发送问题——复用现有 SSE 渲染逻辑
async function sendAppChat(question) {
  if (!_currentAppCode) return false;
  // 调用 /apps/{app_code}/chat
  const url = `/apps/${_currentAppCode}/chat`;
  const body = {
    question,
    conv_uid: _currentConvUid || "",
    skill_name: State.selectedSkill || null,
    connector_ids: State.selectedConnectors || null,
    file_ids: State.attachedFiles || null,
  };
  // 用 fetch + SSE 渲染
  const indicator = document.getElementById("app-indicator");
  if (indicator) {
    // 从第一条 SSE 获取 conv_uid
  }
  await apiStreamSSE(url, body, true);
  return true;
}

document.addEventListener("DOMContentLoaded", initApp);
