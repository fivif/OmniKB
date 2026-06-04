/* ── Settings Panel ─────────────────────────────────────────── */

(function initSettings() {
  const panel = document.getElementById('tab-settings');
  panel.innerHTML = `
    <div class="panel-shell settings-shell">
      <div class="settings-grid">
        <div class="stack-md">
          <section class="section-card">
            <div class="section-card-body stack-md">
              <div class="section-head">
                <div>
                  <div class="section-title">连接与默认模型</div>
                  <div class="section-subtitle">保存后会同时写入浏览器本地和后端运行时。后端重启后，这个页面会自动把本地草稿重新推回去。</div>
                </div>
              </div>

              <div class="field-grid settings-form-grid">
                <div class="stack-sm settings-field">
                  <label class="form-label">HTTP 代理</label>
                  <input id="s-proxy" class="input" type="text" placeholder="http://127.0.0.1:7890" />
                </div>
                <div class="stack-sm settings-field">
                  <label class="form-label">LLM 接口</label>
                  <input id="s-llm-provider" type="hidden" value="custom" />
                  <input class="input" type="text" value="OpenAI-compatible 第三方接口" disabled />
                </div>
                <div class="stack-sm settings-field">
                  <label class="form-label">默认模型</label>
                  <input id="s-llm-model" class="input" type="text" placeholder="例如：deepseek-chat" />
                </div>
                <div class="stack-sm settings-field" id="field-llm-base">
                  <label class="form-label">Base URL</label>
                  <input id="s-llm-base" class="input" type="text" placeholder="https://api.example.com/v1" />
                </div>
                <div class="stack-sm settings-field">
                  <label class="form-label">API Key</label>
                  <input id="s-llm-key" class="input settings-key-input" type="password" placeholder="sk-..." />
                </div>
                <div class="stack-sm settings-field">
                  <label class="form-label">对话上下文窗口 (tokens)</label>
                  <input id="s-chat-context" class="input" type="number" placeholder="1000000" />
                  <span class="hint">默认为 1M tokens。超过此值将触发自动压缩</span>
                </div>
                <div class="stack-sm settings-field">
                  <label class="form-label">压缩阈值</label>
                  <input id="s-chat-compaction" class="input" type="number" step="0.05" min="0.5" max="0.95" placeholder="0.80" />
                  <span class="hint">上下文使用率达到此比例时自动压缩（0.5-0.95），默认 0.80</span>
                </div>
              </div>

              <div id="settings-provider-note" class="surface-note settings-provider-note"></div>

              <div class="settings-save-row">
                <button id="btn-save-settings" class="btn btn-primary" type="button">保存运行设置</button>
                <span id="settings-saved" class="settings-flash">已同步到后端</span>
              </div>
            </div>
          </section>

          <section class="section-card">
            <div class="section-card-body stack-md">
              <div class="section-head">
                <div>
                  <div class="section-title">视觉识别</div>
                  <div class="section-subtitle">启用后，上传的图片、PDF、视频将自动进行文字提取和内容描述。</div>
                </div>
              </div>

              <div class="field-grid settings-form-grid">
                <div class="stack-sm settings-field">
                  <label class="form-label" style="display:flex;align-items:center;gap:8px;cursor:pointer;">
                    <input id="s-vision-enabled" type="checkbox" class="input-check" />
                    启用视觉识别
                  </label>
                </div>
                <div class="stack-sm settings-field">
                  <label class="form-label">Vision 模型</label>
                  <input id="s-vision-model" class="input" type="text" placeholder="例如：gpt-4o-mini" />
                </div>
                <div class="stack-sm settings-field">
                  <label class="form-label">Vision Base URL</label>
                  <input id="s-vision-base-url" class="input" type="text" placeholder="留空则沿用 LLM Base URL" />
                </div>
                <div class="stack-sm settings-field">
                  <label class="form-label">Vision API Key</label>
                  <input id="s-vision-key" class="input settings-key-input" type="password" placeholder="留空则沿用 LLM API Key" />
                </div>
                <div class="stack-sm settings-field">
                  <label class="form-label">视频帧间隔（秒）</label>
                  <input id="s-vision-frame-interval" class="input" type="number" min="0" step="1" placeholder="0 = 禁用帧描述" />
                </div>
              </div>
            </div>
          </section>

          <section class="section-card">
            <div class="section-card-body stack-md">
              <div class="section-head">
                <div>
                  <div class="section-title">对话系统提示词</div>
                  <div class="section-subtitle">影响 AI 对话默认风格。修改后即时生效，不需要单独保存。</div>
                </div>
              </div>

              <textarea id="s-system-prompt" class="settings-textarea" rows="7"></textarea>

              <div class="settings-inline-actions">
                <button id="btn-reset-prompt" class="btn btn-secondary" type="button">恢复默认提示词</button>
                <span id="prompt-saved" class="settings-flash">已更新</span>
              </div>
            </div>
          </section>

          <section class="section-card">
            <div class="section-card-body stack-md">
              <div class="section-head">
                <div>
                  <div class="section-title">Admin 管理密码</div>
                  <div class="section-subtitle">设置后台面板登录密码。留空则关闭鉴权，任何人均可直接访问。</div>
                </div>
              </div>

              <div class="field-grid settings-form-grid">
                <div class="stack-sm settings-field" style="grid-column: 1 / -1;">
                  <label class="form-label">Admin 密码</label>
                  <input id="s-admin-password" class="input settings-key-input" type="password" placeholder="留空 = 关闭鉴权" autocomplete="new-password" />
                </div>
              </div>

              <div id="admin-password-status" class="surface-note" style="margin-top:8px;"></div>

              <div class="settings-save-row" style="margin-top:12px;">
                <button id="btn-save-admin-password" class="btn btn-primary" type="button">保存 Admin 密码</button>
                <span id="admin-password-saved" class="settings-flash">已更新</span>
              </div>
            </div>
          </section>

        </div>

        <aside class="stack-md">
          <section class="section-card settings-runtime-card">
            <div class="section-card-body stack-md">
              <div>
                <div class="section-title">运行时摘要</div>
                <div class="section-subtitle">这里显示的是当前表单对应的实际执行配置，而不是装饰性文案。</div>
              </div>

              <div class="stats-grid settings-summary-grid">
                <div class="stats-card">
                  <span class="stats-label">后端</span>
                  <strong id="settings-summary-base" class="stats-value">同源自动</strong>
                </div>
                <div class="stats-card">
                  <span class="stats-label">代理</span>
                  <strong id="settings-summary-proxy" class="stats-value">直连</strong>
                </div>
                <div class="stats-card">
                  <span class="stats-label">接口</span>
                  <strong id="settings-summary-provider" class="stats-value">OpenAI-compatible</strong>
                </div>
                <div class="stats-card">
                  <span class="stats-label">模型</span>
                  <strong id="settings-summary-model" class="stats-value">未设置</strong>
                </div>
              </div>

              <div class="surface-note">注：LLM 运行时配置存活于当前后端进程。这个页面会把浏览器里保存的草稿在加载时重新回放，所以重启后也能尽快恢复工作态。</div>
            </div>
          </section>

          <section class="section-card">
            <div class="section-card-body stack-sm">
              <div class="section-title">接口提示</div>
              <div class="section-subtitle">前端固定按 OpenAI-compatible 第三方接口发送，你只需要手动填写模型、Base URL 和 API Key。</div>
            </div>
          </section>
        </aside>
      </div>
    </div>
  `;

  const refs = {
    proxy: document.getElementById('s-proxy'),
    provider: document.getElementById('s-llm-provider'),
    model: document.getElementById('s-llm-model'),
    baseUrl: document.getElementById('s-llm-base'),
    apiKey: document.getElementById('s-llm-key'),
    chatContext: document.getElementById('s-chat-context'),
    chatCompaction: document.getElementById('s-chat-compaction'),
    providerNote: document.getElementById('settings-provider-note'),
    saveFlash: document.getElementById('settings-saved'),
    systemPrompt: document.getElementById('s-system-prompt'),
    promptFlash: document.getElementById('prompt-saved'),
    summaryBase: document.getElementById('settings-summary-base'),
    summaryProxy: document.getElementById('settings-summary-proxy'),
    summaryProvider: document.getElementById('settings-summary-provider'),
    summaryModel: document.getElementById('settings-summary-model'),

    visionEnabled: document.getElementById('s-vision-enabled'),
    visionModel: document.getElementById('s-vision-model'),
    visionBaseUrl: document.getElementById('s-vision-base-url'),
    visionApiKey: document.getElementById('s-vision-key'),
    visionFrameInterval: document.getElementById('s-vision-frame-interval'),

    adminPassword: document.getElementById('s-admin-password'),
    adminPasswordStatus: document.getElementById('admin-password-status'),
    adminPasswordSaved: document.getElementById('admin-password-saved'),
  };

  const defaults = {
    http_proxy: '',
    llm_provider: 'custom',
    llm_model: '',
    llm_base_url: '',
    llm_api_key: '',

    vision_enabled: false,
    vision_model: 'gpt-4o-mini',
    vision_base_url: '',
    vision_api_key: '',
    vision_frame_interval: 60,

    admin_password: '',
    chat_context_window: 1000000,
    chat_compaction_threshold: 0.80,
  };

  function normalizeProvider(value) {
    return 'custom';
  }


  let promptDebounceTimer = null;

  async function requestJson(path, options = {}) {
    const response = await fetch(path, options);
    const text = await response.text();
    let data = {};
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = { detail: text };
      }
    }
    if (!response.ok) {
      throw new Error(data.detail || `HTTP ${response.status}`);
    }
    return data;
  }

  function showFlash(node, text) {
    node.textContent = text;
    node.classList.add('is-visible');
    clearTimeout(node._flashTimer);
    node._flashTimer = setTimeout(() => node.classList.remove('is-visible'), 2200);
  }

  function localDraft() {
    const saved = loadSettings();
    return {
      http_proxy: saved.http_proxy || '',
      llm_provider: saved.llm_provider ? normalizeProvider(saved.llm_provider) : '',
      llm_model: saved.llm_model || '',
      llm_base_url: saved.llm_base_url || '',
      llm_api_key: saved.llm_api_key || '',

      vision_enabled: saved.vision_enabled !== undefined ? saved.vision_enabled : defaults.vision_enabled,
      vision_model: saved.vision_model || defaults.vision_model,
      vision_base_url: saved.vision_base_url || '',
      vision_api_key: saved.vision_api_key || '',
      vision_frame_interval: saved.vision_frame_interval !== undefined ? saved.vision_frame_interval : defaults.vision_frame_interval,
      admin_password: saved.admin_password || defaults.admin_password,
      chat_context_window: saved.chat_context_window !== undefined ? saved.chat_context_window : defaults.chat_context_window,
      chat_compaction_threshold: saved.chat_compaction_threshold !== undefined ? saved.chat_compaction_threshold : defaults.chat_compaction_threshold,
    };
  }

  function collectRuntimeValues() {
    const provider = normalizeProvider(refs.provider.value);
    const baseUrl = refs.baseUrl.value.trim();
    return {
      http_proxy: refs.proxy.value.trim(),
      llm_provider: provider,
      llm_model: refs.model.value.trim() || defaults.llm_model,
      llm_base_url: baseUrl,
      llm_api_key: refs.apiKey.value.trim(),

      vision_enabled: refs.visionEnabled.checked,
      vision_model: refs.visionModel.value.trim() || defaults.vision_model,
      vision_base_url: refs.visionBaseUrl.value.trim(),
      vision_api_key: refs.visionApiKey.value.trim(),
      vision_frame_interval: parseInt(refs.visionFrameInterval.value, 10) || defaults.vision_frame_interval,
      admin_password: refs.adminPassword.value.trim(),
      chat_context_window: parseInt(refs.chatContext.value, 10) || defaults.chat_context_window,
      chat_compaction_threshold: parseFloat(refs.chatCompaction.value) || defaults.chat_compaction_threshold,
    };
  }

  let _saveToBackendTimer = null;

  function persistLocalDraft() {
    const values = collectRuntimeValues();
    console.log('persistLocalDraft: saving', values);
    saveSettings({
      ...loadSettings(),
      ...values,
    });
    updateSummary(values);
    // Also sync to backend with a 600ms debounce
    clearTimeout(_saveToBackendTimer);
    _saveToBackendTimer = setTimeout(() => {
      syncRuntimeSettings({ skipLocalSave: true, silent: true });
    }, 600);
  }

  function updateSummary(values) {
    refs.summaryBase.textContent = '当前域名 (同源自动)';
    refs.summaryProxy.textContent = values.http_proxy || '直连';
    refs.summaryProvider.textContent = 'OpenAI-compatible';
    refs.summaryModel.textContent = values.llm_model || '未设置';
  }

  function updateProviderMeta() {
    const meta = {
      note: '前端固定使用 OpenAI-compatible 第三方模式，不再提供默认渠道下拉。请手动填写模型、Base URL 和 API Key。',
      placeholder: 'https://api.example.com/v1',
      keyPlaceholder: 'provider token / sk-...',
    };

    refs.providerNote.textContent = meta.note;
    refs.baseUrl.placeholder = meta.placeholder;
    refs.apiKey.placeholder = meta.keyPlaceholder;

    const baseField = document.getElementById('field-llm-base');
    refs.baseUrl.disabled = false;
    baseField.classList.remove('is-disabled');
  }

  function applyRuntimeValues(values) {
    refs.proxy.value = values.http_proxy || '';
    refs.provider.value = normalizeProvider(values.llm_provider);
    refs.model.value = values.llm_model || defaults.llm_model;
    refs.baseUrl.value = values.llm_base_url || '';
    refs.apiKey.value = values.llm_api_key || '';

    refs.visionEnabled.checked = values.vision_enabled !== undefined ? values.vision_enabled : defaults.vision_enabled;
    refs.visionModel.value = values.vision_model || defaults.vision_model;
    refs.visionBaseUrl.value = values.vision_base_url || '';
    refs.visionApiKey.value = values.vision_api_key || '';
    refs.visionFrameInterval.value = values.vision_frame_interval !== undefined ? values.vision_frame_interval : defaults.vision_frame_interval;
    refs.adminPassword.value = values.admin_password || '';
    refs.chatContext.value = values.chat_context_window !== undefined ? values.chat_context_window : defaults.chat_context_window;
    refs.chatCompaction.value = values.chat_compaction_threshold !== undefined ? values.chat_compaction_threshold : defaults.chat_compaction_threshold;

    updateProviderMeta();
    updateSummary(collectRuntimeValues());
  }

  async function syncRuntimeSettings({ silent = false, skipLocalSave = false } = {}) {
    const values = collectRuntimeValues();
    if (!skipLocalSave) persistLocalDraft();

    await requestJson('/settings/proxy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: values.http_proxy }),
    });

    const runtime = await requestJson('/settings/llm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: values.llm_provider,
        model: values.llm_model,
        base_url: values.llm_base_url,
        api_key: values.llm_api_key,
        context_window: values.chat_context_window,
        compaction_threshold: values.chat_compaction_threshold,
      }),
    });

    const visionRuntime = await requestJson('/settings/vision', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        vision_enabled: values.vision_enabled,
        vision_model: values.vision_model,
        vision_base_url: values.vision_base_url,
        vision_api_key: values.vision_api_key,
        vision_frame_interval: values.vision_frame_interval,
      }),
    });

    // Admin password sync is handled by its dedicated button, not auto-synced here
    // to avoid sending the password to the network on every keystroke.

    applyRuntimeValues({
      ...values,
      llm_provider: runtime.provider,
      llm_model: runtime.model,
      llm_base_url: runtime.base_url || '',
      llm_api_key: runtime.api_key || '',
      chat_context_window: runtime.chat_context_window !== undefined ? runtime.chat_context_window : values.chat_context_window,
      chat_compaction_threshold: runtime.chat_compaction_threshold !== undefined ? runtime.chat_compaction_threshold : values.chat_compaction_threshold,
      vision_enabled: visionRuntime.vision_enabled !== undefined ? visionRuntime.vision_enabled : values.vision_enabled,
      vision_model: visionRuntime.vision_model || values.vision_model,
      vision_base_url: visionRuntime.vision_base_url || '',
      vision_api_key: visionRuntime.vision_api_key || '',
      vision_frame_interval: visionRuntime.vision_frame_interval !== undefined ? visionRuntime.vision_frame_interval : values.vision_frame_interval,
    });

    if (!skipLocalSave) {
      saveSettings({
        ...loadSettings(),
        ...collectRuntimeValues(),
      });
    }

    if (window.OmniKBApp?.refreshBackendStatus) {
      window.OmniKBApp.refreshBackendStatus(false);
    }
    if (!silent) {
      showFlash(refs.saveFlash, '已同步到后端');
      toast('运行设置已更新', 'success');
    }
  }

  async function loadRuntimeSettings() {
    const local = localDraft();
    console.log('loadRuntimeSettings: loaded', local);
    applyRuntimeValues({
      http_proxy: local.http_proxy,
      llm_provider: local.llm_provider || defaults.llm_provider,
      llm_model: local.llm_model || defaults.llm_model,
      llm_base_url: local.llm_base_url,
      llm_api_key: local.llm_api_key,
      chat_context_window: local.chat_context_window,
      chat_compaction_threshold: local.chat_compaction_threshold,
    });

    try {
      const [proxy, llm, vision] = await Promise.all([
        requestJson('/settings/proxy').catch(() => ({ proxy: '' })),
        requestJson('/settings/llm').catch(() => ({
          provider: defaults.llm_provider,
          model: defaults.llm_model,
          base_url: '',
          api_key: '',
        })),
        requestJson('/settings/vision').catch(() => ({
          vision_enabled: defaults.vision_enabled,
          vision_model: defaults.vision_model,
          vision_base_url: '',
          vision_api_key: '',
          vision_frame_interval: defaults.vision_frame_interval,
        })),
      ]);

      applyRuntimeValues({
        http_proxy: local.http_proxy || proxy.proxy || '',
        llm_provider: normalizeProvider(local.llm_provider || llm.provider || defaults.llm_provider),
        llm_model: local.llm_model || llm.model || defaults.llm_model,
        llm_base_url: local.llm_base_url || llm.base_url || '',
        llm_api_key: local.llm_api_key || llm.api_key || '',
        chat_context_window: local.chat_context_window !== undefined ? local.chat_context_window : (llm.chat_context_window !== undefined ? llm.chat_context_window : defaults.chat_context_window),
        chat_compaction_threshold: local.chat_compaction_threshold !== undefined ? local.chat_compaction_threshold : (llm.chat_compaction_threshold !== undefined ? llm.chat_compaction_threshold : defaults.chat_compaction_threshold),
        vision_enabled: local.vision_enabled !== undefined ? local.vision_enabled : (vision.vision_enabled !== undefined ? vision.vision_enabled : defaults.vision_enabled),
        vision_model: local.vision_model || vision.vision_model || defaults.vision_model,
        vision_base_url: local.vision_base_url || vision.vision_base_url || '',
        vision_api_key: local.vision_api_key || vision.vision_api_key || '',
        vision_frame_interval: local.vision_frame_interval !== undefined ? local.vision_frame_interval : (vision.vision_frame_interval !== undefined ? vision.vision_frame_interval : defaults.vision_frame_interval),
      });

      const shouldReplay = Boolean(
        local.http_proxy ||
        local.llm_provider ||
        local.llm_model ||
        local.llm_base_url ||
        local.llm_api_key ||
        local.vision_enabled !== undefined ||
        local.vision_model ||
        local.vision_base_url ||
        local.vision_api_key ||
        local.vision_frame_interval !== undefined ||
        local.chat_context_window !== undefined ||
        local.chat_compaction_threshold !== undefined
      );
      if (shouldReplay) {
        await syncRuntimeSettings({ silent: true, skipLocalSave: true });
      }
      // Load admin password status (never the password itself)
      try {
        const adminStatus = await requestJson('/settings/admin-password').catch(() => ({ auth_enabled: false }));
        if (refs.adminPasswordStatus) {
          refs.adminPasswordStatus.textContent = adminStatus.auth_enabled
            ? '当前状态：鉴权已开启。'
            : '当前状态：鉴权已关闭。';
        }
      } catch {}
    } catch {}
  }

  async function loadSystemPrompt() {
    try {
      const data = await requestJson('/settings/system-prompt');
      refs.systemPrompt.value = data.prompt || '';
    } catch {
      refs.systemPrompt.value = '';
    }
  }

  async function pushSystemPrompt() {
    try {
      await requestJson('/settings/system-prompt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: refs.systemPrompt.value }),
      });
      showFlash(refs.promptFlash, '已更新');
    } catch {
      toast('系统提示词更新失败', 'error');
    }
  }

  // ── Admin password ──────────────────────────────────────────

  async function loadAdminPasswordStatus() {
    try {
      const data = await requestJson('/settings/admin-password');
      if (refs.adminPasswordStatus) {
        refs.adminPasswordStatus.textContent = data.auth_enabled
          ? '当前状态：鉴权已开启。修改密码后需点击下方按钮保存。'
          : '当前状态：鉴权已关闭（留空密码）。';
      }
    } catch {
      // Ignore — will show nothing
    }
  }

  async function saveAdminPassword() {
    const pwd = refs.adminPassword.value.trim();
    try {
      await requestJson('/settings/admin-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: pwd }),
      });
      showFlash(refs.adminPasswordSaved, pwd ? 'Admin 密码已更新' : '鉴权已关闭');
      // Persist locally
      saveSettings({ ...loadSettings(), admin_password: pwd });
      // Refresh status
      await loadAdminPasswordStatus();
    } catch (e) {
      toast('Admin 密码更新失败: ' + (e.message || '未知错误'), 'error');
    }
  }

  document.getElementById('btn-save-admin-password').addEventListener('click', saveAdminPassword);

  [refs.proxy, refs.model, refs.baseUrl, refs.apiKey].forEach(node => {
    node.addEventListener('input', persistLocalDraft);
    node.addEventListener('change', persistLocalDraft);
  });

  [refs.visionEnabled, refs.visionModel, refs.visionBaseUrl, refs.visionApiKey, refs.visionFrameInterval].forEach(node => {
    node.addEventListener('input', persistLocalDraft);
    node.addEventListener('change', persistLocalDraft);
  });

  [refs.chatContext, refs.chatCompaction].forEach(node => {
    node.addEventListener('input', persistLocalDraft);
    node.addEventListener('change', persistLocalDraft);
  });

  refs.systemPrompt.addEventListener('input', () => {
    clearTimeout(promptDebounceTimer);
    promptDebounceTimer = setTimeout(pushSystemPrompt, 800);
  });

  document.getElementById('btn-reset-prompt').addEventListener('click', async () => {
    try {
      await requestJson('/settings/system-prompt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: '' }),
      });
      await loadSystemPrompt();
      showFlash(refs.promptFlash, '已恢复默认');
    } catch {
      toast('恢复默认提示词失败', 'error');
    }
  });

  // Reload form state whenever the settings tab is shown
  document.addEventListener('tab:shown', event => {
    if (event.detail === 'settings') {
      loadRuntimeSettings();
      loadSystemPrompt();
      loadAdminPasswordStatus();
    }
  });

  // Initial load
  loadRuntimeSettings();
  loadSystemPrompt();
  loadAdminPasswordStatus();

})();
