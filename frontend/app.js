const API = "";
marked.setOptions({ breaks: true, gfm: true });

let debates = [];
let activeDebateId = null;
let activeDebate = null;
let models = [];
let sidebarOpen = false;
let searchQuery = "";
let editingDebateId = null;
let confirmDeleteId = null;
let advancing = false;

const $ = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

const sidebar          = $("#sidebar");
const sidebarOverlay   = $("#sidebar-overlay");
const sidebarList      = $("#sidebar-list");
const sidebarSearch    = $("#sidebar-search");
const mobileToggle     = $("#mobile-toggle");
const sidebarToggle    = $("#sidebar-toggle");
const newDebateBtn     = $("#new-debate-btn");
const emptyState       = $("#empty-state");
const emptyNewBtn      = $("#empty-new-btn");
const debateView       = $("#debate-view");
const debateHeader     = $("#debate-header");
const debateRoundIndicator = $("#debate-round-indicator");
const debateProposition = $("#debate-proposition");
const moderatorLogInner = $("#moderator-log-inner");
const factionAStance   = $("#faction-a-stance");
const factionBStance   = $("#faction-b-stance");
const factionAModels   = $("#faction-a-models");
const factionBModels   = $("#faction-b-models");
const factionATurns    = $("#faction-a-turns");
const factionBTurns    = $("#faction-b-turns");
const controlBar       = $("#control-bar");
const advanceBtn       = $("#advance-btn");
const headerRenameBtn  = $("#header-rename-btn");
const exportBtn        = $("#export-btn");
const exportModal      = $("#export-modal");
const exportModalClose = $("#export-modal-close");
const exportIncThinking = $("#export-inc-thinking");
const exportIncTeamMsg  = $("#export-inc-team-msg");
const exportMdConfirm   = $("#export-md-confirm");
const exportJsonConfirm = $("#export-json-confirm");

const createModal    = $("#create-modal");
const modalClose     = $("#modal-close");
const modalCancel    = $("#modal-cancel");
const modalSubmit    = $("#modal-submit");
const propositionInput = $("#proposition-input");
const factionAStanceInput = $("#faction-a-stance-input");
const factionBStanceInput = $("#faction-b-stance-input");
const factionAPicker = $("#faction-a-picker");
const factionBPicker = $("#faction-b-picker");
const maxRoundsInput = $("#max-rounds-input");

const renameModal    = $("#rename-modal");
const renameModalClose = $("#rename-modal-close");
const renameCancel   = $("#rename-cancel");
const renameSubmit   = $("#rename-submit");
const renameInput    = $("#rename-input");

async function api(path, opts = {}) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw Object.assign(new Error(body.detail || body.error || `HTTP ${res.status}`), { status: res.status, body });
  }
  return res.json();
}

function getDebateName(d) {
  if (d.customName) return d.customName;
  const words = (d.proposition || "").trim().split(/\s+/);
  return words.slice(0, 5).join(" ") + (words.length > 5 ? "…" : "") || "New Debate";
}

function sortedDebates() {
  const filtered = searchQuery
    ? debates.filter(d => getDebateName(d).toLowerCase().includes(searchQuery.toLowerCase()))
    : debates;
  return [...filtered].sort((a, b) => {
    if (a.pinned && !b.pinned) return -1;
    if (!a.pinned && b.pinned) return 1;
    return (b.updatedAt || 0) - (a.updatedAt || 0);
  });
}

function renderSidebar() {
  const list = sortedDebates();
  sidebarList.innerHTML = "";

  if (list.length === 0) {
    const el = document.createElement("div");
    el.className = "sidebar-empty";
    el.textContent = searchQuery ? "No matches" : "No debates yet";
    sidebarList.appendChild(el);
    return;
  }

  for (const d of list) {
    const item = document.createElement("div");
    item.className = "debate-item" + (d.id === activeDebateId ? " active" : "");
    item.dataset.id = d.id;

    if (editingDebateId === d.id) {
      const inp = document.createElement("input");
      inp.className = "rename-input";
      inp.value = getDebateName(d);
      inp.addEventListener("click", e => e.stopPropagation());
      inp.addEventListener("blur", () => confirmSidebarRename(d.id, inp.value));
      inp.addEventListener("keydown", e => {
        if (e.key === "Enter") confirmSidebarRename(d.id, inp.value);
        if (e.key === "Escape") { editingDebateId = null; renderSidebar(); }
      });
      item.appendChild(inp);
      requestAnimationFrame(() => { inp.focus(); inp.select(); });

    } else if (confirmDeleteId === d.id) {
      const nameSpan = document.createElement("span");
      nameSpan.className = "debate-item-name";
      nameSpan.textContent = getDebateName(d);
      item.appendChild(nameSpan);

      const conf = document.createElement("div");
      conf.className = "delete-confirm";

      const yes = document.createElement("button");
      yes.className = "delete-confirm-yes";
      yes.textContent = "Delete";
      yes.addEventListener("click", e => { e.stopPropagation(); executeDelete(d.id); });

      const no = document.createElement("button");
      no.className = "delete-confirm-no";
      no.textContent = "Cancel";
      no.addEventListener("click", e => { e.stopPropagation(); confirmDeleteId = null; renderSidebar(); });

      conf.append(yes, no);
      item.append(nameSpan, conf);

    } else {
      const nameSpan = document.createElement("span");
      nameSpan.className = "debate-item-name";
      if (d.pinned) {
        const dot = document.createElement("span");
        dot.className = "pin-dot";
        nameSpan.appendChild(dot);
      }
      nameSpan.appendChild(document.createTextNode(getDebateName(d)));

      const actions = document.createElement("div");
      actions.className = "item-actions";

      const pinBtn = document.createElement("button");
      pinBtn.className = "item-action-btn";
      pinBtn.title = d.pinned ? "Unstar" : "Star";
      pinBtn.setAttribute("aria-label", d.pinned ? "Unstar debate" : "Star debate");
      pinBtn.innerHTML = d.pinned
        ? `<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>`
        : `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>`;
      pinBtn.addEventListener("click", e => { e.stopPropagation(); togglePin(d.id); });

      const renameBtn = document.createElement("button");
      renameBtn.className = "item-action-btn";
      renameBtn.title = "Rename";
      renameBtn.setAttribute("aria-label", "Rename debate");
      renameBtn.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M17 3a2.83 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>`;
      renameBtn.addEventListener("click", e => { e.stopPropagation(); startSidebarRename(d.id); });

      const delBtn = document.createElement("button");
      delBtn.className = "item-action-btn danger";
      delBtn.title = "Delete";
      delBtn.setAttribute("aria-label", "Delete debate");
      delBtn.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`;
      delBtn.addEventListener("click", e => { e.stopPropagation(); confirmDeleteId = d.id; renderSidebar(); });

      actions.append(pinBtn, renameBtn, delBtn);
      item.append(nameSpan, actions);
    }

    item.addEventListener("click", () => switchDebate(d.id));
    sidebarList.appendChild(item);
  }
}

function renderDebateView() {
  if (!activeDebate) {
    emptyState.style.display = "";
    debateView.style.display = "none";
    return;
  }

  emptyState.style.display = "none";
  debateView.style.display = "";

  const d = activeDebate;
  debateRoundIndicator.textContent = `ROUND ${d.currentRound} / ${d.maxRounds}`;

  const arrowSvg = `<svg class="log-arrow" viewBox="0 0 24 24" width="1em" height="1em" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg>`;
  
  if (d.status === "concluded") {
    moderatorLogInner.innerHTML = `<span class="log-entry concluded">${arrowSvg} Debate concluded at Round ${d.currentRound}</span>`;
  } else if (d.status === "error") {
    moderatorLogInner.innerHTML = `<span class="log-entry error">${arrowSvg} Error processing turn</span>`;
  } else if (d.status === "turn_in_progress") {
    moderatorLogInner.innerHTML = `<span class="log-entry">${arrowSvg} Turn in progress...</span>`;
  } else {
    moderatorLogInner.innerHTML = `<span class="log-entry">${arrowSvg} Ready for next turn</span>`;
  }
  debateProposition.textContent = d.proposition;
  debateProposition.title = d.proposition;

  factionAStance.textContent = `"${d.factionA.stance}"`;
  factionBStance.textContent = `"${d.factionB.stance}"`;

  renderFactionChips(factionAModels, d.factionA.models, "a");
  renderFactionChips(factionBModels, d.factionB.models, "b");
  renderControlBar(d.status);
  renderTranscript(d);
}

function renderFactionChips(container, modelIds, faction) {
  container.innerHTML = "";
  for (const mid of modelIds) {
    const m = models.find(x => x.id === mid);
    const chip = document.createElement("span");
    chip.className = "model-chip-display";
    chip.textContent = m ? m.name : mid;
    container.appendChild(chip);
  }
}

function renderControlBar(status) {
  advanceBtn.className = "advance-btn";
  advanceBtn.disabled = false;

  if (status === "active" && !advancing) {
    advanceBtn.textContent = "Advance Turn";
    advanceBtn.disabled = false;
  } else if (status === "turn_in_progress" || advancing) {
    advanceBtn.innerHTML = `Working <span class="typing-dots"><span></span><span></span><span></span></span>`;
    advanceBtn.disabled = true;
  } else if (status === "error") {
    advanceBtn.className = "advance-btn error";
    advanceBtn.textContent = "Retry Turn";
    advanceBtn.disabled = false;
  } else if (status === "concluded") {
    advanceBtn.className = "advance-btn concluded";
    advanceBtn.textContent = "Debate Concluded";
    advanceBtn.disabled = true;
  } else {
    advanceBtn.disabled = true;
  }
}

function renderTranscript(d) {
  const transcript = d.publicTranscript || [];
  const aPrivate = d.factionAPrivate || { teamMessages: [], thinking: [] };
  const bPrivate = d.factionBPrivate || { teamMessages: [], thinking: [] };

  factionATurns.innerHTML = "";
  factionBTurns.innerHTML = "";

  const seenRoundsA = new Set();
  const seenRoundsB = new Set();

  activeDebate.blocks = [];
  let currentBlock = null;

  for (const msg of transcript) {
    const isA = msg.faction === "A";
    const container = isA ? factionATurns : factionBTurns;
    const seenRounds = isA ? seenRoundsA : seenRoundsB;

    if (!seenRounds.has(msg.round)) {
      seenRounds.add(msg.round);
      if (seenRounds.size > 1 || msg.round > 1) {
        const sep = document.createElement("div");
        sep.className = "round-separator";
        sep.textContent = `Round ${msg.round}`;
        container.appendChild(sep);
      }
    }

    const modelName = getModelName(msg.modelId);
    const privateData = isA ? aPrivate : bPrivate;
    const teamMsgEntry = privateData.teamMessages?.find(t => t.round === msg.round && t.modelId === msg.modelId);
    const thinkingEntry = privateData.thinking?.find(t => t.round === msg.round && t.modelId === msg.modelId);

    const card = createTurnCard(msg, modelName, teamMsgEntry, thinkingEntry);
    container.appendChild(card);

    if (!currentBlock || currentBlock.faction !== msg.faction) {
      currentBlock = { faction: msg.faction, cards: [] };
      activeDebate.blocks.push(currentBlock);
    }
    currentBlock.cards.push(card);
  }

  if (advancing) {
    const placeholder = document.createElement("div");
    placeholder.className = "turn-card";
    placeholder.innerHTML = `<div class="turn-card-header"><span class="turn-model-name" style="color:var(--text-muted)">Thinking…</span></div><div class="argument-body"><span class="typing-dots"><span></span><span></span><span></span></span></div>`;
    (activeDebate.factionA ? factionATurns : factionBTurns).appendChild(placeholder);
  }

  factionATurns.scrollTop = factionATurns.scrollHeight;
  factionBTurns.scrollTop = factionBTurns.scrollHeight;

  requestAnimationFrame(drawConnectors);
}

function getModelName(modelId) {
  const m = models.find(x => x.id === modelId);
  return m ? m.name : modelId;
}

function createTurnCard(msg, modelName, teamMsgEntry, thinkingEntry) {
  const card = document.createElement("div");
  card.className = "turn-card";

  const header = document.createElement("div");
  header.className = "turn-card-header";

  const nameEl = document.createElement("span");
  nameEl.className = "turn-model-name";
  nameEl.textContent = modelName;

  const metadataBlock = document.createElement("span");
  metadataBlock.className = "turn-round-badge";
  if (msg.latency != null) {
    metadataBlock.textContent = `R${msg.round} • ${msg.latency}ms`;
  } else {
    metadataBlock.textContent = `R${msg.round}`;
  }

  header.append(nameEl, metadataBlock);
  card.appendChild(header);

  const argEl = document.createElement("div");
  argEl.className = "argument-body";
  argEl.innerHTML = marked.parse(msg.argument || "");
  card.appendChild(argEl);

  if (teamMsgEntry?.teamMessage) {
    const details = document.createElement("details");
    details.className = "collapsible-block";
    const summary = document.createElement("summary");
    summary.textContent = "Team message";
    const content = document.createElement("div");
    content.className = "collapsible-content";
    content.innerHTML = marked.parse(teamMsgEntry.teamMessage);
    details.append(summary, content);
    card.appendChild(details);
  }

  if (thinkingEntry?.thinking) {
    const details = document.createElement("details");
    details.className = "collapsible-block";
    const summary = document.createElement("summary");
    summary.textContent = "Thinking";
    const content = document.createElement("div");
    content.className = "collapsible-content";
    content.innerHTML = marked.parse(thinkingEntry.thinking);
    details.append(summary, content);
    card.appendChild(details);
  }

  return card;
}

function log(message, type = "info") {
  const el = document.createElement("span");
  el.className = `log-entry ${type}`;
  el.textContent = message;
  moderatorLogInner.appendChild(el);
  moderatorLogInner.scrollLeft = moderatorLogInner.scrollWidth;
}

async function fetchDebates() {
  debates = await api("/debates");
}

async function fetchModels() {
  try {
    models = await api("/models");
  } catch {
    models = [];
  }
}

async function loadDebate(id) {
  const d = await api(`/debates/${id}`);
  activeDebate = d;
  const i = debates.findIndex(x => x.id === id);
  if (i >= 0) debates[i] = { ...debates[i], ...d };
}

async function switchDebate(id) {
  if (id === activeDebateId) return;
  activeDebateId = id;
  activeDebate = null;
  renderSidebar();
  renderDebateView();
  try {
    await loadDebate(id);
    renderDebateView();
  } catch (err) {
    log(`Failed to load debate: ${err.message}`, "error");
  }
  if (window.innerWidth < 768) closeSidebar();
}

async function togglePin(id) {
  const d = debates.find(x => x.id === id);
  if (!d) return;
  try {
    await api(`/debates/${id}`, { method: "PATCH", body: JSON.stringify({ pinned: !d.pinned }) });
    d.pinned = !d.pinned;
    renderSidebar();
  } catch (err) {
    console.error("Failed to pin:", err);
  }
}

function startSidebarRename(id) { editingDebateId = id; renderSidebar(); }

async function confirmSidebarRename(id, newName) {
  editingDebateId = null;
  try {
    const trimmed = newName.trim() || null;
    await api(`/debates/${id}`, { method: "PATCH", body: JSON.stringify({ customName: trimmed }) });
    const d = debates.find(x => x.id === id);
    if (d) d.customName = trimmed;
    if (activeDebate?.id === id) activeDebate.customName = trimmed;
  } catch (err) {
    console.error("Failed to rename:", err);
  }
  renderSidebar();
}

async function executeDelete(id) {
  confirmDeleteId = null;
  try {
    await api(`/debates/${id}`, { method: "DELETE" });
    const wasActive = activeDebateId === id;
    debates = debates.filter(x => x.id !== id);
    if (wasActive) {
      const first = sortedDebates()[0];
      activeDebateId = first?.id || null;
      activeDebate = null;
      if (activeDebateId) {
        await loadDebate(activeDebateId);
      }
    }
    renderSidebar();
    renderDebateView();
  } catch (err) {
    console.error("Failed to delete:", err);
  }
}

async function advanceTurn() {
  if (!activeDebate || advancing) return;
  const isRetry = activeDebate.status === "error";
  const endpoint = isRetry ? `/debates/${activeDebateId}/retry-turn` : `/debates/${activeDebateId}/turn`;

  advancing = true;
  renderControlBar(activeDebate.status);
  log(isRetry ? "Retrying last turn…" : `Round ${activeDebate.currentRound} — requesting next speaker…`);

  try {
    const result = await api(endpoint, { method: "POST" });
    log(`${getModelName(result.message.modelId)} (Faction ${result.message.faction}) spoke.`, "info");

    // stamp-style settle animation for moderator handoff
    moderatorLogInner.style.transition = "none";
    moderatorLogInner.style.transform = "scale(1.05)";
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        moderatorLogInner.style.transition = "transform 200ms var(--ease-out)";
        moderatorLogInner.style.transform = "scale(1)";
      });
    });

    if (result.status === "concluded") log("Debate concluded.", "concluded");
    if (!result.message.parseOk) log("Warning: model didn't follow XML format, used fallback.", "warn");

    advancing = false;
    await loadDebate(activeDebateId);
    renderDebateView();
  } catch (err) {
    log(`Turn failed: ${err.message}`, "error");
    advancing = false;
    try { await loadDebate(activeDebateId); renderDebateView(); } catch {}
  } finally {
    advancing = false;
    if (activeDebate) renderControlBar(activeDebate.status);
    requestAnimationFrame(drawConnectors);
  }
}

const connectorOverlay = $("#connector-overlay");

function drawConnectors() {
  if (!connectorOverlay || !activeDebate || !activeDebate.blocks) return;
  connectorOverlay.innerHTML = "";

  const debateAreaRect = $("#debate-area").getBoundingClientRect();
  const blocks = activeDebate.blocks;

  const strokeColor = "oklch(35% 0.01 60 / 0.5)";

  for (let i = 1; i < blocks.length; i++) {
    const prevBlock = blocks[i - 1];
    const currBlock = blocks[i];

    if (prevBlock.cards.length === 0 || currBlock.cards.length === 0) continue;

    const firstPrevCard = prevBlock.cards[0].getBoundingClientRect();
    const lastPrevCard = prevBlock.cards[prevBlock.cards.length - 1].getBoundingClientRect();
    const firstCurrCard = currBlock.cards[0].getBoundingClientRect();

    const isPrevA = prevBlock.faction === "A";

    const prevTop = firstPrevCard.top - debateAreaRect.top;
    const prevBottom = lastPrevCard.bottom - debateAreaRect.top;
    const currTop = firstCurrCard.top - debateAreaRect.top + 20;

    let pathD = "";

    if (isPrevA) {
      const startX = firstPrevCard.right - debateAreaRect.left + 4;
      const endX = firstCurrCard.left - debateAreaRect.left - 4;
      const midY = (prevTop + prevBottom) / 2;
      const bracketDepth = 8;

      pathD = `
        M ${startX} ${prevTop}
        L ${startX + bracketDepth} ${prevTop}
        L ${startX + bracketDepth} ${prevBottom}
        L ${startX} ${prevBottom}
        M ${startX + bracketDepth} ${midY}
        L ${endX} ${currTop}
      `;
    } else {
      const startX = firstPrevCard.left - debateAreaRect.left - 4;
      const endX = firstCurrCard.right - debateAreaRect.left + 4;
      const midY = (prevTop + prevBottom) / 2;
      const bracketDepth = 8;

      pathD = `
        M ${startX} ${prevTop}
        L ${startX - bracketDepth} ${prevTop}
        L ${startX - bracketDepth} ${prevBottom}
        L ${startX} ${prevBottom}
        M ${startX - bracketDepth} ${midY}
        L ${endX} ${currTop}
      `;
    }

    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", pathD);
    path.setAttribute("stroke", strokeColor);
    path.setAttribute("stroke-width", "1.5");
    path.setAttribute("fill", "none");
    connectorOverlay.appendChild(path);
  }
}

const resizeObserver = new ResizeObserver(() => {
  requestAnimationFrame(drawConnectors);
});
resizeObserver.observe($("#debate-area"));

let selectedA = [];
let selectedB = [];

function openCreateModal() {
  selectedA = [];
  selectedB = [];
  propositionInput.value = "";
  factionAStanceInput.value = "for";
  factionBStanceInput.value = "against";
  maxRoundsInput.value = "6";
  renderPickers();
  createModal.style.display = "flex";
  requestAnimationFrame(() => propositionInput.focus());
}

function closeCreateModal() { createModal.style.display = "none"; }

function renderPickers() {
  renderPicker(factionAPicker, selectedA, "A");
  renderPicker(factionBPicker, selectedB, "B");
}

function renderPicker(container, selected, faction) {
  container.innerHTML = "";
  for (const m of models) {
    const btn = document.createElement("button");
    btn.className = "model-pick-btn" + (selected.includes(m.id) ? " selected" : "");
    btn.textContent = m.name;
    btn.type = "button";
    btn.addEventListener("click", () => {
      if (faction === "A") {
        selectedA = toggleInArray(selectedA, m.id);
      } else {
        selectedB = toggleInArray(selectedB, m.id);
      }
      renderPickers();
    });
    container.appendChild(btn);
  }
}

function toggleInArray(arr, val) {
  return arr.includes(val) ? arr.filter(x => x !== val) : [...arr, val];
}

async function submitCreateDebate() {
  const proposition = propositionInput.value.trim();
  if (!proposition) { propositionInput.focus(); return; }
  if (selectedA.length === 0 || selectedB.length === 0) {
    alert("Pick at least one model for each faction.");
    return;
  }

  modalSubmit.disabled = true;
  modalSubmit.textContent = "Starting…";

  try {
    const d = await api("/debates", {
      method: "POST",
      body: JSON.stringify({
        proposition,
        factionA: { models: selectedA, stance: factionAStanceInput.value.trim() || "for" },
        factionB: { models: selectedB, stance: factionBStanceInput.value.trim() || "against" },
        maxRounds: parseInt(maxRoundsInput.value, 10) || 6,
      }),
    });
    debates = [d, ...debates];
    closeCreateModal();
    await switchDebate(d.id);
    log(`Debate started: "${d.proposition.slice(0, 50)}${d.proposition.length > 50 ? "…" : ""}"`);
  } catch (err) {
    alert(`Failed to create debate: ${err.message}`);
  } finally {
    modalSubmit.disabled = false;
    modalSubmit.textContent = "Start Debate";
  }
}

function openRenameModal() {
  if (!activeDebate) return;
  renameInput.value = activeDebate.customName || "";
  renameModal.style.display = "flex";
  requestAnimationFrame(() => { renameInput.focus(); renameInput.select(); });
}

function closeRenameModal() { renameModal.style.display = "none"; }

async function submitRename() {
  if (!activeDebate) return;
  const newName = renameInput.value.trim() || null;
  try {
    await api(`/debates/${activeDebateId}`, { method: "PATCH", body: JSON.stringify({ customName: newName }) });
    activeDebate.customName = newName;
    const d = debates.find(x => x.id === activeDebateId);
    if (d) d.customName = newName;
    renderSidebar();
  } catch (err) {
    console.error("Failed to rename:", err);
  }
  closeRenameModal();
}

function openSidebar() { sidebarOpen = true; sidebar.classList.add("open"); sidebarOverlay.style.display = ""; }
function closeSidebar() { sidebarOpen = false; sidebar.classList.remove("open"); sidebarOverlay.style.display = "none"; }

sidebarToggle.addEventListener("click", () => { sidebarOpen ? closeSidebar() : openSidebar(); });
sidebarOverlay.addEventListener("click", closeSidebar);
mobileToggle.addEventListener("click", openSidebar);

newDebateBtn.addEventListener("click", openCreateModal);
emptyNewBtn.addEventListener("click", openCreateModal);

sidebarSearch.addEventListener("input", e => { searchQuery = e.target.value; renderSidebar(); });

advanceBtn.addEventListener("click", advanceTurn);
headerRenameBtn.addEventListener("click", openRenameModal);

exportBtn.addEventListener("click", () => { exportModal.style.display = "flex"; });
exportModalClose.addEventListener("click", () => { exportModal.style.display = "none"; });
exportModal.addEventListener("click", e => { if (e.target === exportModal) exportModal.style.display = "none"; });
exportMdConfirm.addEventListener("click", () => { exportToMarkdown(); exportModal.style.display = "none"; });
exportJsonConfirm.addEventListener("click", () => { exportToJSON(); exportModal.style.display = "none"; });

modalClose.addEventListener("click", closeCreateModal);
modalCancel.addEventListener("click", closeCreateModal);
modalSubmit.addEventListener("click", submitCreateDebate);

renameModalClose.addEventListener("click", closeRenameModal);
renameCancel.addEventListener("click", closeRenameModal);
renameSubmit.addEventListener("click", submitRename);

renameInput.addEventListener("keydown", e => {
  if (e.key === "Enter") submitRename();
  if (e.key === "Escape") closeRenameModal();
});

createModal.addEventListener("click", e => { if (e.target === createModal) closeCreateModal(); });
renameModal.addEventListener("click", e => { if (e.target === renameModal) closeRenameModal(); });

propositionInput.addEventListener("keydown", e => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) submitCreateDebate();
});

document.addEventListener("keydown", e => {
  if ((e.ctrlKey || e.metaKey) && e.key === "n") { e.preventDefault(); openCreateModal(); }
  if (e.key === "Escape") { closeCreateModal(); closeRenameModal(); }
});

async function init() {
  await Promise.all([fetchDebates(), fetchModels()]);

  renderSidebar();
  renderPickers();

  if (debates.length > 0) {
    activeDebateId = sortedDebates()[0].id;
    try {
      await loadDebate(activeDebateId);
    } catch (err) {
      console.error("Failed to load first debate:", err);
    }
  }

  renderDebateView();

  // redraw connectors when collapsible blocks expand/collapse
  document.addEventListener('toggle', (e) => {
    if (e.target.matches('details.collapsible-block')) {
      setTimeout(drawConnectors, 20);
    }
  }, true);
}

function downloadFile(content, filename, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function exportToJSON() {
  if (!activeDebate) return;
  
  const debateExport = JSON.parse(JSON.stringify(activeDebate));
  const incThinking = exportIncThinking.checked;
  const incTeamMsg = exportIncTeamMsg.checked;
  
  if (!incThinking || !incTeamMsg) {
    if (debateExport.factionAPrivate) {
      if (!incThinking) delete debateExport.factionAPrivate.thinking;
      if (!incTeamMsg) delete debateExport.factionAPrivate.teamMessages;
    }
    if (debateExport.factionBPrivate) {
      if (!incThinking) delete debateExport.factionBPrivate.thinking;
      if (!incTeamMsg) delete debateExport.factionBPrivate.teamMessages;
    }
  }

  const content = JSON.stringify(debateExport, null, 2);
  downloadFile(content, `debate-${activeDebate.id}.json`, 'application/json');
}

function exportToMarkdown() {
  if (!activeDebate) return;
  
  const incThinking = exportIncThinking.checked;
  const incTeamMsg = exportIncTeamMsg.checked;
  const d = activeDebate;
  let md = `# Debate: ${getDebateName(d)}\n\n`;
  md += `**Proposition**: ${d.proposition}\n\n`;
  md += `**Status**: ${d.status}\n\n`;
  md += `**Faction A**: ${d.factionA.models.map(getModelName).join(', ')} (Stance: "${d.factionA.stance}")\n`;
  md += `**Faction B**: ${d.factionB.models.map(getModelName).join(', ')} (Stance: "${d.factionB.stance}")\n\n`;
  md += `---\n\n`;

  const transcript = d.publicTranscript || [];
  const aPrivate = d.factionAPrivate || { teamMessages: [], thinking: [] };
  const bPrivate = d.factionBPrivate || { teamMessages: [], thinking: [] };

  for (const msg of transcript) {
    const modelName = getModelName(msg.modelId);
    md += `### Round ${msg.round} - ${modelName} (Faction ${msg.faction})\n\n`;
    
    if (incThinking || incTeamMsg) {
      const privateData = msg.faction === "A" ? aPrivate : bPrivate;
      const teamMsgEntry = privateData.teamMessages?.find(t => t.round === msg.round && t.modelId === msg.modelId);
      const thinkingEntry = privateData.thinking?.find(t => t.round === msg.round && t.modelId === msg.modelId);
      
      if (incTeamMsg && teamMsgEntry?.teamMessage) {
        md += `<details><summary>Team Message</summary>\n\n${teamMsgEntry.teamMessage}\n\n</details>\n\n`;
      }
      if (incThinking && thinkingEntry?.thinking) {
        md += `<details><summary>Thinking</summary>\n\n${thinkingEntry.thinking}\n\n</details>\n\n`;
      }
    }
    
    md += `${msg.argument}\n\n`;
  }
  
  downloadFile(md, `debate-${activeDebate.id}.md`, 'text/markdown');
}

init().catch(console.error);
