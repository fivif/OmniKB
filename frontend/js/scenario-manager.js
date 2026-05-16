/* ── Scenario Manager (KB Q&A 管理) ────────────────────────── */

(function initScenarioManager() {
  const panel = document.getElementById('tab-scenarios');

  let scenarios = [];
  let currentId = null;   // currently selected scenario ID
  let currentTab = 'info'; // info | chunks | keys
  let sourceCatalog = [];
  let sourceTags = [];
  let selectedScenarioSources = [];

  const SOURCE_TYPE_GROUPS = {
    web: { label: '网页', icon: '🌐', raw: ['url', 'html', 'htm'] },
    text: { label: '文本', icon: '✍️', raw: ['text', 'txt', 'md', 'markdown'] },
    document: { label: '文档', icon: '📚', raw: ['pdf', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'csv', 'json'] },
    media: { label: '媒体', icon: '🎞️', raw: ['mp3', 'wav', 'm4a', 'ogg', 'flac', 'mp4', 'mov', 'mkv', 'avi', 'webm'] },
    image: { label: '图片', icon: '🖼️', raw: ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'tif'] },
    other: { label: '其他', icon: '📁', raw: [] },
  };
  const SOURCE_TYPE_ORDER = ['web', 'text', 'document', 'media', 'image', 'other'];
  const SOURCE_TYPE_LOOKUP = Object.entries(SOURCE_TYPE_GROUPS).reduce((lookup, [key, value]) => {
    value.raw.forEach(rawType => {
      lookup[rawType] = key;
    });
    return lookup;
  }, {});

  const DEFAULT_TEMPLATE = 'assistant';
  const TEMPLATE_PRESETS = {
    assistant: {
      label: '知识问答',
      badge: 'Knowledge Q&A',
      summary: '通用资料库问答入口，适合品牌知识库和内部文档检索。',
      subtitle: '基于知识库的对话式助手',
      welcome: '你好，我会优先基于当前知识库中的内容来回答你的问题。',
      placeholder: '输入你的问题，开始检索与问答…',
      disclaimer: '回答由 AI 基于资料生成，请对关键信息再次核验。',
      color: '#5b8cff',
      tone: 'light',
      hints: ['基于资料回答', '支持长文本问答', '保留引用链路'],
    },
    guide: {
      label: '内容讲解',
      badge: 'Guided Explainer',
      summary: '适合课程、故事、文档讲解和需要分步骤说明的场景。',
      subtitle: '适合课程、故事与讲解型场景',
      welcome: '欢迎来到这里，我会结合资料内容为你梳理重点、背景和细节。',
      placeholder: '想先了解哪一部分内容？',
      disclaimer: '讲解内容会结合资料总结生成，引用与细节请结合原文复核。',
      color: '#f07c52',
      tone: 'light',
      hints: ['适合课程讲解', '先梳理脉络再深入细节', '适合连续追问'],
    },
    support: {
      label: '客服支持',
      badge: 'Support Desk',
      summary: '适合帮助中心、FAQ、售后问答与产品支持入口。',
      subtitle: '面向客户支持与产品答疑',
      welcome: '你好，我会优先基于知识库里的流程、FAQ 与说明文档来回答你。',
      placeholder: '描述你的问题、报错或使用场景…',
      disclaimer: '客服答案可能随版本变化，请以正式公告和产品后台为准。',
      color: '#1bb98a',
      tone: 'dark',
      hints: ['FAQ 与流程优先', '适合支持与排障', '关键步骤可追溯'],
    },
  };
  const TEMPLATE_ORDER = ['assistant', 'guide', 'support'];

  function getStoredApiBase() {
    try {
      const saved = JSON.parse(localStorage.getItem('omnikb_settings') || '{}');
      return String(saved.api_base || 'http://localhost:6886').replace(/\/+$/, '');
    } catch {
      return 'http://localhost:6886';
    }
  }

  function normalizeHexColor(value, fallback = TEMPLATE_PRESETS[DEFAULT_TEMPLATE].color) {
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

  function getTemplateMeta(key) {
    return TEMPLATE_PRESETS[key] || TEMPLATE_PRESETS[DEFAULT_TEMPLATE];
  }

  function normalizeScenarioProvider(value) {
    return 'custom';
  }

  function normalizeSourceTypeKey(type) {
    const raw = String(type || '').trim().toLowerCase();
    return SOURCE_TYPE_LOOKUP[raw] || 'other';
  }

  function getSourceTypeMeta(type) {
    const raw = String(type || '').trim().toLowerCase();
    const key = normalizeSourceTypeKey(raw);
    return {
      key,
      label: SOURCE_TYPE_GROUPS[key].label,
      icon: SOURCE_TYPE_GROUPS[key].icon,
      raw,
    };
  }

  function getSourceSearchText(source) {
    return [
      source.name,
      source.url,
      source.type,
      ...(Array.isArray(source.tags) ? source.tags : []),
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase();
  }

  function guessTemplateFromText(text) {
    if (/(客服|支持|售后|工单|帮助|faq|FAQ|support)/i.test(text)) return 'support';
    if (/(讲解|课程|教学|教程|导览|故事|解读|说明|讲师|讲稿)/i.test(text)) return 'guide';
    return DEFAULT_TEMPLATE;
  }

  function normalizeUiConfig(ui = {}, context = {}) {
    const seed = [context.name, context.description, context.system_prompt, ui.welcome].filter(Boolean).join(' ');
    const template = TEMPLATE_PRESETS[ui.template] ? ui.template : guessTemplateFromText(seed);
    const preset = getTemplateMeta(template);
    const hints = Array.isArray(ui.hints) ? ui.hints : preset.hints;
    return {
      template,
      title: String(ui.title || ''),
      subtitle: String(ui.subtitle || preset.subtitle),
      welcome: String(ui.welcome || preset.welcome),
      placeholder: String(ui.placeholder || preset.placeholder),
      disclaimer: String(ui.disclaimer || preset.disclaimer),
      hints,
      color: normalizeHexColor(ui.color || preset.color, preset.color),
      css: String(ui.css || ''),
    };
  }

  // ── Render layout ──────────────────────────────────────────────

  panel.innerHTML = `
    <div class="sc-shell flex h-full">
      <!-- Left: scenario list -->
      <aside class="sc-sidebar w-56 lg:w-64 flex-shrink-0 border-r flex flex-col" style="background:var(--bg-muted);border-color:var(--bd);">
        <div class="sc-sidebar-head px-4 py-4 border-b flex items-center justify-between" style="border-color:var(--bd);">
          <div>
            <div class="sc-sidebar-kicker">Scene Library</div>
            <h2 class="text-sm font-semibold" style="color:var(--t1);">场景列表</h2>
          </div>
          <button id="btn-sc-new" class="w-6 h-6 flex items-center justify-center rounded-md transition-colors" style="background:var(--accent-bg);color:var(--accent);font-size:16px;line-height:1;" title="新建场景">+</button>
        </div>
        <div id="scenario-list" class="sc-list flex-1 overflow-y-auto p-3"></div>
      </aside>

      <!-- Right: detail -->
      <main class="sc-main flex-1 flex flex-col min-w-0 overflow-hidden">
        <div id="sc-detail-empty" class="sc-detail-empty flex-1 flex items-center justify-center">
          <div class="sc-detail-empty-copy text-center">
            <div class="sc-detail-empty-icon">⚙️</div>
            <p class="text-sm font-medium" style="color:var(--t2);">选择一个场景</p>
            <p class="text-xs mt-1" style="color:var(--t3);">从左侧列表选择或新建一个场景来开始配置</p>
          </div>
        </div>
        <div id="sc-detail" class="sc-detail flex-1 flex-col hidden">
          <!-- Tabs -->
          <div class="sc-detail-tabs flex items-center gap-0 px-6 pt-4 pb-0 border-b" style="border-color:var(--bd);">
            <button data-sctab="info" class="sc-tab-btn px-4 py-2 text-xs font-medium rounded-t-lg transition-colors" style="color:var(--accent);background:var(--accent-bg);">基本信息</button>
            <button data-sctab="chunks" class="sc-tab-btn px-4 py-2 text-xs font-medium rounded-t-lg transition-colors" style="color:var(--t2);">知识库</button>
            <button data-sctab="keys" class="sc-tab-btn px-4 py-2 text-xs font-medium rounded-t-lg transition-colors" style="color:var(--t2);">API 密钥</button>
            <button data-sctab="agent" class="sc-tab-btn px-4 py-2 text-xs font-medium rounded-t-lg transition-colors" style="color:var(--t2);">Agent 助手</button>
            <a id="sc-open-api-doc-tab" class="sc-tab-link px-4 py-2 text-xs font-medium rounded-t-lg transition-colors" href="#" target="_blank" rel="noreferrer">场景 API 接入</a>
            <div class="flex-1"></div>
            <button id="btn-sc-delete" class="text-xs px-3 py-1.5 rounded-lg transition-colors" style="color:var(--c-err);">删除场景</button>
          </div>

          <!-- Tab: info -->
          <div id="sc-panel-info" class="sc-panel-info flex-1 overflow-y-auto px-6 py-5">
            <div class="sc-config-grid">
              <div class="sc-config-stack">
                <section class="sc-card">
                  <div class="sc-card-head">
                    <div>
                      <div class="sc-card-title">场景定位</div>
                      <div class="sc-card-subtitle">定义这个公开问答入口的身份、介绍和系统提示词。</div>
                    </div>
                  </div>
                  <div class="sc-field-grid sc-field-grid--double">
                    <div class="sc-field-group">
                      <label class="form-label">场景名称</label>
                      <input id="sc-name" type="text" class="input" placeholder="例如：客服知识库" />
                    </div>
                    <div class="sc-field-group">
                      <label class="form-label">描述</label>
                      <input id="sc-desc" type="text" class="input" placeholder="简短描述此场景用途" />
                    </div>
                    <div class="sc-field-group sc-field-span-2">
                      <label class="form-label">系统提示词</label>
                      <textarea id="sc-prompt" rows="6" class="textarea sc-textarea" placeholder="为此场景自定义 AI 回复风格…"></textarea>
                    </div>
                  </div>
                </section>

                <section class="sc-card">
                  <div class="sc-card-head">
                    <div>
                      <div class="sc-card-title">LLM 配置</div>
                      <div class="sc-card-subtitle">前端固定按 OpenAI-compatible 第三方接口发送，你只需要填写模型、Base URL 和 API Key。</div>
                    </div>
                  </div>
                  <div class="sc-field-grid sc-field-grid--double">
                    <div class="sc-field-group">
                      <label class="form-label">接口类型</label>
                      <input id="sc-llm-provider" type="hidden" value="custom" />
                      <input type="text" class="input" value="OpenAI-compatible 第三方接口" disabled />
                    </div>
                    <div class="sc-field-group">
                      <label class="form-label">Model</label>
                      <input id="sc-llm-model" type="text" class="input" placeholder="例如：deepseek-chat" />
                    </div>
                    <div class="sc-field-group">
                      <label class="form-label">Base URL</label>
                      <input id="sc-llm-url" type="text" class="input" placeholder="https://api.example.com/v1" />
                    </div>
                    <div class="sc-field-group">
                      <label class="form-label">API Key</label>
                      <input id="sc-llm-key" type="password" class="input" placeholder="sk-…" />
                    </div>
                  </div>
                </section>
              </div>

              <div class="sc-config-stack">
                <section class="sc-card">
                  <div class="sc-card-head">
                    <div>
                      <div class="sc-card-title">发布模板</div>
                      <div class="sc-card-subtitle">先选交付风格，再微调标题、欢迎语和输入提示。</div>
                    </div>
                  </div>
                  <input id="sc-ui-template" type="hidden" value="assistant" />
                  <div id="sc-template-presets" class="sc-template-grid"></div>
                  <div class="sc-field-grid sc-field-grid--double">
                    <div class="sc-field-group">
                      <label class="form-label">公开标题</label>
                      <input id="sc-ui-title" type="text" class="input" placeholder="我的知识库" />
                    </div>
                    <div class="sc-field-group">
                      <label class="form-label">页眉副标题</label>
                      <input id="sc-ui-subtitle" type="text" class="input" placeholder="例如：讲解红楼梦的故事" />
                    </div>
                    <div class="sc-field-group sc-field-span-2">
                      <label class="form-label">欢迎语</label>
                      <textarea id="sc-ui-welcome" rows="4" class="textarea sc-textarea" placeholder="你好！请问有什么可以帮助你？"></textarea>
                    </div>
                    <div class="sc-field-group">
                      <label class="form-label">输入提示语</label>
                      <input id="sc-ui-placeholder" type="text" class="input" placeholder="输入你的问题…" />
                    </div>
                    <div class="sc-field-group">
                      <label class="form-label">底部提示</label>
                      <input id="sc-ui-disclaimer" type="text" class="input" placeholder="重要信息请再次核验" />
                    </div>
                    <div class="sc-field-group sc-field-span-2">
                      <label class="form-label">主题色</label>
                      <div class="sc-color-row">
                        <input id="sc-ui-color" type="color" class="sc-color-picker" />
                        <input id="sc-ui-color-text" type="text" class="input input-sm" placeholder="#5B8CFF" />
                      </div>
                      <div class="helper-text">模板会给出一套推荐主色，你也可以在这里改成品牌色。</div>
                    </div>
                    <div class="sc-field-group sc-field-span-2">
                      <details class="sc-css-details">
                        <summary>高级 CSS 自定义</summary>
                        <textarea id="sc-ui-css" rows="6" class="textarea sc-textarea sc-css-textarea" placeholder="/* 自定义 CSS 变量或覆盖 */"></textarea>
                      </details>
                    </div>
                  </div>
                </section>
              </div>
            </div>

            <div class="sc-save-row">
              <span id="sc-chunk-count" class="sc-save-meta"></span>
              <span id="sc-save-status" class="sc-save-status hidden">已保存</span>
              <button id="btn-sc-save" class="btn btn-primary" type="button">保存场景配置</button>
            </div>
          </div>

          <!-- Tab: chunks -->
          <div id="sc-panel-chunks" class="flex-1 flex-col hidden overflow-hidden">
            <!-- Filter bar -->
            <div class="sc-chunks-toolbar">
              <div class="sc-chunks-filter">
                <input id="sc-source-search" type="text" class="input" placeholder="搜索来源名称、URL 或标签…" />
                <select id="sc-source-type" class="select">
                  <option value="">全部分类</option>
                  ${SOURCE_TYPE_ORDER.map(key => `<option value="${key}">${SOURCE_TYPE_GROUPS[key].label}</option>`).join('')}
                </select>
                <select id="sc-source-tag" class="select">
                  <option value="">全部标签</option>
                </select>
                <button id="btn-sc-source-refresh" class="sc-chunks-btn-subtle" type="button">刷新</button>
              </div>
              <button id="btn-sc-source-add-visible" class="sc-chunks-btn-primary" type="button">添加当前筛选</button>
            </div>
            <!-- Selected sources -->
            <div class="sc-chunks-section">
              <div class="sc-chunks-section-head">
                <span class="sc-chunks-section-title">已关联知识源</span>
                <span id="sc-chunk-count2" class="sc-chunks-section-badge">0</span>
              </div>
              <div id="sc-chunk-list" class="sc-chunks-list sc-chunks-list--selected"></div>
            </div>
            <!-- Available sources -->
            <div class="sc-chunks-section sc-chunks-section--available">
              <div class="sc-chunks-section-head">
                <span class="sc-chunks-section-title">可选知识源</span>
                <span id="sc-source-result-meta" class="sc-chunks-section-desc">按分类、标签或关键词筛选后加入场景</span>
              </div>
              <div id="sc-source-results" class="sc-chunks-list"></div>
            </div>
          </div>

          <!-- Tab: keys -->
          <div id="sc-panel-keys" class="flex-1 flex-col hidden overflow-y-auto">
            <div class="px-6 py-4 border-b flex items-center justify-between" style="border-color:var(--bd);">
              <p class="text-xs" style="color:var(--t2);">创建 API 密钥以允许外部应用访问此场景的问答 API</p>
              <button id="btn-sc-key-new" class="px-3 py-1.5 text-xs rounded-lg font-medium transition-colors" style="background:var(--accent-bg);color:var(--accent);">新建密钥</button>
            </div>
            <div id="sc-key-list" class="px-6 py-4 space-y-2"></div>
            <!-- Key reveal modal -->
            <div id="sc-key-modal" class="hidden fixed inset-0 z-50 flex items-center justify-center" style="background:rgba(0,0,0,.6);backdrop-filter:blur(4px);">
              <div class="rounded-xl p-6 max-w-md w-full mx-4 space-y-4" style="background:var(--bg-card);border:1px solid var(--bd);">
                <h3 class="text-sm font-semibold" style="color:var(--t1);">新 API 密钥</h3>
                <p class="text-xs" style="color:var(--c-warn);">请立即复制此密钥。关闭后将无法再次查看完整密钥。</p>
                <div class="rounded-lg px-4 py-3 font-mono text-sm break-all select-all" style="background:var(--bg-body);border:1px solid var(--bd);color:var(--accent);" id="sc-key-raw"></div>
                <div class="flex justify-end gap-2">
                  <button id="btn-sc-key-copy" class="px-4 py-1.5 text-xs rounded-lg transition-colors" style="background:var(--accent);color:#fff;">复制</button>
                  <button id="btn-sc-key-close" class="px-4 py-1.5 text-xs rounded-lg transition-colors" style="background:var(--bg-muted);color:var(--t2);">关闭</button>
                </div>
              </div>
            </div>
          </div>

          <!-- Tab: agent -->
          <div id="sc-panel-agent" class="flex-1 flex-col hidden overflow-hidden">
            <div id="sc-agent-messages" class="flex-1 overflow-y-auto px-6 py-4 space-y-4"></div>
            <div class="px-6 py-3 border-t flex items-center gap-3" style="border-color:var(--bd);background:var(--bg-body);">
              <input id="sc-agent-input" type="text" class="flex-1 text-sm" placeholder="描述你想要的修改，例如：切到客服模板并整套改成深色帮助中心…" style="background:transparent;border:none;" />
              <button id="btn-sc-agent-send" class="px-4 py-1.5 text-xs rounded-lg font-medium transition-colors flex-shrink-0" style="background:var(--accent);color:#fff;">发送</button>
            </div>
          </div>
        </div>
      </main>
    </div>
  `;

  // ── DOM refs ────────────────────────────────────────────────────

  const $list = document.getElementById('scenario-list');
  const $empty = document.getElementById('sc-detail-empty');
  const $detail = document.getElementById('sc-detail');
  const $saveStatus = document.getElementById('sc-save-status');
  const $chunkCount = document.getElementById('sc-chunk-count');
  const $chunkCount2 = document.getElementById('sc-chunk-count2');
  const $keyModal = document.getElementById('sc-key-modal');
  const $keyRaw = document.getElementById('sc-key-raw');

  // ── Helpers ─────────────────────────────────────────────────────

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  async function apiPost(path, body = {}) {
    const res = await api(path, { method: 'POST', body: JSON.stringify(body) });
    return res.json();
  }

  async function apiPut(path, body = {}) {
    const res = await api(path, { method: 'PUT', body: JSON.stringify(body) });
    return res.json();
  }

  async function apiDelete(path, body = null) {
    const opts = { method: 'DELETE' };
    if (body) {
      opts.headers = { 'Content-Type': 'application/json' };
      opts.body = JSON.stringify(body);
    }
    const res = await api(path, opts);
    return res.json();
  }

  function flashStatus(el, text, color = 'var(--c-ok-t)') {
    el.textContent = text;
    el.style.color = color;
    el.classList.remove('hidden');
    setTimeout(() => el.classList.add('hidden'), 2200);
  }

  let _currentHints = null;

  function getCurrentUiConfigFromForm() {
    return normalizeUiConfig({
      template: document.getElementById('sc-ui-template').value,
      title: document.getElementById('sc-ui-title').value.trim(),
      subtitle: document.getElementById('sc-ui-subtitle').value.trim(),
      welcome: document.getElementById('sc-ui-welcome').value.trim(),
      placeholder: document.getElementById('sc-ui-placeholder').value.trim(),
      disclaimer: document.getElementById('sc-ui-disclaimer').value.trim(),
      hints: _currentHints,
      color: document.getElementById('sc-ui-color-text').value.trim() || document.getElementById('sc-ui-color').value,
      css: document.getElementById('sc-ui-css').value.trim(),
    });
  }

  function setUiColor(value) {
    const templateKey = document.getElementById('sc-ui-template').value || DEFAULT_TEMPLATE;
    const color = normalizeHexColor(value, getTemplateMeta(templateKey).color);
    document.getElementById('sc-ui-color').value = color;
    document.getElementById('sc-ui-color-text').value = color.toUpperCase();
    return color;
  }

  function renderTemplatePresets(activeKey) {
    const container = document.getElementById('sc-template-presets');
    if (!container) return;
    container.innerHTML = TEMPLATE_ORDER.map(key => {
      const preset = getTemplateMeta(key);
      return `
        <button class="sc-template-card ${activeKey === key ? 'is-active' : ''}" data-template="${key}" type="button">
          <span class="sc-template-label">${preset.label}</span>
          <span class="sc-template-badge">${preset.badge}</span>
          <span class="sc-template-summary">${preset.summary}</span>
        </button>
      `;
    }).join('');

    container.querySelectorAll('.sc-template-card').forEach(button => {
      button.addEventListener('click', () => {
        const preset = getTemplateMeta(button.dataset.template);
        document.getElementById('sc-ui-template').value = button.dataset.template;
        document.getElementById('sc-ui-subtitle').value = preset.subtitle;
        document.getElementById('sc-ui-welcome').value = preset.welcome;
        document.getElementById('sc-ui-placeholder').value = preset.placeholder;
        document.getElementById('sc-ui-disclaimer').value = preset.disclaimer;
        setUiColor(preset.color);
        renderTemplatePresets(button.dataset.template);
      });
    });
  }

  function getScenarioApiDocUrl(id) {
    const url = new URL(`scenario-api.html?scenario=${encodeURIComponent(id)}`, window.location.href);
    if (url.protocol === 'file:') {
      url.searchParams.set('api', getStoredApiBase());
    }
    return url.href;
  }

  function updateApiDocLink() {
    if (!currentId) return;
    const docUrl = getScenarioApiDocUrl(currentId);
    document.getElementById('sc-open-api-doc-tab').href = docUrl;
  }

  function resetDetailScroll(position = 'top') {
    const panels = ['sc-panel-info', 'sc-panel-chunks', 'sc-panel-keys', 'sc-panel-agent'];
    const value = position === 'bottom' ? Number.MAX_SAFE_INTEGER : 0;
    panels.forEach(id => {
      const element = document.getElementById(id);
      if (element) element.scrollTop = value;
    });
  }

  function bindUiFormInputs() {
    document.getElementById('sc-ui-color').addEventListener('input', event => {
      setUiColor(event.target.value);
    });

    document.getElementById('sc-ui-color-text').addEventListener('change', event => {
      setUiColor(event.target.value);
    });
  }

  function getScenarioPublicUrl(id) {
    const url = new URL(`kb-chat.html?scenario=${encodeURIComponent(id)}`, window.location.href);
    if (url.protocol === 'file:') {
      url.searchParams.set('api', getStoredApiBase());
    }
    return url.href;
  }

  // ── Load scenarios ──────────────────────────────────────────────

  async function loadScenarios() {
    try {
      const data = await apiJson('/scenarios');
      scenarios = data.scenarios || [];
    } catch {
      scenarios = [];
    }
    renderScenarioList();
    if (!scenarios.length) {
      currentId = null;
      $detail.classList.add('hidden');
      $detail.classList.remove('flex');
      $empty.classList.remove('hidden');
      return;
    }

    const nextId = currentId && scenarios.some(s => s.id === currentId) ? currentId : scenarios[0].id;
    if (!$detail.classList.contains('hidden') && nextId === currentId) return;
    selectScenario(nextId);
  }

  function renderScenarioList() {
    if (!scenarios.length) {
      $list.innerHTML = `<div class="px-4 py-10 text-center">
        <div style="font-size:32px;margin-bottom:8px;">📋</div>
        <p class="text-xs font-medium" style="color:var(--t2);">暂无场景</p>
        <p class="text-xs mt-1" style="color:var(--t3);">点击 <span style="color:var(--accent);">+</span> 新建</p>
      </div>`;
      return;
    }
    $list.innerHTML = scenarios.map(s => {
      const active = s.id === currentId;
      const url = getScenarioPublicUrl(s.id);
      const ui = normalizeUiConfig(s.ui_config || {}, s);
      const template = getTemplateMeta(ui.template);
      const hasSourceCount = typeof s.source_count === 'number';
      return `
        <div class="sc-list-item ${active ? 'is-active' : ''}"
             data-id="${s.id}">
          <div class="sc-list-copy">
            <div class="sc-list-title-row">
              <div class="sc-list-title">${esc(s.name)}</div>
              <span class="sc-list-template">${template.label}</span>
            </div>
            <div class="sc-list-desc">${esc(s.description || '无描述')}</div>
            <div class="sc-list-meta">
              ${hasSourceCount ? `<span>${s.source_count} 来源</span>` : ''}
              <span>${template.badge}</span>
            </div>
          </div>
          <div class="sc-list-actions">
            <button class="sc-action-btn sc-copy-link" data-url="${url}" type="button" title="复制链接">复制</button>
            <a class="sc-action-btn sc-open-link" href="${url}" target="_blank" rel="noreferrer" title="跳转到问答页">跳转</a>
          </div>
        </div>
      `;
    }).join('');

    // Click handlers — select scenario on the row, not on buttons
    $list.querySelectorAll('.sc-list-item').forEach(el => {
      el.addEventListener('click', e => {
        if (e.target.closest('.sc-action-btn')) return;
        selectScenario(el.dataset.id);
      });
    });

    // Copy link buttons
    $list.querySelectorAll('.sc-copy-link').forEach(btn => {
      btn.addEventListener('click', e => {
        e.stopPropagation();
        navigator.clipboard.writeText(btn.dataset.url).then(() => {
          toast('链接已复制', 'success');
        }).catch(() => {
          toast('复制失败，请手动复制', 'error');
        });
      });
    });
  }

  // ── Select scenario ─────────────────────────────────────────────

  async function selectScenario(id) {
    currentId = id;
    try {
      const sc = await apiJson(`/scenarios/${id}`);
      updateCurrentInList(sc);
      populateForm(sc);
      resetDetailScroll('top');
      $empty.classList.add('hidden');
      $detail.classList.remove('hidden');
      $detail.classList.add('flex');
      switchTab('info');
    } catch (e) {
      toast('加载场景失败: ' + e.message, 'error');
    }
  }

  function updateCurrentInList(sc) {
    // Update the cached scenario in our array
    const idx = scenarios.findIndex(s => s.id === sc.id);
    if (idx >= 0) scenarios[idx] = sc;
    renderScenarioList();
  }

  function populateForm(sc) {
    document.getElementById('sc-name').value = sc.name || '';
    document.getElementById('sc-desc').value = sc.description || '';
    document.getElementById('sc-prompt').value = sc.system_prompt || '';
    document.getElementById('sc-llm-provider').value = 'custom';
    document.getElementById('sc-llm-model').value = sc.llm_model || '';
    document.getElementById('sc-llm-url').value = sc.llm_base_url || '';
    document.getElementById('sc-llm-key').value = sc.llm_api_key || '';

    const ui = normalizeUiConfig(sc.ui_config || {}, sc);
    _currentHints = ui.hints;
    document.getElementById('sc-ui-template').value = ui.template;
    document.getElementById('sc-ui-title').value = ui.title;
    document.getElementById('sc-ui-subtitle').value = ui.subtitle;
    document.getElementById('sc-ui-welcome').value = ui.welcome;
    document.getElementById('sc-ui-placeholder').value = ui.placeholder;
    document.getElementById('sc-ui-disclaimer').value = ui.disclaimer;
    document.getElementById('sc-ui-css').value = ui.css;
    setUiColor(ui.color);
    renderTemplatePresets(ui.template);
    updateApiDocLink();

    const cnt = sc.source_count || 0;
    $chunkCount.textContent = `已关联 ${cnt} 个知识源`;
    $chunkCount2.textContent = cnt;
  }

  // ── Sub-tab switching ──────────────────────────────────────────

  function switchTab(tab) {
    currentTab = tab;
    ['info', 'chunks', 'keys', 'agent'].forEach(t => {
      const panel = document.getElementById(`sc-panel-${t}`);
      const btn = document.querySelector(`[data-sctab="${t}"]`);
      if (t === tab) {
        panel.classList.remove('hidden');
        if (t === 'keys' || t === 'chunks' || t === 'agent') panel.classList.add('flex');
        btn.style.color = 'var(--accent)';
        btn.style.background = 'var(--accent-bg)';
        panel.scrollTop = 0;
      } else {
        panel.classList.add('hidden');
        if (t === 'keys' || t === 'chunks' || t === 'agent') panel.classList.remove('flex');
        btn.style.color = 'var(--t2)';
        btn.style.background = 'transparent';
      }
    });

    if (tab === 'chunks') loadSourcesTab();
    if (tab === 'keys') loadKeys();
    if (tab === 'agent') initAgentChat();
  }

  document.getElementById('sc-detail').addEventListener('click', e => {
    const btn = e.target.closest('[data-sctab]');
    if (btn) switchTab(btn.dataset.sctab);
  });

  // ── Save ────────────────────────────────────────────────────────

  document.getElementById('btn-sc-save').addEventListener('click', async () => {
    if (!currentId) return;
    const uiConfig = getCurrentUiConfigFromForm();
    const body = {
      name: document.getElementById('sc-name').value.trim(),
      description: document.getElementById('sc-desc').value.trim(),
      system_prompt: document.getElementById('sc-prompt').value,
      llm_provider: 'custom',
      llm_model: document.getElementById('sc-llm-model').value.trim(),
      llm_base_url: document.getElementById('sc-llm-url').value.trim(),
      llm_api_key: document.getElementById('sc-llm-key').value,
      ui_config: uiConfig,
    };
    try {
      const sc = await apiPut(`/scenarios/${currentId}`, body);
      updateCurrentInList(sc);
      flashStatus($saveStatus, '已保存');
    } catch (e) {
      flashStatus($saveStatus, '保存失败: ' + e.message, 'var(--c-err)');
    }
  });

  // ── New scenario ────────────────────────────────────────────────

  document.getElementById('btn-sc-new').addEventListener('click', async () => {
    const name = prompt('请输入场景名称：');
    if (!name || !name.trim()) {
      if (name !== null) toast('场景名称不能为空', 'error');
      return;
    }
    try {
      const sc = await apiPost('/scenarios', { name: name.trim() });
      scenarios.unshift(sc);
      renderScenarioList();
      selectScenario(sc.id);
      toast('场景已创建', 'success');
    } catch (e) {
      toast('创建失败: ' + e.message, 'error');
    }
  });

  // ── Delete scenario ─────────────────────────────────────────────

  document.getElementById('btn-sc-delete').addEventListener('click', async () => {
    if (!currentId) return;
    const sc = scenarios.find(s => s.id === currentId);
    const name = sc ? sc.name : currentId;
    if (!confirm(`确定要删除场景「${name}」？此操作不可恢复。`)) return;
    try {
      await apiDelete(`/scenarios/${currentId}`);
      scenarios = scenarios.filter(s => s.id !== currentId);
      currentId = null;
      $detail.classList.add('hidden');
      $detail.classList.remove('flex');
      $empty.classList.remove('hidden');
      renderScenarioList();
      toast('场景已删除', 'success');
    } catch (e) {
      toast('删除失败: ' + e.message, 'error');
    }
  });

  // ── Source management ───────────────────────────────────────────

  function aggregateScenarioSources(rows) {
    const grouped = new Map();
    rows.forEach(row => {
      const key = row.source_id || row.chunk_id;
      if (!key) return;
      if (!grouped.has(key)) {
        grouped.set(key, {
          source_id: row.source_id || '',
          source_name: row.source_name || row.source_id || row.chunk_id || '未命名来源',
          source_type: row.source_type || '',
          added_by: row.added_by || 'manual',
          created_at: row.created_at || '',
          whole_source: !row.chunk_id,
          chunk_count: row.chunk_id ? 1 : 0,
          preview: row.chunk_content || '',
        });
        return;
      }
      const entry = grouped.get(key);
      entry.whole_source = entry.whole_source || !row.chunk_id;
      if (row.chunk_id) entry.chunk_count += 1;
      if (!entry.preview && row.chunk_content) entry.preview = row.chunk_content;
      if (!entry.source_name && row.source_name) entry.source_name = row.source_name;
      if (!entry.source_type && row.source_type) entry.source_type = row.source_type;
      if (row.created_at && String(row.created_at) > String(entry.created_at)) entry.created_at = row.created_at;
    });
    return Array.from(grouped.values()).sort((left, right) => String(right.created_at).localeCompare(String(left.created_at)));
  }

  function renderScenarioSourceTagOptions() {
    const select = document.getElementById('sc-source-tag');
    const currentValue = select.value;
    select.innerHTML = '<option value="">全部标签</option>' + sourceTags.map(tag => `<option value="${esc(tag)}">${esc(tag)}</option>`).join('');
    select.value = sourceTags.includes(currentValue) ? currentValue : '';
  }

  async function loadSourceCatalog(force = false) {
    if (!force && sourceCatalog.length) return;
    const [sourceData, tagData] = await Promise.all([
      apiJson('/kb/sources?limit=500&offset=0'),
      apiJson('/kb/tags'),
    ]);
    sourceCatalog = sourceData.sources || [];
    sourceTags = tagData.tags || [];
    renderScenarioSourceTagOptions();
  }

  function getFilteredCatalogSources() {
    const keyword = document.getElementById('sc-source-search').value.trim().toLowerCase();
    const typeKey = document.getElementById('sc-source-type').value;
    const tag = document.getElementById('sc-source-tag').value;
    return sourceCatalog.filter(source => {
      const matchesKeyword = !keyword || getSourceSearchText(source).includes(keyword);
      const matchesType = !typeKey || normalizeSourceTypeKey(source.type) === typeKey;
      const matchesTag = !tag || (Array.isArray(source.tags) && source.tags.includes(tag));
      return matchesKeyword && matchesType && matchesTag;
    });
  }

  function renderSelectedScenarioSources() {
    const list = document.getElementById('sc-chunk-list');
    const sourceMap = new Map(sourceCatalog.map(source => [source.id, source]));
    $chunkCount2.textContent = selectedScenarioSources.length;
    $chunkCount.textContent = `已关联 ${selectedScenarioSources.length} 个知识源`;
    const currentScenario = scenarios.find(scenario => scenario.id === currentId);
    if (currentScenario) {
      currentScenario.source_count = selectedScenarioSources.length;
      renderScenarioList();
    }

    if (!selectedScenarioSources.length) {
      list.innerHTML = `<div class="sc-chunks-empty">尚未关联任何知识源 — 从下方筛选并加入</div>`;
      return;
    }

    list.innerHTML = selectedScenarioSources.map(source => {
      const meta = sourceMap.get(source.source_id) || {};
      const typeMeta = getSourceTypeMeta(source.source_type || meta.type);
      const tags = Array.isArray(meta.tags) ? meta.tags : [];
      const refLabel = source.whole_source ? '整份来源' : `历史片段 ${source.chunk_count} 个`;
      return `
        <div class="sc-chunks-item">
          <div class="sc-chunks-item-body">
            <div class="sc-chunks-item-title">${esc(source.source_name || source.source_id || '未命名来源')}</div>
            <div class="sc-chunks-item-meta">
              <span class="sc-chunks-item-tag">${typeMeta.icon} ${esc(typeMeta.label)}</span>
              <span class="sc-chunks-item-tag">${esc(refLabel)}</span>
              <span class="sc-chunks-item-tag">${esc(source.added_by || 'manual')}</span>
              ${tags.map(tag => `<span class="sc-chunks-item-tag">${esc(tag)}</span>`).join('')}
            </div>
            ${meta.url ? `<div class="sc-chunks-item-url">${esc(meta.url)}</div>` : ''}
            ${source.preview ? `<div class="sc-chunks-item-preview">${esc(String(source.preview).slice(0, 200))}</div>` : ''}
          </div>
          <div class="sc-chunks-item-actions">
            <button class="sc-chunks-item-btn sc-chunks-item-btn--remove" data-source="${esc(source.source_id || '')}" type="button">移除</button>
          </div>
        </div>
      `;
    }).join('');

    list.querySelectorAll('.sc-chunks-item-btn--remove').forEach(button => {
      button.addEventListener('click', async () => {
        try {
          await apiDelete(`/scenarios/${currentId}/sources`, { source_id: button.dataset.source, chunk_id: '' });
          await loadSourcesTab();
        } catch (error) {
          toast('移除失败: ' + error.message, 'error');
        }
      });
    });
  }

  function renderAvailableScenarioSources() {
    const results = document.getElementById('sc-source-results');
    const meta = document.getElementById('sc-source-result-meta');
    const addVisibleButton = document.getElementById('btn-sc-source-add-visible');
    const selectedIds = new Set(selectedScenarioSources.map(source => source.source_id));
    const filtered = getFilteredCatalogSources();
    const addable = filtered.filter(source => !selectedIds.has(source.id));

    meta.textContent = `${filtered.length} 个来源，可加入 ${addable.length} 个`;
    addVisibleButton.disabled = addable.length === 0;
    addVisibleButton.textContent = addable.length ? `添加当前筛选 (${addable.length})` : '添加当前筛选';

    if (!filtered.length) {
      results.innerHTML = `<div class="sc-chunks-empty">当前筛选下没有可选来源</div>`;
      return;
    }

    results.innerHTML = filtered.map(source => {
      const typeMeta = getSourceTypeMeta(source.type);
      const tags = Array.isArray(source.tags) ? source.tags : [];
      const isSelected = selectedIds.has(source.id);
      return `
        <div class="sc-chunks-item">
          <div class="sc-chunks-item-body">
            <div class="sc-chunks-item-title">${esc(source.name || source.id)}</div>
            <div class="sc-chunks-item-meta">
              <span class="sc-chunks-item-tag">${typeMeta.icon} ${esc(typeMeta.label)}</span>
              ${tags.map(tag => `<span class="sc-chunks-item-tag">${esc(tag)}</span>`).join('')}
            </div>
            ${source.url ? `<div class="sc-chunks-item-url">${esc(source.url)}</div>` : ''}
          </div>
          <div class="sc-chunks-item-actions">
            <button class="sc-chunks-item-btn sc-chunks-item-btn--add" data-source="${esc(source.id)}" ${isSelected ? 'disabled' : ''} type="button">
              ${isSelected ? '已加入' : '加入场景'}
            </button>
          </div>
        </div>
      `;
    }).join('');

    results.querySelectorAll('.sc-chunks-item-btn--add').forEach(button => {
      button.addEventListener('click', async () => {
        try {
          const added = await addSourcesToScenario([button.dataset.source]);
          if (added) toast('知识源已加入场景', 'success');
        } catch (error) {
          toast('添加失败: ' + error.message, 'error');
        }
      });
    });
  }

  async function addSourcesToScenario(sourceIds, addedBy = 'manual') {
    const uniqueIds = [...new Set(sourceIds)].filter(Boolean);
    if (!currentId || !uniqueIds.length) return 0;
    const response = await apiPost(`/scenarios/${currentId}/sources`, {
      entries: uniqueIds.map(sourceId => ({ source_id: sourceId, chunk_id: '' })),
      added_by: addedBy,
    });
    await loadSourcesTab();
    return response.added || 0;
  }

  async function loadSourcesTab({ forceCatalog = false } = {}) {
    if (!currentId) return;
    const list = document.getElementById('sc-chunk-list');
    const results = document.getElementById('sc-source-results');
    try {
      await loadSourceCatalog(forceCatalog);
      const data = await apiJson(`/scenarios/${currentId}/sources`);
      selectedScenarioSources = aggregateScenarioSources(data.sources || []);
      renderSelectedScenarioSources();
      renderAvailableScenarioSources();
    } catch (error) {
      list.innerHTML = `<p class="text-xs py-8 text-center" style="color:var(--c-err);">加载场景知识源失败：${esc(error.message)}</p>`;
      results.innerHTML = `<p class="text-xs py-8 text-center" style="color:var(--c-err);">加载知识库列表失败：${esc(error.message)}</p>`;
      toast('加载知识库失败: ' + error.message, 'error');
    }
  }

  document.getElementById('btn-sc-source-refresh').addEventListener('click', () => loadSourcesTab({ forceCatalog: true }));
  document.getElementById('sc-source-search').addEventListener('input', renderAvailableScenarioSources);
  document.getElementById('sc-source-type').addEventListener('change', renderAvailableScenarioSources);
  document.getElementById('sc-source-tag').addEventListener('change', renderAvailableScenarioSources);
  document.getElementById('btn-sc-source-add-visible').addEventListener('click', async () => {
    const selectedIds = new Set(selectedScenarioSources.map(source => source.source_id));
    const addableIds = getFilteredCatalogSources()
      .map(source => source.id)
      .filter(sourceId => !selectedIds.has(sourceId));
    if (!addableIds.length) {
      toast('当前筛选下没有可添加的知识源', 'error');
      return;
    }
    try {
      const added = await addSourcesToScenario(addableIds);
      toast(`已加入 ${added} 个知识源`, 'success');
    } catch (error) {
      toast('批量添加失败: ' + error.message, 'error');
    }
  });

  // ── API Keys ────────────────────────────────────────────────────

  async function loadKeys() {
    if (!currentId) return;
    const list = document.getElementById('sc-key-list');
    try {
      const data = await apiJson(`/scenarios/${currentId}/keys`);
      const keys = data.keys || [];
      if (!keys.length) {
        list.innerHTML = `<p class="text-xs py-8 text-center" style="color:var(--t3);">暂无 API 密钥。创建一个以允许外部访问。</p>`;
        return;
      }
      list.innerHTML = keys.map(k => `
        <div class="stat-card flex items-center justify-between px-4 py-3">
          <div>
            <div class="text-sm font-medium" style="color:var(--t1);">${esc(k.key_name || '未命名')}</div>
            <div class="text-xs mt-0.5 font-mono" style="color:var(--t3);">${esc(k.key_prefix)}****</div>
            ${k.last_used_at ? `<div class="text-xs mt-0.5" style="color:var(--t3);">上次使用: ${esc(k.last_used_at)}</div>` : '<div class="text-xs mt-0.5" style="color:var(--t3);">从未使用</div>'}
          </div>
          <button class="btn-sc-key-del text-xs px-2 py-1 rounded transition-colors"
                  data-id="${esc(k.id)}"
                  style="color:var(--c-err);background:transparent;">删除</button>
        </div>
      `).join('');

      list.querySelectorAll('.btn-sc-key-del').forEach(btn => {
        btn.addEventListener('click', async () => {
          if (!confirm('确定要删除此密钥？使用此密钥的应用将立即无法访问。')) return;
          try {
            await apiDelete(`/scenarios/${currentId}/keys/${btn.dataset.id}`);
            loadKeys();
          } catch (e) {
            toast('删除失败: ' + e.message, 'error');
          }
        });
      });
    } catch (e) {
      toast('加载密钥失败: ' + e.message, 'error');
    }
  }

  document.getElementById('btn-sc-key-new').addEventListener('click', async () => {
    const name = prompt('密钥名称（例如：前端应用、内部工具）：');
    if (name === null) return;
    try {
      const data = await apiPost(`/scenarios/${currentId}/keys`, { key_name: name || '' });
      $keyRaw.textContent = data.raw_key;
      $keyModal.classList.remove('hidden');
      loadKeys();
    } catch (e) {
      toast('创建密钥失败: ' + e.message, 'error');
    }
  });

  document.getElementById('btn-sc-key-close').addEventListener('click', () => {
    $keyModal.classList.add('hidden');
  });

  document.getElementById('btn-sc-key-copy').addEventListener('click', () => {
    navigator.clipboard.writeText($keyRaw.textContent).then(() => {
      toast('已复制到剪贴板', 'success');
    }).catch(() => {
      toast('复制失败，请手动选择并复制', 'error');
    });
  });

  $keyModal.addEventListener('click', e => {
    if (e.target === $keyModal) $keyModal.classList.add('hidden');
  });

  // ── Agent Chat ──────────────────────────────────────────────────

  let agentInited = false;
  let agentStreaming = false;

  function initAgentChat() {
    if (agentInited) return;
    agentInited = true;

    const msgEl = document.getElementById('sc-agent-messages');
    // Show welcome
    msgEl.innerHTML = `
      <div class="flex items-start gap-3">
        <div class="max-w-[85%] bubble-ai px-4 py-3 text-sm">
          <p>你好！我是场景配置助手。你可以用自然语言让我帮你：</p>
          <ul style="margin-top:4px;padding-left:16px;">
            <li>搜索并添加相关片段（「帮我找关于定价的内容」）</li>
            <li>切换模板并整套改写界面（「换成客服模板，做成深色帮助中心」）</li>
            <li>重写 UI 文案和样式（「标题改成产品助手，欢迎语更短，再补一段 CSS」）</li>
            <li>调整系统提示词（「让 AI 回答更简洁」）</li>
            <li>更新 LLM 配置（「换成 GPT-4o 模型」）</li>
          </ul>
          <p style="margin-top:4px;">请描述你想要怎么调整这个场景 👇</p>
        </div>
      </div>
    `;
    msgEl.scrollTop = msgEl.scrollHeight;

    document.getElementById('btn-sc-agent-send').addEventListener('click', sendAgentMsg);
    document.getElementById('sc-agent-input').addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendAgentMsg(); }
    });
  }

  async function sendAgentMsg() {
    if (agentStreaming || !currentId) return;
    const input = document.getElementById('sc-agent-input');
    const text = input.value.trim();
    if (!text) return;
    input.value = '';

    const msgEl = document.getElementById('sc-agent-messages');

    // User bubble
    const userDiv = document.createElement('div');
    userDiv.className = 'flex justify-end items-end gap-3';
    userDiv.innerHTML = `<div class="max-w-[80%] bubble-user px-4 py-2.5 text-xs">${esc(text)}</div>`;
    msgEl.appendChild(userDiv);

    // AI thinking bubble
    const aiDiv = document.createElement('div');
    aiDiv.className = 'flex items-start gap-3';
    aiDiv.innerHTML = `<div class="max-w-[85%] bubble-ai px-4 py-2.5 text-sm typing-cursor"><span class="typing-placeholder">&nbsp;</span></div>`;
    msgEl.appendChild(aiDiv);
    msgEl.scrollTop = msgEl.scrollHeight;

    agentStreaming = true;
    document.getElementById('btn-sc-agent-send').disabled = true;

    try {
      const data = await apiPost(`/scenarios/${currentId}/agent/assist`, { message: text });
      const contentEl = aiDiv.querySelector('.bubble-ai');
      const ph = contentEl.querySelector('.typing-placeholder');
      if (ph) ph.remove();
      contentEl.classList.remove('typing-cursor');

      let replyHtml = `<p style="white-space:pre-wrap;">${esc(data.reply)}</p>`;
      if (data.actions_performed && data.actions_performed.length) {
        replyHtml += `<div style="margin-top:6px;font-size:10px;color:var(--accent);">${data.actions_performed.map(a => '✓ ' + esc(a)).join('<br>')}</div>`;
      }
      if (data.search_results && data.search_results.length) {
        replyHtml += `<div style="margin-top:6px;font-size:10px;color:var(--t3);">找到 ${data.search_results.length} 个片段。去「知识库」标签页按来源查看和添加。</div>`;
      }
      contentEl.innerHTML = replyHtml;

      // Refresh form fields if config was changed
      if (data.actions_performed && data.actions_performed.some(a => a.includes('配置') || a.includes('UI'))) {
        const sc = await apiJson(`/scenarios/${currentId}`);
        populateForm(sc);
      }
    } catch (e) {
      const contentEl = aiDiv.querySelector('.bubble-ai');
      const ph = contentEl.querySelector('.typing-placeholder');
      if (ph) ph.remove();
      contentEl.classList.remove('typing-cursor');
      contentEl.innerHTML = `<span style="color:var(--c-err);">错误：${esc(e.message)}</span>`;
    } finally {
      agentStreaming = false;
      document.getElementById('btn-sc-agent-send').disabled = false;
    }
    msgEl.scrollTop = msgEl.scrollHeight;
  }

  // ── Init ────────────────────────────────────────────────────────

  document.addEventListener('tab:shown', e => {
    if (e.detail === 'scenarios') loadScenarios();
  });

  bindUiFormInputs();
  renderTemplatePresets(DEFAULT_TEMPLATE);
  setUiColor(TEMPLATE_PRESETS[DEFAULT_TEMPLATE].color);

  loadScenarios();
})();
