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
        <div id="drop-zone" class="drop-zone rounded-2xl p-12 text-center cursor-pointer">
          <svg class="w-12 h-12 mx-auto text-slate-600 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
              d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/>
          </svg>
          <p class="text-slate-400 mb-1">拖拽文件到此处，或<span class="text-brand cursor-pointer underline">点击浏览</span></p>
          <p class="text-slate-600 text-xs">支持 TXT、MD、PDF、DOCX、HTML、JSON、CSV<br><span class="text-slate-700">视频 MP4/MKV/AVI/MOV · 音频 MP3/WAV/M4A（自动转录）</span></p>
          <input id="file-input" type="file" class="hidden" multiple accept=".txt,.md,.pdf,.docx,.html,.json,.csv,.mp4,.mkv,.avi,.mov,.webm,.mp3,.wav,.m4a,.ogg,.flac" />
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

        <!-- Crawl mode toggle -->
        <div>
          <label class="text-xs text-slate-400 mb-2 block">爬取模式</label>
          <div class="flex gap-1 bg-slate-950 p-1 rounded-lg w-fit">
            <button data-crawl="single" class="crawl-btn active-crawl px-3 py-1 rounded-md text-xs font-medium transition-colors">单页</button>
            <button data-crawl="site"   class="crawl-btn px-3 py-1 rounded-md text-xs font-medium transition-colors">整站爬取</button>
          </div>
        </div>

        <!-- Site crawl options (hidden by default) -->
        <div id="site-options" class="hidden grid grid-cols-2 gap-3">
          <div>
            <label class="text-xs text-slate-400 mb-1 block">最大页数</label>
            <input id="site-max-pages" type="number" value="20" min="1" max="200"
              class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-brand" />
          </div>
          <div>
            <label class="text-xs text-slate-400 mb-1 block">最大深度</label>
            <input id="site-max-depth" type="number" value="2" min="1" max="5"
              class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-brand" />
          </div>
        </div>

        <div>
          <label class="text-xs text-slate-400 mb-1 block">抓取模式</label>
          <select id="url-fetch-mode" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none">
            <option value="auto">自动（静态优先，失败则回退 httpx）</option>
            <option value="static">静态（scrapling Fetcher）</option>
            <option value="dynamic">动态（scrapling PlayWright，需已安装）</option>
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
            <button id="btn-toggle-log" class="text-xs text-slate-500 hover:text-slate-300 border border-slate-700 px-2 py-1 rounded transition-colors">日志</button>
            <button id="btn-refresh-tasks" class="text-xs text-slate-500 hover:text-slate-300 transition-colors">↺ 刷新</button>
          </div>
        </div>
        <div id="task-list" class="space-y-2"></div>
      </div>
    </div>
  `;

  // Floating log panel — appended to body so it's fixed to viewport
  const logPanel = document.createElement('div');
  logPanel.id = 'log-float';
  logPanel.innerHTML = `
    <div id="log-float-inner">
      <div class="log-float-header">
        <span>处理日志</span>
        <div style="display:flex;gap:8px;align-items:center">
          <button id="btn-clear-log" style="font-size:11px;color:#64748b;background:none;border:none;cursor:pointer">清空</button>
          <button id="btn-hide-log" style="font-size:11px;color:#64748b;background:none;border:none;cursor:pointer" title="隐藏到边界">✕</button>
        </div>
      </div>
      <div id="log-content" class="log-float-body"></div>
    </div>
    <button id="btn-show-log-tab" title="展开日志">日志</button>
  `;
  document.body.appendChild(logPanel);

  // Inject Tailwind-based primary button style via CSS
  const style = document.createElement('style');
  style.textContent = `
    .btn-primary { background:#4f46e5; color:#fff; }
    .btn-primary:hover { background:#4338ca; }
    .mode-btn { color:#64748b; }
    .mode-btn:hover { color:#e2e8f0; }
    .active-mode { background:#4f46e5; color:#fff; }
    .crawl-btn { color:#64748b; }
    .crawl-btn:hover { color:#e2e8f0; }
    .active-crawl { background:#334155; color:#e2e8f0; }
    .task-progress-bar { transition: width 0.6s ease; }
    @keyframes progress-pulse { 0%,100%{opacity:1} 50%{opacity:.5} }
    .progress-indeterminate { animation: progress-pulse 1.4s ease-in-out infinite; }
    /* Floating log panel */
    #log-float {
      position: fixed;
      top: 72px;
      right: 0;
      width: 340px;
      z-index: 9999;
      display: flex;
      align-items: flex-start;
      gap: 0;
      transition: transform 0.3s cubic-bezier(.4,0,.2,1);
    }
    #log-float.log-hidden { transform: translateX(340px); }
    #log-float-inner {
      flex: 1;
      background: #0a0f1a;
      border: 1px solid #1e293b;
      border-right: none;
      border-radius: 12px 0 0 12px;
      overflow: hidden;
      box-shadow: -4px 4px 24px rgba(0,0,0,.5);
    }
    .log-float-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 8px 12px;
      border-bottom: 1px solid #1e293b;
      font-size: 11px;
      font-weight: 600;
      color: #94a3b8;
      background: #0f172a;
    }
    .log-float-body {
      height: 360px;
      overflow-y: auto;
      padding: 10px 12px;
      font-family: monospace;
      font-size: 11px;
      color: #94a3b8;
      line-height: 1.6;
    }
    .log-float-body::-webkit-scrollbar { width:3px; }
    .log-float-body::-webkit-scrollbar-track { background:transparent; }
    .log-float-body::-webkit-scrollbar-thumb { background:#334155; border-radius:3px; }
    #btn-show-log-tab {
      writing-mode: vertical-rl;
      text-orientation: mixed;
      background: #0f172a;
      border: 1px solid #1e293b;
      border-left: none;
      border-radius: 0 6px 6px 0;
      padding: 10px 5px;
      font-size: 11px;
      color: #64748b;
      cursor: pointer;
      align-self: stretch;
      transition: color .2s, background .2s;
      display: none;
    }
    #log-float.log-hidden #btn-show-log-tab { display: block; }
    #btn-show-log-tab:hover { color:#e2e8f0; background:#1e293b; }
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

  // Crawl mode toggle (single / site)
  let crawlMode = 'single';
  panel.querySelectorAll('.crawl-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      panel.querySelectorAll('.crawl-btn').forEach(b => b.classList.remove('active-crawl'));
      btn.classList.add('active-crawl');
      crawlMode = btn.dataset.crawl;
      document.getElementById('site-options').classList.toggle('hidden', crawlMode !== 'site');
    });
  });

  // Drop zone
  const dropZone = document.getElementById('drop-zone');
  const fileInput = document.getElementById('file-input');

  dropZone.addEventListener('click', () => fileInput.click());
  dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
  dropZone.addEventListener('drop', e => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    uploadFiles(e.dataTransfer.files);
  });
  fileInput.addEventListener('change', () => uploadFiles(fileInput.files));

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

    try {
      if (crawlMode === 'site') {
        const maxPages = parseInt(document.getElementById('site-max-pages').value) || 20;
        const maxDepth = parseInt(document.getElementById('site-max-depth').value) || 2;
        const res = await apiJson('/ingest/site', {
          method: 'POST',
          body: JSON.stringify({ url, title, tags, max_pages: maxPages, max_depth: maxDepth, mode }),
        });
        toast(`整站爬取已开始（最多 ${maxPages} 页）`, 'success');
      } else {
        await apiJson('/ingest/url', { method: 'POST', body: JSON.stringify({ url, title, tags, mode }) });
        toast('URL 已加入队列', 'success');
      }
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

  // Task list + Floating log panel
  const taskList = document.getElementById('task-list');
  const logFloat = document.getElementById('log-float');
  const logContent = document.getElementById('log-content');
  const btnToggleLog = document.getElementById('btn-toggle-log');
  const btnHideLog = document.getElementById('btn-hide-log');
  const btnShowLogTab = document.getElementById('btn-show-log-tab');
  const btnClearLog = document.getElementById('btn-clear-log');
  let pollTimer = null;
  const seenLogLen = new Map(); // task_id → char length already rendered

  function showLog() { logFloat.classList.remove('log-hidden'); }
  function hideLog() { logFloat.classList.add('log-hidden'); }

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

  function appendLog(taskId, sourceName, logText) {
    const prev = seenLogLen.get(taskId) || 0;
    if (!logText || logText.length <= prev) return;
    const newPart = logText.slice(prev);
    seenLogLen.set(taskId, logText.length);

    const label = sourceName ? sourceName.slice(0, 30) : taskId.slice(0, 8);
    newPart.split('\n').forEach(line => {
      const trimmed = line.trim();
      if (!trimmed) return;
      // line format from backend: "[HH:MM:SS] msg"
      const div = document.createElement('div');
      div.className = 'text-slate-400';
      div.textContent = trimmed.startsWith('[') ? `${label}  ${trimmed}` : `[--:--:--] ${label}  ${trimmed}`;
      logContent.appendChild(div);
    });
    // Auto-scroll to bottom
    logContent.scrollTop = logContent.scrollHeight;
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
        // Auto-show floating log when tasks are running
        showLog();
      } else {
        refreshStats();
      }
    } catch {}
  }

  // Toggle floating log (button in task header)
  btnToggleLog.addEventListener('click', () => {
    logFloat.classList.contains('log-hidden') ? showLog() : hideLog();
  });
  // Hide via × in panel header
  btnHideLog.addEventListener('click', hideLog);
  // Show tab (visible only when hidden)
  btnShowLogTab.addEventListener('click', showLog);

  // Clear log
  btnClearLog.addEventListener('click', () => {
    logContent.innerHTML = '';
    seenLogLen.clear();
  });

  document.getElementById('btn-refresh-tasks').addEventListener('click', loadTasks);
  document.addEventListener('tab:shown', e => { if (e.detail === 'upload') loadTasks(); });
  loadTasks();
})();
