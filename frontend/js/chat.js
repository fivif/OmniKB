/* ── Chat Panel ─────────────────────────────────────────────── */

(function initChat() {
  const panel = document.getElementById('tab-chat');

  panel.innerHTML = `
    <div style="display:flex;flex-direction:column;height:100%;overflow:hidden;">

      <!-- Header -->
      <div class="glass-header" style="display:flex;align-items:center;justify-content:space-between;padding:0 24px;height:56px;flex-shrink:0;">
        <div>
          <h1 style="font-size:15px;font-weight:650;letter-spacing:-.02em;color:var(--t1);">对话</h1>
          <p style="font-size:11.5px;color:var(--t4);">RAG 智能问答
            <span id="thread-id-display" style="margin-left:6px;font-family:var(--mono);font-size:10.5px;color:var(--t4);"></span>
          </p>
        </div>
        <div style="display:flex;align-items:center;gap:10px;">
          <span style="background:var(--bg-muted);border:1px solid var(--bd);border-radius:var(--r);padding:5px 9px;font-size:12.5px;color:var(--t2);white-space:nowrap;">OpenAI-compatible</span>
          <select id="chat-model" style="background:var(--bg-muted);border:1px solid var(--bd);border-radius:var(--r);padding:5px 9px;font-size:12.5px;color:var(--t2);max-width:220px;">
            <option value="">加载中…</option>
          </select>
          <button id="btn-new-session" class="btn-ghost" style="font-size:12.5px;">新建对话</button>
          <button id="btn-clear-chat" class="btn-ghost" style="font-size:12.5px;">清空</button>
        </div>
      </div>

      <!-- Messages -->
      <div id="chat-messages" style="flex:1;overflow-y:auto;padding:24px 32px;display:flex;flex-direction:column;gap:16px;"></div>

      <!-- Citations drawer -->
      <div id="citations-panel" class="hidden" style="padding:12px 32px;border-top:1px solid var(--bd);background:var(--bg-muted);max-height:100px;overflow-y:auto;flex-shrink:0;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
          <span style="font-size:11.5px;font-weight:600;color:var(--t3);text-transform:uppercase;letter-spacing:.05em;">引用来源</span>
          <button id="btn-close-citations" class="btn-ghost" style="font-size:12px;padding:2px 7px;">✕</button>
        </div>
        <div id="citations-list" style="display:flex;gap:8px;flex-wrap:wrap;"></div>
      </div>

      <!-- Input area -->
      <div class="glass-header" style="padding:14px 24px;flex-shrink:0;">
        <div style="display:flex;gap:10px;align-items:flex-end;">
          <textarea id="chat-input" rows="2" placeholder="向知识库提问…"
            style="flex:1;border-radius:var(--r-lg);padding:11px 14px;font-size:14px;resize:none;background:var(--bg-card);"></textarea>
          <button id="btn-send" class="btn-primary" style="height:44px;padding:0 20px;align-self:flex-end;">发送</button>
        </div>
        <p style="font-size:11.5px;color:var(--t4);margin-top:7px;">
          每次检索 <input id="chat-topk" type="number" value="5" min="1" max="20"
            style="display:inline;width:40px;padding:2px 5px;text-align:center;font-size:11.5px;border:none;border-bottom:1px solid var(--bd);background:transparent;"> 个片段
        </p>
      </div>
    </div>
  `;


  const messagesEl = document.getElementById('chat-messages');
  const inputEl = document.getElementById('chat-input');
  let chatHistory = [];
  let isStreaming = false;
  let messageSeq = 0;

  // Thread-id persistence
  let currentThreadId = localStorage.getItem('omnikb_thread_id') || null;
  function _updateThreadDisplay() {
    const el = document.getElementById('thread-id-display');
    if (el) el.textContent = currentThreadId ? `[${currentThreadId.slice(0, 8)}…]` : '';
  }
  _updateThreadDisplay();

  async function loadModels() {
    const base = loadSettings().api_base || 'http://localhost:6886';
    const selectEl = document.getElementById('chat-model');
    try {
      const resp = await fetch(`${base}/chat/models`);
      const data = await resp.json();
      const models = Array.isArray(data.models) && data.models.length
        ? data.models
        : [data.default].filter(Boolean);

      selectEl.innerHTML = '';
      if (!models.length) {
        selectEl.innerHTML = '<option value="">未发现模型</option>';
        return;
      }

      models.forEach(modelName => {
        const option = document.createElement('option');
        option.value = modelName;
        option.textContent = modelName;
        selectEl.appendChild(option);
      });
      selectEl.value = models[0];
    } catch {
      const fallback = loadSettings().llm_model || '';
      selectEl.innerHTML = fallback
        ? `<option value="${fallback}">${fallback}</option>`
        : '<option value="">未发现模型</option>';
    }
  }

  loadModels();

  function addMessage(role, content = '', id = null) {
    const isUser = role === 'user';
    const msgId = id || makeMessageId(role);
    const el = document.createElement('div');
    el.id = msgId;
    el.className = `flex ${isUser ? 'justify-end' : 'justify-start'} items-end gap-3`;
    el.innerHTML = `
      <div class="max-w-[75%]">
        <div class="${isUser ? 'bubble-user' : 'bubble-ai'} px-4 py-3 text-sm prose-light" id="${msgId}-content">
          ${isUser ? escapeHtml(content) : ''}
          ${!isUser ? '<span class="typing-placeholder">&nbsp;</span>' : ''}
        </div>
      </div>
    `;
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return msgId;
  }

  function makeMessageId(role) {
    messageSeq += 1;
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
      return `msg-${role}-${window.crypto.randomUUID()}`;
    }
    return `msg-${role}-${Date.now()}-${messageSeq}`;
  }

  function escapeHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function renderMarkdown(text) {
    if (typeof marked !== 'undefined') {
      return marked.parse(text);
    }
    return escapeHtml(text).replace(/\n/g, '<br>');
  }

  // Load marked.js lazily
  if (typeof marked === 'undefined') {
    const s = document.createElement('script');
    s.src = 'https://cdn.jsdelivr.net/npm/marked/marked.min.js';
    document.head.appendChild(s);
  }

  async function sendMessage() {
    if (isStreaming) return;
    const text = inputEl.value.trim();
    if (!text) return;
    inputEl.value = '';

    chatHistory.push({ role: 'user', content: text });
    addMessage('user', text);

    const aiMsgId = addMessage('assistant');
    const contentEl = document.getElementById(`${aiMsgId}-content`);
    contentEl.classList.add('typing-cursor');

    isStreaming = true;
    document.getElementById('btn-send').disabled = true;

    const provider = 'custom';
    const model = document.getElementById('chat-model').value.trim() || undefined;
    const topK = parseInt(document.getElementById('chat-topk').value) || 5;

    let fullText = '';
    let renderPending = false;
    function scheduleRender() {
      if (renderPending) return;
      renderPending = true;
      requestAnimationFrame(() => {
        renderPending = false;
        // Remove placeholder on first render
        const ph = contentEl.querySelector('.typing-placeholder');
        if (ph) ph.remove();
        contentEl.innerHTML = renderMarkdown(fullText);
        const atBottom = messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 80;
        if (atBottom) messagesEl.scrollTop = messagesEl.scrollHeight;
      });
    }

    try {
      const base = loadSettings().api_base || 'http://localhost:6886';
      const res = await fetch(`${base}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: chatHistory,
          provider,
          model,
          top_k: topK,
          thread_id: currentThreadId,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || res.statusText);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });

        const lines = buf.split('\n\n');
        buf = lines.pop();

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const raw = line.slice(6);
          if (raw === '[DONE]') break;
          try {
            const evt = JSON.parse(raw);
            if (evt.type === 'token') {
              fullText += evt.content;
              scheduleRender();
            } else if (evt.type === 'citations') {
              showCitations(evt.citations, contentEl);
            } else if (evt.type === 'session') {
              // Persist thread_id
              currentThreadId = evt.thread_id;
              localStorage.setItem('omnikb_thread_id', currentThreadId);
              _updateThreadDisplay();
            }
          } catch {}
        }
      }

      if (renderPending) {
        renderPending = false;
      }
      contentEl.classList.remove('typing-cursor');
      contentEl.innerHTML = renderMarkdown(fullText);
      chatHistory.push({ role: 'assistant', content: fullText });

    } catch (e) {
      contentEl.classList.remove('typing-cursor');
      contentEl.innerHTML = `<span class="text-red-400">错误：${escapeHtml(e.message)}</span>`;
    } finally {
      isStreaming = false;
      document.getElementById('btn-send').disabled = false;
    }
  }

  function showCitations(citations, targetEl) {
    if (!citations.length) return;

    // ── UI.5 inline citation bubbles within the message itself ───────
    if (targetEl && window.OmnikbCitations) {
      try {
        window.OmnikbCitations.render(targetEl, citations);
      } catch (exc) {
        console.warn('[chat] OmnikbCitations.render failed', exc);
      }
    }

    // ── Detailed bottom panel (kept for full-content review) ─────────
    const panel = document.getElementById('citations-panel');
    const list = document.getElementById('citations-list');
    panel.classList.remove('hidden');
    list.innerHTML = citations.map(c => `
      <div class="citation-card rounded-lg px-3 py-2 text-xs cursor-pointer max-w-xs" title="${escapeHtml(c.content)}" data-chunk-id="${escapeHtml(c.chunk_id || '')}">
        <div class="text-brand font-semibold mb-0.5">[${c.index}] ${escapeHtml((c.source || '').slice(0, 40))}</div>
        <div style="color:var(--t3);" class="line-clamp-2">${escapeHtml(c.content)}</div>
      </div>
    `).join('');
  }

  // Wire up bubble click → scroll the corresponding citation card into view
  document.addEventListener('omnikb:citation-click', (ev) => {
    const id = (ev.detail || {}).chunk_id;
    if (!id) return;
    const card = document.querySelector(`.citation-card[data-chunk-id="${CSS.escape(id)}"]`);
    if (card) {
      document.getElementById('citations-panel').classList.remove('hidden');
      card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      card.classList.add('citation-flash');
      setTimeout(() => card.classList.remove('citation-flash'), 1200);
    }
  });

  document.getElementById('btn-close-citations').addEventListener('click', () => {
    document.getElementById('citations-panel').classList.add('hidden');
  });

  document.getElementById('btn-send').addEventListener('click', sendMessage);
  inputEl.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });

  // New session: clears thread_id and chat history
  document.getElementById('btn-new-session').addEventListener('click', () => {
    currentThreadId = null;
    localStorage.removeItem('omnikb_thread_id');
    chatHistory = [];
    messagesEl.innerHTML = '';
    document.getElementById('citations-panel').classList.add('hidden');
    _updateThreadDisplay();
    addMessage('assistant', '新对话已开始。');
  });

  // Clear chat (keep thread_id — same session, new visual slate)
  document.getElementById('btn-clear-chat').addEventListener('click', () => {
    chatHistory = [];
    messagesEl.innerHTML = '';
    document.getElementById('citations-panel').classList.add('hidden');
  });

  // Show welcome on first open
  document.addEventListener('tab:shown', e => {
    if (e.detail === 'chat' && messagesEl.childElementCount === 0) {
      addMessage('assistant', '你好！请随时向知识库提问。');
    }
  });
})();
