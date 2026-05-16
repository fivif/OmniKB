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
                  <label class="form-label">后端地址</label>
                  <input id="s-api-base" class="input" type="text" placeholder="http://localhost:6886" />
                </div>
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
                  <div class="section-title">对话系统提示词</div>
                  <div class="section-subtitle">影响 RAG 对话默认风格。修改后即时生效，不需要单独保存。</div>
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
                  <div class="section-title">本地模型下载</div>
                  <div class="section-subtitle">BM25 稀疏检索和 reranker 都在这里管理。代理会直接沿用你上面保存的连接配置。</div>
                </div>
                <button id="btn-download-all" class="btn btn-secondary" type="button">下载全部模型</button>
              </div>

              <div class="settings-model-grid">
                <article class="settings-model-card">
                  <div>
                    <div class="settings-model-title">BM25 稀疏嵌入</div>
                    <div class="settings-model-copy">Qdrant/bm25，用于 Hybrid 检索里的 sparse 向量。</div>
                  </div>
                  <div class="settings-model-actions">
                    <span id="bm25-status" class="settings-model-status">检测中…</span>
                    <button id="btn-bm25-download" class="btn btn-primary" type="button">下载</button>
                  </div>
                </article>

                <article class="settings-model-card">
                  <div>
                    <div class="settings-model-title">Cross-encoder 重排序</div>
                    <div class="settings-model-copy">BAAI/bge-reranker-v2-m3，用于结果精排；若 .env 未启用会显示禁用。</div>
                  </div>
                  <div class="settings-model-actions">
                    <span id="reranker-status" class="settings-model-status">检测中…</span>
                    <button id="btn-reranker-download" class="btn btn-primary" type="button">下载</button>
                  </div>
                </article>
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
                  <strong id="settings-summary-base" class="stats-value">http://localhost:6886</strong>
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
    apiBase: document.getElementById('s-api-base'),
    proxy: document.getElementById('s-proxy'),
    provider: document.getElementById('s-llm-provider'),
    model: document.getElementById('s-llm-model'),
    baseUrl: document.getElementById('s-llm-base'),
    apiKey: document.getElementById('s-llm-key'),
    providerNote: document.getElementById('settings-provider-note'),
    saveFlash: document.getElementById('settings-saved'),
    systemPrompt: document.getElementById('s-system-prompt'),
    promptFlash: document.getElementById('prompt-saved'),
    summaryBase: document.getElementById('settings-summary-base'),
    summaryProxy: document.getElementById('settings-summary-proxy'),
    summaryProvider: document.getElementById('settings-summary-provider'),
    summaryModel: document.getElementById('settings-summary-model'),
    bm25Status: document.getElementById('bm25-status'),
    rerankerStatus: document.getElementById('reranker-status'),
    bm25Button: document.getElementById('btn-bm25-download'),
    rerankerButton: document.getElementById('btn-reranker-download'),
    downloadAllButton: document.getElementById('btn-download-all'),
  };

  const defaults = {
    api_base: 'http://localhost:6886',
    http_proxy: '',
    llm_provider: 'custom',
    llm_model: '',
    llm_base_url: '',
    llm_api_key: '',
  };

  function normalizeProvider(value) {
    return 'custom';
  }

  const modelStatusMeta = {
    loaded: { text: '已就绪', tone: 'is-ready', disable: true },
    not_loaded: { text: '未下载', tone: '', disable: false },
    downloading: { text: '下载中…', tone: 'is-pending', disable: true },
    failed: { text: '下载失败', tone: 'is-error', disable: false },
    skipped_disabled: { text: '当前未启用', tone: '', disable: true },
  };

  const downloading = { bm25: false, reranker: false };
  let promptDebounceTimer = null;
  let modelPollTimer = null;

  function getBase() {
    return refs.apiBase.value.trim() || defaults.api_base;
  }

  async function requestJson(path, options = {}) {
    const response = await fetch(`${getBase()}${path}`, options);
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
      api_base: saved.api_base || defaults.api_base,
      http_proxy: saved.http_proxy || '',
      llm_provider: saved.llm_provider ? normalizeProvider(saved.llm_provider) : '',
      llm_model: saved.llm_model || '',
      llm_base_url: saved.llm_base_url || '',
      llm_api_key: saved.llm_api_key || '',
    };
  }

  function collectRuntimeValues() {
    const provider = normalizeProvider(refs.provider.value);
    const baseUrl = refs.baseUrl.value.trim();
    return {
      api_base: getBase(),
      http_proxy: refs.proxy.value.trim(),
      llm_provider: provider,
      llm_model: refs.model.value.trim() || defaults.llm_model,
      llm_base_url: baseUrl,
      llm_api_key: refs.apiKey.value.trim(),
    };
  }

  function persistLocalDraft() {
    const values = collectRuntimeValues();
    saveSettings({
      ...loadSettings(),
      ...values,
    });
    updateSummary(values);
  }

  function updateSummary(values) {
    refs.summaryBase.textContent = values.api_base;
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
    refs.apiBase.value = values.api_base || defaults.api_base;
    refs.proxy.value = values.http_proxy || '';
    refs.provider.value = normalizeProvider(values.llm_provider);
    refs.model.value = values.llm_model || defaults.llm_model;
    refs.baseUrl.value = values.llm_base_url || '';
    refs.apiKey.value = values.llm_api_key || '';
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
      }),
    });

    applyRuntimeValues({
      ...values,
      llm_provider: runtime.provider,
      llm_model: runtime.model,
      llm_base_url: runtime.base_url || '',
      llm_api_key: runtime.api_key || '',
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
    applyRuntimeValues({
      api_base: local.api_base,
      http_proxy: local.http_proxy,
      llm_provider: local.llm_provider || defaults.llm_provider,
      llm_model: local.llm_model || defaults.llm_model,
      llm_base_url: local.llm_base_url,
      llm_api_key: local.llm_api_key,
    });

    try {
      const [proxy, llm] = await Promise.all([
        requestJson('/settings/proxy').catch(() => ({ proxy: '' })),
        requestJson('/settings/llm').catch(() => ({
          provider: defaults.llm_provider,
          model: defaults.llm_model,
          base_url: '',
          api_key: '',
        })),
      ]);

      applyRuntimeValues({
        api_base: local.api_base,
        http_proxy: local.http_proxy || proxy.proxy || '',
        llm_provider: normalizeProvider(local.llm_provider || llm.provider || defaults.llm_provider),
        llm_model: local.llm_model || llm.model || defaults.llm_model,
        llm_base_url: local.llm_base_url || llm.base_url || '',
        llm_api_key: local.llm_api_key || llm.api_key || '',
      });

      const shouldReplay = Boolean(
        local.http_proxy ||
        local.llm_provider ||
        local.llm_model ||
        local.llm_base_url ||
        local.llm_api_key
      );
      if (shouldReplay) {
        await syncRuntimeSettings({ silent: true, skipLocalSave: true });
      }
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

  function setModelStatus(kind, state) {
    const meta = modelStatusMeta[state] || modelStatusMeta.not_loaded;
    const label = kind === 'bm25' ? refs.bm25Status : refs.rerankerStatus;
    const button = kind === 'bm25' ? refs.bm25Button : refs.rerankerButton;
    label.textContent = meta.text;
    label.className = 'settings-model-status';
    if (meta.tone) label.classList.add(meta.tone);
    if (!downloading[kind]) {
      button.disabled = meta.disable;
    }
  }

  async function refreshModelStatus() {
    try {
      const data = await requestJson('/settings/models/status');
      setModelStatus('bm25', data.bm25);
      setModelStatus('reranker', data.reranker);
    } catch {
      refs.bm25Status.textContent = '连接失败';
      refs.rerankerStatus.textContent = '连接失败';
      refs.bm25Status.className = 'settings-model-status is-error';
      refs.rerankerStatus.className = 'settings-model-status is-error';
      refs.bm25Button.disabled = false;
      refs.rerankerButton.disabled = false;
    }
  }

  async function downloadModel(kind) {
    const label = kind === 'bm25' ? 'BM25' : 'Reranker';
    downloading[kind] = true;
    setModelStatus(kind, 'downloading');

    try {
      const data = await requestJson('/settings/models/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proxy: refs.proxy.value.trim() }),
      });

      if (data[kind] === 'already_loaded' || data[kind] === 'skipped_disabled') {
        setModelStatus(kind, data[kind] === 'already_loaded' ? 'loaded' : 'skipped_disabled');
        downloading[kind] = false;
        return;
      }

      toast(`${label} 开始下载`, 'success');
      for (let attempt = 0; attempt < 60; attempt += 1) {
        await new Promise(resolve => setTimeout(resolve, 2000));
        const status = await requestJson('/settings/models/status');
        const current = status[kind];
        if (current === 'loaded') {
          downloading[kind] = false;
          setModelStatus(kind, 'loaded');
          toast(`${label} 下载完成`, 'success');
          return;
        }
        if (current === 'failed') {
          downloading[kind] = false;
          setModelStatus(kind, 'failed');
          return;
        }
      }

      downloading[kind] = false;
      refs[kind === 'bm25' ? 'bm25Status' : 'rerankerStatus'].textContent = '下载超时';
      refs[kind === 'bm25' ? 'bm25Status' : 'rerankerStatus'].className = 'settings-model-status is-error';
      refs[kind === 'bm25' ? 'bm25Button' : 'rerankerButton'].disabled = false;
    } catch (error) {
      downloading[kind] = false;
      refs[kind === 'bm25' ? 'bm25Status' : 'rerankerStatus'].textContent = '请求失败';
      refs[kind === 'bm25' ? 'bm25Status' : 'rerankerStatus'].className = 'settings-model-status is-error';
      refs[kind === 'bm25' ? 'bm25Button' : 'rerankerButton'].disabled = false;
      toast(`${label} 下载失败: ${error.message}`, 'error');
    }
  }

  [refs.apiBase, refs.proxy, refs.model, refs.baseUrl, refs.apiKey].forEach(node => {
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

  refs.bm25Button.addEventListener('click', () => downloadModel('bm25'));
  refs.rerankerButton.addEventListener('click', () => downloadModel('reranker'));
  refs.downloadAllButton.addEventListener('click', async () => {
    refs.downloadAllButton.disabled = true;
    await downloadModel('bm25');
    await downloadModel('reranker');
    refs.downloadAllButton.disabled = false;
  });

  document.getElementById('btn-save-settings').addEventListener('click', async () => {
    try {
      await syncRuntimeSettings();
      refreshModelStatus();
    } catch (error) {
      toast(`运行设置保存失败: ${error.message}`, 'error');
    }
  });

  document.addEventListener('tab:shown', event => {
    if (event.detail === 'settings') {
      refreshModelStatus();
      clearInterval(modelPollTimer);
      modelPollTimer = setInterval(refreshModelStatus, 8000);
    } else {
      clearInterval(modelPollTimer);
    }
  });

  loadRuntimeSettings();
  loadSystemPrompt();
  refreshModelStatus();
})();
