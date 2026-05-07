/* ── Chat Panel ─────────────────────────────────────────────── */

(function initChat() {
  const panel = document.getElementById('tab-chat');

  panel.innerHTML = `
    <div class="flex flex-col h-full">
      <!-- Header -->
      <div class="flex items-center justify-between px-6 py-3 border-b border-slate-800 flex-shrink-0">
        <div>
          <h1 class="text-lg font-bold text-white">对话</h1>
          <p class="text-slate-500 text-xs">RAG 对话
            <span id="thread-id-display" class="ml-1.5 font-mono text-slate-700 text-xs"></span>
          </p>
        </div>
        <div class="flex items-center gap-3">
          <select id="chat-provider" class="bg-slate-900 border border-slate-700 rounded-lg px-2 py-1.5 text-xs text-slate-300 focus:outline-none">
            <option value="custom">第三方兼容</option>
            <option value="openai">OpenAI</option>
            <option value="anthropic">Anthropic</option>
            <option value="ollama">Ollama</option>
          </select>
          <select id="chat-model" class="bg-slate-900 border border-slate-700 rounded-lg px-2 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-brand max-w-[180px]">
            <option value="">加载中…</option>
          </select>
          <button id="btn-new-session" title="开始新对话（清除历史）"
            class="text-xs text-slate-500 hover:text-brand border border-slate-700 hover:border-brand px-2 py-1 rounded transition-colors">新建对话</button>
          <button id="btn-clear-chat" class="text-slate-500 hover:text-slate-300 text-xs transition-colors">清空</button>
        </div>
      </div>

      <!-- Messages -->
      <div id="chat-messages" class="flex-1 overflow-y-auto px-6 py-4 space-y-4"></div>

      <!-- Citations drawer -->
      <div id="citations-panel" class="hidden px-6 py-3 border-t border-slate-800 bg-slate-900/50 max-h-40 overflow-y-auto flex-shrink-0">
        <div class="flex items-center justify-between mb-2">
          <span class="text-xs font-semibold text-slate-400">引用来源</span>
          <button id="btn-close-citations" class="text-slate-600 hover:text-slate-400 text-xs">✕</button>
        </div>
        <div id="citations-list" class="flex gap-2 flex-wrap"></div>
      </div>

      <!-- Input -->
      <div class="px-6 py-4 border-t border-slate-800 flex-shrink-0">
        <div class="flex gap-3">
          <textarea id="chat-input" rows="2" placeholder="向知识库提问…"
            class="flex-1 bg-slate-900 border border-slate-700 rounded-xl px-4 py-3 text-sm text-slate-200 focus:outline-none focus:border-brand resize-none"></textarea>
          <button id="btn-send" class="btn-primary px-5 rounded-xl text-sm font-medium self-end py-3">发送</button>
        </div>
        <p class="text-xs text-slate-600 mt-1.5">每次检索 <input id="chat-topk" type="number" value="5" min="1" max="20"
          class="inline w-10 bg-transparent border-b border-slate-700 text-center text-xs focus:outline-none"> 个片段</p>
      </div>
    </div>
  `;

  const messagesEl = document.getElementById('chat-messages');
  const inputEl = document.getElementById('chat-input');
  let chatHistory = [];
  let isStreaming = false;

  // Thread-id persistence
  let currentThreadId = localStorage.getItem('omnikb_thread_id') || null;
  function _updateThreadDisplay() {
    const el = document.getElementById('thread-id-display');
    if (el) el.textContent = currentThreadId ? `[${currentThreadId.slice(0, 8)}…]` : '';
  }
  _updateThreadDisplay();

  // Pre-fill from settings
  const s = loadSettings();
  document.getElementById('chat-provider').value = s.llm_provider || 'custom';

  // Load available models from backend
  async function loadModels() {
    const base = loadSettings().api_base || 'http://localhost:8000';
    const sel = document.getElementById('chat-model');
    try {
      const data = await (await fetch(`${base}/chat/models`)).json();
      const saved = s.llm_model || data.default || '';
      sel.innerHTML = '';
      const models = data.models && data.models.length ? data.models : [data.default].filter(Boolean);
      models.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m;
        opt.textContent = m;
        if (m === saved) opt.selected = true;
        sel.appendChild(opt);
      });
      if (!sel.value && models.length) sel.value = models[0];
    } catch {
      sel.innerHTML = `<option value="${s.llm_model || ''}">${s.llm_model || '(未知)'}</option>`;
    }
  }
  loadModels();

  function addMessage(role, content = '', id = null) {
    const isUser = role === 'user';
    const msgId = id || `msg-${Date.now()}`;
    const el = document.createElement('div');
    el.id = msgId;
    el.className = `flex ${isUser ? 'justify-end' : 'justify-start'} items-end gap-3`;
    el.innerHTML = `
      <div class="max-w-[75%]">
        <div class="${isUser ? 'bubble-user' : 'bubble-ai'} px-4 py-3 text-sm text-slate-100 prose-dark" id="${msgId}-content">
          ${isUser ? escapeHtml(content) : ''}
        </div>
      </div>
    `;
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return msgId;
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

    const provider = document.getElementById('chat-provider').value;
    const model = document.getElementById('chat-model').value || undefined;
    const topK = parseInt(document.getElementById('chat-topk').value) || 5;

    let fullText = '';

    try {
      const base = loadSettings().api_base || 'http://localhost:8000';
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
              contentEl.innerHTML = renderMarkdown(fullText);
              contentEl.classList.add('typing-cursor');
              messagesEl.scrollTop = messagesEl.scrollHeight;
            } else if (evt.type === 'citations') {
              showCitations(evt.citations);
            } else if (evt.type === 'session') {
              // Persist thread_id
              currentThreadId = evt.thread_id;
              localStorage.setItem('omnikb_thread_id', currentThreadId);
              _updateThreadDisplay();
            }
          } catch {}
        }
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

  function showCitations(citations) {
    if (!citations.length) return;
    const panel = document.getElementById('citations-panel');
    const list = document.getElementById('citations-list');
    panel.classList.remove('hidden');
    list.innerHTML = citations.map(c => `
      <div class="citation-card rounded-lg px-3 py-2 text-xs cursor-pointer max-w-xs" title="${escapeHtml(c.content)}">
        <div class="text-brand font-semibold mb-0.5">[${c.index}] ${escapeHtml((c.source || '').slice(0, 40))}</div>
        <div class="text-slate-500 line-clamp-2">${escapeHtml(c.content)}</div>
      </div>
    `).join('');
  }

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
