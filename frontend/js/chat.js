/* ── Chat Panel ─────────────────────────────────────────────── */

(function initChat() {
  const panel = document.getElementById('tab-chat');

  panel.innerHTML = `
    <div style="display:flex;flex-direction:column;height:100%;overflow:hidden;">

      <!-- Header -->
      <div class="glass-header" style="display:flex;align-items:center;justify-content:space-between;padding:0 24px;height:56px;flex-shrink:0;">
        <div>
          <h1 style="font-size:15px;font-weight:650;letter-spacing:-.02em;color:var(--t1);">对话</h1>
          <p style="font-size:11.5px;color:var(--t4);">Wiki 管理 Agent
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
    const base = loadSettings().api_base || '';
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
      // Select saved model preference, fall back to first
      const saved = loadSettings().llm_model;
      selectEl.value = (saved && models.includes(saved)) ? saved : models[0];
    } catch {
      const fallback = loadSettings().llm_model || '';
      selectEl.innerHTML = fallback
        ? `<option value="${fallback}">${fallback}</option>`
        : '<option value="">未发现模型</option>';
    }
  }

  loadModels();

  // Persist model selection to settings on change
  document.getElementById('chat-model').addEventListener('change', () => {
    saveSettings({ llm_model: document.getElementById('chat-model').value });
  });

  function addMessage(role, content = '', id = null) {
    const isUser = role === 'user';
    const isSystem = role === 'system' || role === 'thinking';
    const msgId = id || makeMessageId(role);

    if (isSystem) {
      const el = document.createElement('div');
      el.className = 'chat-system-msg';
      el.id = msgId;
      el.textContent = content;
      messagesEl.appendChild(el);
      messagesEl.scrollTop = messagesEl.scrollHeight;
      return msgId;
    }

    const row = document.createElement('div');
    row.className = isUser ? 'chat-msg-row chat-msg-row--user' : 'chat-msg-row chat-msg-row--ai';
    row.id = msgId;

    const bubble = document.createElement('div');
    bubble.className = isUser ? 'chat-bubble chat-bubble--user' : 'chat-bubble chat-bubble--ai';
    bubble.id = msgId + '-content';

    if (isUser && content) {
      bubble.textContent = content;
    }
    if (!isUser && !content) {
      bubble.innerHTML = '<span class="chat-placeholder">&nbsp;</span>';
    }

    row.appendChild(bubble);
    messagesEl.appendChild(row);
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

  let _markedReady = null;

  function _loadMarked() {
    if (_markedReady) return _markedReady;
    if (typeof marked !== 'undefined') {
      _markedReady = Promise.resolve();
      return _markedReady;
    }
    _markedReady = new Promise((resolve) => {
      const s = document.createElement('script');
      s.src = 'https://cdn.jsdelivr.net/npm/marked/marked.min.js';
      s.onload = () => { resolve(); };
      s.onerror = () => { _markedReady = null; resolve(); };
      document.head.appendChild(s);
    });
    return _markedReady;
  }

  async function renderMarkdown(text) {
    if (typeof marked !== 'undefined') {
      return marked.parse(text);
    }
    await _loadMarked();
    if (typeof marked !== 'undefined') {
      return marked.parse(text);
    }
    return escapeHtml(text).replace(/\n/g, '<br>');
  }

  // Pre-load marked.js
  _loadMarked();

  async function restoreSession() {
    if (!currentThreadId) return false;
    // Try backend first
    try {
      const base = loadSettings().api_base || '';
      const resp = await fetch(`${base}/chat/sessions/${currentThreadId}`);
      if (resp.ok) {
        const data = await resp.json();
        if (data.messages && data.messages.length > 0) {
          chatHistory = data.messages;
          for (const msg of data.messages) {
            addMessage(msg.role, msg.content);
          }
          // Cache to localStorage as backup
          try { localStorage.setItem('omnikb_chat_history', JSON.stringify(data.messages)); } catch {}
          return true;
        }
      }
    } catch {}
    // Fallback to localStorage
    try {
      const saved = localStorage.getItem('omnikb_chat_history');
      if (saved) {
        const msgs = JSON.parse(saved);
        if (Array.isArray(msgs) && msgs.length > 0) {
          chatHistory = msgs;
          for (const msg of msgs) {
            addMessage(msg.role, msg.content);
          }
          return true;
        }
      }
    } catch {}
    return false;
  }

  let thinkMsgId = null;
  let thinkPages = [];

  function ensureThinkingCard() {
    if (thinkMsgId) return;
    thinkMsgId = addMessage('thinking', '');
    const el = document.getElementById(thinkMsgId);
    if (el) {
      el.innerHTML = '<div class="think-card"><div class="think-header"><span class="think-spinner"></span><span class="think-title">正在思考...</span></div><div class="think-pages"></div></div>';
    }
  }
  function finishThinkingCard() {
    const el = document.getElementById(thinkMsgId);
    if (!el) return;
    const sp = el.querySelector('.think-spinner');
    if (sp) { sp.className = 'think-check'; sp.textContent = '✅'; }
    const t = el.querySelector('.think-title');
    if (t) t.textContent = thinkPages.length > 0 ? '已检索 ' + thinkPages.length + ' 个页面' : '思考完成';
    el.classList.add('think-done');
  }


  async function sendMessage() {
    if (isStreaming) return;
    const text = inputEl.value.trim();
    if (!text) return;
    inputEl.value = '';

    chatHistory.push({ role: 'user', content: text });
    addMessage('user', text);

    // Don't create AI bubble yet — wait for first token
    let aiMsgId = null;
    let contentEl = null;

    isStreaming = true;
    document.getElementById('btn-send').disabled = true;

    const provider = 'custom';
    const model = document.getElementById('chat-model').value.trim() || undefined;

    let fullText = '';
    let firstToken = true;
    let renderPending = false;

    function ensureAiBubble() {
      if (!aiMsgId) {
        aiMsgId = addMessage('assistant');
        contentEl = document.getElementById(`${aiMsgId}-content`);
        if (contentEl) contentEl.classList.add('chat-streaming');
      }
    }

    async function scheduleRender() {
      if (renderPending) return;
      renderPending = true;
      requestAnimationFrame(async () => {
        renderPending = false;
        if (!contentEl) return;
        // Remove placeholder on first render
        const ph = contentEl.querySelector('.chat-placeholder');
        if (ph) ph.remove();
        contentEl.innerHTML = await renderMarkdown(fullText);
        const atBottom = messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 80;
        if (atBottom) messagesEl.scrollTop = messagesEl.scrollHeight;
      });
    }

    try {
      const base = loadSettings().api_base || '';
      const res = await fetch(`${base}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: chatHistory,
          provider,
          model,
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
            if (evt.type === 'reasoning') {
              ensureThinkingCard();
              const el = document.getElementById(thinkMsgId);
              if (el) {
                let b = el.querySelector('.think-body');
                if (!b) {
                  b = document.createElement('div');
                  b.className = 'think-body';
                  el.querySelector('.think-card').appendChild(b);
                }
                b.textContent += evt.content;
                messagesEl.scrollTop = messagesEl.scrollHeight;
              }
            } else if (evt.type === 'tool_call') {
              ensureThinkingCard();
              const pn = evt.args?.page_id || evt.name || '';
              if (pn) {
                if (!thinkPages.includes(pn)) thinkPages.push(pn);
                const el = document.getElementById(thinkMsgId);
                if (el) {
                  const pe = el.querySelector('.think-pages');
                  if (pe) {
                    const t = document.createElement('span');
                    t.className = 'think-page-tag';
                    t.textContent = '📄 ' + pn.replace(/_/g, ' ');
                    pe.appendChild(t);
                  }
                }
              }
            } else if (evt.type === 'token') {
              if (firstToken) {
                firstToken = false;
                if (thinkMsgId) finishThinkingCard();
                ensureAiBubble();
              }
              fullText += evt.content;
              scheduleStreamRender();
            } else if (evt.type === 'citations') {

            } else if (evt.type === 'session') {
              currentThreadId = evt.thread_id;
              localStorage.setItem('omnikb_thread_id', currentThreadId);
              _updateThreadDisplay();
            }
          } catch {}
        }
      }

      // Flush any remaining render
      if (renderPending) {
        renderPending = false;
      }
      if (contentEl) {
        contentEl.classList.remove('chat-streaming');
        contentEl.innerHTML = await renderMarkdown(fullText);
      }

      if (fullText) {
        chatHistory.push({ role: 'assistant', content: fullText });
        try { localStorage.setItem('omnikb_chat_history', JSON.stringify(chatHistory)); } catch {}
      } else {
        // No content — remove the empty bubble
        if (aiMsgId) {
          const el = document.getElementById(aiMsgId);
          if (el) el.remove();
        }
      }

    } catch (e) {
      if (!contentEl) {
        ensureAiBubble();
      }
      if (contentEl) {
        contentEl.classList.remove('chat-streaming');
        contentEl.innerHTML = `<span style="color:var(--danger-t);">错误：${escapeHtml(e.message)}</span>`;
      }
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
    localStorage.removeItem('omnikb_chat_history');
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
    try { localStorage.removeItem('omnikb_chat_history'); } catch {}
  });

  // Show welcome on first open
  document.addEventListener('tab:shown', e => {
    if (e.detail === 'chat' && messagesEl.childElementCount === 0) {
      restoreSession().then(loaded => {
        if (!loaded) addMessage('assistant', '你好！我是 Wiki 管理 Agent。用自然语言管理知识库：创建页面、更新内容、检索信息、分析图谱。');
      });
    }
  });

  // Subscribe to agent events — show ingest/wiki progress as system messages
  (function connectAgentEvents() {
    try {
      const base = loadSettings().api_base || '';
      const es = new EventSource(base + '/agent/v2/events');
      es.onmessage = function(e) {
        try {
          const evt = JSON.parse(e.data);
          if (evt.type === 'wiki_analysis_start' || evt.type === 'wiki_batch_start') {
            addMessage('system', '🧠 Wiki 生成中... ' + (evt.data?.source_count ? evt.data.source_count + ' 个来源' : ''));
          } else if (evt.type === 'wiki_sync_complete') {
            const d = evt.data || {};
            const msg = d.total_failed > 0
              ? `⚠️ Wiki 同步完成: ${d.total_created} 创建 / ${d.total_updated} 更新 / ${d.total_failed} 失败`
              : `✅ Wiki 同步完成: ${d.total_created} 创建 / ${d.total_updated} 更新`;
            addMessage('system', msg);
          } else if (evt.type === 'progress' || evt.type === 'info') {
            addMessage('system', evt.data?.message || evt.data || '');
          }
        } catch {}
      };
      es.onerror = function() { es.close(); setTimeout(connectAgentEvents, 5000); };
    } catch {}
  })();
})();
