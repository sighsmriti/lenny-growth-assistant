(() => {
  const state = { sessionId: null, sessions: [], busy: false };
  const byId = (id) => document.getElementById(id);
  let fetcher = (...args) => window.fetch(...args);

  function escapeText(value) {
    return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
  }
  function messageMarkup(message) {
    const assistant = message.role === "assistant";
    const content = escapeText(message.content).replace(/\n/g, "<br>");
    return `<article class="message ${assistant ? "assistant" : "user"}"><div class="avatar" aria-hidden="true">${assistant ? "L" : "Y"}</div><div class="message-body"><div class="message-label">${assistant ? "LENNY GROWTH ASSISTANT" : "YOU"}</div><div class="message-content">${content}</div></div></article>`;
  }
  async function request(url, options) {
    const response = await fetcher(url, options);
    if (!response.ok) {
      let message = `Request failed (${response.status}).`;
      try { const payload = await response.json(); if (payload.detail) message = payload.detail; } catch (_) { /* use status */ }
      throw new Error(message);
    }
    return response.json();
  }
  function showError(error) {
    byId("request-error").textContent = error?.message || "Something went wrong. Please try again.";
    byId("request-error").hidden = false;
  }
  function setBusy(busy, label = "Thinking…") {
    state.busy = busy;
    byId("busy-overlay").hidden = !busy;
    byId("busy-label").textContent = label;
    byId("send-button").disabled = busy;
    byId("essay-button").disabled = busy;
    byId("message-input").disabled = busy;
  }
  function titleFor(session) {
    const firstUser = session.messages?.find((message) => message.role === "user");
    return firstUser ? firstUser.content.replace(/\s+/g, " ").slice(0, 44) : "New conversation";
  }
  function renderSessions() {
    const nav = byId("session-list");
    nav.replaceChildren();
    for (const session of state.sessions) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `session-item${session.id === state.sessionId ? " active" : ""}`;
      button.dataset.sessionId = session.id;
      button.textContent = titleFor(session);
      button.setAttribute("aria-current", session.id === state.sessionId ? "page" : "false");
      nav.append(button);
    }
    byId("sessions-state").hidden = state.sessions.length > 0;
    byId("sessions-state").textContent = state.sessions.length ? "" : "Your conversations will appear here.";
  }
  function renderMessages(messages) {
    const area = byId("messages");
    area.innerHTML = messages.map(messageMarkup).join("");
    const hasMessages = messages.length > 0;
    byId("chat-state").hidden = hasMessages;
    byId("chat-state").textContent = hasMessages ? "" : "Ask a question about product, growth, or startups. Answers are grounded in indexed podcast transcripts.";
    area.scrollTop = area.scrollHeight;
  }
  function appendCitations(citations) {
    if (!citations?.length) return;
    const last = byId("messages").querySelector(".message.assistant:last-child .message-body");
    if (!last) return;
    const details = document.createElement("details");
    details.className = "citations";
    const summary = document.createElement("summary");
    summary.textContent = `Sources · ${citations.length}`;
    details.append(summary);
    const list = document.createElement("ul");
    citations.forEach((citation) => {
      const item = document.createElement("li");
      const title = document.createElement("strong");
      title.textContent = citation.title || citation.filename || "Transcript source";
      item.append(title);
      if (citation.guest_name) item.append(document.createTextNode(` · ${citation.guest_name}`));
      if (citation.excerpt) { const excerpt = document.createElement("p"); excerpt.textContent = citation.excerpt; item.append(excerpt); }
      if (citation.url) {
        try {
          const url = new URL(citation.url);
          if (url.protocol === "http:" || url.protocol === "https:") {
            const link = document.createElement("a"); link.href = url.href; link.target = "_blank"; link.rel = "noreferrer"; link.textContent = "Open source ↗"; item.append(link);
          }
        } catch (_) { /* ignore invalid transcript URLs */ }
      }
      list.append(item);
    });
    details.append(list);
    last.append(details);
  }
  async function loadSessions() {
    byId("sessions-state").hidden = false;
    byId("sessions-state").textContent = "Loading conversations…";
    try {
      const rows = await request("/api/sessions");
      state.sessions = await Promise.all(rows.map(async (session) => ({ ...session, messages: await request(`/api/sessions/${encodeURIComponent(session.id)}/messages`) })));
      renderSessions();
      return state.sessions;
    } catch (error) {
      byId("sessions-state").textContent = "Could not load conversations.";
      byId("sessions-state").hidden = false;
      throw error;
    }
  }
  async function selectSession(id) {
    state.sessionId = id;
    byId("request-error").hidden = true;
    byId("unsupported-note").hidden = true;
    try {
      const messages = await request(`/api/sessions/${encodeURIComponent(id)}/messages`);
      renderMessages(messages);
      renderSessions();
      document.body.classList.remove("sidebar-open");
    } catch (error) { showError(error); }
  }
  async function newSession() {
    byId("request-error").hidden = true;
    try {
      const session = await request("/api/sessions", { method: "POST" });
      state.sessionId = session.id;
      await loadSessions();
      renderMessages([]);
      renderSessions();
      byId("message-input").focus();
      document.body.classList.remove("sidebar-open");
    } catch (error) { showError(error); }
  }
  async function loadConfig() {
    try {
      const result = await request("/api/config");
      const llm = result.llm;
      const label = `${llm.provider} · ${llm.model}${llm.ready ? "" : " · API key required"}`;
      byId("model-status").textContent = label;
      byId("provider-sidebar").textContent = `${llm.provider} · ${llm.model}`;
      byId("model-status").classList.toggle("not-ready", !llm.ready);
    } catch (error) {
      byId("model-status").textContent = "Model configuration unavailable";
      byId("provider-sidebar").textContent = "Model unavailable";
      showError(error);
    }
  }
  function citationsMarkup(citations) {
    if (!citations?.length) return "";
    return `<details class="citations"><summary>Sources · ${citations.length}</summary><ul>${citations.map((item) => `<li><strong>${escapeText(item.title || item.filename)}</strong>${item.guest_name ? ` · ${escapeText(item.guest_name)}` : ""}<p>${escapeText(item.excerpt || "")}</p>${item.url ? `<a href="${escapeText(item.url)}" target="_blank" rel="noreferrer">Open source ↗</a>` : ""}</li>`).join("")}</ul></details>`;
  }
  async function sendMessage(event) {
    event?.preventDefault();
    const input = byId("message-input");
    const message = input.value.trim();
    if (!message || state.busy) return;
    byId("request-error").hidden = true;
    byId("unsupported-note").hidden = true;
    if (!state.sessionId) await newSession();
    if (!state.sessionId) return;
    setBusy(true);
    try {
      const chatResult = await request("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: state.sessionId, message }) });
      input.value = "";
      const messages = await request(`/api/sessions/${encodeURIComponent(state.sessionId)}/messages`);
      renderMessages(messages);
      appendCitations(chatResult.citations);
      const lastAssistant = [...messages].reverse().find((item) => item.role === "assistant");
      const latestUser = [...messages].reverse().find((item) => item.role === "user");
      if (lastAssistant && /available transcripts do not support an answer/i.test(lastAssistant.content) && latestUser?.content === message) byId("unsupported-note").hidden = false;
      await loadSessions();
      renderSessions();
    } catch (error) { showError(error); }
    finally { setBusy(false); input.focus(); }
  }
  async function generateEssay() {
    byId("request-error").hidden = true;
    const task = window.prompt("What should the Ship 30 for 30 essay explore? Add any source notes you want it to use.", "Write a practical essay about a product or growth lesson. Use only factual context provided here; do not invent personal anecdotes.");
    if (!task?.trim()) return;
    setBusy(true, "Writing your essay… This can take a few minutes.");
    try {
      const result = await request("/api/agent/skills/ship-30-for-30-essay/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ task: task.trim() }) });
      const frame = byId("artifact-frame");
      const openArtifact = () => frame.contentWindow?.ArtifactViewer?.showArtifact(result.artifact_id);
      if (frame.contentWindow?.ArtifactViewer) await openArtifact();
      else frame.addEventListener("load", openArtifact, { once: true });
      byId("request-error").hidden = true;
    } catch (error) { showError(error); }
    finally { setBusy(false); }
  }
  function init(customFetch) {
    if (customFetch) fetcher = customFetch;
    byId("new-chat").addEventListener("click", newSession);
    byId("refresh-sessions").addEventListener("click", () => loadSessions().catch(showError));
    byId("session-list").addEventListener("click", (event) => {
      const button = event.target.closest("[data-session-id]");
      if (button) selectSession(button.dataset.sessionId);
    });
    byId("composer").addEventListener("submit", sendMessage);
    byId("message-input").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendMessage(event); } });
    byId("essay-button").addEventListener("click", generateEssay);
    byId("mobile-menu").addEventListener("click", () => document.body.classList.toggle("sidebar-open"));
    Promise.all([loadConfig(), loadSessions()]).then(async ([, sessions]) => {
      if (sessions.length) await selectSession(sessions[0].id);
      else renderMessages([]);
    }).catch(showError);
  }
  window.GrowthChat = { init, loadSessions, selectSession, newSession, sendMessage, generateEssay, renderMessages, messageMarkup };
  if (!window.__GROWTH_CHAT_DISABLE_AUTO_INIT__) {
    const start = () => init();
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
    else queueMicrotask(start);
  }
})();
