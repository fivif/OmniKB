/* ── Search Panel ───────────────────────────────────────────── */

(function initSearch() {
  const panel = document.getElementById('tab-search');

  panel.innerHTML = `
    <div class="max-w-4xl mx-auto space-y-5">
      <div>
        <h1 class="text-2xl font-bold text-white">搜索</h1>
        <p class="text-slate-400 text-sm mt-1">对知识库进行语义、关键词或混合搜索</p>
      </div>

      <!-- Search bar -->
      <div class="flex gap-2">
        <div class="relative flex-1">
          <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
          </svg>
          <input id="search-input" type="text" placeholder="搜索知识库…"
            class="w-full bg-slate-900 border border-slate-700 rounded-xl pl-9 pr-4 py-3 text-sm text-slate-200 focus:outline-none focus:border-brand" />
        </div>
        <button id="btn-search" class="btn-primary px-5 rounded-xl text-sm font-medium">搜索</button>
      </div>

      <!-- Filters row -->
      <div class="flex flex-wrap gap-3 items-center text-sm">
        <div class="flex gap-1 bg-slate-900 p-1 rounded-lg">
          <button data-mode="hybrid"   class="search-mode-btn active-search-mode px-3 py-1 rounded text-xs font-medium transition-colors">混合</button>
          <button data-mode="semantic" class="search-mode-btn px-3 py-1 rounded text-xs font-medium transition-colors">语义</button>
          <button data-mode="bm25"     class="search-mode-btn px-3 py-1 rounded text-xs font-medium transition-colors">BM25</button>
        </div>
        <div class="flex items-center gap-2">
          <label class="text-slate-500 text-xs">结果数：</label>
          <select id="search-topk" class="bg-slate-900 border border-slate-700 rounded-lg px-2 py-1 text-xs text-slate-300 focus:outline-none">
            <option value="5">5</option>
            <option value="10" selected>10</option>
            <option value="20">20</option>
          </select>
        </div>
        <div class="flex items-center gap-2">
          <label class="text-slate-500 text-xs">来源：</label>
          <select id="search-filter-source" class="bg-slate-900 border border-slate-700 rounded-lg px-2 py-1 text-xs text-slate-300 focus:outline-none">
            <option value="">全部</option>
          </select>
        </div>
      </div>

      <!-- Results -->
      <div id="search-results" class="space-y-3"></div>
    </div>
  `;

  const style = document.createElement('style');
  style.textContent = `
    .search-mode-btn { color:#64748b; }
    .search-mode-btn:hover { color:#e2e8f0; }
    .active-search-mode { background:#4f46e5; color:#fff; }
  `;
  document.head.appendChild(style);

  let currentMode = 'hybrid';

  panel.querySelectorAll('.search-mode-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      panel.querySelectorAll('.search-mode-btn').forEach(b => b.classList.remove('active-search-mode'));
      btn.classList.add('active-search-mode');
      currentMode = btn.dataset.mode;
    });
  });

  // Populate source filter
  async function loadSources() {
    try {
      const data = await apiJson('/kb/sources?limit=100');
      const sel = document.getElementById('search-filter-source');
      (data.sources || []).forEach(s => {
        const opt = document.createElement('option');
        opt.value = s.id;
        opt.textContent = s.name.length > 30 ? s.name.slice(0, 28) + '…' : s.name;
        sel.appendChild(opt);
      });
    } catch {}
  }

  document.addEventListener('tab:shown', e => { if (e.detail === 'search') loadSources(); });

  const resultsEl = document.getElementById('search-results');

  async function doSearch() {
    const q = document.getElementById('search-input').value.trim();
    if (!q) return;
    const topK = document.getElementById('search-topk').value;
    const filterSource = document.getElementById('search-filter-source').value;

    resultsEl.innerHTML = Array(3).fill(0).map(() =>
      `<div class="bg-slate-900 rounded-xl p-4 space-y-2">
        <div class="skeleton h-3 w-1/3"></div>
        <div class="skeleton h-3 w-full"></div>
        <div class="skeleton h-3 w-5/6"></div>
      </div>`
    ).join('');

    try {
      let path = `/search?q=${encodeURIComponent(q)}&top_k=${topK}&mode=${currentMode}`;
      if (filterSource) path += `&filter_source=${filterSource}`;
      const data = await apiJson(path);

      if (!data.results.length) {
        resultsEl.innerHTML = '<p class="text-slate-500 text-sm text-center py-8">未找到相关结果</p>';
        return;
      }

      resultsEl.innerHTML = data.results.map((r, i) => {
        const src = r.metadata.source_name || r.metadata.source_url || r.metadata.source_id?.slice(0, 8) || '—';
        const score = (r.score * 100).toFixed(1);
        return `
          <div class="bg-slate-900 rounded-xl p-4 border border-slate-800 hover:border-slate-600 transition-colors">
            <div class="flex items-start justify-between gap-3 mb-2">
              <div class="flex items-center gap-2 min-w-0">
                <span class="text-xs font-mono text-brand">#${i + 1}</span>
                <span class="text-xs text-slate-400 truncate">${src}</span>
              </div>
              <span class="text-xs text-slate-600 flex-shrink-0">相关度 ${score}%</span>
            </div>
            <div class="text-sm text-slate-300 leading-relaxed line-clamp-4">${r.highlight || r.content.slice(0, 400)}</div>
            ${r.metadata.tags?.length ? `<div class="mt-2 flex flex-wrap gap-1">${r.metadata.tags.map(t => `<span class="text-xs bg-slate-800 text-slate-400 px-2 py-0.5 rounded-full">${t}</span>`).join('')}</div>` : ''}
          </div>
        `;
      }).join('');
    } catch {}
  }

  document.getElementById('btn-search').addEventListener('click', doSearch);
  document.getElementById('search-input').addEventListener('keydown', e => {
    if (e.key === 'Enter') doSearch();
  });
})();
