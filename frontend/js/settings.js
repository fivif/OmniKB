/* ── Settings Panel ─────────────────────────────────────────── */

(function initSettings() {
  const panel = document.getElementById('tab-settings');

  panel.innerHTML = `
    <div class="max-w-2xl mx-auto space-y-8">
      <div>
        <h1 class="text-2xl font-bold text-white">设置</h1>
        <p class="text-slate-400 text-sm mt-1">配置 LLM 服务商、嵌入模型及连接地址</p>
      </div>

      <!-- Connection -->
      <section class="space-y-4">
        <h2 class="text-sm font-semibold text-slate-300 uppercase tracking-wider">连接</h2>
        <div class="bg-slate-900 rounded-xl p-5 space-y-4 border border-slate-800">
          <div>
            <label class="block text-xs text-slate-400 mb-1">后端地址</label>
            <input id="s-api-base" type="text" placeholder="http://localhost:8000"
              class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-brand" />
          </div>
        </div>
      </section>

      <!-- LLM -->
      <section class="space-y-4">
        <h2 class="text-sm font-semibold text-slate-300 uppercase tracking-wider">LLM 模型</h2>
        <div class="bg-slate-900 rounded-xl p-5 space-y-4 border border-slate-800">
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-xs text-slate-400 mb-1">服务商</label>
              <select id="s-llm-provider" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-brand">
                <option value="custom">第三方 OpenAI 兼容</option>
                <option value="openai">OpenAI 官方</option>
                <option value="anthropic">Anthropic</option>
                <option value="ollama">Ollama (本地)</option>
              </select>
            </div>
            <div>
              <label class="block text-xs text-slate-400 mb-1">模型</label>
              <input id="s-llm-model" type="text" placeholder="deepseek-ai/DeepSeek-V3"
                class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-brand" />
            </div>
          </div>
          <div id="s-ollama-section">
            <label class="block text-xs text-slate-400 mb-1">Ollama 服务地址</label>
            <input id="s-ollama-url" type="text" placeholder="http://localhost:11434"
              class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-brand" />
          </div>
          <p class="text-xs text-slate-500">
            第三方 / 自定义接口的 <code class="text-slate-400">LLM_BASE_URL</code> 和 <code class="text-slate-400">LLM_API_KEY</code>
            在后端 <code class="text-slate-400">.env</code> 文件中配置，API 密钥不会暴露到前端。
          </p>
        </div>
      </section>

      <!-- Embedding -->
      <section class="space-y-4">
        <h2 class="text-sm font-semibold text-slate-300 uppercase tracking-wider">嵌入模型</h2>
        <div class="bg-slate-900 rounded-xl p-5 space-y-4 border border-slate-800">
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-xs text-slate-400 mb-1">服务商</label>
              <select id="s-embed-provider" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none">
                <option value="siliconflow">硅基流动 SiliconFlow</option>
                <option value="openai">OpenAI</option>
              </select>
            </div>
            <div>
              <label class="block text-xs text-slate-400 mb-1">模型</label>
              <input id="s-embed-model" type="text" placeholder="BAAI/bge-m3"
                class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-brand" />
            </div>
          </div>
          <p class="text-xs text-slate-500">
            嵌入模型密钥通过后端 <code class="text-slate-400">SILICONFLOW_API_KEY</code> 配置。
            BM25 稀疏向量由本地 FastEmbed 生成，无需 API Key。
          </p>
        </div>
      </section>

      <!-- MCP -->
      <section class="space-y-4">
        <h2 class="text-sm font-semibold text-slate-300 uppercase tracking-wider">MCP 服务</h2>
        <div class="bg-slate-900 rounded-xl p-5 space-y-3 border border-slate-800">
          <p class="text-xs text-slate-400">MCP SSE endpoint: <code id="mcp-url" class="text-brand">http://localhost:8000/mcp</code></p>
          <p class="text-xs text-slate-400">鉴权方式：<code class="text-slate-500">Authorization: Bearer &lt;MCP_API_KEY&gt;</code></p>
          <p class="text-xs text-slate-400">Stdio 入口：<code class="text-slate-500">python backend/mcp_server/run_stdio.py</code></p>
          <p class="text-xs text-slate-400">调用日志：<code class="text-slate-500">GET /mcp/logs?limit=50&amp;tool=search_kb</code></p>
        </div>
      </section>

      <!-- P1 features -->
      <section class="space-y-4">
        <h2 class="text-sm font-semibold text-slate-300 uppercase tracking-wider">P1 高级功能</h2>
        <div class="bg-slate-900 rounded-xl p-5 border border-slate-800 space-y-4">
          <p class="text-xs text-slate-500">以下功能通过后端 <code class="text-slate-400">.env</code> 配置，修改后需重启服务。</p>
          <div class="space-y-3">
            <div class="flex items-start gap-3">
              <span class="text-indigo-400 mt-0.5 text-xs font-bold">▶</span>
              <div>
                <div class="text-xs font-medium text-slate-300 mb-0.5">视频 / 音频转录 (Whisper)</div>
                <code class="text-xs text-slate-500">WHISPER_MODEL_SIZE=base</code>
                <span class="text-slate-700 text-xs ml-2">可选: tiny · base · small · medium · large-v2</span>
                <p class="text-slate-600 text-xs mt-0.5">需安装 <code>faster-whisper</code>；视频需 ffmpeg 在 PATH</p>
              </div>
            </div>
            <div class="flex items-start gap-3">
              <span class="text-indigo-400 mt-0.5 text-xs font-bold">▶</span>
              <div>
                <div class="text-xs font-medium text-slate-300 mb-0.5">重排序 Re-rank (CrossEncoder)</div>
                <code class="text-xs text-slate-500">RERANKER_ENABLED=true</code>
                <span class="text-slate-700 text-xs ml-2">模型: BAAI/bge-reranker-v2-m3（首次运行自动下载）</span>
                <p class="text-slate-600 text-xs mt-0.5">需安装 <code>sentence-transformers</code></p>
              </div>
            </div>
            <div class="flex items-start gap-3">
              <span class="text-indigo-400 mt-0.5 text-xs font-bold">▶</span>
              <div>
                <div class="text-xs font-medium text-slate-300 mb-0.5">自动标签 Auto-tag</div>
                <code class="text-xs text-slate-500">AUTOTAG_ENABLED=true</code>
                <span class="text-slate-700 text-xs ml-2">每次摄入调用 LLM 生成 3–5 个标签</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- Save -->
      <div class="flex items-center gap-3">
        <button id="btn-save-settings" class="btn-primary px-5 py-2 rounded-lg text-sm font-medium">保存设置</button>
        <span id="settings-saved" class="text-green-400 text-sm hidden">✓ 已保存</span>
      </div>
    </div>
  `;

  // Load current values
  const s = loadSettings();
  document.getElementById('s-api-base').value = s.api_base || 'http://localhost:8000';
  document.getElementById('s-llm-provider').value = s.llm_provider || 'custom';
  document.getElementById('s-llm-model').value = s.llm_model || 'deepseek-ai/DeepSeek-V3';
  document.getElementById('s-ollama-url').value = s.ollama_base_url || 'http://localhost:11434';
  document.getElementById('s-embed-provider').value = s.embedding_provider || 'siliconflow';
  document.getElementById('s-embed-model').value = s.embedding_model || 'BAAI/bge-m3';

  // Show/hide Ollama URL based on provider
  function toggleOllama() {
    const provider = document.getElementById('s-llm-provider').value;
    document.getElementById('s-ollama-section').style.display = provider === 'ollama' ? '' : 'none';
  }
  document.getElementById('s-llm-provider').addEventListener('change', toggleOllama);
  toggleOllama();

  // Update MCP URL preview
  function updateMcpUrl() {
    const base = document.getElementById('s-api-base').value.trim() || 'http://localhost:8000';
    document.getElementById('mcp-url').textContent = `${base}/mcp`;
  }
  document.getElementById('s-api-base').addEventListener('input', updateMcpUrl);
  updateMcpUrl();

  // Save
  document.getElementById('btn-save-settings').addEventListener('click', () => {
    saveSettings({
      api_base: document.getElementById('s-api-base').value.trim(),
      llm_provider: document.getElementById('s-llm-provider').value,
      llm_model: document.getElementById('s-llm-model').value.trim(),
      ollama_base_url: document.getElementById('s-ollama-url').value.trim(),
      embedding_provider: document.getElementById('s-embed-provider').value,
      embedding_model: document.getElementById('s-embed-model').value.trim(),
    });

    const saved = document.getElementById('settings-saved');
    saved.classList.remove('hidden');
    setTimeout(() => saved.classList.add('hidden'), 2500);
    toast('设置已保存', 'success');
  });
})();
