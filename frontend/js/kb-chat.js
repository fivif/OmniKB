/* ── Public KB Chat (scenario Q&A page) ─────────────────────── */

(function initKbChat() {
  // Parse scenario ID from URL
  const params = new URLSearchParams(window.location.search);
  const scenarioId = params.get('scenario');
  const previewRequested = params.get('demo') === '1' || !scenarioId;
  const DEFAULT_TEMPLATE = 'assistant';
  const CHAT_TEMPLATES = {
    assistant: {
      badge: 'Knowledge Q&A',
      heading: '直接提问，按资料回答',
      subtitle: '基于知识库的对话式助手',
      welcome: '你好，我会优先基于当前知识库中的内容来回答你的问题。',
      placeholder: '输入你的问题，开始检索与问答…',
      disclaimer: '回答由 AI 基于资料生成，请对关键信息再次核验。',
      color: '#5b8cff',
      tone: 'light',
      hints: ['基于资料回答', '支持长文本问答', '保留引用链路'],
    },
    guide: {
      badge: 'Guided Explainer',
      heading: '想先从哪一段开始？',
      subtitle: '适合课程、故事与讲解型场景',
      welcome: '欢迎来到这里，我会结合资料内容为你梳理重点、背景和细节。',
      placeholder: '想先了解哪一部分内容？',
      disclaimer: '讲解内容会结合资料总结生成，引用与细节请结合原文复核。',
      color: '#f07c52',
      tone: 'light',
      hints: ['适合课程讲解', '先梳理脉络再深入细节', '适合连续追问'],
    },
    support: {
      badge: 'Support Desk',
      heading: '把问题告诉我，我来排查',
      subtitle: '面向客户支持与产品答疑',
      welcome: '你好，我会优先基于知识库里的流程、FAQ 与说明文档来回答你。',
      placeholder: '描述你的问题、报错或使用场景…',
      disclaimer: '客服答案可能随版本变化，请以正式公告和产品后台为准。',
      color: '#1bb98a',
      tone: 'dark',
      hints: ['FAQ 与流程优先', '适合支持与排障', '关键步骤可追溯'],
    },
  };

  const PREVIEW_SCENARIO = {
    name: '知识资料问答',
    description: '离线预览模式',
    ui_config: {
      template: 'assistant',
      title: '知识资料问答',
      subtitle: '离线预览模式',
      welcome: '你好，我会优先基于当前知识库中的内容来回答你的问题。',
      placeholder: '输入你的问题，开始检索与问答…',
      disclaimer: '回答由 AI 基于资料生成，请对关键信息再次核验。',
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

  const messagesEl = document.getElementById('chat-messages');
  const inputEl = document.getElementById('chat-input');
  const welcomeEl = document.getElementById('welcome-message');
  const apiKeyInput = document.getElementById('api-key-input');
  const sendBtn = document.getElementById('btn-send');
  const chatDisclaimer = document.getElementById('chat-disclaimer');

  let chatHistory = [];
  let isStreaming = false;
  let scenarioMeta = null;
  let messageSeq = 0;
  let previewMode = previewRequested;

  // Persist API key
  const storageKey = `omnikb_kb_key_${scenarioId || 'preview'}`;
  apiKeyInput.value = localStorage.getItem(storageKey) || '';
  apiKeyInput.addEventListener('change', () => {
    localStorage.setItem(storageKey, apiKeyInput.value.trim());
  });

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
    return {
      template,
      title: String(ui.title || ''),
      subtitle: String(ui.subtitle || ''),
      welcome: String(ui.welcome || preset.welcome),
      placeholder: String(ui.placeholder || preset.placeholder),
      disclaimer: String(ui.disclaimer || preset.disclaimer),
      color: normalizeHexColor(ui.color || preset.color, preset.color),
      css: String(ui.css || ''),
    };
  }

  function getApiBase() {
    // Allow overriding via ?api= URL param for standalone deployment
    const param = params.get('api');
    if (param) return param.replace(/\/+$/, '');
    if (window.location.protocol === 'file:') {
      return String(getLocalSettings().api_base || 'http://localhost:8000').replace(/\/+$/, '');
    }
    return window.location.origin;
  }

  // ── Load scenario info & apply UI config ───────────────────────

  async function loadScenario() {
    if (previewMode) {
      applyPreviewScenario('离线预览模式');
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
      applyPreviewScenario('当前后端不可达，已切换到离线预览模式');
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
      hintsEl.innerHTML = (preset.hints || []).map(hint => `<span class="kbchat-hint-pill">${esc(hint)}</span>`).join('');
    }

    shell.dataset.kbchatTemplate = ui.template;
    shell.dataset.kbchatTone = preset.tone || 'light';
    applyBrandTokens(shell, ui.color);

    document.getElementById('custom-css').textContent = sanitizeCustomCss(ui.css);
  }

  loadScenario();

  // ── Markdown rendering ─────────────────────────────────────────

  // Configure marked for safe, real-time rendering
  if (typeof marked !== 'undefined') {
    marked.setOptions({
      breaks: true,
      gfm: true,
      silent: true, // ignore errors, keep rendering
    });
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
    const msgId = id || makeMessageId(role);
    const el = document.createElement('div');
    el.id = msgId;
    el.className = `kbchat-message-row ${isUser ? 'is-user' : 'is-assistant'}`;
    el.innerHTML = `
      <div class="kbchat-message-author">${isUser ? '你' : 'AI 助手'}</div>
      <div class="kbchat-message-bubble ${isUser ? 'bubble-user' : 'bubble-ai'}" id="${msgId}-content">
        ${isUser ? esc(content) : ''}
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

  // ── Send message ───────────────────────────────────────────────

  document.getElementById('btn-send').addEventListener('click', sendMessage);
  inputEl.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  inputEl.addEventListener('input', resizeComposer);

  document.getElementById('btn-clear-chat').addEventListener('click', resetConversation);

  async function sendMessage() {
    if (isStreaming) return;
    const text = inputEl.value.trim();
    if (!text) return;

    const apiKey = apiKeyInput.value.trim();
    if (!previewMode && !apiKey) {
      alert('请先输入 API 密钥');
      return;
    }

    inputEl.value = '';
    resizeComposer();
    welcomeEl.classList.add('hidden');

    chatHistory.push({ role: 'user', content: text });
    addMessage('user', text);

    const aiMsgId = addMessage('assistant');
    const contentEl = document.getElementById(`${aiMsgId}-content`);
    contentEl.classList.add('typing-cursor');

    isStreaming = true;
    sendBtn.disabled = true;

    if (previewMode) {
      runPreviewAnswer(text, contentEl);
      return;
    }

    let fullText = '';
    let renderPending = false;
    let lastRenderedLen = 0;
    function scheduleRender() {
      if (renderPending) return;
      renderPending = true;
      requestAnimationFrame(() => {
        renderPending = false;
        if (fullText.length !== lastRenderedLen) {
          lastRenderedLen = renderToElement(contentEl, fullText, lastRenderedLen);
          const atBottom = messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 80;
          if (atBottom) messagesEl.scrollTop = messagesEl.scrollHeight;
        }
      });
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
            if (evt.type === 'token') {
              fullText += evt.content;
              scheduleRender();
            } else if (evt.type === 'citations') {
              showCitations(evt.citations, contentEl);
            }
          } catch {}
        }
      }

      if (renderPending) renderPending = false;
      contentEl.classList.remove('typing-cursor');
      contentEl.innerHTML = renderMarkdown(fullText);
      chatHistory.push({ role: 'assistant', content: fullText });

    } catch (e) {
      contentEl.classList.remove('typing-cursor');
      contentEl.innerHTML = `<span style="color:var(--c-err-t);">错误：${esc(e.message)}</span>`;
    } finally {
      isStreaming = false;
      sendBtn.disabled = false;
    }
  }

  function showCitations(citations, targetEl) {
    if (!citations || !citations.length) return;
    // Render citations inline below the answer
    const existing = targetEl.querySelector('.kbchat-citation-list');
    if (existing) existing.remove();
    const block = document.createElement('div');
    block.className = 'kbchat-citation-list';
    block.innerHTML = `
      <div class="kbchat-citation-divider"></div>
      <ol class="kbchat-citation-items">
        ${citations.map((c, i) => `
          <li value="${c.index || i + 1}">
            <span class="kbchat-citation-source">${esc(c.source || 'unknown')}</span>
            ${c.score ? `<span class="kbchat-citation-score">${c.score.toFixed(2)}</span>` : ''}
            <span class="kbchat-citation-text">${esc((c.content || '').substring(0, 200))}</span>
          </li>
        `).join('')}
      </ol>`;
    targetEl.appendChild(block);
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

  // Focus input on load
  resizeComposer();
  inputEl.focus();
})();