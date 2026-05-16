/* ── Upload Panel ───────────────────────────────────────────── */

(function initUpload() {
  const panel = document.getElementById('tab-upload');
  let activeMode = 'file';
  let pollTimer = null;
  const seenLogLen = new Map();

  panel.innerHTML = `
    <div class="panel-shell upload-shell">
      <section class="section-card">
        <div class="section-card-body stack-md">
          <div class="section-head">
            <div>
              <div class="section-title">选择摄入方式</div>
              <div class="section-subtitle">把后端已有能力完整露出来，不再只给你一半入口。</div>
            </div>
          </div>

          <div class="mode-strip">
            <button class="mode-card ingest-mode-card active" data-mode="file" type="button">
              <span class="mode-card-icon">📁</span>
              <span class="mode-card-title">文件 / 文件夹</span>
              <span class="mode-card-copy">拖拽上传、批量选择、截图粘贴，适合本地资料快速入库。</span>
              <span class="mode-card-badge">Batch</span>
            </button>
            <button class="mode-card ingest-mode-card" data-mode="page" type="button">
              <span class="mode-card-icon">🔗</span>
              <span class="mode-card-title">智能抓取</span>
              <span class="mode-card-copy">AI Agent 自主选择策略，智能判断抓取方式，适应各种页面。</span>
              <span class="mode-card-badge">Smart</span>
            </button>
            <button class="mode-card ingest-mode-card" data-mode="text" type="button">
              <span class="mode-card-icon">✍️</span>
              <span class="mode-card-title">粘贴文本</span>
              <span class="mode-card-copy">适合临时笔记、代码片段、会议纪要和复制来的结构化内容。</span>
              <span class="mode-card-badge">Quick Note</span>
            </button>
          </div>

          <div class="surface-note">提示：智能抓取支持“收集意图”。当后端启用 Web Judge 时，它会帮助你过滤掉抓到但没有价值的页面。</div>

          <div class="upload-panels">
            <div id="mode-file" class="ingest-panel stack-md">
              <div id="drop-zone" class="upload-dropzone">
                <div class="upload-drop-icon">
                  <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.6"
                      d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M12 12v8m0-8l-3 3m3-3l3 3" />
                  </svg>
                </div>
                <div class="upload-drop-title">把文件或文件夹拖到这里</div>
                <div class="upload-drop-copy">支持本地资料批量摄入，也支持从浏览器直接拖拽图片链接。截图后按 Ctrl+V 同样会自动上传。</div>
                <div class="upload-drop-actions">
                  <label for="file-input" class="btn btn-primary upload-action-label">浏览文件</label>
                  <label for="folder-input" class="btn btn-secondary upload-action-label">选择文件夹</label>
                </div>
                <div class="upload-drop-meta">TXT · MD · PDF · DOCX · HTML · JSON · CSV · 图片 · 视频 · 音频</div>
                <input id="file-input" type="file" class="hidden" multiple accept=".txt,.md,.pdf,.docx,.html,.json,.csv,.mp4,.mkv,.avi,.mov,.webm,.mp3,.wav,.m4a,.ogg,.flac,.jpg,.jpeg,.png,.gif,.webp,.bmp,.tiff,.tif" />
                <input id="folder-input" type="file" class="hidden" webkitdirectory multiple />
                <span id="folder-hint" class="upload-inline-hint"></span>
              </div>
              <div class="field-grid">
                <div class="stack-sm field-span-2">
                  <label class="form-label">标签（逗号分隔）</label>
                  <input id="file-tags" type="text" class="input" placeholder="研究, 2024, 项目X" />
                </div>
              </div>
            </div>

            <div id="mode-page" class="ingest-panel stack-md hidden">
              <div class="field-grid">
                <div class="stack-sm field-span-2">
                  <label class="form-label">页面 URL</label>
                  <input id="url-input" type="url" class="input" placeholder="https://example.com/article" />
                </div>
                <div class="stack-sm">
                  <label class="form-label">标题（可选）</label>
                  <input id="url-title" type="text" class="input" placeholder="留空自动检测" />
                </div>
                <div class="stack-sm">
                  <label class="form-label">标签</label>
                  <input id="url-tags" type="text" class="input" placeholder="网页, 新闻, 文档" />
                </div>
                <div class="stack-sm">
                  <label class="form-label">收集意图</label>
                  <input id="url-intent" type="text" class="input" placeholder="例如：Python async 教程、RAG 技术文章" />
                </div>
              </div>
              <div class="toolbar-row">
                <div class="upload-inline-hint">适合单篇文章、文档页、登录后单页内容。AI Agent 自动判断最佳抓取策略。</div>
                <button id="btn-ingest-url" class="btn btn-primary" type="button">开始智能抓取</button>
              </div>
            </div>

            <div id="mode-text" class="ingest-panel stack-md hidden">
              <div class="field-grid">
                <div class="stack-sm">
                  <label class="form-label">标题</label>
                  <input id="text-title" type="text" class="input" placeholder="我的笔记" value="未命名" />
                </div>
                <div class="stack-sm">
                  <label class="form-label">标签</label>
                  <input id="text-tags" type="text" class="input" placeholder="笔记, 代码片段" />
                </div>
                <div class="stack-sm field-span-2">
                  <label class="form-label">内容</label>
                  <textarea id="text-content" rows="12" class="textarea upload-textarea" placeholder="粘贴文本、代码、会议纪要、待整理素材…"></textarea>
                </div>
              </div>
              <div class="toolbar-row">
                <div class="upload-inline-hint">适合临时收集不值得做成文件的内容。</div>
                <button id="btn-ingest-text" class="btn btn-primary" type="button">开始摄入文本</button>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section class="section-card">
        <div class="section-card-body stack-md">
          <div class="section-head">
            <div>
              <div class="section-title">摄入任务</div>
              <div class="section-subtitle">所有入口共享同一任务队列。处理中的任务会持续轮询，完成后会自动刷新统计。</div>
            </div>
            <button id="btn-refresh-tasks" class="btn btn-secondary" type="button">刷新队列</button>
          </div>
          <div id="task-list" class="upload-task-list"></div>
        </div>
      </section>
    </div>
  `;

  const dropZone = document.getElementById('drop-zone');
  const fileInput = document.getElementById('file-input');
  const folderInput = document.getElementById('folder-input');
  const folderHint = document.getElementById('folder-hint');
  const taskList = document.getElementById('task-list');

  function setMode(mode) {
    activeMode = mode;
    panel.querySelectorAll('.ingest-mode-card').forEach(button => {
      button.classList.toggle('active', button.dataset.mode === mode);
    });
    panel.querySelectorAll('.ingest-panel').forEach(section => section.classList.add('hidden'));
    const target = document.getElementById(`mode-${mode}`);
    if (target) target.classList.remove('hidden');
  }

  panel.querySelectorAll('.ingest-mode-card').forEach(button => {
    button.addEventListener('click', () => setMode(button.dataset.mode));
  });

  function splitTags(value) {
    return value.split(',').map(tag => tag.trim()).filter(Boolean);
  }

  function escapeHtml(value) {
    return String(value || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  dropZone.addEventListener('dragover', event => {
    event.preventDefault();
    dropZone.classList.add('drag-over');
  });

  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));

  dropZone.addEventListener('drop', async event => {
    event.preventDefault();
    dropZone.classList.remove('drag-over');

    if (event.dataTransfer.items && event.dataTransfer.items.length) {
      const all = await collectFromDataTransfer(event.dataTransfer.items);
      if (all.length) {
        uploadFiles(all);
        return;
      }
    }

    const imageUrl = event.dataTransfer.getData('text/uri-list') || event.dataTransfer.getData('text/plain');
    if (imageUrl && /\.(jpe?g|png|gif|webp|bmp|tiff?)(\?.*)?$/i.test(imageUrl)) {
      uploadImageUrl(imageUrl);
      return;
    }

    uploadFiles(event.dataTransfer.files);
  });

  fileInput.addEventListener('change', () => uploadFiles(fileInput.files));
  folderInput.addEventListener('change', () => {
    const files = Array.from(folderInput.files || []);
    folderHint.textContent = files.length ? `已选 ${files.length} 个文件` : '';
    if (files.length) uploadFiles(files);
  });

  document.addEventListener('paste', event => {
    if (activeMode !== 'file') return;
    const items = Array.from(event.clipboardData?.items || []);
    const imageItems = items.filter(item => item.type.startsWith('image/'));
    if (!imageItems.length) return;

    event.preventDefault();
    const files = imageItems.map((item, index) => {
      const blob = item.getAsFile();
      const ext = item.type.split('/')[1]?.replace('jpeg', 'jpg') || 'png';
      const name = `clipboard-${Date.now()}${index ? `-${index}` : ''}.${ext}`;
      return new File([blob], name, { type: item.type });
    });
    dropZone.classList.add('drag-over');
    setTimeout(() => dropZone.classList.remove('drag-over'), 320);
    uploadFiles(files);
  });

  async function uploadImageUrl(url) {
    try {
      toast('正在获取图片…', 'info');
      const response = await fetch(url);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const blob = await response.blob();
      const ext = (blob.type.split('/')[1] || 'jpg').replace('jpeg', 'jpg');
      const name = `image-${Date.now()}.${ext}`;
      const file = new File([blob], name, { type: blob.type });
      uploadFiles([file]);
    } catch (error) {
      toast(`图片获取失败: ${error.message}`, 'error');
    }
  }

  async function collectFromDataTransfer(items) {
    const files = [];
    const tasks = [];

    for (const item of items) {
      if (item.kind !== 'file') continue;
      const entry = item.webkitGetAsEntry ? item.webkitGetAsEntry() : null;
      if (entry) tasks.push(traverseEntry(entry, files));
      else {
        const file = item.getAsFile();
        if (file) files.push(file);
      }
    }

    await Promise.all(tasks);
    return files;
  }

  async function traverseEntry(entry, files) {
    if (entry.isFile) {
      const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
      files.push(file);
      return;
    }

    if (entry.isDirectory) {
      const reader = entry.createReader();
      const entries = await readAllEntries(reader);
      await Promise.all(entries.map(child => traverseEntry(child, files)));
    }
  }

  function readAllEntries(reader) {
    return new Promise((resolve, reject) => {
      const all = [];
      (function read() {
        reader.readEntries(batch => {
          if (!batch.length) resolve(all);
          else {
            all.push(...batch);
            read();
          }
        }, reject);
      })();
    });
  }

  async function uploadFiles(fileList) {
    if (!fileList.length) return;

    const formData = new FormData();
    for (const file of fileList) formData.append('files', file);
    formData.append('tags', document.getElementById('file-tags').value.trim());

    try {
      const base = loadSettings().api_base || 'http://localhost:6886';
      const response = await fetch(`${base}/ingest/file`, { method: 'POST', body: formData });
      if (!response.ok) throw new Error((await response.json()).detail || response.statusText);
      const data = await response.json();
      folderHint.textContent = `${data.results.length} 个文件已加入队列`;
      toast(`已加入队列 ${data.results.length} 个文件`, 'success');
      loadTasks();
    } catch (error) {
      toast(error.message, 'error');
    }
  }

  document.getElementById('btn-ingest-url').addEventListener('click', async () => {
    const url = document.getElementById('url-input').value.trim();
    if (!url) {
      toast('请输入页面 URL', 'error');
      return;
    }

    try {
      await apiJson('/ingest/url', {
        method: 'POST',
        body: JSON.stringify({
          url,
          title: document.getElementById('url-title').value.trim() || null,
          tags: splitTags(document.getElementById('url-tags').value),
          intent: document.getElementById('url-intent').value.trim(),
        }),
      });
      toast('智能抓取任务已启动', 'success');
      loadTasks();
    } catch {}
  });

  document.getElementById('btn-ingest-text').addEventListener('click', async () => {
    const content = document.getElementById('text-content').value.trim();
    if (!content) {
      toast('请输入要摄入的内容', 'error');
      return;
    }

    try {
      await apiJson('/ingest/text', {
        method: 'POST',
        body: JSON.stringify({
          content,
          title: document.getElementById('text-title').value.trim() || 'Untitled',
          tags: splitTags(document.getElementById('text-tags').value),
        }),
      });
      toast('文本已加入摄入队列', 'success');
      document.getElementById('text-content').value = '';
      loadTasks();
    } catch {}
  });

  function taskStatusBadge(status) {
    const map = {
      pending: { label: '待处理', className: 'badge-pending' },
      processing: { label: '处理中', className: 'badge-processing' },
      done: { label: '完成', className: 'badge-done' },
      error: { label: '失败', className: 'badge-error' },
      failed: { label: '失败', className: 'badge-error' },
    };
    const current = map[status] || map.pending;
    return `<span class="upload-task-status ${current.className}">${current.label}</span>`;
  }

  function taskProgress(status) {
    if (status === 'done') return { width: '100%', extra: '', className: 'is-done' };
    if (status === 'error' || status === 'failed') return { width: '100%', extra: '', className: 'is-error' };
    if (status === 'processing') return { width: '60%', extra: 'upload-progress-bar--indeterminate', className: 'is-processing' };
    return { width: '8%', extra: '', className: 'is-pending' };
  }

  function appendLog(taskId, sourceName, logText) {
    const prev = seenLogLen.get(taskId) || 0;
    if (!logText || logText.length <= prev) return;

    const newPart = logText.slice(prev);
    seenLogLen.set(taskId, logText.length);
    const label = sourceName ? sourceName.slice(0, 40) : taskId.slice(0, 8);

    newPart.split('\n').forEach(line => {
      const trimmed = line.trim();
      if (!trimmed) return;
      let kind = 'progress';
      if (trimmed.startsWith('✅') || trimmed.startsWith('🏁')) kind = 'success';
      else if (trimmed.startsWith('❌') || trimmed.startsWith('⚠️')) kind = 'error';
      else if (trimmed.startsWith('⛔')) kind = 'warning';
      if (window.agentConsole && typeof window.agentConsole.emit === 'function') {
        window.agentConsole.emit({
          t: Date.now(),
          kind,
          agent: 'ingest',
          label,
          msg: trimmed,
        });
      }
    });
  }

  async function loadTasks() {
    try {
      const tasks = await apiJson('/ingest/tasks?limit=20');
      if (!tasks.length) {
        taskList.innerHTML = '<div class="upload-empty-state">还没有摄入任务。先从上面任意一个入口开始。</div>';
        clearInterval(pollTimer);
        refreshStats();
        return;
      }

      taskList.innerHTML = tasks.map(task => {
        const name = escapeHtml(task.source_name || `${task.source_id.slice(0, 8)}…`);
        const time = new Date(task.created_at).toLocaleString();
        const progress = taskProgress(task.status);
        const lastLog = task.log ? escapeHtml(task.log.trim().split('\n').filter(Boolean).pop() || '') : '';
        return `
          <article class="upload-task-card">
            <div class="upload-task-head">
              <div>
                <div class="upload-task-name" title="${name}">${name}</div>
                <div class="upload-task-sub">${time}</div>
              </div>
              ${taskStatusBadge(task.status)}
            </div>
            ${lastLog ? `<div class="upload-task-line">${lastLog}</div>` : ''}
            ${task.error ? `<div class="upload-task-error">${escapeHtml(task.error)}</div>` : ''}
            <div class="upload-progress-track ${progress.className}">
              <div class="upload-progress-bar ${progress.extra}" style="width:${progress.width};"></div>
            </div>
          </article>
        `;
      }).join('');

      tasks.forEach(task => {
        if (!task.log) return;
        try {
          appendLog(task.id, task.source_name, task.log);
        } catch (error) {
          console.warn('[upload] appendLog failed', error);
        }
      });

      const hasPending = tasks.some(task => task.status === 'pending' || task.status === 'processing');
      clearInterval(pollTimer);
      if (hasPending) pollTimer = setInterval(loadTasks, 2000);
      else refreshStats();
    } catch {
      taskList.innerHTML = '<div class="upload-empty-state">无法加载任务列表，请检查后端连接。</div>';
    }
  }

  document.getElementById('btn-refresh-tasks').addEventListener('click', loadTasks);
  document.addEventListener('tab:shown', event => {
    if (event.detail === 'upload') loadTasks();
  });

  setMode(activeMode);
  loadTasks();
})();
