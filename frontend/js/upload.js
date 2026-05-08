/* ── Upload Panel ───────────────────────────────────────────── */

(function initUpload() {
  const panel = document.getElementById('tab-upload');

  panel.innerHTML = `
    <div class="max-w-3xl mx-auto space-y-6">
      <div>
        <h1 class="text-2xl font-bold text-white">上传 & 摄入</h1>
        <p class="text-slate-400 text-sm mt-1">向知识库添加内容</p>
      </div>

      <!-- Input type tabs -->
      <div class="flex gap-1 bg-slate-900 p-1 rounded-xl w-fit">
        <button data-mode="file"  class="mode-btn active-mode px-4 py-1.5 rounded-lg text-sm font-medium transition-colors">文件</button>
        <button data-mode="url"   class="mode-btn px-4 py-1.5 rounded-lg text-sm font-medium transition-colors">URL</button>
        <button data-mode="text"  class="mode-btn px-4 py-1.5 rounded-lg text-sm font-medium transition-colors">粘贴文本</button>
      </div>

      <!-- File mode -->
      <div id="mode-file" class="mode-panel space-y-4">
        <div id="drop-zone" class="drop-zone rounded-2xl p-10 text-center">
          <svg class="w-12 h-12 mx-auto text-slate-600 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
              d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/>
          </svg>
          <p class="text-slate-400 mb-3">拖拽文件或文件夹到此处</p>
          <!-- Pick buttons -->
          <div class="flex items-center justify-center gap-3 mb-3">
            <label for="file-input"
              class="cursor-pointer text-xs text-slate-300 hover:text-white bg-slate-800 hover:bg-slate-700 border border-slate-600 hover:border-slate-400 px-4 py-2 rounded-lg transition-colors select-none">
              📄 浏览文件
            </label>
            <label for="folder-input"
              class="cursor-pointer text-xs text-slate-300 hover:text-white bg-slate-800 hover:bg-slate-700 border border-slate-600 hover:border-slate-400 px-4 py-2 rounded-lg transition-colors select-none">
              📁 选择文件夹
            </label>
          </div>
          <p class="text-slate-600 text-xs mb-1">截图后可直接 <kbd class="bg-slate-800 px-1 rounded text-slate-500">Ctrl+V</kbd> 粘贴上传</p>
          <p class="text-slate-700 text-xs">TXT · MD · PDF · DOCX · HTML · JSON · CSV · 图片 · 视频 · 音频</p>
          <input id="file-input" type="file" class="hidden" multiple accept=".txt,.md,.pdf,.docx,.html,.json,.csv,.mp4,.mkv,.avi,.mov,.webm,.mp3,.wav,.m4a,.ogg,.flac,.jpg,.jpeg,.png,.gif,.webp,.bmp,.tiff,.tif" />
          <input id="folder-input" type="file" class="hidden" webkitdirectory multiple />
          <span id="folder-hint" class="block text-xs text-slate-600 mt-1"></span>
        </div>
        <div>
          <label class="text-xs text-slate-400 mb-1 block">标签（逗号分隔）</label>
          <input id="file-tags" type="text" placeholder="研究, 2024, 项目X"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-brand" />
        </div>
      </div>

      <!-- URL mode -->
      <div id="mode-url" class="mode-panel hidden space-y-4">
        <div>
          <label class="text-xs text-slate-400 mb-1 block">页面 URL</label>
          <input id="url-input" type="url" placeholder="https://example.com/article"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-brand" />
        </div>

        <div>
          <label class="text-xs text-slate-400 mb-1 block">抓取模式</label>
          <select id="url-fetch-mode" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none">
            <option value="smart" selected>智能模式（自动识别 URL 类型，选最优策略）</option>
            <option value="auto">自动（静态优先，失败则回退 httpx）</option>
            <option value="static">静态（scrapling Fetcher）</option>
            <option value="dynamic">动态（scrapling PlayWright，需已安装）</option>
            <option value="stealth">隐身（PlayWright + 反检测，绕过 Cloudflare）</option>
            <option value="agent_browser">交互式浏览器（agent-browser，SPA / 懒加载）</option>
            <option value="jshook">CDP 深度（jshookmcp，高级反爬 / 网络拦截）</option>
          </select>
        </div>

        <div>
          <label class="text-xs text-slate-400 mb-1 block">标题（可选）</label>
          <input id="url-title" type="text" placeholder="留空自动检测"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-brand" />
        </div>
        <div>
          <label class="text-xs text-slate-400 mb-1 block">标签</label>
          <input id="url-tags" type="text" placeholder="网页, 新闻"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-brand" />
        </div>
        <div>
          <label class="text-xs text-slate-400 mb-1 block">
            收集意图
            <span class="text-slate-600 font-normal ml-1">（可选，当 WEB_JUDGE_ENABLED=true 时用于 LLM 过滤无关页面）</span>
          </label>
          <input id="url-intent" type="text" placeholder="例如：Python async 教程、RAG 技术文章、XX 公司产品介绍"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-brand" />
        </div>
        <button id="btn-ingest-url" class="btn-primary px-5 py-2 text-sm rounded-lg font-medium">摄入</button>
      </div>

      <!-- Text mode -->
      <div id="mode-text" class="mode-panel hidden space-y-4">
        <div>
          <label class="text-xs text-slate-400 mb-1 block">标题</label>
          <input id="text-title" type="text" placeholder="我的笔记" value="未命名"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-brand" />
        </div>
        <div>
          <label class="text-xs text-slate-400 mb-1 block">内容</label>
          <textarea id="text-content" rows="10" placeholder="粘贴文本、代码、笔记…"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-brand font-mono resize-y"></textarea>
        </div>
        <div>
          <label class="text-xs text-slate-400 mb-1 block">标签</label>
          <input id="text-tags" type="text" placeholder="笔记, 代码片段"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-brand" />
        </div>
        <button id="btn-ingest-text" class="btn-primary px-5 py-2 text-sm rounded-lg font-medium">摄入文本</button>
      </div>

      <!-- Task queue -->
      <div>
        <div class="flex items-center justify-between mb-3">
          <h2 class="text-sm font-semibold text-slate-300">摄入任务</h2>
          <div class="flex items-center gap-2">
            <button id="btn-refresh-tasks" class="text-xs text-slate-500 hover:text-slate-300 transition-colors">↺ 刷新</button>
          </div>
        </div>
        <div id="task-list" class="space-y-2"></div>
      </div>
    </div>
  `;

  // Base styles
  const style = document.createElement('style');
  style.textContent = `
    .btn-primary { background:#4f46e5; color:#fff; }
    .btn-primary:hover { background:#4338ca; }
    .mode-btn { color:#64748b; }
    .mode-btn:hover { color:#e2e8f0; }
    .active-mode { background:#4f46e5; color:#fff; }
    .task-progress-bar { transition: width 0.6s ease; }
    @keyframes progress-pulse { 0%,100%{opacity:1} 50%{opacity:.5} }
    .progress-indeterminate { animation: progress-pulse 1.4s ease-in-out infinite; }
  `;
  document.head.appendChild(style);

  // Mode switching
  const modeBtns = panel.querySelectorAll('.mode-btn');
  modeBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      modeBtns.forEach(b => b.classList.remove('active-mode'));
      btn.classList.add('active-mode');
      panel.querySelectorAll('.mode-panel').forEach(p => p.classList.add('hidden'));
      document.getElementById(`mode-${btn.dataset.mode}`).classList.remove('hidden');
    });
  });

  // Drop zone
  const dropZone = document.getElementById('drop-zone');
  const fileInput = document.getElementById('file-input');

  const folderInput = document.getElementById('folder-input');
  const folderHint  = document.getElementById('folder-hint');

  // Drop zone click → do nothing (labels inside handle file/folder picker)
  dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
  dropZone.addEventListener('drop', async e => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    // Try FileSystem API for folder/file drop
    if (e.dataTransfer.items && e.dataTransfer.items.length) {
      const all = await _collectFromDataTransfer(e.dataTransfer.items);
      if (all.length) { uploadFiles(all); return; }
    }
    // Fallback: dragged image URL from browser (e.g. drag image from webpage)
    const imgUrl = e.dataTransfer.getData('text/uri-list') || e.dataTransfer.getData('text/plain');
    if (imgUrl && /\.(jpe?g|png|gif|webp|bmp|tiff?)(\?.*)?$/i.test(imgUrl)) {
      _uploadImageUrl(imgUrl); return;
    }
    uploadFiles(e.dataTransfer.files);
  });
  fileInput.addEventListener('change', () => uploadFiles(fileInput.files));

  // ── Clipboard paste (Ctrl+V screenshot / copied image) ───────
  document.addEventListener('paste', async e => {
    // Only handle when file mode is active
    const activeMode = panel.querySelector('.mode-btn.active-mode');
    if (activeMode && activeMode.dataset.mode !== 'file') return;
    const items = Array.from(e.clipboardData?.items || []);
    const imageItems = items.filter(i => i.type.startsWith('image/'));
    if (!imageItems.length) return;
    e.preventDefault();
    const files = imageItems.map((item, idx) => {
      const blob = item.getAsFile();
      // Give it a meaningful filename with timestamp
      const ext = item.type.split('/')[1]?.replace('jpeg', 'jpg') || 'png';
      const name = `clipboard-${Date.now()}${idx ? `-${idx}` : ''}.${ext}`;
      return new File([blob], name, { type: item.type });
    });
    dropZone.classList.add('drag-over');
    setTimeout(() => dropZone.classList.remove('drag-over'), 400);
    uploadFiles(files);
  });

  // Upload an image by URL (fetched client-side then sent as blob)
  async function _uploadImageUrl(url) {
    try {
      toast('正在获取图片…', 'info');
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const blob = await resp.blob();
      const ext = (blob.type.split('/')[1] || 'jpg').replace('jpeg', 'jpg');
      const name = `image-${Date.now()}.${ext}`;
      const file = new File([blob], name, { type: blob.type });
      uploadFiles([file]);
    } catch (err) {
      toast(`图片获取失败: ${err.message}`, 'error');
    }
  }

  // Folder picker
  // folder-input change handled below alongside fileInput
  folderInput.addEventListener('change', () => {
    const files = Array.from(folderInput.files);
    folderHint.textContent = files.length ? `已选 ${files.length} 个文件` : '';
    if (files.length) uploadFiles(files);
  });

  // ── FileSystem API helpers for folder drag-drop ───────────────
  async function _collectFromDataTransfer(items) {
    const files = [];
    const tasks = [];
    for (const item of items) {
      if (item.kind !== 'file') continue;
      const entry = item.webkitGetAsEntry ? item.webkitGetAsEntry() : null;
      if (entry) tasks.push(_traverseEntry(entry, files));
      else { const f = item.getAsFile(); if (f) files.push(f); }
    }
    await Promise.all(tasks);
    return files;
  }

  async function _traverseEntry(entry, files) {
    if (entry.isFile) {
      const f = await new Promise((res, rej) => entry.file(res, rej));
      files.push(f);
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      const entries = await _readAllEntries(reader);
      await Promise.all(entries.map(e => _traverseEntry(e, files)));
    }
  }

  function _readAllEntries(reader) {
    return new Promise((resolve, reject) => {
      const all = [];
      (function read() {
        reader.readEntries(batch => {
          if (!batch.length) resolve(all);
          else { all.push(...batch); read(); }
        }, reject);
      })();
    });
  }

  async function uploadFiles(fileList) {
    if (!fileList.length) return;
    const fd = new FormData();
    for (const f of fileList) fd.append('files', f);
    fd.append('tags', document.getElementById('file-tags').value);

    try {
      const base = loadSettings().api_base || 'http://localhost:8000';
      const res = await fetch(`${base}/ingest/file`, { method: 'POST', body: fd });
      if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
      const data = await res.json();
      toast(`已加入队列 ${data.results.length} 个文件`, 'success');
      loadTasks();
    } catch (e) {
      toast(e.message, 'error');
    }
  }

  // URL ingest
  document.getElementById('btn-ingest-url').addEventListener('click', async () => {
    const url = document.getElementById('url-input').value.trim();
    if (!url) { toast('请输入 URL', 'error'); return; }
    const tags = document.getElementById('url-tags').value.split(',').map(t => t.trim()).filter(Boolean);
    const title = document.getElementById('url-title').value.trim() || null;
    const mode = document.getElementById('url-fetch-mode').value;
    const intent = document.getElementById('url-intent').value.trim();

    try {
      await apiJson('/ingest/url', { method: 'POST', body: JSON.stringify({ url, title, tags, mode, intent }) });
      toast('URL 已加入摄入队列', 'success');
      loadTasks();
    } catch {}
  });

  // Text ingest
  document.getElementById('btn-ingest-text').addEventListener('click', async () => {
    const content = document.getElementById('text-content').value.trim();
    if (!content) { toast('请输入内容', 'error'); return; }
    const title = document.getElementById('text-title').value.trim() || 'Untitled';
    const tags = document.getElementById('text-tags').value.split(',').map(t => t.trim()).filter(Boolean);
    try {
      await apiJson('/ingest/text', { method: 'POST', body: JSON.stringify({ content, title, tags }) });
      toast('文本已加入队列', 'success');
      loadTasks();
      document.getElementById('text-content').value = '';
    } catch {}
  });

  // Task list
  const taskList = document.getElementById('task-list');
  let pollTimer = null;
  const seenLogLen = new Map(); // task_id → char length already rendered

  function statusBadge(status) {
    const map = {
      pending:    'bg-slate-700 text-slate-300',
      processing: 'bg-blue-900 text-blue-300',
      done:       'bg-emerald-900 text-emerald-300',
      error:      'bg-red-900 text-red-400',
      failed:     'bg-red-900 text-red-400',
    };
    const label = { pending:'待处理', processing:'处理中', done:'完成', error:'失败', failed:'失败' };
    const cls = map[status] || 'bg-slate-700 text-slate-300';
    return `<span class="text-xs px-2 py-0.5 rounded-full font-medium ${cls}">${label[status] || status}</span>`;
  }

  function progressBar(status) {
    if (status === 'done') {
      return `<div class="w-full bg-slate-800 rounded-full h-1 mt-2">
        <div class="task-progress-bar bg-emerald-500 h-1 rounded-full" style="width:100%"></div>
      </div>`;
    }
    if (status === 'error' || status === 'failed') {
      return `<div class="w-full bg-slate-800 rounded-full h-1 mt-2">
        <div class="task-progress-bar bg-red-500 h-1 rounded-full" style="width:100%"></div>
      </div>`;
    }
    if (status === 'processing') {
      return `<div class="w-full bg-slate-800 rounded-full h-1 mt-2">
        <div class="task-progress-bar progress-indeterminate bg-blue-500 h-1 rounded-full" style="width:60%"></div>
      </div>`;
    }
    // pending
    return `<div class="w-full bg-slate-800 rounded-full h-1 mt-2">
      <div class="task-progress-bar bg-slate-700 h-1 rounded-full" style="width:5%"></div>
    </div>`;
  }

  // Route task log lines to the bottom agent console
  function appendLog(taskId, sourceName, logText) {
    const prev = seenLogLen.get(taskId) || 0;
    if (!logText || logText.length <= prev) return;
    const newPart = logText.slice(prev);
    seenLogLen.set(taskId, logText.length);

    const label = sourceName ? sourceName.slice(0, 40) : taskId.slice(0, 8);
    newPart.split('\n').forEach(line => {
      const trimmed = line.trim();
      if (!trimmed) return;
      // Infer kind from emoji prefix
      let kind = 'progress';
      if (trimmed.startsWith('✅') || trimmed.startsWith('🏁')) kind = 'success';
      else if (trimmed.startsWith('❌') || trimmed.startsWith('⚠️')) kind = 'error';
      else if (trimmed.startsWith('⛔')) kind = 'warning';
      window.agentConsole?.emit({
        t: Date.now(), kind,
        agent: 'ingest', label,
        msg: trimmed,
      });
    });
  }

  async function loadTasks() {
    try {
      const tasks = await apiJson('/ingest/tasks?limit=20');
      if (!tasks.length) {
        taskList.innerHTML = '<p class="text-slate-600 text-sm">暂无任务</p>';
        return;
      }

      taskList.innerHTML = tasks.map(t => {
        const name = t.source_name || t.source_id.slice(0, 8) + '…';
        const time = new Date(t.created_at).toLocaleTimeString();
        return `
          <div class="bg-slate-900 rounded-lg px-4 py-3 text-sm">
            <div class="flex items-center justify-between">
              <span class="text-slate-300 truncate max-w-[200px]" title="${name}">${name}</span>
              <div class="flex items-center gap-3 flex-shrink-0">
                <span class="text-slate-500 text-xs">${time}</span>
                ${statusBadge(t.status)}
              </div>
            </div>
            ${t.error ? `<p class="text-red-400 text-xs mt-1 truncate" title="${t.error}">${t.error}</p>` : ''}
            ${progressBar(t.status)}
          </div>
        `;
      }).join('');

      // Append new log lines
      tasks.forEach(t => {
        if (t.log) appendLog(t.id, t.source_name, t.log);
      });

      const hasPending = tasks.some(t => t.status === 'pending' || t.status === 'processing');
      clearInterval(pollTimer);
      if (hasPending) {
        pollTimer = setInterval(loadTasks, 2000);
      } else {
        refreshStats();
      }
    } catch {}
  }

  document.getElementById('btn-refresh-tasks').addEventListener('click', loadTasks);
  document.addEventListener('tab:shown', e => { if (e.detail === 'upload') loadTasks(); });
  loadTasks();
})();
