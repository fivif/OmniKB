/* ── Scenario API Integration Page ─────────────────────────── */

(function initScenarioApiPage() {
  const params = new URLSearchParams(window.location.search);
  const scenarioId = params.get('scenario');
  const DEFAULT_TEMPLATE = 'assistant';
  const TEMPLATE_META = {
    assistant: {
      badge: 'Knowledge Q&A',
      subtitle: '通用资料库问答入口，适合品牌知识库和内部文档检索。',
      color: '#5b8cff',
    },
    guide: {
      badge: 'Guided Explainer',
      subtitle: '适合课程、故事、文档讲解和需要分步骤说明的场景。',
      color: '#f07c52',
    },
    support: {
      badge: 'Support Desk',
      subtitle: '适合帮助中心、FAQ、售后问答与产品支持入口。',
      color: '#1bb98a',
    },
  };

  const statusEl = document.getElementById('sapi-status');
  const titleEl = document.getElementById('sapi-title');
  const descEl = document.getElementById('sapi-description');
  const leadEl = document.getElementById('sapi-lead');
  const templateEl = document.getElementById('sapi-template');
  const idEl = document.getElementById('sapi-id');
  const baseEl = document.getElementById('sapi-base');
  const metaUrlEl = document.getElementById('sapi-meta-url');
  const chatUrlEl = document.getElementById('sapi-chat-url');
  const publicUrlEl = document.getElementById('sapi-public-url');
  const openChatEl = document.getElementById('sapi-open-chat');

  function getLocalSettings() {
    try {
      return JSON.parse(localStorage.getItem('omnikb_settings') || '{}');
    } catch {
      return {};
    }
  }

  function getApiBase() {
    const param = params.get('api');
    if (param) return param.replace(/\/+$/, '');
    if (window.location.protocol === 'file:') {
      return String(getLocalSettings().api_base || '').replace(/\/+$/, '');
    }
    return window.location.origin;
  }

  function getScenarioPublicUrl(id) {
    const url = new URL(`kb-chat.html?scenario=${encodeURIComponent(id)}`, window.location.href);
    if (url.protocol === 'file:') {
      url.searchParams.set('api', getApiBase());
    }
    return url.href;
  }

  function getScenarioApiUrls(id) {
    const encodedId = encodeURIComponent(id);
    const base = getApiBase();
    return {
      base,
      metaUrl: `${base}/kb-api/${encodedId}`,
      chatUrl: `${base}/kb-api/${encodedId}/chat`,
      publicUrl: getScenarioPublicUrl(id),
    };
  }

  function normalizeHexColor(value, fallback = TEMPLATE_META[DEFAULT_TEMPLATE].color) {
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

  function applyBrandTokens(hex) {
    const rgb = hexToRgb(hex);
    const solidRgb = luminance(rgb) > 0.72 ? mixRgb(rgb, { r: 43, g: 70, b: 120 }, 0.62) : rgb;
    document.body.style.setProperty('--accent', `rgb(${solidRgb.r}, ${solidRgb.g}, ${solidRgb.b})`);
    document.body.style.setProperty('--accent-bg', `rgba(${solidRgb.r}, ${solidRgb.g}, ${solidRgb.b}, 0.12)`);
    document.body.style.setProperty('--accent-bd', `rgba(${solidRgb.r}, ${solidRgb.g}, ${solidRgb.b}, 0.24)`);
    document.body.style.setProperty('--sapi-accent-strong', `rgba(${solidRgb.r}, ${solidRgb.g}, ${solidRgb.b}, 0.2)`);
  }

  function getTemplateMeta(key) {
    return TEMPLATE_META[key] || TEMPLATE_META[DEFAULT_TEMPLATE];
  }

  function guessTemplateFromText(text) {
    if (/(客服|支持|售后|工单|帮助|faq|FAQ|support)/i.test(text)) return 'support';
    if (/(讲解|课程|教学|教程|导览|故事|解读|说明|讲师|讲稿)/i.test(text)) return 'guide';
    return DEFAULT_TEMPLATE;
  }

  function normalizeUiConfig(ui, context) {
    const seed = [context.name, context.description, ui?.welcome].filter(Boolean).join(' ');
    const template = TEMPLATE_META[ui?.template] ? ui.template : guessTemplateFromText(seed);
    const preset = getTemplateMeta(template);
    return {
      template,
      title: String(ui?.title || ''),
      subtitle: String(ui?.subtitle || preset.subtitle),
      color: normalizeHexColor(ui?.color || preset.color, preset.color),
    };
  }

  function setStatus(message, tone) {
    statusEl.hidden = false;
    statusEl.textContent = message;
    statusEl.dataset.tone = tone || 'info';
  }

  function clearStatus() {
    statusEl.hidden = true;
    statusEl.textContent = '';
    statusEl.dataset.tone = 'info';
  }

  function buildMetaCurlExample(metaUrl) {
    return `curl '${metaUrl}'`;
  }

  function buildChatCurlExample(chatUrl) {
    const payload = JSON.stringify({
      messages: [
        { role: 'user', content: '请概述这个场景适合回答哪些问题？' },
      ],
      top_k: 5,
    }, null, 2);

    return [
      'curl -N \\',
      `  -X POST '${chatUrl}' \\`,
      "  -H 'Content-Type: application/json' \\",
      "  -H 'Authorization: Bearer YOUR_SCENARIO_API_KEY' \\",
      `  -d '${payload}'`,
    ].join('\n');
  }

  function buildFetchExample(chatUrl) {
    return [
      `const response = await fetch('${chatUrl}', {`,
      "  method: 'POST',",
      '  headers: {',
      "    'Content-Type': 'application/json',",
      "    'Authorization': 'Bearer YOUR_SCENARIO_API_KEY',",
      '  },',
      '  body: JSON.stringify({',
      '    messages: [',
      "      { role: 'user', content: '请概述这个场景适合回答哪些问题？' },",
      '    ],',
      '    top_k: 5,',
      '  }),',
      '});',
      '',
      'if (!response.ok || !response.body) {',
      '  throw new Error(await response.text());',
      '}',
      '',
      'const reader = response.body.getReader();',
      'const decoder = new TextDecoder();',
      "let buffer = '';",
      '',
      'while (true) {',
      '  const { value, done } = await reader.read();',
      '  if (done) break;',
      '  buffer += decoder.decode(value, { stream: true });',
      "  const frames = buffer.split('\\n\\n');",
      "  buffer = frames.pop() || '';",
      '',
      '  for (const frame of frames) {',
      "    if (!frame.startsWith('data: ')) continue;",
      '    const payload = frame.slice(6);',
      "    if (payload === '[DONE]') break;",
      '    const event = JSON.parse(payload);',
      "    if (event.type === 'token') console.log(event.content);",
      "    if (event.type === 'citations') console.log(event.citations);",
      '  }',
      '}',
    ].join('\n');
  }

  function buildStreamExample() {
    return [
      'data: {"type":"token","content":"这个场景主要回答..."}',
      '',
      'data: {"type":"citations","citations":[{"index":1,"source":"doc.pdf","score":0.9321}]}',
      '',
      'data: [DONE]',
    ].join('\n');
  }

  function applyExamples(urls) {
    document.getElementById('sapi-meta-curl').textContent = buildMetaCurlExample(urls.metaUrl);
    document.getElementById('sapi-chat-curl').textContent = buildChatCurlExample(urls.chatUrl);
    document.getElementById('sapi-fetch-example').textContent = buildFetchExample(urls.chatUrl);
    document.getElementById('sapi-stream-example').textContent = buildStreamExample();
  }

  function applyScenario(sc) {
    const ui = normalizeUiConfig(sc.ui_config || {}, sc);
    const preset = getTemplateMeta(ui.template);
    const title = ui.title || sc.name || '未命名场景';
    const description = ui.subtitle || sc.description || preset.subtitle;
    const urls = getScenarioApiUrls(sc.id || scenarioId);

    document.title = `${title} · 场景 API 接入`;
    leadEl.textContent = '这页会跟随当前场景生成实际可用的接口地址和流式请求示例。';
    templateEl.textContent = preset.badge;
    titleEl.textContent = title;
    descEl.textContent = description;
    idEl.textContent = sc.id || scenarioId;
    baseEl.textContent = urls.base;
    metaUrlEl.textContent = urls.metaUrl;
    chatUrlEl.textContent = urls.chatUrl;
    publicUrlEl.textContent = urls.publicUrl;
    publicUrlEl.href = urls.publicUrl;
    openChatEl.href = urls.publicUrl;
    applyExamples(urls);
    applyBrandTokens(ui.color);
    clearStatus();
  }

  async function loadScenario() {
    if (!scenarioId) {
      document.title = '场景 API 接入';
      titleEl.textContent = '缺少场景 ID';
      descEl.textContent = '请在 URL 上带上 ?scenario=场景ID。';
      leadEl.textContent = '例如：scenario-api.html?scenario=YOUR_SCENARIO_ID';
      setStatus('当前 URL 缺少 scenario 参数，无法生成接入信息。', 'error');
      return;
    }

    const urls = getScenarioApiUrls(scenarioId);
    idEl.textContent = scenarioId;
    baseEl.textContent = urls.base;
    metaUrlEl.textContent = urls.metaUrl;
    chatUrlEl.textContent = urls.chatUrl;
    publicUrlEl.textContent = urls.publicUrl;
    publicUrlEl.href = urls.publicUrl;
    openChatEl.href = urls.publicUrl;
    applyExamples(urls);

    try {
      const res = await fetch(urls.metaUrl);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const sc = await res.json();
      applyScenario(sc);
    } catch (error) {
      document.title = '场景 API 接入';
      titleEl.textContent = '场景加载失败';
      descEl.textContent = '请检查场景 ID 或后端地址是否正确。';
      leadEl.textContent = '如果你是本地打开 HTML，可以通过 ?api=http://localhost:6886 指定后端地址。';
      setStatus(`读取场景配置失败：${error.message}`, 'error');
    }
  }

  loadScenario();
})();