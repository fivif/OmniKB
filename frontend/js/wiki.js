/* ── Wiki tab controller ─────────────────────────────────────────────
 *
 * Mounts a three-pane layout into #tab-wiki on first show:
 *   [tree] [markdown preview] [graph]
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
 *   - graphology + sigma globals
 *
 * If a CDN fails to load we degrade gracefully — the tree + preview
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
  let _sigma = null;    // sigma instance

  /* ── API helpers (use the global one if available) ───────── */
  function apiBase() {
    return (window.OmniKBApp && window.OmniKBApp.loadSettings &&
      (window.OmniKBApp.loadSettings().api_base || 'http://localhost:6886')) ||
      'http://localhost:6886';
  }
  async function apiGet(path) {
    const res = await fetch(apiBase() + path, { cache: 'no-store' });
    if (!res.ok) {
      const detail = await res.text().catch(() => '');
      throw new Error(`${res.status} ${res.statusText}: ${detail.slice(0, 120)}`);
    }
    return res.json();
  }

  /* ── Mount the layout into #tab-wiki ──────────────────────── */
  function mount() {
    const root = document.getElementById(TAB_ID);
    if (!root || _mounted) return;
    _mounted = true;

    root.innerHTML = `
      <aside class="wiki-pane wiki-tree" id="wiki-tree">
        <div class="wiki-pane-header">
          <h3>页面</h3>
          <div style="display:flex; gap:6px;">
            <button class="wiki-refresh-btn" id="wiki-insights-btn" title="健康检查 / 洞察">
              <i data-lucide="activity"></i>
            </button>
            <button class="wiki-refresh-btn" id="wiki-refresh-btn" title="刷新">
              <i data-lucide="refresh-cw"></i>
            </button>
          </div>
        </div>
        <div class="wiki-pane-body" id="wiki-tree-body">
          <div class="wiki-tree-empty">加载中…</div>
        </div>
      </aside>

      <main class="wiki-pane wiki-preview" id="wiki-preview">
        <div class="wiki-pane-header">
          <h3 id="wiki-preview-title">未选择页面</h3>
          <span class="wiki-stat" id="wiki-preview-stat"></span>
          <div style="margin-left:auto; display:flex; gap:6px;">
            <button class="wiki-refresh-btn wiki-research-btn" id="wiki-research-btn"
                    title="Deep Research — 从 web 主动补充本页" hidden>
              <i data-lucide="telescope"></i>
            </button>
          </div>
        </div>
        <div class="wiki-research-panel" id="wiki-research-panel" hidden></div>
        <div class="wiki-pane-body" id="wiki-preview-body">
          <div class="wiki-preview-empty">
            选择左侧任意页面查看内容。<br>
            尚无页面？先到「上传」摄入一份资料，wiki worker 会自动生成。
          </div>
        </div>
      </main>

      <aside class="wiki-pane wiki-graph" id="wiki-graph">
        <div class="wiki-pane-header">
          <h3>关系图谱</h3>
          <span class="wiki-stat" id="wiki-graph-stat">—</span>
        </div>
        <div class="wiki-graph-canvas" id="wiki-graph-canvas">
          <div class="wiki-graph-empty">加载中…</div>
        </div>
        <div class="wiki-graph-toolbar">
          <button id="wiki-graph-zoom-in"  title="放大">＋</button>
          <button id="wiki-graph-zoom-out" title="缩小">−</button>
          <button id="wiki-graph-fit"      title="适配">⤧</button>
        </div>
      </aside>
    `;

    if (window.lucide) window.lucide.createIcons();

    document.getElementById('wiki-refresh-btn')
      .addEventListener('click', refreshAll);
    document.getElementById('wiki-insights-btn')
      .addEventListener('click', showInsights);
    document.getElementById('wiki-research-btn')
      .addEventListener('click', () => toggleResearchPanel(_currentPageId));

    // graph toolbar — bound now even if sigma isn't ready yet
    document.getElementById('wiki-graph-zoom-in')
      .addEventListener('click', () => _sigma && _sigma.getCamera().animatedZoom({ factor: 1.5 }));
    document.getElementById('wiki-graph-zoom-out')
      .addEventListener('click', () => _sigma && _sigma.getCamera().animatedZoom({ factor: 0.667 }));
    document.getElementById('wiki-graph-fit')
      .addEventListener('click', () => _sigma && _sigma.getCamera().animatedReset());
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
          🎉 wiki 没有发现任何问题。<br><small>${res.count || 0} 条洞察</small>
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

  /* ── Tree pane ────────────────────────────────────────────── */
  async function loadTree() {
    const body = document.getElementById('wiki-tree-body');
    if (!body) return;
    try {
      // One request per type — small, cacheable, keeps UI responsive
      // when one section has lots of pages.
      const counts = await apiGet('/wiki/stats').then(s => s.page_counts || {});
      const sectionPromises = SECTIONS.map(async ({ type, label }) => ({
        type, label,
        count: counts[type] || 0,
        pages: counts[type] ? await apiGet(`/wiki/pages?page_type=${type}&limit=200`) : [],
      }));
      const sections = await Promise.all(sectionPromises);
      _allPages = sections.flatMap(s => s.pages);
      renderTree(sections);
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
      // Always-open for non-empty sections; collapsed if empty.
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

    // Loading a different page hides any half-finished research panel
    // — a stale task UI on a new page is more confusing than helpful.
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
      const html = renderMarkdown(page.body || '*(此页面没有内容——可能 wiki worker 仍在生成中)*');
      bodyEl.innerHTML = meta + `<div class="wiki-md">${html}</div>`;

      // Wire wikilink clicks
      bodyEl.querySelectorAll('a.wikilink').forEach(a => {
        a.addEventListener('click', (e) => {
          e.preventDefault();
          const target = a.dataset.pageId;
          if (target) loadPage(target);
        });
      });

      // Highlight the current node in the graph if it's loaded
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
      // Marked failed to load — render escaped text in <pre> as fallback
      return `<pre>${escape(body)}</pre>`;
    }

    // 1. Resolve wikilinks BEFORE markdown parsing so the parser
    //    doesn't escape the brackets.
    //    [[type:slug]] OR [[type:slug|display]] OR [[bare-slug]]
    const replaced = body.replace(/\[\[([^\[\]\n|]+)(?:\|([^\[\]\n]+))?\]\]/g,
      (match, target, display) => {
        const t = target.trim();
        const text = (display || t).trim();
        const [maybeType, maybeSlug] = t.split(':', 2);
        let pageId = null;
        if (maybeSlug && ['entity','concept','source','query','overview'].includes(maybeType)) {
          pageId = `${maybeType}:${maybeSlug}`;
        } else {
          // Bare reference — try to find a unique match in _allPages
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

  /* ── Graph pane (sigma.js) ────────────────────────────────── */
  async function loadGraph() {
    const canvas = document.getElementById('wiki-graph-canvas');
    const stat = document.getElementById('wiki-graph-stat');
    if (!canvas) return;

    if (typeof window.graphology === 'undefined' || typeof window.Sigma === 'undefined') {
      canvas.innerHTML = `<div class="wiki-graph-empty">
        图谱依赖未加载（CDN 网络问题）。<br>
        <small>左栏与中栏功能不受影响。</small>
      </div>`;
      stat.textContent = '—';
      return;
    }

    try {
      const data = await apiGet('/wiki/graph?edge_limit=2000&page_limit=500');
      const nodes = data.nodes || [];
      const edges = data.edges || [];
      stat.textContent = `${nodes.length} 节点 · ${edges.length} 边`;

      if (nodes.length === 0) {
        canvas.innerHTML = `<div class="wiki-graph-empty">
          暂无节点。<br>
          <small>摄入资料后 wiki worker 会持续构建关系图。</small>
        </div>`;
        return;
      }

      // Build graphology graph
      const g = new window.graphology.Graph({ multi: true });
      const colorByType = {
        entity:   '#4f9eff',
        concept:  '#a07fe5',
        source:   '#10b981',
        query:    '#f59e0b',
        overview: '#ef4444',
      };
      // Spread nodes randomly first; ForceAtlas2 will untangle.
      nodes.forEach((n, i) => {
        const angle = (i / Math.max(1, nodes.length)) * 2 * Math.PI;
        g.addNode(n.id, {
          label: n.title || n.slug,
          x: Math.cos(angle), y: Math.sin(angle),
          size: 4 + Math.sqrt((n.source_ids || []).length || 1),
          color: colorByType[n.page_type] || '#888',
          // Custom data for hover handler
          _pageType: n.page_type,
        });
      });
      edges.forEach(e => {
        if (g.hasNode(e.src_page_id) && g.hasNode(e.dst_page_id) && e.src_page_id !== e.dst_page_id) {
          try {
            g.addEdge(e.src_page_id, e.dst_page_id, {
              size: Math.min(4, 0.5 + Math.log2(1 + e.weight)),
              color: '#999',
            });
          } catch (_) { /* duplicate edge — ignore */ }
        }
      });

      // Layout: ForceAtlas2 a few iterations is enough for moderate graphs
      if (window.graphologyLayoutForceAtlas2) {
        window.graphologyLayoutForceAtlas2.assign(g, {
          iterations: Math.min(200, 20 + nodes.length * 2),
          settings: { gravity: 1, scalingRatio: 8, slowDown: 4 },
        });
      }

      // Clear placeholder
      canvas.innerHTML = '';
      // Sigma needs explicit dimensions
      canvas.style.position = 'relative';

      if (_sigma) {
        try { _sigma.kill(); } catch (_) {}
        _sigma = null;
      }
      _sigma = new window.Sigma(g, canvas, {
        renderLabels: nodes.length <= 80,
        labelSize: 11,
        defaultNodeColor: '#888',
        defaultEdgeColor: '#999',
        minCameraRatio: 0.1,
        maxCameraRatio: 10,
      });

      _sigma.on('clickNode', ({ node }) => loadPage(node));

      // Hover dim non-neighbours
      _sigma.on('enterNode', ({ node }) => {
        const neighbors = new Set([node, ...g.neighbors(node)]);
        _sigma.setSetting('nodeReducer', (n, attrs) => {
          if (neighbors.has(n)) return attrs;
          return { ...attrs, color: '#22232b', label: '' };
        });
        _sigma.setSetting('edgeReducer', (e, attrs) => {
          const ext = g.extremities(e);
          if (ext.includes(node)) return attrs;
          return { ...attrs, hidden: true };
        });
      });
      _sigma.on('leaveNode', () => {
        _sigma.setSetting('nodeReducer', null);
        _sigma.setSetting('edgeReducer', null);
      });

      highlightInGraph(_currentPageId);
    } catch (err) {
      canvas.innerHTML = `<div class="wiki-graph-empty">图谱加载失败：${escape(err.message)}</div>`;
      stat.textContent = '—';
    }
  }

  function highlightInGraph(pageId) {
    if (!_sigma || !pageId) return;
    const g = _sigma.getGraph();
    if (!g.hasNode(pageId)) return;
    // Center camera on this node
    const attrs = g.getNodeAttributes(pageId);
    _sigma.getCamera().animate({ x: attrs.x, y: attrs.y, ratio: 0.5 }, { duration: 400 });
  }

  /* ── Deep Research panel ──────────────────────────────────────
   *
   * Click the telescope button → reveal an inline form (focus textarea +
   * max_urls slider + "Run" button). Submitting POSTs to /wiki/research,
   * then we poll /wiki/research/{task_id} every ~1.5 s and update the
   * panel's status line. On terminal status we reload the active page
   * so the new "## Recent Research" section becomes visible.
   *
   * State is purely DOM-driven — one panel at a time, scoped to the
   * currently-displayed page; no module-level handles aside from a
   * single _researchPoll timer reference for cancellation safety.
   */

  let _researchPoll = null;

  function toggleResearchPanel(pageId) {
    const panel = document.getElementById('wiki-research-panel');
    if (!panel || !pageId) return;
    if (!panel.hidden) {
      // Toggle off — but don't kill an in-flight task, just hide the UI.
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
          // Reload the active page so the appended "Recent Research"
          // section materialises in the preview pane.
          loadPage(pageId);
          // Keep the panel visible with the success summary.
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
      // Re-load the active page if there is one (its body may have updated)
      if (_currentPageId) await loadPage(_currentPageId);
    } finally {
      if (btn) btn.classList.remove('is-spinning');
    }
  }

  /* ── Show-on-tab-event hook ─────────────────────────────── */
  document.addEventListener('tab:shown', async (ev) => {
    if (ev.detail !== 'wiki') return;
    mount();
    // Wait for Sigma to refresh its WebGL viewport now that the panel
    // has real dimensions (it was display:none until just now).
    setTimeout(() => { if (_sigma) _sigma.refresh(); }, 50);
    if (_allPages.length === 0) await refreshAll();
  });

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
  window.OmniWiki = { mount, refreshAll, loadPage, toggleResearchPanel };
})();
