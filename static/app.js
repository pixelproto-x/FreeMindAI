(() => {
  "use strict";
  const $ = (selector) => document.querySelector(selector);
  const els = {
    sidebar: $("#sidebar"), scrim: $("#sidebarScrim"), list: $("#conversationList"), count: $("#conversationCount"),
    title: $("#activeTitle"), welcome: $("#welcome"), messages: $("#messages"), input: $("#messageInput"),
    send: $("#sendButton"), charCount: $("#charCount"), healthDot: $("#healthDot"), healthLabel: $("#healthLabel"),
    statusDialog: $("#statusDialog"), providerList: $("#providerList"), statusSummary: $("#statusSummary"), toastRegion: $("#toastRegion")
  };
  let currentConversationId = null;
  let isSending = false;
  let lastStatus = null;

  function escapeText(text) { return String(text ?? ""); }
  function toast(message, duration = 4200) {
    const node = document.createElement("div");
    node.className = "toast";
    node.textContent = message;
    els.toastRegion.append(node);
    window.setTimeout(() => node.remove(), duration);
  }

  async function api(path, options = {}, retried = false) {
    const headers = new Headers(options.headers || {});
    headers.set("Accept", "application/json");
    if (options.body) headers.set("Content-Type", "application/json");
    const savedPassword = sessionStorage.getItem("freemind_app_password");
    if (savedPassword) headers.set("Authorization", `Bearer ${savedPassword}`);
    let response;
    try {
      response = await fetch(path, { ...options, headers, cache: "no-store" });
    } catch (_error) {
      throw new Error("無法連到 FreeMind AI 伺服器。請確認服務已啟動，或稍後再試。");
    }
    if (response.status === 401 && !retried) {
      const password = window.prompt("這個 FreeMind AI 工作區有設定存取密碼。請輸入密碼（只保存在目前瀏覽器分頁）：");
      if (password === null || !password.trim()) throw new Error("需要存取密碼才能使用此工作區。");
      sessionStorage.setItem("freemind_app_password", password);
      return api(path, options, true);
    }
    if (response.status === 401 && retried) {
      sessionStorage.removeItem("freemind_app_password");
      throw new Error("存取密碼不正確，請重新操作再輸入。");
    }
    if (response.status === 204) return null;
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(data.error || data.detail || `伺服器錯誤（HTTP ${response.status}）`);
      error.status = response.status;
      error.data = data;
      throw error;
    }
    return data;
  }

  function formatTime(iso) {
    if (!iso) return "";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }

  function renderConversationList(conversations) {
    els.list.replaceChildren();
    els.count.textContent = String(conversations.length);
    for (const convo of conversations) {
      const row = document.createElement("div");
      row.className = `conversation-item${convo.id === currentConversationId ? " active" : ""}`;
      const open = document.createElement("button");
      open.className = "conversation-item";
      open.style.cssText = "flex:1;min-width:0;border:0;background:transparent;padding:0;color:inherit";
      open.type = "button";
      open.setAttribute("aria-label", `開啟對話：${convo.title}`);
      const symbol = document.createElement("span"); symbol.className = "conversation-symbol"; symbol.textContent = "◌";
      const title = document.createElement("span"); title.className = "conversation-title"; title.textContent = convo.title || "新對話";
      open.append(symbol, title);
      open.addEventListener("click", () => loadConversation(convo.id));
      const del = document.createElement("button"); del.type = "button"; del.className = "delete-conversation"; del.textContent = "×";
      del.title = "刪除對話"; del.setAttribute("aria-label", `刪除對話：${convo.title}`);
      del.addEventListener("click", async (event) => {
        event.stopPropagation();
        if (!window.confirm(`確定刪除「${convo.title || "新對話"}」及其紀錄？此動作無法復原。`)) return;
        try {
          await api(`/api/conversations/${encodeURIComponent(convo.id)}`, { method: "DELETE" });
          if (currentConversationId === convo.id) currentConversationId = null;
          await refreshConversationList();
          if (!currentConversationId) await createConversation();
          toast("對話已刪除。");
        } catch (error) { toast(error.message); }
      });
      row.append(open, del);
      els.list.append(row);
    }
  }

  async function refreshConversationList() {
    const data = await api("/api/conversations");
    renderConversationList(data.conversations || []);
  }

  function scrollToBottom() {
    const panel = $("#chatScroll");
    requestAnimationFrame(() => { panel.scrollTop = panel.scrollHeight; });
  }

  function renderMessage(message) {
    const row = document.createElement("article");
    row.className = `message-row ${message.role === "assistant" ? "assistant" : "user"}`;
    const avatar = document.createElement("div"); avatar.className = "message-avatar"; avatar.textContent = message.role === "assistant" ? "F" : "你";
    const body = document.createElement("div"); body.className = "message-body";
    const meta = document.createElement("div"); meta.className = "message-meta";
    const name = document.createElement("strong"); name.textContent = message.role === "assistant" ? "FreeMind AI" : "你";
    meta.append(name);
    if (message.role === "assistant" && message.provider) {
      const provider = document.createElement("span"); provider.className = "meta-detail";
      provider.textContent = `${message.provider} · ${message.model || ""}${message.created_at ? " · " + formatTime(message.created_at) : ""}`;
      meta.append(provider);
    } else if (message.created_at) {
      const time = document.createElement("span"); time.className = "meta-detail"; time.textContent = formatTime(message.created_at); meta.append(time);
    }
    const content = document.createElement("div"); content.className = "message-content"; content.textContent = escapeText(message.content);
    body.append(meta, content); row.append(avatar, body); els.messages.append(row);
    return row;
  }

  async function loadConversation(id) {
    try {
      const data = await api(`/api/conversations/${encodeURIComponent(id)}/messages`);
      currentConversationId = id;
      els.messages.replaceChildren();
      for (const message of data.messages || []) renderMessage(message);
      els.welcome.hidden = (data.messages || []).length > 0;
      const listData = await api("/api/conversations");
      const convo = (listData.conversations || []).find(x => x.id === id);
      els.title.textContent = convo?.title || "新對話";
      renderConversationList(listData.conversations || []);
      closeMobileSidebar();
      scrollToBottom();
    } catch (error) { toast(error.message); }
  }

  async function createConversation() {
    try {
      const data = await api("/api/conversations", { method: "POST", body: JSON.stringify({ title: "新對話" }) });
      currentConversationId = data.conversation.id;
      els.title.textContent = "新對話";
      els.messages.replaceChildren();
      els.welcome.hidden = false;
      await refreshConversationList();
      closeMobileSidebar();
      els.input.focus();
    } catch (error) { toast(error.message); }
  }

  function setSending(value) {
    isSending = value;
    els.send.disabled = value || !els.input.value.trim();
    els.send.querySelector("span:first-child").textContent = value ? "思考中" : "傳送";
    els.input.disabled = value;
  }

  async function sendMessage(textOverride = null) {
    if (isSending) return;
    const message = (textOverride ?? els.input.value).trim();
    if (!message) return;
    if (!currentConversationId) {
      await createConversation();
      if (!currentConversationId) return;
    }
    els.welcome.hidden = true;
    renderMessage({ role: "user", content: message, created_at: new Date().toISOString() });
    els.input.value = ""; resizeInput(); updateCharCount(); setSending(true);
    const typing = document.createElement("article"); typing.className = "message-row assistant";
    const avatar = document.createElement("div"); avatar.className = "message-avatar"; avatar.textContent = "F";
    const body = document.createElement("div"); body.className = "message-body";
    const meta = document.createElement("div"); meta.className = "message-meta";
    const name = document.createElement("strong"); name.textContent = "FreeMind AI"; meta.append(name);
    const dots = document.createElement("div"); dots.className = "typing-indicator";
    for (let i = 0; i < 3; i++) dots.append(document.createElement("i"));
    body.append(meta, dots); typing.append(avatar, body); els.messages.append(typing); scrollToBottom();
    try {
      const data = await api("/api/chat", { method: "POST", body: JSON.stringify({ conversation_id: currentConversationId, message }) });
      typing.remove();
      renderMessage({ role: "assistant", content: data.content, provider: data.provider, model: data.model, created_at: new Date().toISOString() });
      if (data.fallback_used) toast(`已自動切換至 ${data.provider}，前一個服務暫時不可用。`);
      const conversations = await api("/api/conversations");
      const convo = (conversations.conversations || []).find(x => x.id === currentConversationId);
      els.title.textContent = convo?.title || "新對話";
      renderConversationList(conversations.conversations || []);
    } catch (error) {
      typing.remove();
      const row = document.createElement("article"); row.className = "message-row assistant";
      const avatar = document.createElement("div"); avatar.className = "message-avatar"; avatar.textContent = "!";
      const body = document.createElement("div"); body.className = "message-body";
      const meta = document.createElement("div"); meta.className = "message-meta";
      const name = document.createElement("strong"); name.textContent = "這次沒有成功送出"; meta.append(name);
      const content = document.createElement("div"); content.className = "message-error"; content.textContent = error.message;
      body.append(meta, content);
      if (error.data?.failures?.length) {
        const detail = document.createElement("div"); detail.className = "message-error";
        detail.textContent = error.data.failures.map(x => `${x.provider}：${x.reason}`).join("\n"); body.append(detail);
      }
      const retry = document.createElement("button"); retry.type = "button"; retry.className = "text-button"; retry.style.marginTop = "10px"; retry.textContent = "重試這則訊息";
      retry.addEventListener("click", () => sendMessage(message)); body.append(retry); row.append(avatar, body); els.messages.append(row);
      toast(error.message, 6000);
    } finally {
      setSending(false); els.input.disabled = false; els.input.focus(); scrollToBottom();
      if (currentConversationId) refreshConversationList().catch(() => {});
    }
  }

  function resizeInput() { els.input.style.height = "auto"; els.input.style.height = `${Math.min(els.input.scrollHeight, 200)}px`; }
  function updateCharCount() { els.charCount.textContent = `${els.input.value.length.toLocaleString()} / 12000`; els.send.disabled = isSending || !els.input.value.trim(); }
  function closeMobileSidebar() { els.sidebar.classList.remove("open"); els.scrim.classList.remove("active"); }

  async function refreshHealth() {
    try {
      const health = await api("/api/health");
      els.healthDot.className = "status-dot healthy"; els.healthLabel.textContent = health.status === "ok" ? "服務連線正常" : "服務狀態未知";
      const status = await api("/api/providers"); lastStatus = status;
      const ready = (status.providers || []).filter(x => x.state === "ready").length;
      if (!status.configured_count) { els.healthLabel.textContent = "尚未設定 AI 服務"; els.healthDot.className = "status-dot error"; }
      else if (!ready) { els.healthLabel.textContent = "AI 服務暫時冷卻"; els.healthDot.className = "status-dot error"; }
      renderProviderStatus(status);
    } catch (error) {
      els.healthDot.className = "status-dot error"; els.healthLabel.textContent = "無法連線";
      if (els.statusDialog.open) els.statusSummary.textContent = error.message;
    }
  }

  function renderProviderStatus(data) {
    els.providerList.replaceChildren();
    if (!data.providers?.length) {
      const empty = document.createElement("div"); empty.className = "empty-providers";
      empty.textContent = "尚未設定 AI 服務。請複製 .env.example 為 .env，填入至少一家服務的 API Key 與模型設定，再重新啟動。金鑰只放在伺服器，不會送到瀏覽器。";
      els.providerList.append(empty); els.statusSummary.textContent = "0 家服務已設定"; return;
    }
    for (const item of data.providers) {
      const card = document.createElement("div"); card.className = "provider-card";
      const dot = document.createElement("span"); dot.className = `provider-state-dot${item.state === "cooldown" ? " cooldown" : ""}`;
      const main = document.createElement("div"); main.className = "provider-main";
      const providerName = document.createElement("div"); providerName.className = "provider-name"; providerName.textContent = item.label;
      const model = document.createElement("div"); model.className = "provider-model"; model.textContent = item.model;
      main.append(providerName, model);
      const state = document.createElement("div"); state.className = "provider-status";
      state.textContent = item.state === "cooldown" ? `暫停嘗試 · 約 ${Math.ceil(item.cooldown_seconds / 60)} 分鐘` : (item.last_error ? `上次失敗：${item.last_error}` : (item.last_success ? `上次成功 · ${new Date(item.last_success * 1000).toLocaleTimeString()}` : "已設定 · 尚未測試"));
      card.append(dot, main, state); els.providerList.append(card);
    }
    const ready = data.providers.filter(x => x.state === "ready").length;
    if (data.configured_count < 2) {
      const warning = document.createElement("div");
      warning.className = "empty-providers";
      warning.setAttribute("role", "status");
      warning.textContent = data.configured_count === 1
        ? "目前只設定 1 家 AI 服務，沒有真正的備援。這家服務遇到每日額度限制時，聊天就會暫停。請在本機 .env 再設定至少一家不同供應商（例如 Groq 或 OpenRouter）的 API Key 與可用模型，儲存後重新啟動 FreeMind AI。不要把 API Key 貼到聊天或公開 GitHub。"
        : "目前沒有設定 AI 服務。請在本機 .env 設定至少一家供應商的 API Key 與可用模型，再重新啟動 FreeMind AI。";
      els.providerList.prepend(warning);
    }
    els.statusSummary.textContent = `${data.configured_count} 家已設定 · ${ready} 家目前未冷卻${data.configured_count < 2 ? " · 備援不足" : ""}`;
  }

  els.input.addEventListener("input", () => { resizeInput(); updateCharCount(); });
  els.input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); sendMessage(); }
  });
  els.send.addEventListener("click", () => sendMessage());
  $("#newChat").addEventListener("click", createConversation);
  $("#refreshStatus").addEventListener("click", refreshHealth);
  $("#openStatus").addEventListener("click", async () => { els.statusDialog.showModal(); await refreshHealth(); });
  $("#closeStatus").addEventListener("click", () => els.statusDialog.close());
  $("#statusRefreshButton").addEventListener("click", refreshHealth);
  $("#openSidebar").addEventListener("click", () => { els.sidebar.classList.add("open"); els.scrim.classList.add("active"); });
  $("#closeSidebar").addEventListener("click", closeMobileSidebar);
  els.scrim.addEventListener("click", closeMobileSidebar);
  document.querySelectorAll(".suggestion").forEach(button => button.addEventListener("click", () => { els.input.value = button.dataset.prompt || ""; resizeInput(); updateCharCount(); els.input.focus(); }));

  async function boot() {
    try {
      await refreshHealth();
      const data = await api("/api/conversations");
      const conversations = data.conversations || [];
      renderConversationList(conversations);
      if (conversations.length) await loadConversation(conversations[0].id);
      else await createConversation();
    } catch (error) { toast(error.message, 7000); }
  }
  updateCharCount(); boot();
})();
