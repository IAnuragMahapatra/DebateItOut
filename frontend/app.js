
const API_BASE = "";
const WELCOME_MESSAGES = [
  "Hello there! Ready to start chatting?",
  "Greetings! How can I help you today?",
  "Welcome! Let's explore some ideas together.",
  "Hi! I'm here and ready to assist you.",
  "Good to see you! What's on your mind?",
  "Hello! Let's get this conversation started.",
  "Welcome back! How can I be of service?",
  "Hi there! Curious about something? Let's chat.",
];
const GREETING = WELCOME_MESSAGES[Math.floor(Math.random() * WELCOME_MESSAGES.length)];
let sessions = [];
let activeSessionId = null;
let messages = [];
let sidebarOpen = false;
let models = [];
let selectedModel = null;
let modelsLoading = true;
let loading = false;
let editingSessionId = null;     // sidebar inline rename
let editingHeader = false;       // header rename
let searchQuery = "";
let confirmDeleteId = null;      // session pending delete confirm
const $ = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

const sidebar         = $("#sidebar");
const sidebarOverlay  = $("#sidebar-overlay");
const sidebarList     = $("#sidebar-list");
const sidebarSearch   = $("#sidebar-search");
const mobileToggle    = $("#mobile-toggle");
const sidebarToggle   = $("#sidebar-toggle");
const newChatBtn      = $("#new-chat-btn");
const chatHeader      = $("#chat-header-title");
const headerInput     = $("#header-rename-input");
const exportBtn       = $("#export-btn");
const chatBox         = $("#chat-box");
const modelSelector   = $("#model-selector");
const textarea        = $("#input-field");
const sendBtn         = $("#send-button");
marked.setOptions({ breaks: true, gfm: true });
function getDisplayName(session) {
  if (session.customName) return session.customName;
  if (session.preview) {
    const words = session.preview.trim().split(/\s+/);
    return words.slice(0, 6).join(" ") + (words.length > 6 ? "…" : "");
  }
  return "New Chat";
}

function sortedSessions() {
  const filtered = searchQuery
    ? sessions.filter(s => getDisplayName(s).toLowerCase().includes(searchQuery.toLowerCase()))
    : sessions;
  return [...filtered].sort((a, b) => {
    if (a.pinned && !b.pinned) return -1;
    if (!a.pinned && b.pinned) return 1;
    return (b.updatedAt || 0) - (a.updatedAt || 0);
  });
}

function scrollChatToBottom() {
  chatBox.scrollTop = chatBox.scrollHeight;
}
function renderMarkdown(text) {
  const div = document.createElement("div");
  div.innerHTML = marked.parse(text || "");
  return div;
}
function renderSidebar() {
  const list = sortedSessions();
  sidebarList.innerHTML = "";

  if (list.length === 0) {
    const empty = document.createElement("div");
    empty.className = "sidebar-empty";
    empty.textContent = searchQuery ? "No matches" : "No chats yet";
    sidebarList.appendChild(empty);
    return;
  }

  for (const session of list) {
    const item = document.createElement("div");
    item.className = "session-item" + (session.id === activeSessionId ? " active" : "");
    item.dataset.id = session.id;

    if (editingSessionId === session.id) {

      const input = document.createElement("input");
      input.className = "rename-input";
      input.value = getDisplayName(session);
      input.addEventListener("click", e => e.stopPropagation());
      input.addEventListener("blur", () => confirmSidebarRename(session.id, input.value));
      input.addEventListener("keydown", e => {
        if (e.key === "Enter") confirmSidebarRename(session.id, input.value);
        if (e.key === "Escape") { editingSessionId = null; renderSidebar(); }
      });
      item.appendChild(input);
      requestAnimationFrame(() => { input.focus(); input.select(); });
    } else if (confirmDeleteId === session.id) {

      const nameSpan = document.createElement("span");
      nameSpan.className = "session-name";
      nameSpan.textContent = getDisplayName(session);
      item.appendChild(nameSpan);

      const confirm = document.createElement("div");
      confirm.className = "delete-confirm";

      const yes = document.createElement("button");
      yes.className = "delete-confirm-yes";
      yes.textContent = "Delete";
      yes.addEventListener("click", e => { e.stopPropagation(); executeDelete(session.id); });

      const no = document.createElement("button");
      no.className = "delete-confirm-no";
      no.textContent = "Cancel";
      no.addEventListener("click", e => { e.stopPropagation(); confirmDeleteId = null; renderSidebar(); });

      confirm.appendChild(yes);
      confirm.appendChild(no);
      item.appendChild(confirm);
    } else {

      const nameSpan = document.createElement("span");
      nameSpan.className = "session-name";
      if (session.pinned) {
        const dot = document.createElement("span");
        dot.className = "pin-indicator";
        nameSpan.appendChild(dot);
      }
      nameSpan.appendChild(document.createTextNode(getDisplayName(session)));

      const actions = document.createElement("div");
      actions.className = "session-actions";

      const pinBtn = document.createElement("button");
      pinBtn.className = "session-action-btn";
      pinBtn.title = session.pinned ? "Unstar" : "Star";
      pinBtn.innerHTML = session.pinned
        ? `<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>`
        : `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>`;
      pinBtn.addEventListener("click", e => { e.stopPropagation(); togglePin(session.id); });

      const renameBtn = document.createElement("button");
      renameBtn.className = "session-action-btn";
      renameBtn.title = "Rename";
      renameBtn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.83 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>`;
      renameBtn.addEventListener("click", e => { e.stopPropagation(); startSidebarRename(session.id); });

      const deleteBtn = document.createElement("button");
      deleteBtn.className = "session-action-btn delete";
      deleteBtn.title = "Delete";
      deleteBtn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`;
      deleteBtn.addEventListener("click", e => { e.stopPropagation(); startDelete(session.id); });

      actions.append(pinBtn, renameBtn, deleteBtn);
      item.append(nameSpan, actions);
    }

    item.addEventListener("click", () => switchSession(session.id));
    sidebarList.appendChild(item);
  }
}
function renderHeader() {
  const activeSession = sessions.find(s => s.id === activeSessionId);
  if (editingHeader) {
    chatHeader.style.display = "none";
    headerInput.style.display = "";
    exportBtn.style.display = "none";
  } else {
    chatHeader.style.display = "";
    headerInput.style.display = "none";
    chatHeader.textContent = activeSession ? getDisplayName(activeSession) : "PromptCouncil";
    exportBtn.style.display = messages.length > 0 && activeSession ? "" : "none";
  }
}
function renderMessages() {
  chatBox.innerHTML = "";

  if (messages.length === 0) {
    const welcome = document.createElement("div");
    welcome.className = "welcome-container";
    welcome.innerHTML = `<h2>${GREETING}</h2>`;
    chatBox.appendChild(welcome);
    renderHeader();
    return;
  }

  for (const msg of messages) {
    chatBox.appendChild(createMessageEl(msg));
  }

  if (loading) {
    const loadingEl = document.createElement("div");
    loadingEl.className = "message-wrapper assistant";
    const avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.textContent = models.find(m => m.id === selectedModel)?.name || "AI";
    const bubble = document.createElement("div");
    bubble.className = "message-bubble";
    bubble.innerHTML = `<div class="typing-indicator"><span></span><span></span><span></span></div>`;
    loadingEl.append(avatar, bubble);
    chatBox.appendChild(loadingEl);
  }

  renderHeader();
  scrollChatToBottom();
}

function createMessageEl(msg) {
  const wrapper = document.createElement("div");
  wrapper.className = `message-wrapper ${msg.role}`;

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = msg.role === "user" ? "You" : (msg.modelName || "AI");

  const bubble = document.createElement("div");
  bubble.className = "message-bubble";

  if (msg.thinking) {
    const thinkingBox = document.createElement("div");
    thinkingBox.className = "thinking-box";
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "Thought Process";
    details.appendChild(summary);
    details.appendChild(renderMarkdown(msg.thinking));
    thinkingBox.appendChild(details);
    bubble.appendChild(thinkingBox);
  }

  if (msg.role === "assistant") {
    bubble.appendChild(renderMarkdown(msg.text));
  } else {
    bubble.appendChild(document.createTextNode(msg.text));
  }

  wrapper.append(avatar, bubble);
  return wrapper;
}
function renderModelSelector() {
  modelSelector.innerHTML = "";
  if (modelsLoading) {
    const span = document.createElement("span");
    span.className = "model-loading";
    span.textContent = "Loading models…";
    modelSelector.appendChild(span);
    return;
  }
  if (models.length === 0) {
    const span = document.createElement("span");
    span.className = "model-loading";
    span.textContent = "No models available";
    modelSelector.appendChild(span);
    return;
  }
  for (const m of models) {
    const btn = document.createElement("button");
    btn.className = "model-chip" + (selectedModel === m.id ? " active" : "");
    btn.textContent = m.name;
    btn.title = `Switch to ${m.name}`;
    btn.addEventListener("click", () => {
      selectedModel = m.id;
      renderModelSelector();
      updateSendState();
    });
    modelSelector.appendChild(btn);
  }
}

function updateSendState() {
  sendBtn.disabled = loading || !textarea.value.trim() || !selectedModel;
  textarea.disabled = !selectedModel;
  textarea.placeholder = selectedModel
    ? `Message ${models.find(m => m.id === selectedModel)?.name || "AI"}...`
    : "Select a model first...";
}
function render() {
  renderSidebar();
  renderHeader();
  renderMessages();
  renderModelSelector();
  updateSendState();
}
async function fetchSessions() {
  const res = await fetch(`${API_BASE}/sessions`);
  sessions = await res.json();
}

async function fetchModels() {
  try {
    const res = await fetch(`${API_BASE}/models`);
    models = await res.json();
    if (models.length > 0) selectedModel = models[0].id;
  } catch {
    models = [];
  } finally {
    modelsLoading = false;
  }
}

async function fetchMessages(sessionId) {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}`);
  const data = await res.json();
  messages = data.messages || [];
}
async function createNewSession() {
  try {
    const res = await fetch(`${API_BASE}/sessions`, { method: "POST" });
    const newSession = await res.json();
    sessions = [{ ...newSession, messageCount: 0, preview: null }, ...sessions];
    activeSessionId = newSession.id;
    messages = [];
    renderSidebar();
    renderHeader();
    renderMessages();
  } catch (err) {
    console.error("Failed to create session:", err);
  }
}

function switchSession(id) {
  if (id === activeSessionId) return;
  activeSessionId = id;
  editingHeader = false;
  messages = [];
  renderSidebar();
  renderHeader();
  renderMessages();
  fetchMessages(id).then(() => renderMessages()).catch(console.error);

  if (window.innerWidth <= 768) {
    sidebarOpen = false;
    sidebar.classList.remove("open");
    sidebarOverlay.style.display = "none";
  }
}

async function togglePin(id) {
  const session = sessions.find(s => s.id === id);
  if (!session) return;
  try {
    await fetch(`${API_BASE}/sessions/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pinned: !session.pinned }),
    });
    session.pinned = !session.pinned;
    renderSidebar();
  } catch (err) {
    console.error("Failed to toggle pin:", err);
  }
}

function startSidebarRename(id) {
  editingSessionId = id;
  renderSidebar();
}

async function confirmSidebarRename(id, newName) {
  editingSessionId = null;
  try {
    await fetch(`${API_BASE}/sessions/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ customName: newName.trim() || null }),
    });
    const s = sessions.find(s => s.id === id);
    if (s) s.customName = newName.trim() || null;
  } catch (err) {
    console.error("Failed to rename session:", err);
  }
  renderSidebar();
  renderHeader();
}

function startDelete(id) {
  confirmDeleteId = id;
  renderSidebar();
}

async function executeDelete(id) {
  confirmDeleteId = null;
  try {
    await fetch(`${API_BASE}/sessions/${id}`, { method: "DELETE" });
    const prevActive = activeSessionId === id;
    sessions = sessions.filter(s => s.id !== id);
    if (prevActive) {
      const sorted = sortedSessions();
      activeSessionId = sorted.length > 0 ? sorted[0].id : null;
      messages = [];
      if (activeSessionId) {
        fetchMessages(activeSessionId).then(() => renderMessages()).catch(console.error);
      }
    }
    renderSidebar();
    renderHeader();
    renderMessages();
  } catch (err) {
    console.error("Failed to delete session:", err);
  }
}

function startHeaderRename() {
  const activeSession = sessions.find(s => s.id === activeSessionId);
  if (!activeSession) return;
  editingHeader = true;
  headerInput.value = getDisplayName(activeSession);
  renderHeader();
  requestAnimationFrame(() => { headerInput.focus(); headerInput.select(); });
}

async function confirmHeaderRename() {
  const activeSession = sessions.find(s => s.id === activeSessionId);
  if (activeSession) {
    const newName = headerInput.value.trim() || null;
    try {
      await fetch(`${API_BASE}/sessions/${activeSessionId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ customName: newName }),
      });
      activeSession.customName = newName;
    } catch (err) {
      console.error("Failed to rename session:", err);
    }
  }
  editingHeader = false;
  renderSidebar();
  renderHeader();
}
async function sendMessage() {
  const text = textarea.value.trim();

  if (!text || !selectedModel || loading) return;

  const userMessage = text;
  textarea.value = "";
  textarea.style.height = "auto";
  loading = true;

  messages = [...messages, { role: "user", text: userMessage }];
  renderMessages();
  updateSendState();

  try {
    const res = await fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sessionId: activeSessionId,
        message: userMessage,
        modelId: selectedModel,
      }),
    });

    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.detail || data.error || `HTTP ${res.status}`);
    }

    if (!activeSessionId && data.sessionId) {
      activeSessionId = data.sessionId;

      await fetchSessions();
    }

    const assistantMsg = {
      role: "assistant",
      text: data.reply,
      thinking: data.thinking,
      modelName: data.modelName,
    };
    messages = [...messages, assistantMsg];

    const s = sessions.find(s => s.id === (data.sessionId || activeSessionId));
    if (s) {
      s.preview = userMessage;
      s.messageCount = (s.messageCount || 0) + 2;
      s.updatedAt = Date.now();
    }

  } catch (err) {
    console.error("Failed to send message:", err);
    messages = [...messages, {
      role: "assistant",
      text: `Connection error: ${err.message}`,
      modelName: models.find(m => m.id === selectedModel)?.name || "AI",
    }];
  } finally {
    loading = false;
    renderSidebar();
    renderMessages();
    updateSendState();
    textarea.focus();
  }
}
function exportConversation() {
  const activeSession = sessions.find(s => s.id === activeSessionId);
  const title = activeSession ? getDisplayName(activeSession) : "PromptCouncil Chat";
  const date = new Date().toISOString().split("T")[0];

  let md = `# ${title}\n\n_Exported ${date}_\n\n---\n\n`;
  for (const msg of messages) {
    const label = msg.role === "user" ? "**You**" : `**${msg.modelName || "AI"}**`;
    if (msg.thinking) {
      md += `${label} *(thinking)*\n\n${msg.thinking}\n\n---\n\n`;
    }
    md += `${label}\n\n${msg.text}\n\n---\n\n`;
  }

  const blob = new Blob([md], { type: "text/markdown" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${title.replace(/[^a-z0-9]/gi, "_").toLowerCase()}_${date}.md`;
  a.click();
  URL.revokeObjectURL(url);
}
sidebarToggle.addEventListener("click", () => {
  sidebarOpen = !sidebarOpen;
  sidebar.classList.toggle("open", sidebarOpen);
  sidebarOverlay.style.display = "";
});

sidebarOverlay.addEventListener("click", () => {
  sidebarOpen = false;
  sidebar.classList.remove("open");
  sidebarOverlay.style.display = "none";
});

mobileToggle.addEventListener("click", () => {
  sidebarOpen = true;
  sidebar.classList.add("open");
  sidebarOverlay.style.display = "";
});

newChatBtn.addEventListener("click", createNewSession);

document.addEventListener("keydown", e => {
  if ((e.ctrlKey || e.metaKey) && e.key === "n") {
    e.preventDefault();
    createNewSession();
  }
});

chatHeader.addEventListener("dblclick", startHeaderRename);

headerInput.addEventListener("blur", confirmHeaderRename);
headerInput.addEventListener("keydown", e => {
  if (e.key === "Enter") confirmHeaderRename();
  if (e.key === "Escape") { editingHeader = false; renderHeader(); }
});

exportBtn.addEventListener("click", exportConversation);

sidebarSearch.addEventListener("input", e => {
  searchQuery = e.target.value;
  renderSidebar();
});

textarea.addEventListener("input", () => {
  textarea.style.height = "auto";
  textarea.style.height = Math.min(textarea.scrollHeight, 150) + "px";
  updateSendState();
});

textarea.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

sendBtn.addEventListener("click", sendMessage);
async function init() {

  renderModelSelector();
  renderSidebar();

  await Promise.all([
    fetchSessions().then(() => {
      if (sessions.length > 0) {
        activeSessionId = sessions[0].id;
        return fetchMessages(activeSessionId);
      }
    }),
    fetchModels(),
  ]);

  render();
}

init().catch(console.error);


