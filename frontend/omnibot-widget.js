/* OmniBot Widget v1.0 — Embeddable KB Q&A chat bubble
   Usage:
     <script src="http://your-server:8000/omnibot-widget.js"
             data-scenario="SCENARIO_ID"
             data-api-key="sk-..."
             data-api-base="http://your-server:8000"
             data-title="Ask me anything"
             data-color="#007AFF"
             data-position="bottom-right">
     </script>
*/

(function () {
  const script = document.currentScript;
  if (!script) return;

  const config = {
    scenario: script.getAttribute('data-scenario') || '',
    apiKey: script.getAttribute('data-api-key') || '',
    apiBase: (script.getAttribute('data-api-base') || window.location.origin).replace(/\/+$/, ''),
    title: script.getAttribute('data-title') || '知识库问答',
    color: script.getAttribute('data-color') || '#007AFF',
    position: script.getAttribute('data-position') || 'bottom-right',
    welcome: script.getAttribute('data-welcome') || '你好！请问有什么可以帮助你？',
  };

  if (!config.scenario) {
    console.warn('[OmniBot] data-scenario is required');
    return;
  }

  // ── Inject styles ──────────────────────────────────────────────
  const style = document.createElement('style');
  style.textContent = `
    #omnibot-bubble {
      position: fixed;
      z-index: 99998;
      width: 52px;
      height: 52px;
      border-radius: 50%;
      background: ${config.color};
      color: #fff;
      border: none;
      cursor: pointer;
      box-shadow: 0 4px 16px rgba(0,0,0,.25);
      display: flex;
      align-items: center;
      justify-content: center;
      transition: transform 200ms cubic-bezier(0.34,1.56,0.64,1), box-shadow 200ms ease;
      font-size: 22px;
    }
    #omnibot-bubble:hover {
      transform: scale(1.08);
      box-shadow: 0 6px 24px rgba(0,0,0,.35);
    }
    #omnibot-bubble svg { width: 24px; height: 24px; }
    #omnibot-container {
      position: fixed;
      z-index: 99999;
      width: 380px;
      max-width: calc(100vw - 24px);
      height: 560px;
      max-height: calc(100vh - 120px);
      border-radius: 16px;
      overflow: hidden;
      box-shadow: 0 12px 48px rgba(0,0,0,.3);
      display: none;
      flex-direction: column;
      background: #ffffff;
      border: 1px solid rgba(0,0,0,.08);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Inter', system-ui, sans-serif;
      transition: opacity 200ms ease, transform 200ms ease;
    }
    #omnibot-container.open {
      display: flex;
    }
    #omnibot-header {
      padding: 12px 16px;
      background: ${config.color};
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-shrink: 0;
    }
    #omnibot-header span { font-size: 14px; font-weight: 600; }
    #omnibot-header button {
      background: rgba(255,255,255,.15);
      border: none;
      color: #fff;
      width: 26px;
      height: 26px;
      border-radius: 50%;
      cursor: pointer;
      font-size: 14px;
      line-height: 1;
      transition: background 150ms;
    }
    #omnibot-header button:hover { background: rgba(255,255,255,.25); }
    #omnibot-messages {
      flex: 1;
      overflow-y: auto;
      padding: 12px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    #omnibot-messages::-webkit-scrollbar { width: 4px; }
    #omnibot-messages::-webkit-scrollbar-thumb { background: rgba(0,0,0,.08); border-radius: 100px; }
    .omb-msg { max-width: 85%; padding: 8px 14px; border-radius: 16px; font-size: 13px; line-height: 1.5; word-break: break-word; }
    .omb-user { align-self: flex-end; background: ${config.color}; color: #fff; border-bottom-right-radius: 4px; }
    .omb-ai  { align-self: flex-start; background: #f5f5f7; color: #1d1d1f; border: 1px solid rgba(0,0,0,.06); border-bottom-left-radius: 4px; }
    #omnibot-input-wrap {
      padding: 12px;
      border-top: 1px solid rgba(0,0,0,.06);
      display: flex;
      gap: 8px;
      flex-shrink: 0;
    }
    #omnibot-input {
      flex: 1;
      background: #f5f5f7;
      border: 1px solid rgba(0,0,0,.1);
      border-radius: 10px;
      padding: 8px 12px;
      color: #1d1d1f;
      font-size: 13px;
      resize: none;
      outline: none;
    }
    #omnibot-input:focus { border-color: ${config.color}; }
    #omnibot-send {
      background: ${config.color};
      color: #fff;
      border: none;
      border-radius: 10px;
      padding: 8px 16px;
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      transition: opacity 150ms;
    }
    #omnibot-send:disabled { opacity: 0.5; cursor: not-allowed; }
    #omnibot-send:hover:not(:disabled) { opacity: 0.9; }

    ${config.position === 'bottom-right' ? `
      #omnibot-bubble { bottom: 20px; right: 20px; }
      #omnibot-container { bottom: 84px; right: 20px; }
    ` : config.position === 'bottom-left' ? `
      #omnibot-bubble { bottom: 20px; left: 20px; }
      #omnibot-container { bottom: 84px; left: 20px; }
    ` : `
      #omnibot-bubble { bottom: 20px; right: 20px; }
      #omnibot-container { bottom: 84px; right: 20px; }
    `}
  `;
  document.head.appendChild(style);

  // ── Create DOM ──────────────────────────────────────────────────
  const bubble = document.createElement('button');
  bubble.id = 'omnibot-bubble';
  bubble.innerHTML = `<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/></svg>`;
  bubble.title = config.title;

  const container = document.createElement('div');
  container.id = 'omnibot-container';
  container.innerHTML = `
    <div id="omnibot-header">
      <span>${escHtml(config.title)}</span>
      <button id="omnibot-close">&times;</button>
    </div>
    <div id="omnibot-messages">
      <div class="omb-msg omb-ai">${escHtml(config.welcome)}</div>
    </div>
    <div id="omnibot-input-wrap">
      <textarea id="omnibot-input" rows="1" placeholder="输入问题…" autocomplete="off"></textarea>
      <button id="omnibot-send">发送</button>
    </div>
  `;

  document.body.appendChild(bubble);
  document.body.appendChild(container);

  function escHtml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // ── Toggle ──────────────────────────────────────────────────────
  let isOpen = false;
  bubble.addEventListener('click', () => {
    isOpen = !isOpen;
    container.classList.toggle('open', isOpen);
    bubble.style.display = isOpen ? 'none' : 'flex';
    if (isOpen) document.getElementById('omnibot-input').focus();
  });
  document.getElementById('omnibot-close').addEventListener('click', () => {
    isOpen = false;
    container.classList.remove('open');
    bubble.style.display = 'flex';
  });

  // ── Chat logic ──────────────────────────────────────────────────
  const messagesEl = document.getElementById('omnibot-messages');
  const inputEl = document.getElementById('omnibot-input');
  const sendBtn = document.getElementById('omnibot-send');
  let chatHistory = [];
  let isStreaming = false;

  function addMessage(role, content) {
    const el = document.createElement('div');
    el.className = `omb-msg ${role === 'user' ? 'omb-user' : 'omb-ai'}`;
    el.textContent = content;
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return el;
  }

  async function sendMessage() {
    if (isStreaming) return;
    const text = inputEl.value.trim();
    if (!text) return;
    inputEl.value = '';
    inputEl.style.height = 'auto';

    chatHistory.push({ role: 'user', content: text });
    addMessage('user', text);

    const aiEl = addMessage('assistant', '…');
    isStreaming = true;
    sendBtn.disabled = true;

    try {
      const res = await fetch(`${config.apiBase}/kb-api/${config.scenario}/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${config.apiKey}`,
        },
        body: JSON.stringify({
          messages: chatHistory,
          top_k: 5,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      let fullText = '';

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
              aiEl.textContent = fullText;
              messagesEl.scrollTop = messagesEl.scrollHeight;
            }
          } catch {}
        }
      }
      chatHistory.push({ role: 'assistant', content: fullText });
    } catch (e) {
      aiEl.textContent = '错误: ' + e.message;
      aiEl.style.color = '#f87171';
    } finally {
      isStreaming = false;
      sendBtn.disabled = false;
    }
  }

  sendBtn.addEventListener('click', sendMessage);
  inputEl.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  inputEl.addEventListener('input', () => {
    inputEl.style.height = 'auto';
    inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + 'px';
  });
})();
