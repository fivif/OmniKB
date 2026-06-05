/* ── Public KB Chat (scenario Q&A page) ─────────────────────── */

(function initKbChat() {
  // Parse scenario ID from URL: /s/slug or ?scenario=id
  const params = new URLSearchParams(window.location.search);
  let scenarioId = params.get('scenario');
  if (!scenarioId) {
    const pathMatch = window.location.pathname.match(/^\/s\/([a-z0-9-]+)$/);
    if (pathMatch) scenarioId = pathMatch[1];
  }
  const previewRequested = params.get('demo') === '1' || !scenarioId;
  const DEFAULT_TEMPLATE = 'assistant';
  const CHAT_TEMPLATES = {
    assistant: {
      badge: 'Knowledge Q&A',
      heading: 'Hi, how can I help?',
      subtitle: '',
      welcome: 'Ask any question about your knowledge base.',
      placeholder: 'Ask a question...',
      disclaimer: 'AI may make mistakes. Verify important information.',
      color: '#5b8cff',
      tone: 'light',
      hints: [],
    },
    guide: {
      badge: 'Guided Explainer',
      heading: 'What would you like to explore?',
      subtitle: '',
      welcome: 'I\'ll walk you through the material step by step.',
      placeholder: 'What topic interests you?',
      disclaimer: 'AI may make mistakes. Verify important information.',
      color: '#f07c52',
      tone: 'light',
      hints: [],
    },
    support: {
      badge: 'Support Desk',
      heading: 'How can I help you?',
      subtitle: '',
      welcome: 'Describe your issue and I\'ll find answers from our knowledge base.',
      placeholder: 'Describe your problem or question...',
      disclaimer: 'AI may make mistakes. Verify important information.',
      color: '#1bb98a',
      tone: 'dark',
      hints: [],
    },
  };

  const PREVIEW_SCENARIO = {
    name: 'Knowledge Q&A',
    description: '',
    ui_config: {
      template: 'assistant',
      title: 'Knowledge Q&A',
      subtitle: '',
      welcome: 'Ask any question about your knowledge base.',
      placeholder: 'Ask a question...',
      disclaimer: 'AI may make mistakes. Verify important information.',
      color: '#5b8cff',
    },
  };

  if (!scenarioId && !previewRequested) {
    document.body.innerHTML = `
      <div class="h-full flex items-center justify-center">
        <p style="color:var(--text-muted);">缺少场景 ID — 请在 URL 中添加 ?scenario=ID</p>
      </div>
    `;
    return;
  }

  let messagesEl = document.getElementById('chat-messages');
  let inputEl = document.getElementById('chat-input');
  let welcomeEl = document.getElementById('welcome-message');
  let apiKeyInput = document.getElementById('api-key-input');
  let sendBtn = document.getElementById('btn-send');
  let chatDisclaimer = document.getElementById('chat-disclaimer');

  let chatHistory = [];
  let isStreaming = false;
  let scenarioMeta = null;
  let messageSeq = 0;
  let previewMode = previewRequested;

  // Persist API key — saved on button click, not every keystroke
  const storageKey = `omnikb_kb_key_${scenarioId || 'preview'}`;
  apiKeyInput.value = localStorage.getItem(storageKey) || '';
  const btnSettings = document.getElementById('btn-show-key-modal');
  if (btnSettings && apiKeyInput.value) btnSettings.classList.add('has-key');

  // ── Key modal ────────────────────────────────────────
  const keyModal = document.getElementById('key-modal-backdrop');
  const btnCloseModal = document.getElementById('btn-close-key-modal');
  const btnSaveKey = document.getElementById('btn-save-key');

  // Key modal event listeners moved to bindAllEvents()

  // Key visibility toggle
  const btnKeyToggle = document.getElementById('btn-key-toggle');
  const iconKeyEye = document.getElementById('icon-key-eye');
  // Key visibility toggle moved to bindAllEvents()

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function getLocalSettings() {
    try {
      return JSON.parse(localStorage.getItem('omnikb_settings') || '{}');
    } catch {
      return {};
    }
  }

  function normalizeHexColor(value, fallback = CHAT_TEMPLATES[DEFAULT_TEMPLATE].color) {
    const raw = String(value || '').trim();
    if (/^#[0-9a-f]{6}$/i.test(raw)) return raw;
    if (/^#[0-9a-f]{3}$/i.test(raw)) {
      return `#${raw.slice(1).split('').map(char => char + char).join('')}`;
    }
    return fallback;
  }

  function hexToRgb(hex) {
    const normalized = normalizeHexColor(hex).slice(1);
    return {
      r: Number.parseInt(normalized.slice(0, 2), 16),
      g: Number.parseInt(normalized.slice(2, 4), 16),
      b: Number.parseInt(normalized.slice(4, 6), 16),
    };
  }

  function mixRgb(base, target, ratio) {
    return {
      r: Math.round(base.r * (1 - ratio) + target.r * ratio),
      g: Math.round(base.g * (1 - ratio) + target.g * ratio),
      b: Math.round(base.b * (1 - ratio) + target.b * ratio),
    };
  }

  function luminance(rgb) {
    const transform = value => {
      const channel = value / 255;
      return channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
    };
    return 0.2126 * transform(rgb.r) + 0.7152 * transform(rgb.g) + 0.0722 * transform(rgb.b);
  }

  function deriveBrandTokens(hex) {
    const rgb = hexToRgb(hex);
    const solidRgb = luminance(rgb) > 0.72 ? mixRgb(rgb, { r: 43, g: 70, b: 120 }, 0.62) : rgb;
    return {
      solid: `rgb(${solidRgb.r}, ${solidRgb.g}, ${solidRgb.b})`,
      bg: `rgba(${solidRgb.r}, ${solidRgb.g}, ${solidRgb.b}, 0.14)`,
      border: `rgba(${solidRgb.r}, ${solidRgb.g}, ${solidRgb.b}, 0.28)`,
      glow: `rgba(${solidRgb.r}, ${solidRgb.g}, ${solidRgb.b}, 0.18)`,
    };
  }

  function applyBrandTokens(target, hex) {
    const tokens = deriveBrandTokens(hex);
    target.style.setProperty('--accent', tokens.solid);
    target.style.setProperty('--accent-bg', tokens.bg);
    target.style.setProperty('--accent-bd', tokens.border);
    target.style.setProperty('--kbchat-brand-solid', tokens.solid);
    target.style.setProperty('--kbchat-brand-bg', tokens.bg);
    target.style.setProperty('--kbchat-brand-border', tokens.border);
    target.style.setProperty('--kbchat-brand-glow', tokens.glow);
  }

  function sanitizeCustomCss(css) {
    return css
      ? String(css).replace(/@import\b/gi, '/* blocked */').replace(/url\s*\(/gi, 'url(/* blocked */')
      : '';
  }

  function getTemplateMeta(key) {
    return CHAT_TEMPLATES[key] || CHAT_TEMPLATES[DEFAULT_TEMPLATE];
  }

  function guessTemplateFromText(text) {
    if (/(客服|支持|售后|工单|帮助|faq|FAQ|support)/i.test(text)) return 'support';
    if (/(讲解|课程|教学|教程|导览|故事|解读|说明|讲师|讲稿)/i.test(text)) return 'guide';
    return DEFAULT_TEMPLATE;
  }

  function normalizeUiConfig(ui = {}, context = {}) {
    const seed = [context.name, context.description, context.system_prompt, ui.welcome].filter(Boolean).join(' ');
    const template = CHAT_TEMPLATES[ui.template] ? ui.template : guessTemplateFromText(seed);
    const preset = getTemplateMeta(template);
    const hints = Array.isArray(ui.hints) ? ui.hints : preset.hints;
    return {
      template,
      title: String(ui.title || ''),
      subtitle: String(ui.subtitle || ''),
      welcome: String(ui.welcome || preset.welcome),
      placeholder: String(ui.placeholder || preset.placeholder),
      disclaimer: String(ui.disclaimer || preset.disclaimer),
      hints,
      color: normalizeHexColor(ui.color || preset.color, preset.color),
      css: String(ui.css || ''),
    };
  }

  function getApiBase() {
    // Allow overriding via ?api= URL param for standalone deployment
    const param = params.get('api');
    if (param) return param.replace(/\/+$/, '');
    if (window.location.protocol === 'file:') {
      return String(getLocalSettings().api_base || '').replace(/\/+$/, '');
    }
    return window.location.origin;
  }

  // ── Load scenario info & apply UI config ───────────────────────

  async function loadScenario() {
    if (previewMode) {
      applyPreviewScenario('');
      return;
    }

    try {
      const res = await fetch(`${getApiBase()}/kb-api/${scenarioId}`);
      if (!res.ok) throw new Error('Scenario not found');
      const sc = await res.json();
      scenarioMeta = sc;
      applyUiConfig(sc);
    } catch (e) {
      previewMode = true;
      applyPreviewScenario('');
    }
  }

  function applyPreviewScenario(subtitle) {
    scenarioMeta = {
      ...PREVIEW_SCENARIO,
      ui_config: {
        ...PREVIEW_SCENARIO.ui_config,
        subtitle,
      },
    };
    applyUiConfig(scenarioMeta);
  }

  function applyUiConfig(sc) {
    const ui = normalizeUiConfig(sc.ui_config || {}, sc);
    const preset = getTemplateMeta(ui.template);
    const title = ui.title || sc.name || '知识库问答';
    const subtitle = ui.subtitle || sc.description || preset.subtitle;
    const shell = document.body;
    const hintsEl = document.getElementById('welcome-hints');

    document.title = title;
    document.getElementById('scenario-title').textContent = title;
    document.getElementById('scenario-desc').textContent = subtitle;
    document.getElementById('scenario-template').textContent = preset.badge;
    document.getElementById('welcome-kicker').textContent = preset.badge;
    document.getElementById('welcome-heading').textContent = preset.heading;
    document.getElementById('welcome-text').textContent = ui.welcome;
    inputEl.placeholder = ui.placeholder;
    chatDisclaimer.textContent = ui.disclaimer;
    if (hintsEl) {
      if (ui.hints && ui.hints.length) {
        hintsEl.innerHTML = ui.hints.map(hint => `<span class="kbchat-hint-pill">${esc(hint)}</span>`).join('');
        hintsEl.style.display = '';
      } else {
        hintsEl.innerHTML = '';
        hintsEl.style.display = 'none';
      }
    }

    shell.dataset.kbchatTemplate = ui.template;
    shell.dataset.kbchatTone = preset.tone || 'light';
    applyBrandTokens(shell, ui.color);

    document.getElementById('custom-css').textContent = sanitizeCustomCss(ui.css);

    // ── Apply agent-written full page customizations ──
    if (sc && sc.ui_config) {
      const uiCfg = sc.ui_config;
      if (uiCfg.page_html) {
        document.body.innerHTML = uiCfg.page_html;
        rebindDomRefs();
        bindAllEvents();
      }
      if (uiCfg.page_css) {
        document.getElementById('custom-css').textContent = sanitizeCustomCss(uiCfg.page_css);
      }
      if (uiCfg.page_js) {
        try { new Function(uiCfg.page_js)(); } catch(e) {}
      }
    }
  }

  function rebindDomRefs() {
    messagesEl = document.getElementById('chat-messages');
    inputEl = document.getElementById('chat-input');
    welcomeEl = document.getElementById('welcome-message');
    apiKeyInput = document.getElementById('api-key-input');
    sendBtn = document.getElementById('btn-send');
    chatDisclaimer = document.getElementById('chat-disclaimer');
  }

  function bindAllEvents() {
    const btnSettings = document.getElementById('btn-show-key-modal');
    const btnCloseModal = document.getElementById('btn-close-key-modal');
    const keyModal = document.getElementById('key-modal-backdrop');
    const btnSaveKey = document.getElementById('btn-save-key');

    if (btnSettings) btnSettings.addEventListener('click', () => keyModal.classList.remove('hidden'));
    if (btnCloseModal) btnCloseModal.addEventListener('click', () => keyModal.classList.add('hidden'));
    keyModal.addEventListener('click', e => { if (e.target === keyModal) keyModal.classList.add('hidden'); });
    btnSaveKey.addEventListener('click', () => {
      localStorage.setItem(storageKey, apiKeyInput.value.trim());
      if (btnSettings) btnSettings.classList.toggle('has-key', !!apiKeyInput.value.trim());
      keyModal.classList.add('hidden');
      toast('API 密钥已保存', 'success');
    });

    // Key visibility toggle
    const btnKeyToggle = document.getElementById('btn-key-toggle');
    const iconKeyEye = document.getElementById('icon-key-eye');
    if (btnKeyToggle && iconKeyEye) {
      btnKeyToggle.addEventListener('click', () => {
        const isVisible = apiKeyInput.type === 'text';
        apiKeyInput.type = isVisible ? 'password' : 'text';
        if (isVisible) {
          iconKeyEye.innerHTML = '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>';
        } else {
          iconKeyEye.innerHTML = '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/>';
        }
      });
    }

    // Send / input / clear
    sendBtn.addEventListener('click', sendMessage);
    inputEl.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });
    inputEl.addEventListener('input', resizeComposer);
    document.getElementById('btn-clear-chat').addEventListener('click', resetConversation);
  }

  bindAllEvents();
  loadScenario();

  // ── Markdown rendering ─────────────────────────────────────────

  // Configure marked + highlight.js for safe, real-time rendering
  if (typeof marked !== 'undefined') {
    marked.setOptions({
      breaks: true,
      gfm: true,
      silent: true, // ignore errors, keep rendering
    });
    if (typeof hljs !== 'undefined') {
      marked.setOptions({
        highlight: function(code, lang) {
          const language = hljs.getLanguage(lang) ? lang : 'plaintext';
          return hljs.highlight(code, { language }).value;
        },
        langPrefix: 'hljs language-',
      });
    }
  }

  function renderMarkdown(text) {
    if (!text) return '';
    if (typeof marked !== 'undefined') {
      try {
        return marked.parse(text);
      } catch {
        // Fall through to plain-text escape
      }
    }
    return esc(text).replace(/\n/g, '<br>');
  }

  // Incremental render: compare raw text lengths, re-render only on change
  function renderToElement(el, rawText, lastLength) {
    if (rawText.length === lastLength) return lastLength;
    el.innerHTML = renderMarkdown(rawText);
    return rawText.length;
  }

  function resizeComposer() {
    inputEl.style.height = '0px';
    inputEl.style.height = `${Math.min(inputEl.scrollHeight, 220)}px`;
  }

  function resetConversation() {
    chatHistory = [];
    messagesEl.querySelectorAll('.kbchat-message-row').forEach(node => node.remove());
    welcomeEl.classList.remove('hidden');
    messagesEl.scrollTop = 0;
  }

  // ── Message rendering ──────────────────────────────────────────

  function addMessage(role, content = '', id = null) {
    const isUser = role === 'user';
    const isThinking = role === 'thinking';
    const msgId = id || makeMessageId(role);
    const el = document.createElement('div');
    el.id = msgId;
    if (isThinking) {
      el.className = 'think-row';
      el.innerHTML = content;
    } else {
      el.className = `kbchat-message-row ${isUser ? 'is-user' : 'is-assistant'}`;
      el.innerHTML = `
        <div class="kbchat-message-bubble ${isUser ? 'bubble-user' : 'bubble-ai'}" id="${msgId}-content">
          ${isUser ? esc(content) : ''}
        </div>
      `;
    }
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

  // ── Send message ───────────────────────────────────────────────

  // Send/input/clear listeners moved to bindAllEvents()

  async function sendMessage() {
    if (isStreaming) return;
    const text = inputEl.value.trim();
    if (!text) return;

    const apiKey = apiKeyInput.value.trim();
    if (!previewMode && !apiKey) {
      toast('请先输入 API 密钥', 'warning');
      return;
    }

    inputEl.value = '';
    resizeComposer();
    welcomeEl.classList.add('hidden');

    chatHistory.push({ role: 'user', content: text });
    addMessage('user', text);

    // Don't create AI bubble yet — wait for first token
    let aiMsgId = null;
    let contentEl = null;

    isStreaming = true;
    sendBtn.disabled = true;

    // Show thinking card immediately — provides visual feedback while waiting
    ensureThinkingCard();
    if (thinkMsgId) {
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    if (previewMode) {
      // Still need a bubble for preview mode too
      aiMsgId = addMessage('assistant');
      contentEl = document.getElementById(`${aiMsgId}-content`);
      contentEl.classList.add('typing-cursor');
      runPreviewAnswer(text, contentEl);
      return;
    }

    let fullText = '';
    let firstToken = true;
    let thinkMsgId = null;
    let thinkPages = [];

    function ensureThinkingCard() {
      if (thinkMsgId) return;
      thinkMsgId = addMessage('thinking', '');
      const thinkDiv = document.getElementById(thinkMsgId);
      if (thinkDiv) {
        thinkDiv.innerHTML = '<div class="think-card"><div class="think-header"><span class="think-spinner"></span><span class="think-title">正在检索知识库...</span></div><div class="think-pages"></div></div>';
      }
    }

    function addThinkingPage(pages) {
      if (!pages) return;
      const thinkDiv = document.getElementById(thinkMsgId);
      if (!thinkDiv) return;
      const pagesEl = thinkDiv.querySelector('.think-pages');
      if (!pagesEl) return;
      const items = pages.filter(p => !thinkPages.includes(p));
      thinkPages.push(...items);
      for (const p of items) {
        const tag = document.createElement('span');
        tag.className = 'think-page-tag';
        tag.innerHTML = icon.document({size:14}) + ' ' + p;
        pagesEl.appendChild(tag);
      }
      thinkDiv.querySelector('.think-title').textContent = `已检索 ${thinkPages.length} 个页面`;
    }

    function finishThinking() {
      const thinkDiv = document.getElementById(thinkMsgId);
      if (!thinkDiv) return;
      thinkDiv.querySelector('.think-spinner').classList.replace('think-spinner', 'think-check');
      thinkDiv.querySelector('.think-check').innerHTML = icon.check({size:14});
      thinkDiv.querySelector('.think-title').textContent = `已检索 ${thinkPages.length} 个页面`;
      // 折叠思考卡片
      thinkDiv.classList.add('think-done');
      setTimeout(() => {
        thinkDiv.querySelector('.think-card').style.maxHeight = '40px';
      }, 1500);
    }

    function toggleThinking(e) {
      const card = e.currentTarget.querySelector('.think-card');
      if (!card) return;
      card.style.maxHeight = card.style.maxHeight === '40px' ? card.scrollHeight + 'px' : '40px';
    }

    function ensureAiBubble() {
      if (!aiMsgId) {
        aiMsgId = addMessage('assistant');
        contentEl = document.getElementById(`${aiMsgId}-content`);
        if (contentEl) contentEl.classList.add('typing-cursor');
      }
    }

    function scheduleStreamRender() {
      // Direct render — no debounce for true streaming feel
      if (!contentEl) return;
      contentEl.innerHTML = renderMarkdown(fullText);
      if (typeof hljs !== 'undefined') {
        contentEl.querySelectorAll('pre code:not(.hljs)').forEach(b => hljs.highlightElement(b));
      }
      _addCopyButtons(contentEl);
      const atBottom = messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 80;
      if (atBottom) messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    try {
      const res = await fetch(`${getApiBase()}/kb-api/${scenarioId}/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${apiKey}`,
        },
        body: JSON.stringify({
          messages: chatHistory,
          top_k: 5,
          agentic: true,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `HTTP ${res.status}`);
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
              const thinkDiv = document.getElementById(thinkMsgId);
              if (thinkDiv) {
                let body = thinkDiv.querySelector('.think-body');
                if (!body) {
                  body = document.createElement('div');
                  body.className = 'think-body';
                  thinkDiv.querySelector('.think-card').appendChild(body);
                }
                body.textContent += evt.content;
                thinkDiv.querySelector('.think-title').textContent = '正在思考...';
                messagesEl.scrollTop = messagesEl.scrollHeight;
              }
            } else if (evt.type === 'tool_call') {
              ensureThinkingCard();
              const pageName = evt.args?.page_id || evt.name || '';
              if (pageName) addThinkingPage([pageName.replace(/_/g, ' ')]);
            } else if (evt.type === 'tool_result') {
              // tool completed
            } else if (evt.type === 'token') {
              if (firstToken) {
                firstToken = false;
                if (thinkMsgId) finishThinking();
                ensureAiBubble();
              }
              fullText += evt.content;
              scheduleStreamRender();
            } else if (evt.type === 'citations') {
              ensureAiBubble();
              showCitations(evt.citations, contentEl);
            }
          } catch {}
        }
      }

      if (contentEl) {
        contentEl.classList.remove('typing-cursor');
        contentEl.innerHTML = renderMarkdown(fullText);
        if (typeof hljs !== 'undefined') {
          contentEl.querySelectorAll('pre code:not(.hljs)').forEach(b => hljs.highlightElement(b));
        }
      }
      chatHistory.push({ role: 'assistant', content: fullText });
      addSaveToWikiButton(aiMsgId, fullText);

    } catch (e) {
      if (!contentEl) ensureAiBubble();
      if (contentEl) {
        contentEl.classList.remove('typing-cursor');
        contentEl.innerHTML = `<span style="color:var(--c-err-t);">Error: ${esc(e.message)}</span>`;
      }
    } finally {
      isStreaming = false;
      sendBtn.disabled = false;
    }
  }

  function showCitations(citations, targetEl) {
    if (!citations || !citations.length) return;
    if (window.OmnikbCitations) {
      OmnikbCitations.clear(targetEl);
      OmnikbCitations.render(targetEl, citations);
    }
  }

  function addSaveToWikiButton(msgId, fullText) {
    const msgEl = document.getElementById(msgId);
    if (!msgEl) return;
    const bubble = msgEl.querySelector('.bubble-ai, .kbchat-message-bubble');
    if (!bubble) return;
    // Avoid duplicate buttons
    if (bubble.querySelector('.save-to-wiki-btn')) return;
    const btn = document.createElement('button');
    btn.className = 'save-to-wiki-btn';
    btn.innerHTML = icon.save({size:14}) + ' 保存';
    btn.title = '保存到 Wiki';
    btn.onclick = async () => {
      const title = prompt('Wiki 页面标题:', '');
      if (!title) return;
      try {
        const r = await fetch((typeof getApiBase === 'function' ? getApiBase() : '') + '/wiki/save-chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title, content: fullText }),
        });
        if (r.ok) {
          const data = await r.json();
          if (typeof toast === 'function') toast('已保存到 Wiki: ' + data.id, 'success');
        } else {
          const err = await r.json().catch(() => ({}));
          if (typeof toast === 'function') toast('保存失败: ' + (err.detail || r.statusText), 'error');
        }
      } catch (e) {
        if (typeof toast === 'function') toast('保存失败: ' + e.message, 'error');
      }
    };
    bubble.appendChild(btn);
  }

  function runPreviewAnswer(text, contentEl) {
    const lines = [
      `关于“${text}”，我会先给你一版简洁回答。`,
      '先抓主线，确认这份资料主要在讲什么、解决什么问题。',
      '再把关键概念、步骤和关系串起来，避免答案只停在零散片段上。',
      '如果你继续追问，我可以再把它压缩成摘要、清单或新人入门版。',
    ];

    let fullText = '';
    let index = 0;

    const step = () => {
      if (index < lines.length) {
        _addCopyButtons(contentEl);
        fullText += `${index ? '\n\n' : ''}${lines[index]}`;
        contentEl.innerHTML = renderMarkdown(fullText);
        messagesEl.scrollTop = messagesEl.scrollHeight;
        index += 1;
        window.setTimeout(step, 150);
        return;
      }

      contentEl.classList.remove('typing-cursor');
      chatHistory.push({ role: 'assistant', content: fullText });
      isStreaming = false;
      sendBtn.disabled = false;
    };

    step();
  }

  // ── Dark mode highlight.js theme swap ─────────────────────────

  function syncHljsTheme() {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    document.querySelectorAll('link[id^="hljs-theme"]').forEach(l => {
      l.disabled = l.id.includes('light') ? isDark : !isDark;
    });
  }
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', syncHljsTheme);
  window.addEventListener('omni-theme-change', syncHljsTheme);
  syncHljsTheme();

  // Focus input on load
  resizeComposer();
  inputEl.focus();

  function _addCopyButtons(el) {
    el.querySelectorAll('pre').forEach(pre => {
      if (pre.querySelector('.kbchat-copy-btn')) return;
      const wrapper = document.createElement('div');
      wrapper.className = 'kbchat-code-block';
      pre.parentNode.insertBefore(wrapper, pre);
      wrapper.appendChild(pre);
      const btn = document.createElement('button');
      btn.className = 'kbchat-copy-btn';
      btn.textContent = '复制';
      btn.onclick = () => {
        const code = pre.textContent || '';
        navigator.clipboard.writeText(code).then(() => {
          btn.textContent = '已复制!';
          setTimeout(() => btn.textContent = '复制', 2000);
        });
      };
      wrapper.appendChild(btn);
    });
  }
})();