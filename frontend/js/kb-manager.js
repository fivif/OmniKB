/* ── KB Manager Panel ───────────────────────────────────────── */

(function initKbManager() {
  const panel = document.getElementById('tab-kb');

  panel.innerHTML = `
    <div class="max-w-5xl mx-auto space-y-5">
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-2xl font-bold text-white">知识库管理</h1>
          <p class="text-slate-400 text-sm mt-1">浏览并管理知识库来源</p>
        </div>
        <div class="flex items-center gap-3">
          <input id="kb-search" type="text" placeholder="过滤来源…"
            class="bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-300 focus:outline-none focus:border-brand w-40" />
          <select id="kb-tag-filter"
            class="bg-slate-900 border border-slate-700 rounded-lg px-2 py-1.5 text-sm text-slate-300 focus:outline-none focus:border-brand w-36">
            <option value="">所有标签</option>
          </select>
          <button id="btn-kb-refresh" class="text-slate-500 hover:text-slate-300 text-sm transition-colors">↺</button>
        </div>
      </div>

      <!-- Stats -->
      <div class="grid grid-cols-2 gap-3">
        <div class="bg-slate-900 rounded-xl p-4">
          <div class="text-2xl font-bold text-white" id="kb-stat-sources">—</div>
          <div class="text-slate-500 text-xs mt-1">来源总数</div>
        </div>
        <div class="bg-slate-900 rounded-xl p-4">
          <div class="text-2xl font-bold text-white" id="kb-stat-chunks">—</div>
          <div class="text-slate-500 text-xs mt-1">片段总数</div>
        </div>
      </div>

      <!-- Sources table -->
      <div class="bg-slate-900 rounded-xl overflow-hidden border border-slate-800">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-slate-800 text-left text-xs text-slate-500 uppercase">
              <th class="px-4 py-3">名称</th>
              <th class="px-4 py-3 hidden md:table-cell">类型</th>
              <th class="px-4 py-3 hidden lg:table-cell">创建时间</th>
              <th class="px-4 py-3">状态</th>
              <th class="px-4 py-3 w-20">操作</th>
            </tr>
          </thead>
          <tbody id="kb-tbody"></tbody>
        </table>
      </div>

      <!-- Pagination -->
      <div class="flex items-center justify-between text-sm">
        <button id="kb-prev" class="text-slate-500 hover:text-slate-300 disabled:opacity-30 transition-colors" disabled>← 上一页</button>
        <span id="kb-page-info" class="text-slate-500 text-xs"></span>
        <button id="kb-next" class="text-slate-500 hover:text-slate-300 disabled:opacity-30 transition-colors">下一页 →</button>
      </div>
    </div>

    <!-- Delete confirm modal -->
    <div id="delete-modal" class="hidden fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div class="bg-slate-900 border border-slate-700 rounded-2xl p-6 max-w-sm w-full mx-4 space-y-4">
        <h3 class="font-semibold text-white">删除来源</h3>
        <p class="text-slate-400 text-sm">此操作将永久删除该来源及其所有片段，无法撤销。</p>
        <div class="flex gap-3 justify-end">
          <button id="btn-cancel-delete" class="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 transition-colors">取消</button>
          <button id="btn-confirm-delete" class="px-4 py-2 text-sm bg-red-700 hover:bg-red-600 text-white rounded-lg transition-colors">确认删除</button>
        </div>
      </div>
    </div>

    <!-- Chunks drawer -->
    <div id="chunks-drawer" class="hidden fixed inset-y-0 right-0 w-full max-w-xl bg-slate-950 border-l border-slate-800 flex flex-col z-40">
      <div class="flex items-center justify-between px-5 py-4 border-b border-slate-800">
        <h3 class="font-semibold text-white text-sm" id="drawer-title">片段列表</h3>
        <button id="btn-close-drawer" class="text-slate-500 hover:text-slate-300 text-lg leading-none">✕</button>
      </div>
      <div id="drawer-content" class="flex-1 overflow-y-auto p-5 space-y-3"></div>
    </div>
  `;

  let page = 0;
  const pageSize = 20;
  let deleteTargetId = null;
  let filterText = '';
  let filterTag = '';

  async function loadTagFilter() {
    try {
      const data = await apiJson('/kb/tags');
      const sel = document.getElementById('kb-tag-filter');
      (data.tags || []).forEach(tag => {
        const opt = document.createElement('option');
        opt.value = tag;
        opt.textContent = tag;
        sel.appendChild(opt);
      });
    } catch {}
  }

  async function loadStats() {
    try {
      const data = await apiJson('/kb/stats');
      document.getElementById('kb-stat-sources').textContent = data.total_sources;
      document.getElementById('kb-stat-chunks').textContent = data.total_chunks;
    } catch {}
  }

  async function loadSources() {
    const tbody = document.getElementById('kb-tbody');
    tbody.innerHTML = `<tr><td colspan="5" class="px-4 py-8 text-center text-slate-600 text-sm">加载中…</td></tr>`;

    try {
      const tagParam = filterTag ? `&filter_tag=${encodeURIComponent(filterTag)}` : '';
      const data = await apiJson(`/kb/sources?limit=${pageSize}&offset=${page * pageSize}${tagParam}`);
      const sources = data.sources || [];

      document.getElementById('kb-prev').disabled = page === 0;
      document.getElementById('kb-next').disabled = sources.length < pageSize;
      document.getElementById('kb-page-info').textContent = `第 ${page + 1} 页`;

      const filtered = filterText
        ? sources.filter(s => s.name.toLowerCase().includes(filterText))
        : sources;
      if (!filtered.length) {
        tbody.innerHTML = `<tr><td colspan="5" class="px-4 py-8 text-center text-slate-600 text-sm">未找到来源</td></tr>`;
        return;
      }

      tbody.innerHTML = filtered.map(s => `
        <tr class="border-b border-slate-800 hover:bg-slate-800/40 transition-colors">
          <td class="px-4 py-3 text-slate-200 max-w-xs">
            <button class="btn-view-chunks text-left hover:text-brand transition-colors truncate block max-w-full" data-id="${s.id}" data-name="${escapeHtml(s.name)}">
              ${escapeHtml(s.name)}
            </button>
            ${s.tags?.length ? `<div class="flex flex-wrap gap-1 mt-1">${s.tags.map(t => `<span class="text-xs bg-slate-800 text-slate-500 px-1.5 rounded-full">${t}</span>`).join('')}</div>` : ''}
          </td>
          <td class="px-4 py-3 hidden md:table-cell">
            <span class="text-xs text-slate-500 uppercase">${s.type}</span>
          </td>
          <td class="px-4 py-3 hidden lg:table-cell text-slate-500 text-xs">
            ${new Date(s.created_at).toLocaleDateString()}
          </td>
          <td class="px-4 py-3">${statusBadge(s.status)}</td>
          <td class="px-4 py-3">
            <button class="btn-delete-source text-slate-600 hover:text-red-400 transition-colors text-xs" data-id="${s.id}">删除</button>
          </td>
        </tr>
      `).join('');

      // Bind chunk viewer buttons
      tbody.querySelectorAll('.btn-view-chunks').forEach(btn => {
        btn.addEventListener('click', () => openChunksDrawer(btn.dataset.id, btn.dataset.name));
      });

      // Bind delete buttons
      tbody.querySelectorAll('.btn-delete-source').forEach(btn => {
        btn.addEventListener('click', () => openDeleteModal(btn.dataset.id));
      });
    } catch {}
  }

  function escapeHtml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // Chunks drawer
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
          <p class="text-xs text-slate-300 leading-relaxed">${escapeHtml(c.content.slice(0, 500))}${c.content.length > 500 ? '…' : ''}</p>
        </div>
      `).join('');
    } catch {
      content.innerHTML = '<p class="text-red-400 text-sm">加载片段失败</p>';
    }
  }

  document.getElementById('btn-close-drawer').addEventListener('click', () => {
    document.getElementById('chunks-drawer').classList.add('hidden');
  });

  // Delete modal
  function openDeleteModal(sourceId) {
    deleteTargetId = sourceId;
    document.getElementById('delete-modal').classList.remove('hidden');
  }

  document.getElementById('btn-cancel-delete').addEventListener('click', () => {
    document.getElementById('delete-modal').classList.add('hidden');
    deleteTargetId = null;
  });

  document.getElementById('btn-confirm-delete').addEventListener('click', async () => {
    if (!deleteTargetId) return;
    try {
      await apiJson(`/kb/sources/${deleteTargetId}`, { method: 'DELETE' });
      toast('来源已删除', 'success');
      document.getElementById('delete-modal').classList.add('hidden');
      deleteTargetId = null;
      loadSources();
      loadStats();
      refreshStats();
    } catch {}
  });

  document.getElementById('kb-prev').addEventListener('click', () => { page--; loadSources(); });
  document.getElementById('kb-next').addEventListener('click', () => { page++; loadSources(); });
  document.getElementById('btn-kb-refresh').addEventListener('click', () => { loadSources(); loadStats(); });

  // Text filter
  document.getElementById('kb-search').addEventListener('input', e => {
    filterText = e.target.value.toLowerCase();
    page = 0;
    loadSources();
  });

  // Tag filter
  document.getElementById('kb-tag-filter').addEventListener('change', e => {
    filterTag = e.target.value;
    page = 0;
    loadSources();
  });

  document.addEventListener('tab:shown', e => {
    if (e.detail === 'kb') { loadSources(); loadStats(); loadTagFilter(); }
  });
})();
