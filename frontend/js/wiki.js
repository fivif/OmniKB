/* ── Wiki tab controller ─────────────────────────────────────────────
 *
 * Mounts a three-pane resizable layout into #tab-wiki on first show:
 *   [tree] | [markdown preview] | [graph]
 *
 * Side panes are collapsible and resizable via drag dividers.
 * Graph can be maximized to full width.
 *
 * Backend contract (read-only — see backend/api/wiki.py):
 *   GET /wiki/stats              — counts + worker
 *   GET /wiki/pages?type=...     — page metadata, paginated
 *   GET /wiki/pages/{id}         — single page incl. body
 *   GET /wiki/graph              — full graph (capped)
 *
 * No external state aside from the currently-selected page id; all
 * other state (filters, search) lives in the DOM.
 *
 * Hard requirements when this script loads:
 *   - window.OmniKBApp.{loadSettings, showTab}
 *   - marked.parse(...) (from the CDN <script>)
 *   - d3.js globals (for the force graph)
 *
 * If D3 fails to load we degrade gracefully — the tree + preview
 * still work; only the graph pane shows an error placeholder.
 */
(function () {
  'use strict';

  const TAB_ID = 'tab-wiki';
  const SECTIONS = [
    { type: 'overview', label: '总览' },
    { type: 'entity',   label: '实体' },
    { type: 'concept',  label: '概念' },
    { type: 'source',   label: '来源' },
    { type: 'query',    label: '查询' },
  ];

  let _mounted = false;
  let _currentPageId = null;
  let _allPages = [];   // last loaded page list, used to resolve wikilinks
  let _d3Graph = null;   // { svg, simulation, zoom, nodes }
  let _graphResizeTimer = null;  // debounce timer for graph re-render on resize
  let _wikiTabVisible = false;    // whether wiki tab is currently visible

  /* ── API helpers (use the global one if available) ───────── */
  function apiBase() {
    try {
      if (window.OmniKBApp && window.OmniKBApp.loadSettings) {
        var s = window.OmniKBApp.loadSettings();
        if (s && s.api_base) return s.api_base;
      }
    } catch(e) {}
    return '';
  }
  async function apiGet(path) {
    const res = await fetch(apiBase() + path, { cache: 'no-store' });
    if (!res.ok) {
      const detail = await res.text().catch(() => '');
      throw new Error(`${res.status} ${res.statusText}: ${detail.slice(0, 120)}`);
    }
    return res.json();
  }
  async function apiPost(path, body) {
    const res = await fetch(apiBase() + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const detail = await res.text().catch(() => '');
      throw new Error(`${res.status} ${res.statusText}: ${detail.slice(0, 180)}`);
    }
    return res.json();
  }

  /* ── Sync panel CSS ────────────────────────────────────────── */
  (function _injectSyncCSS() {
    const style = document.createElement('style');
    style.textContent = `
.wiki-sync-panel { position: fixed; top:0; right:0; width:380px; height:100vh; background:var(--bg-card); border-left:1px solid var(--bd); z-index:100; padding:16px; overflow-y:auto; display:none; box-shadow:-4px 0 24px rgba(0,0,0,.25); }
.wiki-sync-panel.open { display:flex; flex-direction:column; }
@media (max-width:480px) { .wiki-sync-panel { width:100vw; left:0; } }
.wiki-sync-row { display:flex; align-items:flex-start; gap:6px; padding:5px 4px; cursor:pointer; border-radius:6px; transition:background .15s; }
.wiki-sync-row:hover { background:var(--bg-muted); }
.wiki-sync-row input[type="checkbox"] { margin:2px 0 0; flex-shrink:0; }
.wiki-sync-row label { font-size:12px; color:var(--t1); cursor:pointer; line-height:1.4; word-break:break-all; flex:1; }
.wiki-sync-panel h4 { font-size:13px; margin:0 0 12px; color:var(--t1); }
.wiki-sync-panel .wiki-sync-actions { display:flex; gap:8px; margin-top:12px; }
.wiki-sync-panel .wiki-sync-btn { font-size:12px; padding:6px 14px; border-radius:6px; cursor:pointer; border:1px solid var(--accent); background:var(--accent); color:#fff; }
.wiki-sync-panel .wiki-sync-btn:hover { filter:brightness(1.15); }
.wiki-sync-panel .wiki-sync-btn:disabled { opacity:0.5; cursor:not-allowed; }
.wiki-sync-panel .wiki-sync-btn-cancel { background:transparent; color:var(--t2); border:1px solid var(--bd-subtle); }
.wiki-sync-panel .wiki-sync-btn-cancel:hover { color:var(--t1); background:var(--bg-base); }
.wiki-sync-panel .wiki-sync-toggle-row { display:flex; align-items:center; gap:6px; margin-bottom:10px; font-size:11px; color:var(--t3); }
.wiki-sync-panel .wiki-sync-toggle-row a { color:var(--accent); cursor:pointer; text-decoration:none; }
.wiki-sync-panel .wiki-sync-toggle-row a:hover { text-decoration:underline; }
.wiki-sync-panel .wiki-sync-list { flex:1; overflow-y:auto; list-style:none; margin:0 -4px; padding:0 4px; }
.wiki-sync-backdrop { display:none; position:fixed; inset:0; background:rgba(0,0,0,.35); z-index:99; }
.wiki-sync-backdrop.open { display:block; }
`;
    document.head.appendChild(style);
  })();

  /* ── Mount the layout into #tab-wiki ──────────────────────── */
  function mount() {
    const root = document.getElementById(TAB_ID);
    if (!root || _mounted) return;
    _mounted = true;

    root.innerHTML = `
      <aside class="wiki-pane wiki-tree" id="wiki-tree" style="position:relative;">
        <div class="wiki-pane-header">
          <button class="wiki-collapse-btn" id="wiki-tree-collapse" title="收起页面树">
            <i data-lucide="chevron-left"></i>
          </button>
          <h3>页面</h3>
          <div style="display:flex; gap:6px; margin-left:auto;">
            <button class="wiki-refresh-btn" id="wiki-sync-btn" title="同步来源到 Wiki">
              <i data-lucide="folder-sync"></i>
            </button>
            <button class="wiki-refresh-btn" id="wiki-insights-btn" title="健康检查 / 洞察">
              <i data-lucide="activity"></i>
            </button>
            <button class="wiki-refresh-btn" id="wiki-refresh-btn" title="刷新">
              <i data-lucide="refresh-cw"></i>
            </button>
          </div>
        </div>
        <div class="wiki-tree-search-wrap" id="wiki-tree-search-wrap">
          <input type="text" class="wiki-search" id="wiki-search" placeholder="搜索页面…" autocomplete="off">
          <button class="wiki-search-clear" id="wiki-search-clear" title="清除搜索" style="display:none;">×</button>
        </div>
        <div class="wiki-progress" id="wiki-progress">
          <i data-lucide="loader-2" class="wiki-progress-spinner"></i>
          <span id="wiki-progress-text">Wiki 生成中…</span>
          <div class="wiki-progress-bar"><div class="wiki-progress-fill"></div></div>
        </div>
        <div class="wiki-pane-body" id="wiki-tree-body">
          <div class="wiki-tree-empty">加载中…</div>
        </div>
        <div class="wiki-sync-backdrop" id="wiki-sync-backdrop"></div>
        <div class="wiki-sync-panel" id="wiki-sync-panel">
          <h4>选择知识库来源同步到 Wiki</h4>
          <div class="wiki-sync-toggle-row">
            <a id="wiki-sync-toggle-all">全选 / 取消全选</a>
          </div>
          <ul class="wiki-sync-list" id="wiki-sync-list"></ul>
          <div class="wiki-sync-actions">
            <button class="wiki-sync-btn" id="wiki-sync-start">开始同步</button>
            <button class="wiki-sync-btn wiki-sync-btn-cancel" id="wiki-sync-close">关闭</button>
          </div>
        </div>
      </aside>

      <div class="wiki-resizer" id="wiki-resizer-tree" data-target="wiki-tree"></div>

      <main class="wiki-pane wiki-preview" id="wiki-preview">
        <div class="wiki-pane-header">
          <button class="wiki-expand-btn" id="expand-tree-btn" title="展开页面树" style="display:none;">
            <i data-lucide="panel-left"></i>
          </button>
          <h3 id="wiki-preview-title">未选择页面</h3>
          <span class="wiki-stat" id="wiki-preview-stat"></span>
          <div style="margin-left:auto; display:flex; gap:6px;">
            <button class="wiki-refresh-btn wiki-research-btn" id="wiki-research-btn"
                    title="Deep Research — 从 web 主动补充本页" hidden>
              <i data-lucide="telescope"></i>
            </button>
          </div>
          <button class="wiki-expand-btn" id="expand-graph-btn" title="展开关系图谱" style="display:none;">
            <i data-lucide="panel-right"></i>
          </button>
        </div>
        <div class="wiki-research-panel" id="wiki-research-panel" hidden></div>
        <div class="wiki-pane-body" id="wiki-preview-body">
          <div class="wiki-preview-empty">
            选择左侧任意页面查看内容。<br>
            尚无页面？先到「上传」摄入一份资料，wiki worker 会自动生成。
          </div>
        </div>
      </main>

      <div class="wiki-resizer" id="wiki-resizer-graph" data-target="wiki-graph"></div>

      <aside class="wiki-pane wiki-graph" id="wiki-graph">
        <div class="wiki-pane-header">
          <h3>关系图谱</h3>
          <span class="wiki-stat" id="wiki-graph-stat">—</span>
          <button class="wiki-maximize-btn" id="wiki-maximize-btn" title="最大化图谱">
            <i data-lucide="maximize-2" class="wiki-icon-max"></i>
            <i data-lucide="minimize-2" class="wiki-icon-min" style="display:none;"></i>
          </button>
          <button class="wiki-collapse-btn" id="wiki-graph-collapse" title="收起图谱">
            <i data-lucide="chevron-right"></i>
          </button>
        </div>
        <div class="wiki-pane-body">
          <div class="wiki-graph-canvas" id="wiki-graph-canvas">
            <div class="wiki-graph-empty">加载中…</div>
          </div>
        </div>
        <div class="wiki-graph-toolbar">
          <button id="wiki-graph-zoom-in"  title="放大">＋</button>
          <button id="wiki-graph-zoom-out" title="缩小">−</button>
          <button id="wiki-graph-fit"      title="适配">⤧</button>
        </div>
      </aside>
    `;

    if (window.lucide) window.lucide.createIcons();

    /* ── Wire standard buttons ──────────────────────────────── */
    document.getElementById('wiki-refresh-btn')
      .addEventListener('click', refreshAll);
    document.getElementById('wiki-insights-btn')
      .addEventListener('click', showInsights);
    document.getElementById('wiki-sync-btn')
      .addEventListener('click', openSyncPanel);
    document.getElementById('wiki-sync-close')
      .addEventListener('click', closeSyncPanel);
    document.getElementById('wiki-sync-toggle-all')
      .addEventListener('click', toggleAllSources);
    document.getElementById('wiki-sync-start')
      .addEventListener('click', startSync);
    document.getElementById('wiki-sync-backdrop')
      .addEventListener('click', closeSyncPanel);
    document.getElementById('wiki-research-btn')
      .addEventListener('click', () => toggleResearchPanel(_currentPageId));

    /* ── Wire search ─────────────────────────────────────────── */
    var searchInput = document.getElementById('wiki-search');
    var searchClear = document.getElementById('wiki-search-clear');
    var searchTimer = null;
    if (searchInput) {
      searchInput.addEventListener('input', function() {
        var val = this.value.trim();
        if (searchClear) searchClear.style.display = val ? 'inline-flex' : 'none';
        if (searchTimer) clearTimeout(searchTimer);
        searchTimer = setTimeout(function() { filterTree(val); }, 250);
      });
      searchInput.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') { this.value = ''; this.blur(); filterTree(''); if (searchClear) searchClear.style.display = 'none'; }
      });
    }
    if (searchClear) {
      searchClear.addEventListener('click', function() {
        if (searchInput) { searchInput.value = ''; searchInput.focus(); }
        filterTree('');
        this.style.display = 'none';
      });
    }

    /* ── Graph toolbar ──────────────────────────────────────── */
    document.getElementById('wiki-graph-zoom-in')
      .addEventListener('click', () => { if (_d3Graph) _d3Graph.svg.transition().duration(300).call(_d3Graph.zoom.scaleBy, 1.4); });
    document.getElementById('wiki-graph-zoom-out')
      .addEventListener('click', () => { if (_d3Graph) _d3Graph.svg.transition().duration(300).call(_d3Graph.zoom.scaleBy, 0.7); });
    document.getElementById('wiki-graph-fit')
      .addEventListener('click', () => { if (_d3Graph) _fitGraphToBounds(); });

    /* ── Wire collapse / expand / maximize ──────────────────── */
    document.getElementById('wiki-tree-collapse')
      .addEventListener('click', () => togglePane('wiki-tree'));
    document.getElementById('wiki-graph-collapse')
      .addEventListener('click', () => togglePane('wiki-graph'));
    document.getElementById('expand-tree-btn')
      .addEventListener('click', () => togglePane('wiki-tree'));
    document.getElementById('expand-graph-btn')
      .addEventListener('click', () => togglePane('wiki-graph'));
    document.getElementById('wiki-maximize-btn')
      .addEventListener('click', toggleMaximizeGraph);

    /* ── Wire resizers ──────────────────────────────────────── */
    initResizers();

    /* ── Graph resize observer (ResizeObserver) ─────────────── */
    initGraphResizeObserver();
  }

  /* ── Resize dividers between panes ─────────────────────────── */
  function initResizers() {
    document.querySelectorAll('.wiki-resizer').forEach(resizer => {
      let startX, startW;
      const targetId = resizer.dataset.target;
      if (!targetId) return;

      resizer.addEventListener('mousedown', (e) => {
        e.preventDefault();
        const target = document.getElementById(targetId);
        if (!target || target.classList.contains('collapsed')) return;

        startX = e.clientX;
        startW = target.getBoundingClientRect().width;
        resizer.classList.add('is-dragging');
        document.body.classList.add('wiki-is-resizing');

        const onMove = (ev) => {
          const delta = ev.clientX - startX;
          // For the graph (right side), dragging left makes it wider
          const effectiveDelta = targetId === 'wiki-graph' ? -delta : delta;
          const newW = startW + effectiveDelta;
          const maxW = window.innerWidth * 0.55;
          if (newW >= 200 && newW <= maxW) {
            target.style.flexBasis = newW + 'px';
            target.style.flexGrow = '0';
            target.style.flexShrink = '0';
          }
          // Live-update graph viewBox during drag
          if (targetId === 'wiki-graph') scheduleGraphResize();
        };

        const onUp = () => {
          document.removeEventListener('mousemove', onMove);
          document.removeEventListener('mouseup', onUp);
          resizer.classList.remove('is-dragging');
          document.body.classList.remove('wiki-is-resizing');
          if (targetId === 'wiki-graph') scheduleGraphResize();
        };

        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
      });
    });
  }

  /* ── Collapse / expand a side pane ─────────────────────────── */
  function togglePane(targetId) {
    const pane = document.getElementById(targetId);
    if (!pane) return;

    // Before collapsing a maximized graph, restore the other panes first
    if (targetId === 'wiki-graph' && !pane.classList.contains('collapsed') && pane.classList.contains('maximized')) {
      toggleMaximizeGraph();  // restore from maximized, then re-run
      if (pane.classList.contains('collapsed')) return; // restore also collapsed it
      // Now pane is not maximized and not collapsed, proceed to collapse
    }

    const isCollapsing = !pane.classList.contains('collapsed');
    pane.classList.toggle('collapsed');

    // Toggle the associated resizer visibility
    const resizerId = targetId === 'wiki-tree' ? 'wiki-resizer-tree' : 'wiki-resizer-graph';
    const resizer = document.getElementById(resizerId);
    if (resizer) {
      resizer.classList.toggle('is-hidden', isCollapsing);
      // Also force inline display toggle as a fallback for :has() support
      resizer.style.display = isCollapsing ? 'none' : '';
    }

    // Show/hide the expand button in the preview header
    const expandBtnId = targetId === 'wiki-tree' ? 'expand-tree-btn' : 'expand-graph-btn';
    const expandBtn = document.getElementById(expandBtnId);
    if (expandBtn) {
      expandBtn.style.display = isCollapsing ? 'inline-flex' : 'none';
    }

    // Update collapse button icon
    const collapseBtnId = targetId === 'wiki-tree' ? 'wiki-tree-collapse' : 'wiki-graph-collapse';
    const collapseBtn = document.getElementById(collapseBtnId);
    if (collapseBtn && window.lucide) {
      // Re-render icon: chevron-left when expanded, chevron-right when collapsed
      const iconName = targetId === 'wiki-tree'
        ? (isCollapsing ? 'chevron-right' : 'chevron-left')
        : (isCollapsing ? 'chevron-left' : 'chevron-right');
      collapseBtn.innerHTML = `<i data-lucide="${iconName}"></i>`;
      window.lucide.createIcons({ icons: collapseBtn.querySelectorAll('i') });
    }

    // Re-render graph if the graph pane visibility changed
    if (targetId === 'wiki-graph') scheduleGraphResize();
  }

  /* ── Maximize / restore graph ───────────────────────────────── */
  function toggleMaximizeGraph() {
    const graph = document.getElementById('wiki-graph');
    const tree = document.getElementById('wiki-tree');
    const preview = document.getElementById('wiki-preview');
    const resizerTree = document.getElementById('wiki-resizer-tree');
    const resizerGraph = document.getElementById('wiki-resizer-graph');
    const expandTreeBtn = document.getElementById('expand-tree-btn');
    const expandGraphBtn = document.getElementById('expand-graph-btn');
    const maximizeBtn = document.getElementById('wiki-maximize-btn');

    if (!graph) return;

    const isMaximizing = !graph.classList.contains('maximized');

    if (isMaximizing) {
      // Maximize: collapse tree + preview, expand graph to full width
      if (tree && !tree.classList.contains('collapsed')) {
        tree.classList.add('collapsed');
      }
      if (preview) preview.classList.add('collapsed');
      graph.classList.add('maximized');

      if (resizerTree) { resizerTree.classList.add('is-hidden'); resizerTree.style.display = 'none'; }
      if (resizerGraph) { resizerGraph.classList.add('is-hidden'); resizerGraph.style.display = 'none'; }

      // Show expand buttons so the user can restore individual panes
      if (expandTreeBtn) expandTreeBtn.style.display = 'inline-flex';
      if (expandGraphBtn) expandGraphBtn.style.display = 'none';
    } else {
      // Restore: un-collapse tree + preview, restore graph size
      if (tree) tree.classList.remove('collapsed');
      if (preview) preview.classList.remove('collapsed');
      graph.classList.remove('maximized');

      if (resizerTree) { resizerTree.classList.remove('is-hidden'); resizerTree.style.display = ''; }
      if (resizerGraph) { resizerGraph.classList.remove('is-hidden'); resizerGraph.style.display = ''; }

      if (expandTreeBtn) expandTreeBtn.style.display = 'none';
      if (expandGraphBtn) expandGraphBtn.style.display = 'none';
    }

    // Toggle maximize/minimize icon
    const iconMax = maximizeBtn?.querySelector('.wiki-icon-max');
    const iconMin = maximizeBtn?.querySelector('.wiki-icon-min');
    if (iconMax) iconMax.style.display = isMaximizing ? 'none' : '';
    if (iconMin) iconMin.style.display = isMaximizing ? '' : 'none';
    maximizeBtn.title = isMaximizing ? '恢复默认布局' : '最大化图谱';

    scheduleGraphResize();
  }

  /* ── Graph resize handling ──────────────────────────────────── */
  function initGraphResizeObserver() {
    const canvas = document.getElementById('wiki-graph-canvas');
    if (!canvas) return;

    if (typeof ResizeObserver !== 'undefined') {
      const observer = new ResizeObserver(() => {
        scheduleGraphResize();
      });
      observer.observe(canvas);
    }
  }

  function scheduleGraphResize() {
    if (_graphResizeTimer) clearTimeout(_graphResizeTimer);
    _graphResizeTimer = setTimeout(() => updateGraphDimensions(), 100);
  }

  function updateGraphDimensions() {
    if (!_d3Graph) return;
    const canvas = document.getElementById('wiki-graph-canvas');
    if (!canvas) return;

    const rect = canvas.getBoundingClientRect();
    const cw = Math.max(rect.width, 200);
    const ch = Math.max(rect.height, 200);

    if (Math.abs(_d3Graph.width - cw) < 5 && Math.abs(_d3Graph.height - ch) < 5) return;

    _d3Graph.width = cw;
    _d3Graph.height = ch;
    _d3Graph.svg
      .attr('viewBox', [0, 0, cw, ch])
      .attr('width', cw)
      .attr('height', ch);
    _d3Graph.simulation.force('center', d3.forceCenter(cw / 2, ch / 2));
    _d3Graph.simulation.alpha(0.15).restart();
  }

  /* ── Sync panel ───────────────────────────────────────────── */
  let _syncSources = [];

  async function openSyncPanel() {
    const panel = document.getElementById('wiki-sync-panel');
    const list = document.getElementById('wiki-sync-list');
    if (!panel || !list) return;

    try {
      const res = await apiGet('/kb/sources?limit=200');
      _syncSources = (res.sources || []);
      renderSourceList(list);
      panel.classList.add('open');
      const bd = document.getElementById('wiki-sync-backdrop');
      if (bd) bd.classList.add('open');
    } catch (err) {
      toast(`获取来源失败：${err.message}`, 'error');
    }
  }

  function closeSyncPanel() {
    const panel = document.getElementById('wiki-sync-panel');
    const bd = document.getElementById('wiki-sync-backdrop');
    if (panel) panel.classList.remove('open');
    if (bd) bd.classList.remove('open');
  }

  function renderSourceList(listEl) {
    listEl.innerHTML = _syncSources.map((s, i) => `
      <li class="wiki-sync-row" data-index="${i}">
        <input type="checkbox" id="wiki-sync-cb-${i}" checked>
        <label for="wiki-sync-cb-${i}">
          ${escape(s.name || s.title || s.url || s.id || '来源 #' + (i + 1))}
        </label>
        <button class="wiki-sync-del" data-index="${i}" title="删除此来源及其 Wiki 内容" style="background:none;border:none;color:var(--c-warn);cursor:pointer;font-size:14px;padding:0 4px;line-height:1;">×</button>
      </li>
    `).join('');

    listEl.querySelectorAll('.wiki-sync-del').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const idx = parseInt(btn.dataset.index);
        const src = _syncSources[idx];
        if (!src) return;
        const sid = src.id || src.source_id;
        const name = src.name || src.title || sid;
        if (!confirm(`确定要删除「${name}」及其关联的 Wiki 内容吗？此操作不可恢复。`)) return;
        try {
          const res = await fetch(apiBase() + `/kb/sources/${encodeURIComponent(sid)}`, { method: 'DELETE' });
          if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
          _syncSources.splice(idx, 1);
          renderSourceList(listEl);
          toast(`已删除: ${name}`, 'success');
        } catch (err) {
          toast(`删除失败: ${err.message}`, 'error');
        }
      });
    });
  }

  function toggleAllSources() {
    const cbs = document.querySelectorAll('#wiki-sync-list input[type="checkbox"]');
    if (cbs.length === 0) return;
    const allChecked = Array.from(cbs).every(cb => cb.checked);
    cbs.forEach(cb => { cb.checked = !allChecked; });
  }

  async function startSync() {
    const cbs = document.querySelectorAll('#wiki-sync-list input[type="checkbox"]');
    const checkedIds = [];
    cbs.forEach((cb, i) => {
      if (cb.checked && _syncSources[i]) {
        checkedIds.push(_syncSources[i].source_id || _syncSources[i].id);
      }
    });
    if (checkedIds.length === 0) {
      toast('请至少选择一个来源', 'warning');
      return;
    }

    const btn = document.getElementById('wiki-sync-start');
    if (btn) { btn.disabled = true; btn.textContent = '提交中…'; }

    try {
      const result = await apiPost('/wiki/sync', { source_ids: checkedIds });
      toast(`同步任务已创建: ${result.task_id || '(无 task_id)'}`, 'success');
      closeSyncPanel();
      toast('请在 Agent Console 查看同步进度', 'info');
    } catch (err) {
      toast(`同步失败：${err.message}`, 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '开始同步'; }
    }
  }

  /* ── Insights pane (overlays the preview) ──────────────────── */
  async function showInsights() {
    const bodyEl = document.getElementById('wiki-preview-body');
    const titleEl = document.getElementById('wiki-preview-title');
    const statEl = document.getElementById('wiki-preview-stat');
    if (!bodyEl) return;
    titleEl.textContent = '健康检查 / 图谱洞察';
    statEl.textContent = '';
    bodyEl.innerHTML = '<div class="wiki-preview-empty">分析中…</div>';
    try {
      const res = await apiGet('/wiki/insights');
      const items = res.items || [];
      if (!items.length) {
        bodyEl.innerHTML = `<div class="wiki-preview-empty">
          Wiki 审查通过，没有发现任何问题。<br><small>${res.count || 0} 条洞察</small>
        </div>`;
        return;
      }
      const sevColor = { error: '#ef4444', warning: '#f59e0b', info: '#4f9eff' };
      const sevLabel = { error: '错误', warning: '提示', info: '洞察' };
      const cards = items.map(it => `
        <div class="wiki-preview-meta" style="border-left: 3px solid ${sevColor[it.severity] || '#888'};">
          <div style="flex: 1 1 100%;">
            <strong style="color: ${sevColor[it.severity] || 'inherit'};">[${sevLabel[it.severity] || it.severity}]</strong>
            ${escape(it.title)}
          </div>
          <div style="flex: 1 1 100%; color: var(--t2);">${escape(it.detail)}</div>
          ${it.suggestion ? `<div style="flex: 1 1 100%; color: var(--t3); font-style: italic;">→ ${escape(it.suggestion)}</div>` : ''}
          ${it.page_ids && it.page_ids.length ? `
            <div style="flex: 1 1 100%; display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px;">
              ${it.page_ids.slice(0, 12).map(pid =>
                `<a href="#" class="wikilink" data-page-id="${escape(pid)}">${escape(pid)}</a>`
              ).join('')}
              ${it.page_ids.length > 12 ? `<span style="color: var(--t3); font-size: 11px;">+${it.page_ids.length - 12} 更多…</span>` : ''}
            </div>
          ` : ''}
        </div>
      `).join('');
      bodyEl.innerHTML = `<div class="wiki-md">${cards}</div>`;
      bodyEl.querySelectorAll('a.wikilink[data-page-id]').forEach(a =>
        a.addEventListener('click', e => { e.preventDefault(); loadPage(a.dataset.pageId); }));
    } catch (err) {
      bodyEl.innerHTML = `<div class="wiki-preview-empty">分析失败：${escape(err.message)}</div>`;
    }
  }

  /* ── Tree search / filter ──────────────────────────────────── */
  function filterTree(query) {
    var body = document.getElementById('wiki-tree-body');
    if (!body) return;
    var q = (query || '').trim().toLowerCase();

    // Unwrap rendered sections back to _allPages
    if (!q) {
      // Re-render full tree from cached _allPages
      rebuildTreeFromCache();
      return;
    }

    // Filter _allPages by title / slug / tags
    var matched = _allPages.filter(function(p) {
      var title = (p.title || '').toLowerCase();
      var slug = (p.slug || '').toLowerCase();
      var tags = '';
      try { var fm = p.frontmatter || {}; tags = (fm.tags || []).join(' ').toLowerCase(); } catch(_) {}
      return title.indexOf(q) >= 0 || slug.indexOf(q) >= 0 || tags.indexOf(q) >= 0;
    });

    // Group by page_type
    var groups = {};
    SECTIONS.forEach(function(s) { groups[s.type] = []; });
    matched.forEach(function(p) { if (groups[p.page_type]) groups[p.page_type].push(p); });

    // Render filtered tree
    var html = '';
    for (var i = 0; i < SECTIONS.length; i++) {
      var sec = SECTIONS[i];
      var pages = groups[sec.type] || [];
      if (pages.length === 0) continue;
      var items = pages.map(function(p) {
        var title = escape(p.title || p.slug);
        if (q) {
          var re = new RegExp('(' + q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi');
          title = title.replace(re, '<mark class="wiki-search-hl">$1</mark>');
        }
        return '<li class="wiki-tree-item' + (p.id === _currentPageId ? ' is-active' : '') +
          '" data-page-id="' + escape(p.id) + '" title="' + escape(p.summary || p.title) + '">' +
          title + '</li>';
      }).join('');
      html += '<details class="wiki-tree-section" open><summary><span>' + sec.label +
        '</span><span class="wiki-badge">' + pages.length + '</span></summary>' +
        '<ul class="wiki-tree-list">' + items + '</ul></details>';
    }
    if (!html) html = '<div class="wiki-tree-empty">没有匹配的页面</div>';

    body.innerHTML = html;
    body.querySelectorAll('.wiki-tree-item[data-page-id]').forEach(function(el) {
      el.addEventListener('click', function() { loadPage(el.dataset.pageId); });
    });
  }

  function rebuildTreeFromCache() {
    // Group _allPages by page_type
    var groups = {};
    SECTIONS.forEach(function(s) { groups[s.type] = []; });
    _allPages.forEach(function(p) { if (groups[p.page_type]) groups[p.page_type].push(p); });

    var body = document.getElementById('wiki-tree-body');
    if (!body) return;

    if (_allPages.length === 0) {
      body.innerHTML = '<div class="wiki-tree-empty">知识库还没有 wiki 页面。<br><small>到「上传」摄入资料后 wiki worker 会自动生成。</small></div>';
      return;
    }

    var html = SECTIONS.map(function(sec) {
      var pages = groups[sec.type] || [];
      var items = pages.map(function(p) {
        return '<li class="wiki-tree-item' + (p.id === _currentPageId ? ' is-active' : '') +
          '" data-page-id="' + escape(p.id) + '" title="' + escape(p.summary || p.title) + '">' +
          escape(p.title || p.slug) + '</li>';
      }).join('') || '<li class="wiki-tree-empty">（暂无）</li>';
      var open = pages.length > 0 ? 'open' : '';
      return '<details class="wiki-tree-section" ' + open + '>' +
        '<summary><span>' + sec.label + '</span><span class="wiki-badge">' + pages.length + '</span></summary>' +
        '<ul class="wiki-tree-list">' + items + '</ul></details>';
    }).join('');

    body.innerHTML = html;
    body.querySelectorAll('.wiki-tree-item[data-page-id]').forEach(function(el) {
      el.addEventListener('click', function() { loadPage(el.dataset.pageId); });
    });
  }

  /* ── Tree pane data loading ───────────────────────────────── */
  async function loadTree() {
    const body = document.getElementById('wiki-tree-body');
    if (!body) return;
    try {
      const counts = await apiGet('/wiki/stats').then(s => s.page_counts || {});
      const sectionPromises = SECTIONS.map(async ({ type, label }) => ({
        type, label,
        count: counts[type] || 0,
        pages: counts[type] ? await apiGet(`/wiki/pages?page_type=${type}&limit=200`) : [],
      }));
      const sections = await Promise.all(sectionPromises);
      _allPages = sections.flatMap(s => s.pages);
      // Check if there's an active search query — if so re-apply the filter
      var searchInput = document.getElementById('wiki-search');
      if (searchInput && searchInput.value.trim()) {
        filterTree(searchInput.value.trim());
      } else {
        renderTree(sections);
      }
    } catch (err) {
      body.innerHTML = `<div class="wiki-tree-empty">加载失败：${escape(err.message)}</div>`;
    }
  }

  function renderTree(sections) {
    const body = document.getElementById('wiki-tree-body');
    if (!body) return;
    if (sections.every(s => s.pages.length === 0)) {
      body.innerHTML = `
        <div class="wiki-tree-empty">
          知识库还没有 wiki 页面。<br>
          <small>到「上传」摄入资料后 wiki worker 会自动生成。</small>
        </div>`;
      return;
    }

    body.innerHTML = sections.map(({ type, label, count, pages }) => {
      const items = pages.map(p => `
        <li class="wiki-tree-item ${p.id === _currentPageId ? 'is-active' : ''}"
            data-page-id="${escape(p.id)}" title="${escape(p.summary || p.title)}">
          ${escape(p.title || p.slug)}
        </li>
      `).join('') || `<li class="wiki-tree-empty">（暂无）</li>`;
      const open = pages.length > 0 ? 'open' : '';
      return `
        <details class="wiki-tree-section" ${open}>
          <summary>
            <span>${label}</span>
            <span class="wiki-badge">${count}</span>
          </summary>
          <ul class="wiki-tree-list">${items}</ul>
        </details>
      `;
    }).join('');

    body.querySelectorAll('.wiki-tree-item[data-page-id]').forEach(el => {
      el.addEventListener('click', () => loadPage(el.dataset.pageId));
    });
  }

  /* ── Preview pane ─────────────────────────────────────────── */
  async function loadPage(pageId) {
    if (!pageId) return;
    _currentPageId = pageId;
    document.querySelectorAll('.wiki-tree-item').forEach(el =>
      el.classList.toggle('is-active', el.dataset.pageId === pageId));

    const titleEl = document.getElementById('wiki-preview-title');
    const statEl = document.getElementById('wiki-preview-stat');
    const bodyEl = document.getElementById('wiki-preview-body');
    const researchBtn = document.getElementById('wiki-research-btn');
    const researchPanel = document.getElementById('wiki-research-panel');
    if (!bodyEl) return;

    if (researchPanel) {
      researchPanel.hidden = true;
      researchPanel.innerHTML = '';
    }

    bodyEl.innerHTML = '<div class="wiki-preview-empty">加载中…</div>';
    try {
      const page = await apiGet('/wiki/pages/' + encodeURIComponent(pageId));
      titleEl.textContent = page.title || page.slug;
      statEl.textContent = `rev ${page.revision} · 更新于 ${formatTs(page.updated_at)}`;
      if (researchBtn) researchBtn.hidden = false;

      const meta = renderMeta(page);
      const tocHtml = renderTOC(page.body || '');
      const html = renderMarkdown(page.body || '*(此页面没有内容——可能 wiki worker 仍在生成中)*');
      bodyEl.innerHTML = meta + tocHtml + `<div class="wiki-md">${html}</div>`;

      // Post-process: highlight article numbers in legal text
      var mdEl = bodyEl.querySelector('.wiki-md');
      if (mdEl) highlightArticleRefs(mdEl);

      // Wire TOC scroll tracking
      if (tocHtml) initTOCScrollSpy(bodyEl);

      bodyEl.querySelectorAll('a.wikilink').forEach(a => {
        a.addEventListener('click', (e) => {
          e.preventDefault();
          const target = a.dataset.pageId;
          if (target) loadPage(target);
        });
      });

      highlightInGraph(pageId);
    } catch (err) {
      bodyEl.innerHTML = `<div class="wiki-preview-empty">加载失败：${escape(err.message)}</div>`;
    }
  }

  function renderMeta(page) {
    const fm = page.frontmatter || {};
    const tags = (fm.tags || []).map(t => escape(t)).join(', ') || '—';
    const aliases = (fm.aliases || []).map(t => escape(t)).join(', ') || '—';
    const sources = (page.source_ids || []).map(s => `<code>${escape(s)}</code>`).join(' ') || '—';
    return `
      <div class="wiki-preview-meta">
        <div><strong>类型:</strong>${escape(page.page_type)}</div>
        <div><strong>Slug:</strong><code>${escape(page.slug)}</code></div>
        <div><strong>标签:</strong>${tags}</div>
        <div><strong>别名:</strong>${aliases}</div>
        <div><strong>来源:</strong>${sources}</div>
      </div>
    `;
  }

  /* ── Markdown rendering with [[wikilink]] support ─────────── */
  function renderMarkdown(body) {
    if (!window.marked || typeof window.marked.parse !== 'function') {
      return `<pre>${escape(body)}</pre>`;
    }

    const replaced = body.replace(/\[\[([^\[\]\n|]+)(?:\|([^\[\]\n]+))?\]\]/g,
      (match, target, display) => {
        const t = target.trim();
        const text = (display || t).trim();
        const [maybeType, maybeSlug] = t.split(':', 2);
        let pageId = null;
        if (maybeSlug && ['entity','concept','source','query','overview'].includes(maybeType)) {
          pageId = `${maybeType}:${maybeSlug}`;
        } else {
          const candidates = _allPages.filter(p => p.slug === t);
          if (candidates.length === 1) pageId = candidates[0].id;
        }
        const known = pageId && _allPages.some(p => p.id === pageId);
        const cls = known ? 'wikilink' : 'wikilink is-broken';
        const dataAttr = known ? ` data-page-id="${escape(pageId)}"` : '';
        return `<a href="#" class="${cls}"${dataAttr}>${escape(text)}</a>`;
      });

    return window.marked.parse(replaced, { breaks: true, gfm: true });
  }

  /* ── Graph pane (D3.js force-directed) ───────────────────── */

  function _getThemeColors() {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    return {
      edge:       isDark ? 'rgba(255,255,255,0.25)' : 'rgba(0,0,0,0.20)',
      label:      isDark ? '#8b8d91' : '#5b5d61',
      labelHover: isDark ? '#e0e2e6' : '#15120f',
      nodeStroke: isDark ? '#1a1b1e' : '#f3ede2',
    };
  }

  const _NODE_COLORS = {
    entity:   '#5e6ad2',
    concept:  '#10b981',
    source:   '#f59e0b',
    query:    '#8b5cf6',
    overview: '#ef4444',
  };

  function _fitGraphToBounds() {
    if (!_d3Graph) return;
    const { svg, zoom, simulation } = _d3Graph;
    const nodes = simulation.nodes();
    if (!nodes.length) return;
    const xExt = d3.extent(nodes, d => d.x);
    const yExt = d3.extent(nodes, d => d.y);
    if (!xExt[0]) return;
    const dx = xExt[1] - xExt[0] || 1;
    const dy = yExt[1] - yExt[0] || 1;
    const cx = (xExt[0] + xExt[1]) / 2;
    const cy = (yExt[0] + yExt[1]) / 2;
    const { width: cw, height: ch } = _d3Graph;
    const pad = 40;
    const ecw = Math.max(cw - pad * 2, 1);
    const ech = Math.max(ch - pad * 2, 1);
    const scale = 0.85 / Math.max(dx / ecw, dy / ech, 0.2);
    const tx = cw / 2 - cx * scale;
    const ty = ch / 2 - cy * scale;
    svg.transition().duration(500).call(
      zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(Math.min(scale, 2)));
  }

  async function loadGraph() {
    const canvas = document.getElementById('wiki-graph-canvas');
    const stat = document.getElementById('wiki-graph-stat');
    if (!canvas) return;

    if (typeof d3 === 'undefined') {
      canvas.innerHTML = `<div class="wiki-graph-empty">
        图谱依赖未加载（CDN 网络问题）。<br>
        <small>左栏与中栏功能不受影响。</small>
      </div>`;
      stat.textContent = '—';
      return;
    }

    try {
      const data = await apiGet('/wiki/graph?edge_limit=2000&page_limit=500');
      const nodes = (data.nodes || []).map(n => ({
        id:         n.id,
        title:      n.title || n.slug || n.id,
        page_type:  n.page_type || 'entity',
      }));
      const edges = (data.edges || [])
        .map(e => ({
          source: e.src_page_id || e.src || e.source,
          target: e.dst_page_id || e.dst || e.target,
        }))
        .filter(e => e.source && e.target && e.source !== e.target);

      // Degree (connection count) for each node — drives radius and label size
      const degree = {};
      edges.forEach(e => {
        const s = typeof e.source === 'object' ? e.source.id : e.source;
        const t = typeof e.target === 'object' ? e.target.id : e.target;
        degree[s] = (degree[s] || 0) + 1;
        degree[t] = (degree[t] || 0) + 1;
      });
      nodes.forEach(n => { n._deg = degree[n.id] || 0; });

      // Node radius: sqrt scale by degree (Obsidian hallmark)
      const rScale = d3.scaleSqrt().domain([1, 20]).range([3, 10]).clamp(true);

      stat.textContent = `${nodes.length} 节点 · ${edges.length} 边`;

      if (nodes.length === 0) {
        canvas.innerHTML = `<div class="wiki-graph-empty">
          暂无节点。<br>
          <small>摄入资料后 wiki worker 会持续构建关系图。</small>
        </div>`;
        return;
      }

      // Kill previous simulation
      if (_d3Graph && _d3Graph.simulation) _d3Graph.simulation.stop();
      canvas.innerHTML = '';

      const rect = canvas.getBoundingClientRect();
      const cw = Math.max(rect.width, 200);
      const ch = Math.max(rect.height, 200);
      const tc = _getThemeColors();

      // ── SVG container ──
      const svg = d3.select(canvas)
        .append('svg')
        .attr('viewBox', [0, 0, cw, ch])
        .attr('width', cw)
        .attr('height', ch)
        .style('display', 'block');

      // ── Zoom behaviour ──
      const g = svg.append('g');
      const zoom = d3.zoom()
        .scaleExtent([0.08, 8])
        .on('zoom', ev => {
          g.attr('transform', ev.transform);
          const k = ev.transform.k;
          // Labels: hide when zoomed out, show + scale when zoomed in
          label.style('display', k > 0.6 ? null : 'none');
          label.attr('font-size', d => Math.max(6, Math.min(14, rScale(d._deg || 1) * k * 0.8)));
          // Edge opacity: fainter when zoomed out
          link.attr('stroke-opacity', Math.min(0.6, 0.2 + k * 0.15));
        });
      svg.call(zoom);

      // ── Simulation (Obsidian-style compact clustering) ──
      nodes.forEach(n => { n.x = cw/2 + (Math.random()-0.5)*8; n.y = ch/2 + (Math.random()-0.5)*8; });
      const simulation = d3.forceSimulation(nodes)
        .force('link',    d3.forceLink(edges).id(d => d.id).distance(55))
        .force('charge',  d3.forceManyBody().strength(-30))
        .force('x',       d3.forceX(cw / 2).strength(0.005))
        .force('y',       d3.forceY(ch / 2).strength(0.005))
        .force('collide', d3.forceCollide(d => rScale(d._deg || 1) + 4))
        .alphaDecay(0.02)
        .alpha(0.3);

      // ── Edges ──
      const link = g.append('g')
        .selectAll('line')
        .data(edges)
        .join('line')
        .attr('stroke', tc.edge)
        .attr('stroke-width', 0.8)
        .attr('stroke-opacity', 0.45);

      // ── Nodes ──
      const node = g.append('g')
        .selectAll('circle')
        .data(nodes)
        .join('circle')
        .attr('r', d => rScale(d._deg || 1))
        .attr('fill', d => _NODE_COLORS[d.page_type] || '#888')
        .attr('stroke', tc.nodeStroke)
        .attr('stroke-width', 1.5)
        .style('cursor', 'pointer');

      node.append('title').text(d => d.title || d.id);

      // ── Labels ──
      const label = g.append('g')
        .selectAll('text')
        .data(nodes)
        .join('text')
        .text(d => {
          const t = d.title || '';
          return t.length > 20 ? t.slice(0, 18) + '…' : t;
        })
        .attr('dx', 0)
        .attr('dy', 14)
        .attr('text-anchor', 'middle')
        .attr('font-size', 9)
        .attr('font-family', 'system-ui, -apple-system, sans-serif')
        .attr('fill', tc.label)
        .style('pointer-events', 'none')
        .style('user-select', 'none');

      // ── Hover ──
      node.on('mouseenter', function(_, d) {
        d3.select(this)
          .transition().duration(120)
          .attr('r', rScale(d._deg || 1) + 3)
          .attr('stroke', '#fff')
          .attr('stroke-width', 2.5);
        label.filter(nd => nd.id === d.id)
          .transition().duration(120)
          .attr('fill', tc.labelHover)
          .attr('font-size', 11);
      });
      node.on('mouseleave', function(_, d) {
        d3.select(this)
          .transition().duration(120)
          .attr('r', rScale(d._deg || 1))
          .attr('stroke', tc.nodeStroke)
          .attr('stroke-width', 1.5);
        label.filter(nd => nd.id === d.id)
          .transition().duration(120)
          .attr('fill', tc.label)
          .attr('font-size', 9);
      });

      // ── Click → navigate ──
      node.on('click', (_, d) => { loadPage(d.id); });

      // ── Drag ──
      const drag = d3.drag()
        .on('start', (ev, d) => {
          if (!ev.active) simulation.alphaTarget(0.08).restart();
          d.fx = d.x; d.fy = d.y;
        })
        .on('drag', (ev, d) => { d.fx = ev.x; d.fy = ev.y; })
        .on('end', (ev, d) => {
          if (!ev.active) simulation.alphaTarget(0);
          d.fx = null; d.fy = null;
        });
      node.call(drag);

      // ── Tick ──
      simulation.on('tick', () => {
        link
          .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
          .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
        node
          .attr('cx', d => d.x).attr('cy', d => d.y);
        label
          .attr('x', d => d.x).attr('y', d => d.y);
      });

      // ── Fit once layout settles ──
      simulation.on('end', _fitGraphToBounds);

      // ── Store ref ──
      _d3Graph = { svg, simulation, zoom, nodes, width: cw, height: ch };

      highlightInGraph(_currentPageId);

    } catch (err) {
      canvas.innerHTML = `<div class="wiki-graph-empty">图谱加载失败：${escape(err.message)}</div>`;
      stat.textContent = '—';
    }
  }

  function highlightInGraph(pageId) {
    if (!_d3Graph || !pageId) return;
    const { svg, zoom, simulation } = _d3Graph;
    const node = simulation.nodes().find(n => n.id === pageId);
    if (!node || node.x == null) return;
    const scale = 0.75;
    const tx = _d3Graph.width  / 2 - node.x * scale;
    const ty = _d3Graph.height / 2 - node.y * scale;
    svg.transition().duration(400).call(
      zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
  }

  /* ── Deep Research panel ────────────────────────────────────── */

  let _researchPoll = null;

  function toggleResearchPanel(pageId) {
    const panel = document.getElementById('wiki-research-panel');
    if (!panel || !pageId) return;
    if (!panel.hidden) {
      panel.hidden = true;
      return;
    }
    renderResearchForm(pageId);
    panel.hidden = false;
  }

  function renderResearchForm(pageId) {
    const panel = document.getElementById('wiki-research-panel');
    if (!panel) return;
    panel.innerHTML = `
      <div class="wiki-research-form">
        <div class="wiki-research-title">
          <i data-lucide="telescope"></i>
          <strong>Deep Research</strong>
          <span class="wiki-research-hint">从 web 主动补充 <code>${escape(pageId)}</code></span>
        </div>
        <label class="wiki-research-label">
          <span>关注点（可选）</span>
          <textarea id="wiki-research-focus" rows="2"
                    placeholder="例：教育领域近期工作 / 与同行的对比 / 公开批评"></textarea>
        </label>
        <label class="wiki-research-label wiki-research-row">
          <span>最多研究 URL</span>
          <input type="range" id="wiki-research-urls" min="1" max="6" value="3" step="1">
          <output id="wiki-research-urls-val">3</output>
        </label>
        <div class="wiki-research-actions">
          <button class="wiki-research-run" id="wiki-research-run">
            <i data-lucide="play"></i> 开始研究
          </button>
          <button class="wiki-research-cancel" id="wiki-research-cancel" type="button">取消</button>
        </div>
        <div class="wiki-research-status" id="wiki-research-status"></div>
      </div>
    `;
    if (window.lucide) window.lucide.createIcons();

    const slider = document.getElementById('wiki-research-urls');
    const slLabel = document.getElementById('wiki-research-urls-val');
    slider.addEventListener('input', () => { slLabel.textContent = slider.value; });

    document.getElementById('wiki-research-run')
      .addEventListener('click', () => kickoffResearch(pageId));
    document.getElementById('wiki-research-cancel')
      .addEventListener('click', () => { panel.hidden = true; });
  }

  async function kickoffResearch(pageId) {
    const focusEl = document.getElementById('wiki-research-focus');
    const urlsEl  = document.getElementById('wiki-research-urls');
    const runBtn  = document.getElementById('wiki-research-run');
    const cancelBtn = document.getElementById('wiki-research-cancel');
    const status = document.getElementById('wiki-research-status');
    if (!status) return;

    const focus = (focusEl && focusEl.value || '').trim();
    const max_urls = parseInt(urlsEl && urlsEl.value, 10) || 3;

    runBtn.disabled = true;
    runBtn.classList.add('is-running');
    status.innerHTML = `<div class="wiki-research-line">提交任务中…</div>`;

    let task;
    try {
      const res = await fetch(apiBase() + '/wiki/research', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ page_id: pageId, focus, max_urls }),
      });
      if (!res.ok) {
        const detail = await res.text().catch(() => '');
        throw new Error(`${res.status} ${res.statusText}: ${detail.slice(0, 180)}`);
      }
      task = await res.json();
    } catch (err) {
      status.innerHTML = `<div class="wiki-research-line is-failed">提交失败：${escape(err.message)}</div>`;
      runBtn.disabled = false;
      runBtn.classList.remove('is-running');
      return;
    }

    cancelBtn.textContent = '收起';
    pollResearchTask(task.task_id, pageId, status, runBtn);
  }

  function pollResearchTask(taskId, pageId, statusEl, runBtn) {
    if (_researchPoll) { clearTimeout(_researchPoll); _researchPoll = null; }
    const startedAt = Date.now();

    const tick = async () => {
      let task;
      try {
        task = await apiGet('/wiki/research/' + encodeURIComponent(taskId));
      } catch (err) {
        statusEl.innerHTML = `<div class="wiki-research-line is-failed">轮询失败：${escape(err.message)}</div>`;
        runBtn.disabled = false;
        runBtn.classList.remove('is-running');
        return;
      }
      const elapsed = Math.round((Date.now() - startedAt) / 1000);
      statusEl.innerHTML = renderResearchStatus(task, elapsed);
      if (task.status === 'done' || task.status === 'failed') {
        runBtn.disabled = false;
        runBtn.classList.remove('is-running');
        if (task.status === 'done') {
          loadPage(pageId);
        }
        return;
      }
      _researchPoll = setTimeout(tick, 1500);
    };

    tick();
  }

  function renderResearchStatus(task, elapsedS) {
    const phase = escape(task.phase_note || task.status || '');
    const cls = task.status === 'failed' ? 'is-failed'
              : task.status === 'done'   ? 'is-done'
              : 'is-running';
    let head = `<div class="wiki-research-line ${cls}">
        <strong>${escape(task.status)}</strong>
        ${phase ? '· ' + phase : ''}
        <span class="wiki-research-elapsed">${elapsedS}s</span>
      </div>`;
    if (task.status === 'failed') {
      head += `<div class="wiki-research-error">${escape(task.error || '(未知错误)')}</div>`;
    }
    if (task.status === 'done' && task.result) {
      const r = task.result;
      head += `
        <div class="wiki-research-result">
          <div>新增 <strong>${r.new_chars || 0}</strong> 字符 · <strong>${r.new_links || 0}</strong> 条新链接</div>
          <div>使用 ${(r.urls_used || []).length}/${(r.urls_used || []).length + (r.urls_failed || []).length} 个 URL</div>
          ${(r.queries || []).length ? '<div class="wiki-research-queries">查询：' +
            r.queries.map(q => `<code>${escape(q.query)}</code>`).join(' ') + '</div>' : ''}
        </div>
      `;
    }
    return head;
  }

  /* ── Refresh + lifecycle ───────────────────────────────────── */
  async function refreshAll() {
    const btn = document.getElementById('wiki-refresh-btn');
    if (btn) btn.classList.add('is-spinning');
    try {
      await Promise.all([loadTree(), loadGraph()]);
      if (_currentPageId) await loadPage(_currentPageId);
    } finally {
      if (btn) btn.classList.remove('is-spinning');
    }
  }

  /* ── Show-on-tab-event hook ─────────────────────────────── */
  document.addEventListener('tab:shown', async (ev) => {
    if (ev.detail !== 'wiki') {
      _wikiTabVisible = false;
      stopProgressPoll();
      disconnectAgentEvents();
      return;
    }
    _wikiTabVisible = true;
    mount();
    if (_allPages.length === 0) await refreshAll();
    startProgressPoll();
    connectAgentEvents();
  });

  /* ── TOC rendering ──────────────────────────────────────────── */
  function renderTOC(body) {
    if (!body) return '';
    // Extract h1, h2, h3 headings
    var headingRe = /^(#{1,3})\s+(.+)$/gm;
    var headings = [];
    var m;
    while ((m = headingRe.exec(body)) !== null) {
      headings.push({ level: m[1].length, text: m[2].trim().replace(/[#*_`~\[\]]/g, '') });
    }
    if (headings.length < 3) return ''; // too few headings for a useful TOC

    var items = '';
    headings.forEach(function(h, i) {
      var cls = 'toc-h' + h.level;
      var indent = '  '.repeat(Math.max(0, h.level - 1));
      items += '<li class="' + cls + '"><a href="#toc-h-' + i + '" data-toc-i="' + i + '">' + indent + escape(h.text) + '</a></li>';
    });

    return '<details class="wiki-toc" open>' +
      '<summary>目录</summary>' +
      '<ol>' + items + '</ol>' +
      '</details>';
  }

  /* ── TOC scroll spy ──────────────────────────────────────────── */
  function initTOCScrollSpy(bodyEl) {
    // Add anchor IDs to headings in the rendered markdown
    var headingEls = bodyEl.querySelectorAll('.wiki-md h1, .wiki-md h2, .wiki-md h3');
    headingEls.forEach(function(el, i) {
      el.id = 'toc-h-' + i;
    });

    // IntersectionObserver to highlight active TOC item
    var tocLinks = bodyEl.querySelectorAll('.wiki-toc a[data-toc-i]');
    if (tocLinks.length === 0) return;

    var observer = new IntersectionObserver(function(entries) {
      entries.forEach(function(entry) {
        if (entry.isIntersecting) {
          var idx = Array.prototype.indexOf.call(headingEls, entry.target);
          tocLinks.forEach(function(a) { a.classList.remove('is-active'); });
          var active = bodyEl.querySelector('.wiki-toc a[data-toc-i="' + idx + '"]');
          if (active) active.classList.add('is-active');
        }
      });
    }, { rootMargin: '-20% 0px -70% 0px' });

    headingEls.forEach(function(el) { observer.observe(el); });

    // Click → smooth scroll
    tocLinks.forEach(function(a) {
      a.addEventListener('click', function(e) {
        e.preventDefault();
        var idx = parseInt(this.dataset.tocI);
        var target = headingEls[idx];
        if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    });
  }

  /* ── Article reference highlighting ───────────────────────────── */
  function highlightArticleRefs(mdEl) {
    // Highlight legal article references: 第X条, 第XXX条
    var walker = document.createTreeWalker(mdEl, NodeFilter.SHOW_TEXT, null, false);
    var nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);

    var re = /第[一二三四五六七八九十百千0-9]+条(?:之[一二三四五六七八九十百千0-9]+)?/g;
    nodes.forEach(function(textNode) {
      var text = textNode.textContent;
      if (!re.test(text)) { re.lastIndex = 0; return; }
      re.lastIndex = 0;
      var frag = document.createDocumentFragment();
      var lastIdx = 0;
      var m;
      while ((m = re.exec(text)) !== null) {
        if (m.index > lastIdx) {
          frag.appendChild(document.createTextNode(text.slice(lastIdx, m.index)));
        }
        var span = document.createElement('strong');
        span.className = 'article-ref';
        span.textContent = m[0];
        frag.appendChild(span);
        lastIdx = m.index + m[0].length;
      }
      if (lastIdx < text.length) {
        frag.appendChild(document.createTextNode(text.slice(lastIdx)));
      }
      textNode.parentNode.replaceChild(frag, textNode);
    });

    // Add .has-article class to paragraphs that start with article numbers
    mdEl.querySelectorAll('p').forEach(function(p) {
      var t = p.textContent.trim();
      if (/^第[一二三四五六七八九十百千\d]+条/.test(t)) {
        p.classList.add('has-article');
      }
    });
  }

  /* ── Wiki progress polling ────────────────────────────────────── */
  var _progressPollTimer = null;
  var _lastEventCount = 0;

  function startProgressPoll() {
    if (_progressPollTimer) return;
    _progressPollTimer = setInterval(checkProgress, 3000);
  }

  function stopProgressPoll() {
    if (_progressPollTimer) { clearInterval(_progressPollTimer); _progressPollTimer = null; }
  }

  async function checkProgress() {
    var progEl = document.getElementById('wiki-progress');
    if (!progEl) return;
    try {
      var events = await apiGet('/wiki/events?limit=5');
      if (!events || events.length === 0) return;
      var latestCount = events.length;
      if (latestCount > _lastEventCount) {
        _lastEventCount = latestCount;
        progEl.classList.add('is-active');
        // Auto-refresh tree if new events detected
        if (_allPages.length >= 0) {
          var counts = await apiGet('/wiki/stats').then(function(s) { return s.page_counts || {}; });
          var total = Object.values(counts).reduce(function(a, b) { return a + b; }, 0);
          if (total > _allPages.length) {
            await loadTree();
            await loadGraph();
            progEl.classList.remove('is-active');
          }
        }
      } else {
        // No new events — check if there are pending tasks
        var stats = await apiGet('/wiki/stats');
        if (stats && stats.worker && stats.worker.queued > 0) {
          progEl.classList.add('is-active');
        } else {
          progEl.classList.remove('is-active');
        }
      }
    } catch (_) {
      progEl.classList.remove('is-active');
    }
  }

  /* ── Agent EventSource — real-time wiki progress ────────────── */
  var _agentEventSource = null;

  function connectAgentEvents() {
    try {
      var base = apiBase();
      if (!base) return;
      var es = new EventSource(base + '/agent/v2/events');
      es.onmessage = function(e) {
        try {
          var evt = JSON.parse(e.data);
          var progEl = document.getElementById('wiki-progress');
          var progText = document.getElementById('wiki-progress-text');
          if (evt.type === 'wiki_analysis_start' || evt.type === 'wiki_batch_start') {
            if (progEl) progEl.classList.add('is-active');
            if (progText) progText.textContent = 'Wiki 生成中' + (evt.data && evt.data.source_count ? '（' + evt.data.source_count + ' 个来源）' : '') + '…';
          } else if (evt.type === 'wiki_sync_complete') {
            if (progEl) progEl.classList.remove('is-active');
            refreshAll();
          } else if (evt.type === 'progress' || evt.type === 'info') {
            if (progEl) progEl.classList.add('is-active');
            if (progText && evt.data && evt.data.message) progText.textContent = evt.data.message;
          }
        } catch (_) {}
      };
      es.onerror = function() { es.close(); _agentEventSource = null; setTimeout(connectAgentEvents, 5000); };
      _agentEventSource = es;
    } catch (_) {}
  }

  function disconnectAgentEvents() {
    if (_agentEventSource) { _agentEventSource.close(); _agentEventSource = null; }
  }

  /* ── Tiny utilities ─────────────────────────────────────── */
  function escape(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }
  function formatTs(iso) {
    if (!iso) return '—';
    try {
      const d = new Date(iso);
      return d.toLocaleString('zh-CN', { hour12: false });
    } catch (_) { return iso; }
  }

  // Expose for debugging
  window.OmniWiki = { mount, refreshAll, loadPage, togglePane, toggleMaximizeGraph, toggleResearchPanel, filterTree, startProgressPoll, stopProgressPoll, connectAgentEvents, disconnectAgentEvents };
})();
