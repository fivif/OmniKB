/* ── Upload Panel ───────────────────────────────────────────── */

(function initUpload() {
  const panel = document.getElementById('tab-upload');
  let activeMode = 'file';
  let pollTimer = null;
  let _taskOffset = 0;
  let _taskTotal = 0;
  let agentEventSource = null;

  panel.innerHTML = `
    <div class="panel-shell upload-shell">
      <section class="section-card">
        <div class="section-card-body stack-md">
          <div class="section-head">
            <div>
              <div class="section-title">选择摄入方式</div>
            </div>
          </div>

          <div class="mode-strip">
            <button class="mode-card ingest-mode-card active" data-mode="file" type="button">
              <span class="mode-card-icon">${icon.folder({size:20})}</span>
              <span class="mode-card-title">文件 / 文件夹</span>
              <span class="mode-card-badge">Batch</span>
            </button>
            <button class="mode-card ingest-mode-card" data-mode="page" type="button">
              <span class="mode-card-icon">${icon.link({size:20})}</span>
              <span class="mode-card-title">智能抓取</span>
              <span class="mode-card-badge">Smart</span>
            </button>
            <button class="mode-card ingest-mode-card" data-mode="text" type="button">
              <span class="mode-card-icon">${icon.edit({size:20})}</span>
              <span class="mode-card-title">粘贴文本</span>
              <span class="mode-card-badge">Quick Note</span>
            </button>
          </div>


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
                <div class="upload-drop-meta">TXT · MD · PDF · DOCX · HTML · JSON · CSV · 图片</div>
                <input id="file-input" type="file" class="hidden" multiple accept=".txt,.md,.pdf,.docx,.html,.json,.csv,.jpg,.jpeg,.png,.gif,.webp,.bmp,.tiff,.tif" />
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
                  <input id="url-intent" type="text" class="input" placeholder="例如：Python async 教程、LLM 技术文章" />
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
            <div class="upload-tasks-toolbar">
              <button id="btn-clear-tasks" class="btn btn-secondary" type="button">清除已完成</button>
              <button id="btn-refresh-tasks" class="btn btn-secondary" type="button">刷新队列</button>
            </div>
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
      const base = loadSettings().api_base || '';
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


  async function loadTasks({offset = 0, append = false} = {}) {
    try {
      const response = await apiJson(`/ingest/tasks?limit=20&offset=${offset}`);
      const tasks = response.tasks || [];
      const total = response.total || 0;
      _taskTotal = total;
      _taskOffset = offset;

      if (!tasks.length && !append) {
        taskList.innerHTML = '<div class="upload-empty-state">还没有摄入任务。先从上面任意一个入口开始。</div>';
        clearInterval(pollTimer);
        refreshStats();
        return;
      }

      const html = tasks.map(task => {
        const escapedName = task.source_name ? escapeHtml(task.source_name) : null;
        const nameHtml = escapedName
          ? `<div class="upload-task-name" title="${escapedName}">${escapedName}</div>`
          : `<div class="upload-task-name"><span class="upload-task-name-orphan">[已删除]</span></div>`;
        const time = new Date(task.created_at).toLocaleString();
        const progress = taskProgress(task.status);
        const lastLog = task.log ? escapeHtml(task.log.trim().split('\n').filter(Boolean).pop() || '') : '';

        let logHtml = '';
        if (task.log) {
          const lines = task.log.trim().split('\n').filter(Boolean);
          if (lines.length > 0) {
            const displayLines = lines.slice(-5);
            const moreCount = lines.length - 5;
            logHtml = `
              <div class="upload-task-lines is-collapsed">
                ${displayLines.map(l => `<div>${escapeHtml(l)}</div>`).join('')}
              </div>
              ${moreCount > 0 ? `<button class="upload-task-log-toggle" type="button">展开全部 (${moreCount} 行)</button>` : ''}
            `;
          }
        }

        return `
          <article class="upload-task-card" data-task-id="${task.id}">
            <div class="upload-task-head">
              <div>
                ${nameHtml}
                <div class="upload-task-sub">${time}</div>
              </div>
              ${taskStatusBadge(task.status)}
            </div>
            ${lastLog ? `<div class="upload-task-line">${lastLog}</div>` : ''}
            ${task.error ? `<div class="upload-task-error">${escapeHtml(task.error)}</div>` : ''}
            ${logHtml}
            <div class="upload-task-stream"></div>
            <div class="upload-progress-track ${progress.className}">
              <div class="upload-progress-bar ${progress.extra}" style="width:${progress.width};"></div>
            </div>
          </article>
        `;
      }).join('');

      if (append) {
        taskList.insertAdjacentHTML('beforeend', html);
      } else {
        taskList.innerHTML = html;
      }

      if (_taskOffset + tasks.length < _taskTotal) {
        taskList.insertAdjacentHTML('beforeend', '<button class="btn btn-secondary upload-load-more" type="button">加载更多</button>');
      }

      const hasPending = tasks.some(task => task.status === 'pending' || task.status === 'processing');
      clearInterval(pollTimer);
      if (hasPending) {
        pollTimer = setInterval(() => loadTasks({offset: _taskOffset, append: false}), 30000);
      } else {
        refreshStats();
      }

      connectAgentEvents();
    } catch {
      if (!append) {
        taskList.innerHTML = '<div class="upload-empty-state">无法加载任务列表，请检查后端连接。</div>';
      }
    }
  }

  async function clearCompletedTasks() {
    try {
      await apiJson('/ingest/tasks?status=done,error', { method: 'DELETE' });
      toast('已清除完成/失败的任务', 'success');
      _taskOffset = 0;
      loadTasks({offset: 0, append: false});
    } catch {
      toast('清除失败', 'error');
    }
  }

  document.addEventListener('click', function(e) {
    if (e.target.id === 'btn-clear-tasks' || e.target.closest('#btn-clear-tasks')) {
      clearCompletedTasks();
      return;
    }
    if (e.target.id === 'btn-refresh-tasks' || e.target.closest('#btn-refresh-tasks')) {
      _taskOffset = 0;
      loadTasks({offset: 0, append: false});
      return;
    }
    if (e.target.classList.contains('upload-load-more')) {
      _taskOffset += 20;
      loadTasks({offset: _taskOffset, append: true});
      return;
    }
    if (e.target.classList.contains('upload-task-log-toggle')) {
      const linesEl = e.target.previousElementSibling;
      const isExpanded = linesEl.classList.contains('is-expanded');
      if (isExpanded) {
        linesEl.classList.remove('is-expanded');
        linesEl.classList.add('is-collapsed');
        e.target.textContent = e.target.textContent.replace('收起', '展开全部');
      } else {
        linesEl.classList.remove('is-collapsed');
        linesEl.classList.add('is-expanded');
        e.target.textContent = e.target.textContent.replace('展开全部', '收起');
      }
      return;
    }
  });

  document.addEventListener('tab:shown', event => {
    if (event.detail === 'upload') {
      _taskOffset = 0;
      loadTasks({offset: 0, append: false});
      connectAgentEvents();
    } else {
      disconnectAgentEvents();
    }
  });

  function connectAgentEvents() {
    if (agentEventSource) return;
    try {
      const base = loadSettings().api_base || '';
      agentEventSource = new EventSource(base + '/agent/v2/events');
      agentEventSource.onmessage = function(e) {
        try {
          const evt = JSON.parse(e.data);
          if (!evt.type) return;
          if (!evt.type.startsWith('ingest_') && !evt.type.startsWith('wiki_') && evt.type !== 'message_start' && evt.type !== 'message_end') return;
          handleIngestEvent(evt);
        } catch {}
      };
      agentEventSource.onerror = function() {
        agentEventSource.close();
        agentEventSource = null;
        setTimeout(connectAgentEvents, 5000);
      };
    } catch {}
  }

  function disconnectAgentEvents() {
    if (agentEventSource) { agentEventSource.close(); agentEventSource = null; }
  }

  function handleIngestEvent(evt) {
    const card = taskList.querySelector(`[data-task-id="${evt.task_id}"]`);
    if (!card) return;
    const d = evt.data || {};

    const badgeEl = card.querySelector('.upload-task-status');
    const lineEl = card.querySelector('.upload-task-line');
    const trackEl = card.querySelector('.upload-progress-track');
    const barEl = card.querySelector('.upload-progress-bar');
    const streamEl = card.querySelector('.upload-task-stream');

    function appendStream(text) {
      if (!streamEl) return;
      const line = document.createElement('div');
      line.textContent = text;
      streamEl.appendChild(line);
      streamEl.scrollTop = streamEl.scrollHeight;
      // Prune old entries if too many
      while (streamEl.children.length > 50) {
        streamEl.removeChild(streamEl.firstChild);
      }
    }

    switch (evt.type) {
      case 'ingest_start':
        if (badgeEl) badgeEl.outerHTML = taskStatusBadge('processing');
        if (trackEl) { trackEl.className = 'upload-progress-track is-processing'; }
        if (barEl) { barEl.className = 'upload-progress-bar upload-progress-bar--indeterminate'; barEl.style.width = '20%'; }
        if (lineEl && d.title) lineEl.textContent = '[开始] ' + d.title;
        appendStream('[开始] ' + (d.title || d.source_id || ''));
        break;
      case 'ingest_progress':
        if (lineEl && d.stage) {
          const label = d.stage === 'metadata' ? '[元数据]' : d.stage === 'autotag' ? '[标签]' : d.stage === 'analysis' ? '[分析]' : d.stage === 'page' ? '[生成]' : '[Wiki]';
          lineEl.textContent = label + ' ' + (d.detail || d.stage);
        }
        if (trackEl) { trackEl.className = 'upload-progress-track is-processing'; }
        if (d.stage === 'page') {
          const pt = d.page_type || '';
          const ptLabel = pt === 'concept' ? '[概念]' : pt === 'entity' ? '[实体]' : pt === 'source' ? '[来源]' : pt === 'query' ? '[问答]' : pt === 'overview' ? '[综述]' : '[' + pt + ']';
          appendStream(ptLabel + ' ' + (d.detail || d.page_id || ''));
        } else if (d.stage === 'analysis') {
          appendStream('[分析] 分析完成');
        } else {
          appendStream((d.stage === 'metadata' ? '[元数据] ' : d.stage === 'autotag' ? '[标签] ' : '[Wiki] ') + (d.detail || d.stage));
        }
        break;
      case 'ingest_complete':
        if (badgeEl) badgeEl.outerHTML = taskStatusBadge('done');
        if (trackEl) { trackEl.className = 'upload-progress-track is-done'; }
        if (barEl) { barEl.className = 'upload-progress-bar'; barEl.style.width = '100%'; }
        if (lineEl) lineEl.textContent = '[完成] Wiki: ' + (d.wiki_pages || 0) + ' 页面';
        appendStream('[完成] 摄入完成 — ' + (d.wiki_pages || 0) + ' 页面, ' + (d.pages_created || 0) + ' 新建 / ' + (d.pages_updated || 0) + ' 更新');
        break;
      case 'ingest_error':
        if (badgeEl) badgeEl.outerHTML = taskStatusBadge('error');
        if (trackEl) { trackEl.className = 'upload-progress-track is-error'; }
        if (barEl) { barEl.className = 'upload-progress-bar'; barEl.style.width = '100%'; }
        if (lineEl && d.error) lineEl.textContent = '[错误] ' + d.error;
        appendStream('[错误] ' + (d.error || '未知错误'));
        break;
      case 'wiki_analysis_start':
        if (trackEl) { trackEl.className = 'upload-progress-track is-processing'; }
        appendStream('[分析] LLM 分析中: ' + (d.title || ''));
        break;
      case 'wiki_analysis_complete':
        appendStream('[完成] 分析完成 — 计划 ' + (d.plan_pages || '?') + ' 页面');
        break;
      case 'wiki_page_generating':
        appendStream('[生成] 生成页面: ' + (d.page_id || ''));
        break;
      case 'wiki_page_created':
        appendStream('[完成] 页面创建: ' + (d.page_id || '') + (d.kind === 'updated' ? ' (更新)' : ''));
        break;
      case 'wiki_batch_start':
        appendStream('[批量] 批量生成 ' + (d.batch_size || '?') + ' 页面');
        break;
      case 'wiki_sync_complete':
        appendStream('[同步] Wiki 同步完成 — ' + (d.pages_created || 0) + ' 新建');
        break;
      case 'message_start':
        // Only show analysis start — generation steps are covered by ingest_progress
        if (d.step === 'analysis') appendStream('[LLM] 分析中…');
        break;
      case 'message_end':
        // Suppressed — ingest_progress / wiki_* events carry the structured summary
        break;
    }
  }

  setMode(activeMode);
  loadTasks({offset: 0, append: false});
  connectAgentEvents();
})();
