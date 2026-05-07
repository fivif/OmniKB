/* ── KB Manager Panel ───────────────────────────────────────── */

(function initKbManager() {
  const panel = document.getElementById('tab-kb');

  panel.innerHTML = `
    <div class="max-w-6xl mx-auto space-y-4">

      <!-- Header row -->
      <div class="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 class="text-2xl font-bold text-white">知识库管理</h1>
          <p class="text-slate-400 text-sm mt-0.5">浏览、批量管理来源，按类型或标签分类归纳</p>
        </div>
        <div class="flex items-center gap-2 flex-wrap">
          <!-- View mode -->
          <div class="flex bg-slate-800 rounded-lg p-0.5 text-xs">
            <button id="btn-view-list"  class="view-btn active-view px-2.5 py-1 rounded-md transition-colors">列表</button>
            <button id="btn-view-type"  class="view-btn px-2.5 py-1 rounded-md transition-colors">按类型</button>
            <button id="btn-view-tag"   class="view-btn px-2.5 py-1 rounded-md transition-colors">按标签</button>
          </div>
          <!-- Filters -->
          <input id="kb-search" type="text" placeholder="搜索名称…"
            class="bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-300 focus:outline-none focus:border-brand w-36" />
          <select id="kb-tag-filter"
            class="bg-slate-900 border border-slate-700 rounded-lg px-2 py-1.5 text-sm text-slate-300 focus:outline-none focus:border-brand w-32">
            <option value="">所有标签</option>
          </select>
          <!-- Export -->
          <div class="relative" id="export-wrap">
            <button id="btn-export" class="bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs px-3 py-1.5 rounded-lg transition-colors">导出 ▾</button>
            <div id="export-menu" class="hidden absolute right-0 top-8 bg-slate-800 border border-slate-700 rounded-lg shadow-lg z-20 w-32 py-1">
              <a id="export-json" href="#" class="block px-3 py-2 text-xs text-slate-300 hover:bg-slate-700">JSON</a>
              <a id="export-csv"  href="#" class="block px-3 py-2 text-xs text-slate-300 hover:bg-slate-700">CSV (ZIP)</a>
              <a id="export-zip"  href="#" class="block px-3 py-2 text-xs text-slate-300 hover:bg-slate-700">每源 ZIP</a>
            </div>
          </div>
          <button id="btn-kb-refresh" class="text-slate-500 hover:text-slate-300 text-sm transition-colors">↺</button>
        </div>
      </div>

      <!-- Stats -->
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div class="bg-slate-900 rounded-xl p-4">
          <div class="text-2xl font-bold text-white" id="kb-stat-sources">—</div>
          <div class="text-slate-500 text-xs mt-1">来源总数</div>
        </div>
        <div class="bg-slate-900 rounded-xl p-4">
          <div class="text-2xl font-bold text-white" id="kb-stat-chunks">—</div>
          <div class="text-slate-500 text-xs mt-1">片段总数</div>
        </div>
        <div class="bg-slate-900 rounded-xl p-4">
          <div class="text-2xl font-bold text-white" id="kb-stat-selected">0</div>
          <div class="text-slate-500 text-xs mt-1">已选中</div>
        </div>
        <div class="bg-slate-900 rounded-xl p-4">
          <div class="text-2xl font-bold text-white" id="kb-stat-tags">—</div>
          <div class="text-slate-500 text-xs mt-1">标签数</div>
        </div>
      </div>

      <!-- Batch toolbar (hidden until selection) -->
      <div id="batch-toolbar" class="hidden bg-brand/10 border border-brand/30 rounded-xl px-4 py-3 flex items-center gap-3 flex-wrap">
        <span id="batch-count" class="text-brand text-sm font-medium"></span>
        <div class="flex-1"></div>
        <!-- Tag input for batch -->
        <input id="batch-tag-input" type="text" placeholder="标签（逗号分隔）"
          class="bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-300 focus:outline-none focus:border-brand w-48" />
        <button id="btn-batch-add-tag"    class="text-xs bg-slate-700 hover:bg-slate-600 text-slate-200 px-3 py-1.5 rounded-lg transition-colors">+ 追加标签</button>
        <button id="btn-batch-replace-tag" class="text-xs bg-slate-700 hover:bg-slate-600 text-slate-200 px-3 py-1.5 rounded-lg transition-colors">= 替换标签</button>
        <button id="btn-batch-remove-tag" class="text-xs bg-slate-700 hover:bg-slate-600 text-slate-200 px-3 py-1.5 rounded-lg transition-colors">− 移除标签</button>
        <div class="w-px h-5 bg-slate-700"></div>
        <button id="btn-batch-delete" class="text-xs bg-red-800 hover:bg-red-700 text-white px-3 py-1.5 rounded-lg transition-colors">🗑 批量删除</button>
        <button id="btn-batch-clear"  class="text-xs text-slate-500 hover:text-slate-300 px-2 py-1.5 transition-colors">取消选择</button>
      </div>

      <!-- Main content (list view) -->
      <div id="kb-list-view">
        <div class="bg-slate-900 rounded-xl overflow-hidden border border-slate-800">
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b border-slate-800 text-left text-xs text-slate-500 uppercase">
                <th class="px-4 py-3 w-8">
                  <input type="checkbox" id="chk-select-all" class="rounded border-slate-600 bg-slate-800 text-brand focus:ring-0 cursor-pointer" />
                </th>
                <th class="px-4 py-3">名称</th>
                <th class="px-4 py-3 hidden md:table-cell w-20">类型</th>
                <th class="px-4 py-3 hidden lg:table-cell w-28">创建时间</th>
                <th class="px-4 py-3 w-20">状态</th>
                <th class="px-4 py-3 w-28">操作</th>
              </tr>
            </thead>
            <tbody id="kb-tbody"></tbody>
          </table>
        </div>
        <!-- Pagination -->
        <div class="flex items-center justify-between text-sm mt-3">
          <button id="kb-prev" class="text-slate-500 hover:text-slate-300 disabled:opacity-30 transition-colors" disabled>← 上一页</button>
          <span id="kb-page-info" class="text-slate-500 text-xs"></span>
          <button id="kb-next" class="text-slate-500 hover:text-slate-300 disabled:opacity-30 transition-colors">下一页 →</button>
        </div>
      </div>

      <!-- Grouped views -->
      <div id="kb-group-view" class="hidden space-y-4"></div>

    </div>

    <!-- Delete confirm modal -->
    <div id="delete-modal" class="hidden fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div class="bg-slate-900 border border-slate-700 rounded-2xl p-6 max-w-sm w-full mx-4 space-y-4">
        <h3 class="font-semibold text-white" id="delete-modal-title">删除来源</h3>
        <p class="text-slate-400 text-sm" id="delete-modal-desc">此操作将永久删除该来源及其所有片段，无法撤销。</p>
        <div class="flex gap-3 justify-end">
          <button id="btn-cancel-delete" class="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 transition-colors">取消</button>
          <button id="btn-confirm-delete" class="px-4 py-2 text-sm bg-red-700 hover:bg-red-600 text-white rounded-lg transition-colors">确认删除</button>
        </div>
      </div>
    </div>

    <!-- Chunks drawer -->
    <div id="chunks-drawer" class="hidden fixed inset-y-0 right-0 w-full max-w-xl bg-slate-950 border-l border-slate-800 flex flex-col z-40">
      <div class="flex items-center justify-between px-5 py-4 border-b border-slate-800">
        <h3 class="font-semibold text-white text-sm truncate max-w-xs" id="drawer-title">片段列表</h3>
        <button id="btn-close-drawer" class="text-slate-500 hover:text-slate-300 text-lg leading-none ml-4">✕</button>
      </div>
      <div id="drawer-content" class="flex-1 overflow-y-auto p-5 space-y-3"></div>
    </div>

    <!-- Tag edit drawer -->
    <div id="tag-edit-modal" class="hidden fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div class="bg-slate-900 border border-slate-700 rounded-2xl p-6 max-w-sm w-full mx-4 space-y-4">
        <h3 class="font-semibold text-white text-sm">编辑标签</h3>
        <p class="text-slate-500 text-xs" id="tag-edit-source-name"></p>
        <input id="tag-edit-input" type="text" placeholder="标签（逗号分隔）"
          class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-300 focus:outline-none focus:border-brand" />
        <div class="flex gap-3 justify-end">
          <button id="btn-cancel-tag-edit" class="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 transition-colors">取消</button>
          <button id="btn-confirm-tag-edit" class="px-4 py-2 text-sm bg-brand hover:bg-brand/80 text-white rounded-lg transition-colors">保存</button>
        </div>
      </div>
    </div>
  `;

  /* ── State ── */
  let page = 0;
  const pageSize = 20;
  let deleteTargetId = null;       // single delete
  let deleteBatchMode = false;     // true when batch delete
  let tagEditTargetId = null;
  let filterText = '';
  let filterTag = '';
  let viewMode = 'list';           // list | type | tag
  let selectedIds = new Set();
  let allSources = [];             // current page sources (for select-all)

  /* ── Helpers ── */
  function escapeHtml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function parseTags(str) {
    return str.split(',').map(t => t.trim()).filter(Boolean);
  }

  function typeColor(t) {
    const map = { pdf: 'text-red-400', docx: 'text-blue-400', url: 'text-green-400',
                  site: 'text-cyan-400', text: 'text-yellow-400', mp4: 'text-purple-400',
                  mp3: 'text-purple-400' };
    return map[t] || 'text-slate-400';
  }

  function typeIcon(t) {
    const map = { pdf: '📄', docx: '📝', url: '🌐', site: '🌍', text: '✏️',
                  mp4: '🎬', mp3: '🎵', csv: '📊', json: '🗃' };
    return map[t] || '📁';
  }

  /* ── Selection management ── */
  function updateSelectionUI() {
    document.getElementById('kb-stat-selected').textContent = selectedIds.size;
    const toolbar = document.getElementById('batch-toolbar');
    const batchCount = document.getElementById('batch-count');
    if (selectedIds.size > 0) {
      toolbar.classList.remove('hidden');
      batchCount.textContent = `已选 ${selectedIds.size} 项`;
    } else {
      toolbar.classList.add('hidden');
    }
  }

  function toggleSelect(id, checked) {
    if (checked) selectedIds.add(id);
    else selectedIds.delete(id);
    updateSelectionUI();
  }

  function clearSelection() {
    selectedIds.clear();
    document.querySelectorAll('.row-chk').forEach(c => c.checked = false);
    document.getElementById('chk-select-all').checked = false;
    updateSelectionUI();
  }

  /* ── Tag filter ── */
  async function loadTagFilter() {
    try {
      const data = await apiJson('/kb/tags');
      const sel = document.getElementById('kb-tag-filter');
      // Remove old options except first
      while (sel.options.length > 1) sel.remove(1);
      (data.tags || []).forEach(tag => {
        const opt = document.createElement('option');
        opt.value = tag; opt.textContent = tag;
        sel.appendChild(opt);
      });
      document.getElementById('kb-stat-tags').textContent = (data.tags || []).length;
    } catch {}
  }

  /* ── Stats ── */
  async function loadStats() {
    try {
      const data = await apiJson('/kb/stats');
      document.getElementById('kb-stat-sources').textContent = data.total_sources;
      document.getElementById('kb-stat-chunks').textContent = data.total_chunks;
    } catch {}
  }

  /* ── Source row HTML ── */
  function sourceRowHtml(s) {
    const checked = selectedIds.has(s.id) ? 'checked' : '';
    return `
      <tr class="border-b border-slate-800 hover:bg-slate-800/40 transition-colors" data-id="${s.id}">
        <td class="px-4 py-3">
          <input type="checkbox" class="row-chk rounded border-slate-600 bg-slate-800 text-brand focus:ring-0 cursor-pointer"
            data-id="${s.id}" ${checked} />
        </td>
        <td class="px-4 py-3 text-slate-200 max-w-[260px]">
          <button class="btn-view-chunks text-left hover:text-brand transition-colors truncate block max-w-full text-sm"
            data-id="${s.id}" data-name="${escapeHtml(s.name)}">${escapeHtml(s.name)}</button>
          ${s.tags?.length ? `<div class="flex flex-wrap gap-1 mt-1">${s.tags.map(t =>
            `<span class="tag-pill text-xs bg-slate-800 text-slate-400 px-1.5 rounded-full cursor-pointer hover:bg-slate-700"
               data-tag="${escapeHtml(t)}">${escapeHtml(t)}</span>`).join('')}</div>` : ''}
        </td>
        <td class="px-4 py-3 hidden md:table-cell">
          <span class="text-xs ${typeColor(s.type)} uppercase">${typeIcon(s.type)} ${s.type}</span>
        </td>
        <td class="px-4 py-3 hidden lg:table-cell text-slate-500 text-xs">
          ${new Date(s.created_at).toLocaleDateString()}
        </td>
        <td class="px-4 py-3">${statusBadge(s.status)}</td>
        <td class="px-4 py-3 flex items-center gap-2">
          <button class="btn-edit-tags text-slate-500 hover:text-brand text-xs transition-colors" data-id="${s.id}" data-name="${escapeHtml(s.name)}" data-tags="${escapeHtml(JSON.stringify(s.tags||[]))}">标签</button>
          <button class="btn-delete-source text-slate-600 hover:text-red-400 text-xs transition-colors" data-id="${s.id}">删除</button>
        </td>
      </tr>`;
  }

  /* ── List view ── */
  async function loadSources() {
    const tbody = document.getElementById('kb-tbody');
    tbody.innerHTML = `<tr><td colspan="6" class="px-4 py-8 text-center text-slate-600 text-sm">加载中…</td></tr>`;
    try {
      const tagParam = filterTag ? `&filter_tag=${encodeURIComponent(filterTag)}` : '';
      const data = await apiJson(`/kb/sources?limit=${pageSize}&offset=${page * pageSize}${tagParam}`);
      allSources = data.sources || [];

      document.getElementById('kb-prev').disabled = page === 0;
      document.getElementById('kb-next').disabled = allSources.length < pageSize;
      document.getElementById('kb-page-info').textContent = `第 ${page + 1} 页`;

      const filtered = filterText
        ? allSources.filter(s => s.name.toLowerCase().includes(filterText))
        : allSources;

      if (!filtered.length) {
        tbody.innerHTML = `<tr><td colspan="6" class="px-4 py-8 text-center text-slate-600 text-sm">未找到来源</td></tr>`;
        return;
      }

      tbody.innerHTML = filtered.map(sourceRowHtml).join('');
      bindTableEvents(tbody);
    } catch {}
  }

  /* ── Grouped view ── */
  async function loadGroupView() {
    const container = document.getElementById('kb-group-view');
    container.innerHTML = '<p class="text-slate-600 text-sm">加载中…</p>';
    try {
      // Fetch all (up to 500 for grouping)
      const tagParam = filterTag ? `&filter_tag=${encodeURIComponent(filterTag)}` : '';
      const data = await apiJson(`/kb/sources?limit=500&offset=0${tagParam}`);
      let sources = data.sources || [];
      if (filterText) sources = sources.filter(s => s.name.toLowerCase().includes(filterText));

      if (!sources.length) {
        container.innerHTML = '<p class="text-slate-600 text-sm">未找到来源</p>';
        return;
      }

      let groups = {};
      if (viewMode === 'type') {
        sources.forEach(s => {
          const key = s.type || 'other';
          if (!groups[key]) groups[key] = [];
          groups[key].push(s);
        });
      } else {
        // by tag
        const untagged = [];
        sources.forEach(s => {
          if (!s.tags || !s.tags.length) { untagged.push(s); return; }
          s.tags.forEach(t => {
            if (!groups[t]) groups[t] = [];
            groups[t].push(s);
          });
        });
        if (untagged.length) groups['（未标签）'] = untagged;
      }

      // Sort group keys
      const sortedKeys = Object.keys(groups).sort();
      container.innerHTML = sortedKeys.map(key => {
        const list = groups[key];
        const label = viewMode === 'type'
          ? `${typeIcon(key)} ${key.toUpperCase()} <span class="text-slate-500 font-normal">(${list.length})</span>`
          : `🏷 ${escapeHtml(key)} <span class="text-slate-500 font-normal">(${list.length})</span>`;
        return `
          <div class="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
            <div class="flex items-center justify-between px-4 py-2.5 border-b border-slate-800 cursor-pointer group-header"
                 data-group="${escapeHtml(key)}">
              <span class="text-sm font-semibold text-slate-200">${label}</span>
              <button class="btn-select-group text-xs text-slate-500 hover:text-brand transition-colors" data-ids="${list.map(s=>s.id).join(',')}">全选该组</button>
            </div>
            <table class="w-full text-sm">
              <tbody class="group-tbody" data-group="${escapeHtml(key)}">
                ${list.map(sourceRowHtml).join('')}
              </tbody>
            </table>
          </div>`;
      }).join('');

      container.querySelectorAll('tbody').forEach(tb => bindTableEvents(tb));
      container.querySelectorAll('.btn-select-group').forEach(btn => {
        btn.addEventListener('click', e => {
          e.stopPropagation();
          const ids = btn.dataset.ids.split(',').filter(Boolean);
          ids.forEach(id => { selectedIds.add(id); });
          container.querySelectorAll('.row-chk').forEach(c => {
            if (ids.includes(c.dataset.id)) c.checked = true;
          });
          updateSelectionUI();
        });
      });

    } catch(e) {
      container.innerHTML = `<p class="text-red-400 text-sm">加载失败：${e.message}</p>`;
    }
  }

  /* ── Bind table row events ── */
  function bindTableEvents(tbody) {
    tbody.querySelectorAll('.row-chk').forEach(chk => {
      chk.addEventListener('change', e => toggleSelect(chk.dataset.id, e.target.checked));
    });
    tbody.querySelectorAll('.btn-view-chunks').forEach(btn => {
      btn.addEventListener('click', () => openChunksDrawer(btn.dataset.id, btn.dataset.name));
    });
    tbody.querySelectorAll('.btn-delete-source').forEach(btn => {
      btn.addEventListener('click', () => openDeleteModal(btn.dataset.id));
    });
    tbody.querySelectorAll('.btn-edit-tags').forEach(btn => {
      btn.addEventListener('click', () => openTagEdit(btn.dataset.id, btn.dataset.name, btn.dataset.tags));
    });
    tbody.querySelectorAll('.tag-pill').forEach(pill => {
      pill.addEventListener('click', () => {
        document.getElementById('kb-tag-filter').value = pill.dataset.tag;
        filterTag = pill.dataset.tag;
        page = 0;
        render();
      });
    });
  }

  /* ── Render dispatcher ── */
  function render() {
    clearSelection();
    const listView = document.getElementById('kb-list-view');
    const groupView = document.getElementById('kb-group-view');
    const pagDiv = listView.querySelector('.flex.items-center.justify-between');
    if (viewMode === 'list') {
      listView.classList.remove('hidden');
      groupView.classList.add('hidden');
      loadSources();
    } else {
      listView.classList.add('hidden');
      groupView.classList.remove('hidden');
      loadGroupView();
    }
  }

  /* ── View mode buttons ── */
  document.querySelectorAll('.view-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active-view', 'bg-slate-700', 'text-white'));
      btn.classList.add('active-view', 'bg-slate-700', 'text-white');
      viewMode = btn.id.replace('btn-view-', '');
      render();
    });
  });
  // Init first active
  document.getElementById('btn-view-list').classList.add('bg-slate-700', 'text-white');

  /* ── Select all ── */
  document.getElementById('chk-select-all').addEventListener('change', e => {
    allSources.forEach(s => {
      if (e.target.checked) selectedIds.add(s.id);
      else selectedIds.delete(s.id);
    });
    document.querySelectorAll('.row-chk').forEach(c => c.checked = e.target.checked);
    updateSelectionUI();
  });

  /* ── Batch toolbar actions ── */
  async function batchTag(mode) {
    const input = document.getElementById('batch-tag-input').value.trim();
    const tags = parseTags(input);
    if (mode !== 'remove' && !tags.length) { toast('请输入至少一个标签', 'error'); return; }
    if (!selectedIds.size) { toast('请先选择来源', 'error'); return; }
    try {
      await apiJson('/kb/sources/batch-tag', {
        method: 'POST',
        body: JSON.stringify({ ids: [...selectedIds], tags, mode }),
      });
      toast(`已${mode==='add'?'追加':mode==='replace'?'替换':'移除'} ${selectedIds.size} 个来源的标签`, 'success');
      clearSelection();
      loadTagFilter();
      render();
    } catch(e) { toast('操作失败：' + e.message, 'error'); }
  }

  document.getElementById('btn-batch-add-tag').addEventListener('click', () => batchTag('add'));
  document.getElementById('btn-batch-replace-tag').addEventListener('click', () => batchTag('replace'));
  document.getElementById('btn-batch-remove-tag').addEventListener('click', () => batchTag('remove'));

  document.getElementById('btn-batch-delete').addEventListener('click', () => {
    if (!selectedIds.size) return;
    deleteBatchMode = true;
    document.getElementById('delete-modal-title').textContent = `批量删除 ${selectedIds.size} 个来源`;
    document.getElementById('delete-modal-desc').textContent = '此操作将永久删除所选来源及其全部片段，无法撤销。';
    document.getElementById('delete-modal').classList.remove('hidden');
  });

  document.getElementById('btn-batch-clear').addEventListener('click', clearSelection);

  /* ── Chunks drawer ── */
  async function openChunksDrawer(sourceId, sourceName) {
    const drawer = document.getElementById('chunks-drawer');
    const content = document.getElementById('drawer-content');
    document.getElementById('drawer-title').textContent = sourceName;
    content.innerHTML = '<p class="text-slate-600 text-sm">加载片段中…</p>';
    drawer.classList.remove('hidden');
    try {
      const data = await apiJson(`/kb/sources/${sourceId}/chunks?limit=50`);
      const chunks = data.chunks || [];
      if (!chunks.length) {
        content.innerHTML = '<p class="text-slate-600 text-sm">未找到片段</p>';
        return;
      }
      content.innerHTML = chunks.map(c => `
        <div class="bg-slate-900 rounded-lg p-3 border border-slate-800">
          <div class="flex items-center justify-between mb-1.5">
            <span class="text-xs text-slate-500">片段 #${c.chunk_index}</span>
            <span class="text-xs font-mono text-slate-700">${c.id.slice(0, 8)}</span>
          </div>
          <p class="text-xs text-slate-300 leading-relaxed whitespace-pre-wrap">${escapeHtml(c.content.slice(0, 500))}${c.content.length > 500 ? '…' : ''}</p>
        </div>
      `).join('');
    } catch {
      content.innerHTML = '<p class="text-red-400 text-sm">加载片段失败</p>';
    }
  }

  document.getElementById('btn-close-drawer').addEventListener('click', () => {
    document.getElementById('chunks-drawer').classList.add('hidden');
  });

  /* ── Tag edit modal ── */
  function openTagEdit(id, name, tagsJson) {
    tagEditTargetId = id;
    document.getElementById('tag-edit-source-name').textContent = name;
    let tags = [];
    try { tags = JSON.parse(tagsJson); } catch {}
    document.getElementById('tag-edit-input').value = tags.join(', ');
    document.getElementById('tag-edit-modal').classList.remove('hidden');
  }

  document.getElementById('btn-cancel-tag-edit').addEventListener('click', () => {
    document.getElementById('tag-edit-modal').classList.add('hidden');
    tagEditTargetId = null;
  });

  document.getElementById('btn-confirm-tag-edit').addEventListener('click', async () => {
    if (!tagEditTargetId) return;
    const tags = parseTags(document.getElementById('tag-edit-input').value);
    try {
      await apiJson(`/kb/sources/${tagEditTargetId}/tags`, {
        method: 'PATCH',
        body: JSON.stringify({ tags }),
      });
      toast('标签已更新', 'success');
      document.getElementById('tag-edit-modal').classList.add('hidden');
      tagEditTargetId = null;
      loadTagFilter();
      render();
    } catch { toast('更新标签失败', 'error'); }
  });

  /* ── Delete modal ── */
  function openDeleteModal(sourceId) {
    deleteBatchMode = false;
    deleteTargetId = sourceId;
    document.getElementById('delete-modal-title').textContent = '删除来源';
    document.getElementById('delete-modal-desc').textContent = '此操作将永久删除该来源及其所有片段，无法撤销。';
    document.getElementById('delete-modal').classList.remove('hidden');
  }

  document.getElementById('btn-cancel-delete').addEventListener('click', () => {
    document.getElementById('delete-modal').classList.add('hidden');
    deleteTargetId = null;
    deleteBatchMode = false;
  });

  document.getElementById('btn-confirm-delete').addEventListener('click', async () => {
    document.getElementById('delete-modal').classList.add('hidden');
    try {
      if (deleteBatchMode) {
        const ids = [...selectedIds];
        await apiJson('/kb/sources/batch-delete', {
          method: 'POST',
          body: JSON.stringify({ ids }),
        });
        toast(`已删除 ${ids.length} 个来源`, 'success');
        clearSelection();
      } else {
        await apiJson(`/kb/sources/${deleteTargetId}`, { method: 'DELETE' });
        toast('来源已删除', 'success');
      }
      deleteTargetId = null;
      deleteBatchMode = false;
      loadStats();
      loadTagFilter();
      render();
      if (typeof refreshStats === 'function') refreshStats();
    } catch { toast('删除失败', 'error'); }
  });

  /* ── Export dropdown ── */
  document.getElementById('btn-export').addEventListener('click', () => {
    document.getElementById('export-menu').classList.toggle('hidden');
  });
  document.addEventListener('click', e => {
    if (!document.getElementById('export-wrap').contains(e.target))
      document.getElementById('export-menu').classList.add('hidden');
  });
  ['json','csv','zip'].forEach(fmt => {
    document.getElementById(`export-${fmt}`).addEventListener('click', e => {
      e.preventDefault();
      const base = (typeof API_BASE !== 'undefined' ? API_BASE : 'http://localhost:8000');
      window.open(`${base}/kb/export?fmt=${fmt}`, '_blank');
      document.getElementById('export-menu').classList.add('hidden');
    });
  });

  /* ── Filters ── */
  document.getElementById('kb-prev').addEventListener('click', () => { page--; loadSources(); });
  document.getElementById('kb-next').addEventListener('click', () => { page++; loadSources(); });
  document.getElementById('btn-kb-refresh').addEventListener('click', () => { loadStats(); loadTagFilter(); render(); });

  document.getElementById('kb-search').addEventListener('input', e => {
    filterText = e.target.value.toLowerCase();
    page = 0;
    render();
  });

  document.getElementById('kb-tag-filter').addEventListener('change', e => {
    filterTag = e.target.value;
    page = 0;
    render();
  });

  /* ── Tab switch ── */
  document.addEventListener('tab:shown', e => {
    if (e.detail === 'kb') { loadStats(); loadTagFilter(); render(); }
  });
})();
