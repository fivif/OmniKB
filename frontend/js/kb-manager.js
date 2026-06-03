/* ── KB Manager Panel (Obsidian/Quartz minimal redesign) ────── */

(function initKbManager() {
  const panel = document.getElementById('tab-kb');

  const TYPE_GROUPS = {
    web:      { label: '网页',   icon: 'globe',      raw: ['url', 'html', 'htm'] },
    text:     { label: '文本',   icon: 'fileText',   raw: ['text', 'txt', 'md', 'markdown'] },
    document: { label: '文档',   icon: 'bookOpen',   raw: ['pdf', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'csv', 'json'] },
    media:    { label: '媒体',   icon: 'film',        raw: ['mp3', 'wav', 'm4a', 'ogg', 'flac', 'mp4', 'mov', 'mkv', 'avi', 'webm'] },
    image:    { label: '图片',   icon: 'image',       raw: ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'tif'] },
    other:    { label: '其他',   icon: 'folder',      raw: [] },
  };

  const TYPE_ORDER = ['web', 'text', 'document', 'media', 'image', 'other'];
  const TYPE_LOOKUP = Object.entries(TYPE_GROUPS).reduce((lookup, [key, value]) => {
    value.raw.forEach(rawType => { lookup[rawType] = key; });
    return lookup;
  }, {});

  // SVG icons (Feather-style minimal)
  const ICONS = {
    search:     '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
    refresh:    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>',
    chevronDown:'<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>',
    pencil:     '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>',
    trash:      '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>',
    download:   '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>',
    globe:      '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>',
    fileText:   '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>',
    bookOpen:   '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>',
    film:       '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="2" y1="7" x2="7" y2="7"/><line x1="2" y1="17" x2="7" y2="17"/><line x1="17" y1="7" x2="22" y2="7"/><line x1="17" y1="17" x2="22" y2="17"/></svg>',
    image:      '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>',
    folder:     '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>',
    tag:        '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg>',
    plus:       '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>',
  };

  panel.innerHTML = `
    <div class="kb-shell">
      <div class="kb-topbar">
        <div class="kb-search-wrap">
          <span class="kb-search-icon">${ICONS.search}</span>
          <input id="kb-search" class="kb-search-input" type="search" placeholder="搜索来源名称、URL 或标签…" />
        </div>
        <div class="kb-topbar-actions">
          <select id="kb-tag-filter" class="kb-tag-select">
            <option value="">所有标签</option>
          </select>
          <button id="btn-kb-refresh" class="kb-icon-btn" type="button" title="刷新" aria-label="刷新">${ICONS.refresh}</button>
          <div class="kb-export-wrap">
            <button id="btn-export" class="kb-icon-btn" type="button" title="导出" aria-label="导出">${ICONS.download}</button>
            <div id="export-menu" class="kb-export-menu hidden">
              <button id="export-json" type="button">JSON</button>
              <button id="export-csv" type="button">CSV (ZIP)</button>
              <button id="export-zip" type="button">每源 ZIP</button>
            </div>
          </div>
        </div>
      </div>

      <div id="kb-category-strip" class="kb-category-strip"></div>
      <div id="kb-result-meta" class="kb-result-meta"></div>

      <div id="batch-toolbar" class="kb-batch-toolbar hidden">
        <span id="batch-count" class="kb-batch-count"></span>
        <button id="btn-select-all" class="kb-batch-btn" type="button" title="全选当前页">☐ 全选</button>
        <button id="btn-deselect-all" class="kb-batch-btn kb-batch-btn--ghost hidden" type="button" title="取消全选">☑ 取消全选</button>
        <div class="kb-batch-spacer"></div>
        <select id="kb-scenario-select" class="kb-batch-select">
          <option value="">选择场景</option>
        </select>
        <button id="btn-batch-wiki" class="kb-batch-btn kb-batch-btn--primary" type="button" title="为选中的来源批量生成 Wiki 页面">🧠 生成 Wiki</button>
        <button id="btn-batch-add-scenario" class="kb-batch-btn kb-batch-btn--primary" type="button">${ICONS.plus} 加入场景</button>
        <input id="batch-tag-input" class="kb-batch-input" type="text" placeholder="标签（逗号分隔）" />
        <button id="btn-batch-add-tag" class="kb-batch-btn" type="button">追加标签</button>
        <button id="btn-batch-replace-tag" class="kb-batch-btn" type="button">替换标签</button>
        <button id="btn-batch-remove-tag" class="kb-batch-btn" type="button">移除标签</button>
        <button id="btn-batch-delete" class="kb-batch-btn kb-batch-btn--danger" type="button">批量删除</button>
        <button id="btn-batch-clear" class="kb-batch-btn kb-batch-btn--ghost" type="button">取消选择</button>
      </div>

      <div id="kb-group-view" class="kb-group-view"></div>

      <div class="kb-pagination-row">
        <button id="kb-prev" class="kb-page-btn" type="button" disabled>上一页</button>
        <span id="kb-page-info" class="kb-page-info"></span>
        <button id="kb-next" class="kb-page-btn" type="button" disabled>下一页</button>
      </div>
    </div>

    <!-- Chunks Drawer -->
    <div id="chunks-drawer" class="kb-drawer-overlay hidden">
      <div class="kb-drawer-backdrop" id="drawer-backdrop"></div>
      <div class="kb-drawer-panel">
        <div class="kb-drawer-header">
          <h3 id="drawer-title" class="kb-drawer-title"></h3>
          <button id="btn-close-drawer" class="kb-drawer-close" type="button" aria-label="关闭">&times;</button>
        </div>
        <div id="drawer-content" class="kb-drawer-body"></div>
      </div>
    </div>

    <!-- Delete Confirmation Modal -->
    <div id="delete-modal" class="kb-modal-overlay hidden">
      <div class="kb-modal-backdrop"></div>
      <div class="kb-modal-card">
        <h3 id="delete-modal-title" class="kb-modal-title">删除来源</h3>
        <p id="delete-modal-desc" class="kb-modal-desc"></p>
        <div class="kb-modal-actions">
          <button id="btn-cancel-delete" class="kb-batch-btn" type="button">取消</button>
          <button id="btn-confirm-delete" class="kb-batch-btn kb-batch-btn--danger" type="button">确认删除</button>
        </div>
      </div>
    </div>

    <!-- Tag Edit Modal -->
    <div id="tag-edit-modal" class="kb-modal-overlay hidden">
      <div class="kb-modal-backdrop"></div>
      <div class="kb-modal-card">
        <h3 class="kb-modal-title">编辑标签</h3>
        <p id="tag-edit-source-name" class="kb-modal-subtitle"></p>
        <input id="tag-edit-input" class="kb-tag-edit-input" type="text" placeholder="标签（逗号分隔）" />
        <div class="kb-modal-actions">
          <button id="btn-cancel-tag-edit" class="kb-batch-btn" type="button">取消</button>
          <button id="btn-confirm-tag-edit" class="kb-batch-btn kb-batch-btn--primary" type="button">确认</button>
        </div>
      </div>
    </div>
  `;

  // ── State ──────────────────────────────────────────────────
  let page = 0;
  const pageSize = 50;
  let deleteTargetId = null;
  let deleteBatchMode = false;
  let tagEditTargetId = null;
  let filterText = '';
  let filterTag = '';
  let categoryKey = 'all';
  let selectedIds = new Set();
  let catalogSources = [];
  let currentPageSources = [];
  let scenarioOptions = [];
  let collapsedSections = new Set();

  // ── Helpers ────────────────────────────────────────────────
  function escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function parseTags(value) {
    return String(value || '')
      .split(',')
      .map(tag => tag.trim())
      .filter(Boolean);
  }

  function normalizeTypeKey(type) {
    const raw = String(type || '').trim().toLowerCase();
    return TYPE_LOOKUP[raw] || 'other';
  }

  function getTypeMeta(type) {
    const raw = String(type || '').trim().toLowerCase();
    const key = normalizeTypeKey(raw);
    const group = TYPE_GROUPS[key];
    return { key, label: group.label, icon: group.icon, raw, rawLabel: raw ? raw.toUpperCase() : 'UNKNOWN' };
  }

  function formatDate(value) {
    try { return new Date(value).toLocaleDateString(); }
    catch { return ''; }
  }

  function getSourceSearchText(source) {
    return [source.name, source.url, source.type, ...(Array.isArray(source.tags) ? source.tags : [])]
      .filter(Boolean).join(' ').toLowerCase();
  }

  function getBaseFilteredSources() {
    return catalogSources.filter(source => {
      const matchesTag = !filterTag || (Array.isArray(source.tags) && source.tags.includes(filterTag));
      const matchesText = !filterText || getSourceSearchText(source).includes(filterText);
      return matchesTag && matchesText;
    });
  }

  function getVisibleSources() {
    const baseSources = getBaseFilteredSources();
    if (categoryKey === 'all') return baseSources;
    return baseSources.filter(source => getTypeMeta(source.type).key === categoryKey);
  }

  function getCategoryCounts(sources) {
    const counts = { all: sources.length };
    TYPE_ORDER.forEach(key => { counts[key] = 0; });
    sources.forEach(source => { counts[getTypeMeta(source.type).key] += 1; });
    return counts;
  }

  // ── Render: category filter pills ──────────────────────────
  function renderCategoryStrip() {
    const strip = document.getElementById('kb-category-strip');
    const baseSources = getBaseFilteredSources();
    const counts = getCategoryCounts(baseSources);

    if (categoryKey !== 'all' && counts[categoryKey] === 0) {
      categoryKey = 'all';
    }

    let html = `<button class="kb-cat-pill${categoryKey === 'all' ? ' active' : ''}" data-category="all" type="button">全部<span class="kb-cat-count">${counts.all}</span></button>`;

    TYPE_ORDER.forEach(key => {
      if (counts[key] > 0) {
        const group = TYPE_GROUPS[key];
        html += `<button class="kb-cat-pill${categoryKey === key ? ' active' : ''}" data-category="${key}" type="button">${ICONS[group.icon]} ${escapeHtml(group.label)}<span class="kb-cat-count">${counts[key]}</span></button>`;
      }
    });

    strip.innerHTML = html;
    strip.querySelectorAll('.kb-cat-pill').forEach(btn => {
      btn.addEventListener('click', () => {
        categoryKey = btn.dataset.category;
        page = 0;
        clearSelection();
        render();
      });
    });
  }

  // ── Render: result meta bar ────────────────────────────────
  function renderResultMeta() {
    const meta = document.getElementById('kb-result-meta');
    const baseCount = getBaseFilteredSources().length;
    const visibleCount = getVisibleSources().length;
    const categoryLabel = categoryKey === 'all' ? '全部分类' : TYPE_GROUPS[categoryKey].label;
    const parts = [`<strong>${visibleCount}</strong> 条来源`];
    if (visibleCount !== baseCount) parts.push(`筛选自 ${baseCount}`);
    parts.push(escapeHtml(categoryLabel));
    if (filterTag) parts.push(`标签: ${escapeHtml(filterTag)}`);
    if (filterText) parts.push(`"${escapeHtml(filterText)}"`);
    meta.innerHTML = parts.join(' · ');
  }

  // ── Selection ──────────────────────────────────────────────
  function toggleSelect(id, checked) {
    if (checked) selectedIds.add(id);
    else selectedIds.delete(id);
    updateSelectionUI();
    updateSelectAllButtons();
  }

  function selectAllVisible() {
    document.querySelectorAll('.kb-row-checkbox').forEach(cb => {
      cb.checked = true;
      selectedIds.add(cb.dataset.id);
    });
    updateSelectionUI();
    updateSelectAllButtons();
  }

  function deselectAll() {
    clearSelection();
    updateSelectAllButtons();
  }

  function updateSelectAllButtons() {
    const btnSelectAll = document.getElementById('btn-select-all');
    const btnDeselectAll = document.getElementById('btn-deselect-all');
    if (!btnSelectAll || !btnDeselectAll) return;
    const allCbs = document.querySelectorAll('.kb-row-checkbox');
    const allChecked = allCbs.length > 0 && [...allCbs].every(cb => cb.checked);
    const someChecked = [...allCbs].some(cb => cb.checked);
    btnSelectAll.classList.toggle('hidden', allChecked);
    btnDeselectAll.classList.toggle('hidden', !someChecked);
  }

  function clearSelection() {
    selectedIds.clear();
    document.querySelectorAll('.kb-row-checkbox').forEach(cb => { cb.checked = false; });
    updateSelectionUI();
  }

  function updateSelectionUI() {
    const toolbar = document.getElementById('batch-toolbar');
    const batchCount = document.getElementById('batch-count');
    const scenarioSelect = document.getElementById('kb-scenario-select');
    const addScenarioBtn = document.getElementById('btn-batch-add-scenario');

    if (selectedIds.size > 0) {
      toolbar.classList.remove('hidden');
      batchCount.textContent = `已选 ${selectedIds.size} 项`;
    } else {
      toolbar.classList.add('hidden');
    }

    scenarioSelect.disabled = !scenarioOptions.length;
    addScenarioBtn.disabled = !selectedIds.size || !scenarioOptions.length || !scenarioSelect.value;
  }

  // ── Render: individual source row ──────────────────────────
  function sourceRowHtml(source) {
    const checked = selectedIds.has(source.id) ? 'checked' : '';
    const typeMeta = getTypeMeta(source.type);
    const tags = Array.isArray(source.tags) ? source.tags : [];
    const dateStr = formatDate(source.created_at);
    const statusHtml = typeof statusBadge === 'function' ? statusBadge(source.status) : '';

    const tagsHtml = tags.length
      ? tags.map(tag => `<span class="kb-tag-pill" data-tag="${escapeHtml(tag)}">${escapeHtml(tag)}</span>`).join('')
      : '';

    return `
      <div class="kb-source-row" data-id="${escapeHtml(source.id)}">
        <label class="kb-row-check">
          <input type="checkbox" class="kb-row-checkbox" data-id="${escapeHtml(source.id)}" ${checked} />
        </label>
        <button class="kb-source-name" data-id="${escapeHtml(source.id)}" data-name="${escapeHtml(source.name)}" type="button" title="查看关联 Wiki">
          <span class="kb-source-icon">${ICONS[typeMeta.icon] || ICONS.folder}</span>
          <span class="kb-source-label">${escapeHtml(source.name)}</span>
        </button>
        <span class="kb-source-url">${escapeHtml(source.url || '')}</span>
        <span class="kb-source-type">${escapeHtml(typeMeta.label)}</span>
        ${statusHtml ? `<span class="kb-source-status">${statusHtml}</span>` : ''}
        ${tagsHtml ? `<span class="kb-source-tags">${tagsHtml}</span>` : ''}
        <span class="kb-source-date">${escapeHtml(dateStr)}</span>
        <span class="kb-row-actions">
          <button class="kb-row-action" data-id="${escapeHtml(source.id)}" data-name="${escapeHtml(source.name)}" data-tags="${encodeURIComponent(JSON.stringify(tags))}" type="button" title="编辑标签" aria-label="编辑标签">${ICONS.tag}</button>
          <button class="kb-row-action kb-row-action--danger" data-id="${escapeHtml(source.id)}" type="button" title="删除" aria-label="删除">${ICONS.trash}</button>
        </span>
      </div>`;
  }

  // ── Build type groups from sources ─────────────────────────
  function buildTypeGroups(sources) {
    const grouped = {};
    sources.forEach(source => {
      const key = getTypeMeta(source.type).key;
      if (!grouped[key]) grouped[key] = [];
      grouped[key].push(source);
    });

    return TYPE_ORDER
      .filter(key => grouped[key] && grouped[key].length)
      .map(key => ({
        id: key,
        label: TYPE_GROUPS[key].label,
        icon: TYPE_GROUPS[key].icon,
        sources: grouped[key],
      }));
  }

  // ── Render: grouped source list ────────────────────────────
  function renderGroupView() {
    const container = document.getElementById('kb-group-view');
    const visibleSources = getVisibleSources();
    currentPageSources = [];

    if (!visibleSources.length) {
      container.innerHTML = `
        <div class="kb-empty-state">
          <div class="kb-empty-icon">${ICONS.folder}</div>
          <div class="kb-empty-title">没有找到来源</div>
          <div class="kb-empty-copy">换个分类、标签或关键词试试。</div>
        </div>`;
      document.getElementById('kb-prev').disabled = true;
      document.getElementById('kb-next').disabled = true;
      document.getElementById('kb-page-info').textContent = '';
      return;
    }

    const groups = buildTypeGroups(visibleSources);
    const totalPages = Math.max(1, Math.ceil(groups.length / pageSize));
    if (page >= totalPages) page = totalPages - 1;

    const pageGroups = groups.slice(page * pageSize, page * pageSize + pageSize);

    document.getElementById('kb-prev').disabled = page === 0;
    document.getElementById('kb-next').disabled = page >= totalPages - 1;
    document.getElementById('kb-page-info').textContent = totalPages > 1 ? `${page + 1} / ${totalPages}` : '';

    let html = '';

    pageGroups.forEach(group => {
      const isCollapsed = collapsedSections.has(group.id);
      const sectionId = `kb-section-${group.id}`;

      html += `
        <section class="kb-section">
          <button class="kb-section-header" data-section="${group.id}" type="button" aria-expanded="${!isCollapsed}">
            <span class="kb-section-chevron">${ICONS.chevronDown}</span>
            <span class="kb-section-icon">${ICONS[group.icon] || ICONS.folder}</span>
            <span class="kb-section-label">${escapeHtml(group.label)}</span>
            <span class="kb-section-count">${group.sources.length}</span>
          </button>
          <div id="${sectionId}" class="kb-section-body${isCollapsed ? ' hidden' : ''}">
            ${group.sources.map(sourceRowHtml).join('')}
          </div>
        </section>`;
    });

    container.innerHTML = html;

    // Bind events
    bindRowEvents(container);
    bindSectionToggles(container);
  }

  function bindSectionToggles(container) {
    container.querySelectorAll('.kb-section-header').forEach(btn => {
      btn.addEventListener('click', () => {
        const sectionId = btn.dataset.section;
        const body = document.getElementById(`kb-section-${sectionId}`);
        if (!body) return;
        const isHidden = body.classList.toggle('hidden');
        if (isHidden) collapsedSections.add(sectionId);
        else collapsedSections.delete(sectionId);
        btn.setAttribute('aria-expanded', !isHidden);
      });
    });
  }

  function bindRowEvents(container) {
    // Checkboxes
    container.querySelectorAll('.kb-row-checkbox').forEach(cb => {
      cb.addEventListener('change', () => toggleSelect(cb.dataset.id, cb.checked));
    });
    updateSelectAllButtons();

    // Source name click -> open chunks drawer
    container.querySelectorAll('.kb-source-name').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        openChunksDrawer(btn.dataset.id, btn.dataset.name);
      });
    });

    // Tag pills -> filter by tag
    container.querySelectorAll('.kb-tag-pill').forEach(pill => {
      pill.addEventListener('click', (e) => {
        e.stopPropagation();
        document.getElementById('kb-tag-filter').value = pill.dataset.tag;
        filterTag = pill.dataset.tag;
        page = 0;
        clearSelection();
        render();
      });
    });

    // Row action: edit tags
    container.querySelectorAll('.kb-row-action[data-tags]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        openTagEdit(btn.dataset.id, btn.dataset.name, btn.dataset.tags);
      });
    });

    // Row action: delete
    container.querySelectorAll('.kb-row-action--danger').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        openDeleteModal(btn.dataset.id);
      });
    });
  }

  // ── Main render ────────────────────────────────────────────
  function render() {
    renderCategoryStrip();
    renderResultMeta();
    renderGroupView();
  }

  // ── Data loading ───────────────────────────────────────────
  async function loadTagFilter() {
    try {
      const data = await apiJson('/kb/tags');
      const select = document.getElementById('kb-tag-filter');
      while (select.options.length > 1) select.remove(1);
      (data.tags || []).forEach(tag => {
        const option = document.createElement('option');
        option.value = tag;
        option.textContent = tag;
        select.appendChild(option);
      });
      select.value = filterTag;
    } catch { /* silent */ }
  }

  async function loadScenarioOptions() {
    try {
      const data = await apiJson('/scenarios');
      scenarioOptions = data.scenarios || [];
    } catch {
      scenarioOptions = [];
    }
    const select = document.getElementById('kb-scenario-select');
    const currentValue = select.value;
    select.innerHTML = '<option value="">选择场景</option>' + scenarioOptions.map(s => (
      `<option value="${escapeHtml(s.id)}">${escapeHtml(s.name || s.id)}</option>`
    )).join('');
    select.value = scenarioOptions.some(s => s.id === currentValue) ? currentValue : '';
    updateSelectionUI();
  }

  async function loadCatalog() {
    const data = await apiJson('/kb/sources?limit=500&offset=0');
    catalogSources = data.sources || [];
  }

  async function refreshAll({ silent = false } = {}) {
    try {
      await Promise.all([loadTagFilter(), loadCatalog(), loadScenarioOptions()]);
      render();
      if (!silent) toast('知识库列表已刷新', 'success');
    } catch (error) {
      document.getElementById('kb-group-view').innerHTML = `
        <div class="kb-empty-state">
          <div class="kb-empty-icon">${ICONS.folder}</div>
          <div class="kb-empty-title">无法加载知识库</div>
          <div class="kb-empty-copy">${escapeHtml(error.message)}</div>
        </div>`;
    }
  }

  // ── Source detail drawer (shows wiki pages instead of chunks) ──
  async function openChunksDrawer(sourceId, sourceName) {
    const drawer = document.getElementById('chunks-drawer');
    const content = document.getElementById('drawer-content');
    document.getElementById('drawer-title').textContent = sourceName;
    content.innerHTML = '<p class="kb-drawer-loading">加载关联 Wiki 页面…</p>';
    drawer.classList.remove('hidden');

    try {
      // Fetch wiki pages linked to this source
      const data = await apiJson(`/wiki/pages?limit=200`);
      const allPages = Array.isArray(data) ? data : [];
      const linked = allPages.filter(p => {
        const sids = p.source_ids || [];
        return sids.includes(sourceId);
      });
      if (!linked.length) {
        content.innerHTML = `<p class="kb-drawer-loading">该来源尚未生成 Wiki 页面。</p>
          <button class="btn btn-primary kb-gen-wiki-btn" style="margin-top:12px;width:100%;"
            data-source-id="${sourceId}" data-source-name="${escapeHtml(sourceName)}">生成 Wiki 页面</button>`;
        // Wire the button after DOM insert
        setTimeout(() => {
          const btn = content.querySelector('.kb-gen-wiki-btn');
          if (btn) btn.addEventListener('click', async () => {
            btn.disabled = true;
            btn.textContent = '生成中…';
            try {
              const base = (window.getApiBase && window.getApiBase()) || '';
              const r = await fetch(base + '/wiki/sync', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({source_ids: [btn.dataset.sourceId]})
              });
              const d = await r.json();
              btn.textContent = '已加入队列: ' + d.task_id.slice(-8);
              setTimeout(() => openChunksDrawer(btn.dataset.sourceId, btn.dataset.sourceName), 3000);
            } catch(e) {
              btn.textContent = '失败: ' + e.message;
              btn.disabled = false;
            }
          });
        }, 50);
        return;
      }
      content.innerHTML = linked.map(p => {
        const pid = p.id;
        return `
        <div class="kb-chunk-card" style="cursor:pointer" onclick="window.OmniKBApp&&window.OmniKBApp.showTab('wiki');setTimeout(()=>window.OmniWiki&&window.OmniWiki.loadPage('${escapeHtml(pid)}'),200)">
          <div class="kb-chunk-head">
            <span class="kb-chunk-index">${escapeHtml(p.page_type)}:${escapeHtml(p.slug)}</span>
            <span class="kb-chunk-id">rev ${p.revision || 1}</span>
          </div>
          <p class="kb-chunk-text">${escapeHtml(p.title)}</p>
          ${p.summary ? `<p style="font-size:12px;color:var(--t-secondary);margin-top:4px;">${escapeHtml(p.summary.slice(0, 200))}</p>` : ''}
        </div>`;
      }).join('');
    } catch {
      content.innerHTML = '<p class="kb-drawer-loading" style="color:var(--danger)">加载 Wiki 页面失败</p>';
    }
  }

  function closeDrawer() {
    document.getElementById('chunks-drawer').classList.add('hidden');
  }

  // ── Tag edit modal ─────────────────────────────────────────
  function openTagEdit(id, name, tagsJson) {
    tagEditTargetId = id;
    document.getElementById('tag-edit-source-name').textContent = name;
    let tags = [];
    try { tags = JSON.parse(decodeURIComponent(tagsJson)); } catch {}
    document.getElementById('tag-edit-input').value = tags.join(', ');
    document.getElementById('tag-edit-modal').classList.remove('hidden');
  }

  async function confirmTagEdit() {
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
      await refreshAll({ silent: true });
    } catch {
      toast('更新标签失败', 'error');
    }
  }

  // ── Delete modal ───────────────────────────────────────────
  function openDeleteModal(sourceId) {
    deleteBatchMode = false;
    deleteTargetId = sourceId;
    document.getElementById('delete-modal-title').textContent = '删除来源';
    document.getElementById('delete-modal-desc').textContent = '此操作将永久删除该来源及其所有片段，无法撤销。';
    document.getElementById('delete-modal').classList.remove('hidden');
  }

  async function confirmDelete() {
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
      await refreshAll({ silent: true });
      if (window.OmniKBApp?.refreshStats) window.OmniKBApp.refreshStats();
      else if (typeof refreshStats === 'function') refreshStats();
    } catch {
      toast('删除失败', 'error');
    }
  }

  // ── Batch tag ──────────────────────────────────────────────
  async function batchTag(mode) {
    const input = document.getElementById('batch-tag-input').value.trim();
    const tags = parseTags(input);
    if (mode !== 'remove' && !tags.length) {
      toast('请输入至少一个标签', 'error');
      return;
    }
    if (!selectedIds.size) {
      toast('请先选择来源', 'error');
      return;
    }
    try {
      await apiJson('/kb/sources/batch-tag', {
        method: 'POST',
        body: JSON.stringify({ ids: [...selectedIds], tags, mode }),
      });
      toast('批量标签操作已完成', 'success');
      clearSelection();
      await refreshAll({ silent: true });
    } catch (error) {
      toast(`操作失败：${error.message}`, 'error');
    }
  }

  // ── Batch generate Wiki ─────────────────────────────────────
  async function batchGenerateWiki() {
    if (!selectedIds.size) { toast('请先选择来源', 'error'); return; }
    const ids = [...selectedIds];
    try {
      const base = (typeof getApiBase === 'function' ? getApiBase() : '');
      const r = await fetch(base + '/wiki/sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_ids: ids }),
      });
      const data = await r.json();
      if (r.ok) {
        toast(`Wiki 生成已启动: ${data.accepted} 个处理, ${data.rejected} 个跳过`, 'success');
      } else {
        toast('Wiki 生成失败: ' + (data.detail || r.statusText), 'error');
      }
    } catch (e) {
      toast('Wiki 生成失败: ' + e.message, 'error');
    }
  }

  // ── Batch add to scenario ──────────────────────────────────
  async function batchAddToScenario() {
    const scenarioId = document.getElementById('kb-scenario-select').value;
    if (!selectedIds.size) { toast('请先选择来源', 'error'); return; }
    if (!scenarioId) { toast('请先选择场景', 'error'); return; }

    try {
      const data = await apiJson(`/scenarios/${scenarioId}/sources`, {
        method: 'POST',
        body: JSON.stringify({
          entries: [...selectedIds].map(sourceId => ({ source_id: sourceId, chunk_id: '' })),
          added_by: 'kb_manager',
        }),
      });
      let msg = `已将 ${data.added || 0} 个来源加入场景`;
      if (data.wiki_linked > 0) {
        msg += `（含 ${data.wiki_linked} 个关联 Wiki 页）`;
      }
      toast(msg, 'success');
      clearSelection();
    } catch (error) {
      toast(`加入场景失败：${error.message}`, 'error');
    }
  }

  // ── Event listeners ────────────────────────────────────────
  document.getElementById('btn-close-drawer').addEventListener('click', closeDrawer);
  document.getElementById('drawer-backdrop').addEventListener('click', closeDrawer);

  document.getElementById('btn-cancel-tag-edit').addEventListener('click', () => {
    document.getElementById('tag-edit-modal').classList.add('hidden');
    tagEditTargetId = null;
  });
  document.getElementById('btn-confirm-tag-edit').addEventListener('click', confirmTagEdit);

  document.getElementById('btn-cancel-delete').addEventListener('click', () => {
    document.getElementById('delete-modal').classList.add('hidden');
    deleteTargetId = null;
    deleteBatchMode = false;
  });
  document.getElementById('btn-confirm-delete').addEventListener('click', confirmDelete);

  document.getElementById('btn-batch-add-tag').addEventListener('click', () => batchTag('add'));
  document.getElementById('btn-batch-replace-tag').addEventListener('click', () => batchTag('replace'));
  document.getElementById('btn-batch-remove-tag').addEventListener('click', () => batchTag('remove'));
  document.getElementById('kb-scenario-select').addEventListener('change', updateSelectionUI);
  document.getElementById('btn-batch-add-scenario').addEventListener('click', batchAddToScenario);
  document.getElementById('btn-batch-wiki').addEventListener('click', batchGenerateWiki);
  document.getElementById('btn-batch-clear').addEventListener('click', deselectAll);
  document.getElementById('btn-select-all').addEventListener('click', selectAllVisible);
  document.getElementById('btn-deselect-all').addEventListener('click', deselectAll);

  document.getElementById('btn-batch-delete').addEventListener('click', () => {
    if (!selectedIds.size) return;
    deleteBatchMode = true;
    document.getElementById('delete-modal-title').textContent = `批量删除 ${selectedIds.size} 个来源`;
    document.getElementById('delete-modal-desc').textContent = '此操作将永久删除所选来源及其全部片段，无法撤销。';
    document.getElementById('delete-modal').classList.remove('hidden');
  });

  // Export
  document.getElementById('btn-export').addEventListener('click', () => {
    document.getElementById('export-menu').classList.toggle('hidden');
  });
  document.addEventListener('click', (event) => {
    const wrap = document.querySelector('.kb-export-wrap');
    if (wrap && !wrap.contains(event.target)) {
      document.getElementById('export-menu').classList.add('hidden');
    }
  });
  ['json', 'csv', 'zip'].forEach(format => {
    document.getElementById(`export-${format}`).addEventListener('click', () => {
      const base = typeof getApiBase === 'function' ? getApiBase() : '';
      window.open(`${base}/kb/export?fmt=${format}`, '_blank');
      document.getElementById('export-menu').classList.add('hidden');
    });
  });

  // Pagination
  document.getElementById('kb-prev').addEventListener('click', () => {
    if (page === 0) return;
    page -= 1;
    render();
  });
  document.getElementById('kb-next').addEventListener('click', () => {
    page += 1;
    render();
  });

  // Search & filter
  document.getElementById('btn-kb-refresh').addEventListener('click', () => {
    clearSelection();
    refreshAll();
  });
  document.getElementById('kb-search').addEventListener('input', (event) => {
    filterText = event.target.value.trim().toLowerCase();
    page = 0;
    clearSelection();
    render();
  });
  document.getElementById('kb-tag-filter').addEventListener('change', (event) => {
    filterTag = event.target.value;
    page = 0;
    clearSelection();
    render();
  });

  // Tab activation
  document.addEventListener('tab:shown', event => {
    if (event.detail === 'kb') {
      refreshAll({ silent: true });
    }
  });

  // Initial load
  refreshAll({ silent: true });
})();
