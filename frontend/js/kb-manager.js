/* ── KB Manager Panel ───────────────────────────────────────── */

(function initKbManager() {
  const panel = document.getElementById('tab-kb');

  const TYPE_GROUPS = {
    web: {
      label: '网页',
      icon: '🌐',
      raw: ['url', 'html', 'htm'],
    },
    text: {
      label: '文本',
      icon: '✍️',
      raw: ['text', 'txt', 'md', 'markdown'],
    },
    document: {
      label: '文档',
      icon: '📚',
      raw: ['pdf', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'csv', 'json'],
    },
    media: {
      label: '媒体',
      icon: '🎞️',
      raw: ['mp3', 'wav', 'm4a', 'ogg', 'flac', 'mp4', 'mov', 'mkv', 'avi', 'webm'],
    },
    image: {
      label: '图片',
      icon: '🖼️',
      raw: ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'tif'],
    },
    other: {
      label: '其他',
      icon: '📁',
      raw: [],
    },
  };

  const TYPE_ORDER = ['web', 'text', 'document', 'media', 'image', 'other'];
  const TYPE_LOOKUP = Object.entries(TYPE_GROUPS).reduce((lookup, [key, value]) => {
    value.raw.forEach(rawType => {
      lookup[rawType] = key;
    });
    return lookup;
  }, {});

  panel.innerHTML = `
    <div class="kb-shell">
      <div class="kb-actions-row">
        <div class="btn-group">
          <button id="btn-view-list" class="view-btn active" type="button">列表</button>
          <button id="btn-view-type" class="view-btn" type="button">按分类</button>
          <button id="btn-view-tag" class="view-btn" type="button">按标签</button>
        </div>
        <button id="btn-kb-refresh" class="btn btn-secondary btn-sm" type="button">刷新</button>
      </div>

      <div class="kb-stats-grid">
        <div class="stat-card">
          <div class="stat-value" id="kb-stat-sources">—</div>
          <div class="stat-label">来源总数</div>
        </div>
        <div class="stat-card">
          <div class="stat-value" id="kb-stat-chunks">—</div>
          <div class="stat-label">片段总数</div>
        </div>
        <div class="stat-card">
          <div class="stat-value" id="kb-stat-selected">0</div>
          <div class="stat-label">当前选择</div>
        </div>
        <div class="stat-card">
          <div class="stat-value" id="kb-stat-tags">—</div>
          <div class="stat-label">标签数</div>
        </div>
      </div>

      <div class="section-card kb-discovery-card">
        <div class="section-card-body stack-md">
          <div class="kb-filter-row">
            <div class="input-group kb-search-wrap">
              <span class="input-prefix kb-search-prefix">🔎</span>
              <input id="kb-search" class="input kb-search-input" type="search" placeholder="搜索来源名称、URL 或标签…" />
            </div>
            <select id="kb-tag-filter" class="select kb-tag-select">
              <option value="">所有标签</option>
            </select>
            <div class="kb-export-wrap" id="export-wrap">
              <button id="btn-export" class="btn btn-secondary" type="button">导出</button>
              <div id="export-menu" class="kb-export-menu hidden">
                <a id="export-json" href="#">JSON</a>
                <a id="export-csv" href="#">CSV (ZIP)</a>
                <a id="export-zip" href="#">每源 ZIP</a>
              </div>
            </div>
          </div>

          <div id="kb-category-strip" class="kb-category-strip"></div>
          <div id="kb-result-meta" class="kb-result-meta"></div>
        </div>
      </div>

      <div id="batch-toolbar" class="hidden kb-batch-toolbar">
        <span id="batch-count" class="kb-batch-count"></span>
        <div class="kb-batch-spacer"></div>
        <input id="batch-tag-input" class="input kb-batch-input" type="text" placeholder="标签（逗号分隔）" />
        <button id="btn-batch-add-tag" class="btn btn-secondary btn-sm" type="button">追加标签</button>
        <button id="btn-batch-replace-tag" class="btn btn-secondary btn-sm" type="button">替换标签</button>
        <button id="btn-batch-remove-tag" class="btn btn-secondary btn-sm" type="button">移除标签</button>
        <button id="btn-batch-delete" class="btn btn-danger btn-sm" type="button">批量删除</button>
        <button id="btn-batch-clear" class="btn btn-ghost btn-sm" type="button">取消选择</button>
      </div>

      <div id="kb-list-view" class="kb-list-view">
        <div class="table-card kb-table-shell">
          <table class="table table-sticky-head kb-table">
            <thead>
              <tr>
                <th style="width:36px;padding-left:16px;">
                  <input type="checkbox" id="chk-select-all" style="accent-color:var(--accent);cursor:pointer;" />
                </th>
                <th>来源</th>
                <th style="width:140px;">分类</th>
                <th style="width:110px;">创建时间</th>
                <th style="width:104px;">状态</th>
                <th style="width:152px;">操作</th>
              </tr>
            </thead>
            <tbody id="kb-tbody"></tbody>
          </table>
        </div>
        <div class="kb-pagination-row">
          <button id="kb-prev" class="btn btn-secondary btn-sm" type="button">← 上页</button>
          <span id="kb-page-info" class="kb-page-info">第 1 页</span>
          <button id="kb-next" class="btn btn-secondary btn-sm" type="button">下页 →</button>
        </div>
      </div>

      <div id="kb-group-view" class="kb-group-view hidden"></div>
    </div>

    <div id="chunks-drawer" class="hidden" style="position:fixed;inset:0;z-index:var(--z-modal);display:flex;">
      <div style="position:absolute;inset:0;background:rgba(0,0,0,.45);backdrop-filter:blur(4px);" id="drawer-backdrop"></div>
      <div style="position:absolute;right:0;top:0;bottom:0;width:520px;max-width:100vw;background:var(--bg-surface);border-left:1px solid var(--bd-default);display:flex;flex-direction:column;box-shadow:var(--sh-xl);">
        <div style="display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid var(--bd-subtle);">
          <h3 id="drawer-title" style="font-size:15px;font-weight:600;color:var(--t-primary);"></h3>
          <button id="btn-close-drawer" style="width:28px;height:28px;display:flex;align-items:center;justify-content:center;border-radius:var(--r-sm);border:none;background:transparent;color:var(--t-tertiary);cursor:pointer;font-size:18px;transition:background var(--dur-fast);">&times;</button>
        </div>
        <div id="drawer-content" style="flex:1;overflow-y:auto;padding:16px 20px;"></div>
      </div>
    </div>

    <div id="delete-modal" class="hidden" style="position:fixed;inset:0;z-index:var(--z-modal);display:flex;align-items:center;justify-content:center;">
      <div style="position:absolute;inset:0;background:rgba(0,0,0,.45);backdrop-filter:blur(4px);"></div>
      <div style="position:relative;background:var(--bg-surface);border:1px solid var(--bd-default);border-radius:var(--r-lg);box-shadow:var(--sh-xl);padding:24px;max-width:420px;width:90vw;">
        <h3 id="delete-modal-title" style="font-size:15px;font-weight:600;color:var(--t-primary);margin-bottom:8px;">删除来源</h3>
        <p id="delete-modal-desc" style="font-size:13px;color:var(--t-secondary);margin-bottom:20px;line-height:1.5;"></p>
        <div style="display:flex;justify-content:flex-end;gap:8px;">
          <button id="btn-cancel-delete" class="btn btn-secondary btn-sm" type="button">取消</button>
          <button id="btn-confirm-delete" class="btn btn-danger btn-sm" type="button">确认删除</button>
        </div>
      </div>
    </div>

    <div id="tag-edit-modal" class="hidden" style="position:fixed;inset:0;z-index:var(--z-modal);display:flex;align-items:center;justify-content:center;">
      <div style="position:absolute;inset:0;background:rgba(0,0,0,.45);backdrop-filter:blur(4px);"></div>
      <div style="position:relative;background:var(--bg-surface);border:1px solid var(--bd-default);border-radius:var(--r-lg);box-shadow:var(--sh-xl);padding:24px;max-width:420px;width:90vw;">
        <h3 style="font-size:15px;font-weight:600;color:var(--t-primary);margin-bottom:4px;">编辑标签</h3>
        <p id="tag-edit-source-name" style="font-size:13px;color:var(--t-secondary);margin-bottom:12px;"></p>
        <input id="tag-edit-input" class="input" type="text" placeholder="标签（逗号分隔）" style="margin-bottom:16px;" />
        <div style="display:flex;justify-content:flex-end;gap:8px;">
          <button id="btn-cancel-tag-edit" class="btn btn-secondary btn-sm" type="button">取消</button>
          <button id="btn-confirm-tag-edit" class="btn btn-primary btn-sm" type="button">确认</button>
        </div>
      </div>
    </div>
  `;

  let page = 0;
  const pageSize = 12;
  let deleteTargetId = null;
  let deleteBatchMode = false;
  let tagEditTargetId = null;
  let filterText = '';
  let filterTag = '';
  let viewMode = 'list';
  let categoryKey = 'all';
  let selectedIds = new Set();
  let catalogSources = [];
  let currentPageSources = [];

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
    return {
      key,
      label: group.label,
      icon: group.icon,
      raw,
      rawLabel: raw ? raw.toUpperCase() : 'UNKNOWN',
    };
  }

  function formatDate(value) {
    try {
      return new Date(value).toLocaleDateString();
    } catch {
      return '—';
    }
  }

  function getSourceSearchText(source) {
    return [
      source.name,
      source.url,
      source.type,
      ...(Array.isArray(source.tags) ? source.tags : []),
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase();
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
    TYPE_ORDER.forEach(key => {
      counts[key] = 0;
    });
    sources.forEach(source => {
      counts[getTypeMeta(source.type).key] += 1;
    });
    return counts;
  }

  function getRawTypeSummary(sources) {
    const counter = new Map();
    sources.forEach(source => {
      const raw = getTypeMeta(source.type).rawLabel;
      counter.set(raw, (counter.get(raw) || 0) + 1);
    });
    return Array.from(counter.entries())
      .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0], 'zh-CN'))
      .slice(0, 3)
      .map(([raw, count]) => `${escapeHtml(raw)} ${count}`)
      .join(' · ');
  }

  function tableEmptyRow(title, detail) {
    return `
      <tr>
        <td colspan="6" style="padding:0;">
          <div class="kb-empty-state kb-empty-state--table">
            <div class="kb-empty-emoji">🗂️</div>
            <div class="kb-empty-title">${escapeHtml(title)}</div>
            <div class="kb-empty-copy">${escapeHtml(detail)}</div>
          </div>
        </td>
      </tr>
    `;
  }

  function blockEmptyState(title, detail) {
    return `
      <div class="kb-empty-state">
        <div class="kb-empty-emoji">🗂️</div>
        <div class="kb-empty-title">${escapeHtml(title)}</div>
        <div class="kb-empty-copy">${escapeHtml(detail)}</div>
      </div>
    `;
  }

  function renderCategoryStrip() {
    const strip = document.getElementById('kb-category-strip');
    const baseSources = getBaseFilteredSources();
    const counts = getCategoryCounts(baseSources);

    if (categoryKey !== 'all' && counts[categoryKey] === 0) {
      categoryKey = 'all';
    }

    const chips = [
      { key: 'all', icon: '🧠', label: '全部' },
      ...TYPE_ORDER
        .filter(key => counts[key] > 0)
        .map(key => ({ key, icon: TYPE_GROUPS[key].icon, label: TYPE_GROUPS[key].label })),
    ];

    strip.innerHTML = chips.map(chip => `
      <button class="kb-category-chip ${categoryKey === chip.key ? 'is-active' : ''}" data-category="${chip.key}" type="button">
        <span class="kb-category-icon">${chip.icon}</span>
        <span>${escapeHtml(chip.label)}</span>
        <span class="kb-category-count">${counts[chip.key] || 0}</span>
      </button>
    `).join('');

    strip.querySelectorAll('.kb-category-chip').forEach(button => {
      button.addEventListener('click', () => {
        categoryKey = button.dataset.category;
        page = 0;
        clearSelection();
        render();
      });
    });
  }

  function renderResultMeta() {
    const meta = document.getElementById('kb-result-meta');
    const baseCount = getBaseFilteredSources().length;
    const visibleCount = getVisibleSources().length;
    const categoryLabel = categoryKey === 'all' ? '全部分类' : TYPE_GROUPS[categoryKey].label;
    const viewLabel = viewMode === 'list' ? '列表模式' : viewMode === 'type' ? '按业务分类分组' : '按标签分组';
    const extra = filterTag ? ` · 标签：${escapeHtml(filterTag)}` : '';
    meta.innerHTML = `
      <strong>${visibleCount}</strong> / ${baseCount} 条来源
      <span>· ${escapeHtml(categoryLabel)}</span>
      <span>· ${escapeHtml(viewLabel)}${extra}</span>
    `;
  }

  function syncSelectAllCheckbox() {
    const checkbox = document.getElementById('chk-select-all');
    if (!checkbox) return;
    if (!currentPageSources.length) {
      checkbox.checked = false;
      checkbox.indeterminate = false;
      return;
    }
    const selectedCount = currentPageSources.filter(source => selectedIds.has(source.id)).length;
    checkbox.checked = selectedCount === currentPageSources.length;
    checkbox.indeterminate = selectedCount > 0 && selectedCount < currentPageSources.length;
  }

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
    syncSelectAllCheckbox();
  }

  function toggleSelect(id, checked) {
    if (checked) selectedIds.add(id);
    else selectedIds.delete(id);
    updateSelectionUI();
  }

  function clearSelection() {
    selectedIds.clear();
    document.querySelectorAll('.row-chk').forEach(checkbox => {
      checkbox.checked = false;
    });
    updateSelectionUI();
  }

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
      document.getElementById('kb-stat-tags').textContent = (data.tags || []).length;
    } catch {
      document.getElementById('kb-stat-tags').textContent = '—';
    }
  }

  async function loadStats() {
    try {
      const data = await apiJson('/kb/stats');
      document.getElementById('kb-stat-sources').textContent = data.total_sources;
      document.getElementById('kb-stat-chunks').textContent = data.total_chunks;
    } catch {
      document.getElementById('kb-stat-sources').textContent = '—';
      document.getElementById('kb-stat-chunks').textContent = '—';
    }
  }

  async function loadCatalog() {
    const data = await apiJson('/kb/sources?limit=500&offset=0');
    catalogSources = data.sources || [];
  }

  function sourceRowHtml(source) {
    const checked = selectedIds.has(source.id) ? 'checked' : '';
    const typeMeta = getTypeMeta(source.type);
    const tags = Array.isArray(source.tags) ? source.tags : [];
    const tagsHtml = tags.length
      ? `<div class="kb-tag-list">${tags.map(tag => `<span class="tag-pill" data-tag="${escapeHtml(tag)}">${escapeHtml(tag)}</span>`).join('')}</div>`
      : '<span class="kb-tag-empty">未标签</span>';

    return `
      <tr class="kb-row" data-id="${escapeHtml(source.id)}">
        <td class="kb-cell-select" style="padding-left:16px;">
          <input type="checkbox" class="row-chk" data-id="${escapeHtml(source.id)}" ${checked}
            style="accent-color:var(--accent);cursor:pointer;" />
        </td>
        <td class="kb-source-cell">
          <div class="kb-source-main">
            <button class="btn-view-chunks kb-source-link" data-id="${escapeHtml(source.id)}" data-name="${escapeHtml(source.name)}" type="button">${escapeHtml(source.name)}</button>
            <div class="kb-source-meta">${escapeHtml(source.url || '本地来源')}</div>
          </div>
          ${tagsHtml}
        </td>
        <td>
          <div class="kb-type-stack">
            <span class="kb-type-pill kb-type-${typeMeta.key}">${typeMeta.icon} ${escapeHtml(typeMeta.label)}</span>
            <span class="kb-type-raw">${escapeHtml(typeMeta.rawLabel)}</span>
          </div>
        </td>
        <td class="kb-date-cell">${escapeHtml(formatDate(source.created_at))}</td>
        <td>${statusBadge(source.status)}</td>
        <td class="kb-cell-actions">
          <div class="kb-row-actions">
            <button class="btn-edit-tags kb-row-action" data-id="${escapeHtml(source.id)}" data-name="${escapeHtml(source.name)}" data-tags="${escapeHtml(JSON.stringify(tags))}" type="button">改标签</button>
            <button class="btn-delete-source kb-row-action is-danger" data-id="${escapeHtml(source.id)}" type="button">删除</button>
          </div>
        </td>
      </tr>
    `;
  }

  function bindTableEvents(root) {
    root.querySelectorAll('.row-chk').forEach(checkbox => {
      checkbox.addEventListener('change', event => toggleSelect(checkbox.dataset.id, event.target.checked));
    });

    root.querySelectorAll('.btn-view-chunks').forEach(button => {
      button.addEventListener('click', () => openChunksDrawer(button.dataset.id, button.dataset.name));
    });

    root.querySelectorAll('.btn-delete-source').forEach(button => {
      button.addEventListener('click', () => openDeleteModal(button.dataset.id));
    });

    root.querySelectorAll('.btn-edit-tags').forEach(button => {
      button.addEventListener('click', () => openTagEdit(button.dataset.id, button.dataset.name, button.dataset.tags));
    });

    root.querySelectorAll('.tag-pill').forEach(pill => {
      pill.addEventListener('click', () => {
        document.getElementById('kb-tag-filter').value = pill.dataset.tag;
        filterTag = pill.dataset.tag;
        page = 0;
        clearSelection();
        render();
      });
    });
  }

  function renderListView() {
    const tbody = document.getElementById('kb-tbody');
    const visibleSources = getVisibleSources();

    if (!visibleSources.length) {
      currentPageSources = [];
      tbody.innerHTML = tableEmptyRow('当前筛选下没有来源', '换个标签、分类或关键词试试。');
      document.getElementById('kb-prev').disabled = true;
      document.getElementById('kb-next').disabled = true;
      document.getElementById('kb-page-info').textContent = '无结果';
      syncSelectAllCheckbox();
      return;
    }

    const totalPages = Math.max(1, Math.ceil(visibleSources.length / pageSize));
    if (page >= totalPages) page = totalPages - 1;
    currentPageSources = visibleSources.slice(page * pageSize, page * pageSize + pageSize);

    document.getElementById('kb-prev').disabled = page === 0;
    document.getElementById('kb-next').disabled = page >= totalPages - 1;
    document.getElementById('kb-page-info').textContent = `第 ${page + 1} / ${totalPages} 页 · 共 ${visibleSources.length} 条`;

    tbody.innerHTML = currentPageSources.map(sourceRowHtml).join('');
    bindTableEvents(tbody);
    syncSelectAllCheckbox();
  }

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
        kind: 'type',
        sources: grouped[key],
        summary: getRawTypeSummary(grouped[key]),
      }));
  }

  function buildTagGroups(sources) {
    const grouped = {};
    const untagged = [];

    sources.forEach(source => {
      const tags = Array.isArray(source.tags) ? source.tags : [];
      if (!tags.length) {
        untagged.push(source);
        return;
      }
      tags.forEach(tag => {
        if (!grouped[tag]) grouped[tag] = [];
        grouped[tag].push(source);
      });
    });

    const groups = Object.entries(grouped)
      .map(([label, entries]) => ({
        id: label,
        label,
        icon: '🏷️',
        kind: 'tag',
        sources: entries,
        summary: `包含 ${entries.length} 个来源`,
      }))
      .sort((left, right) => right.sources.length - left.sources.length || left.label.localeCompare(right.label, 'zh-CN'));

    if (untagged.length) {
      groups.push({
        id: 'untagged',
        label: '未标签',
        icon: '🏷️',
        kind: 'tag',
        sources: untagged,
        summary: `包含 ${untagged.length} 个来源`,
      });
    }

    return groups;
  }

  function groupSectionHtml(group, index) {
    const bodyId = `kb-group-body-${index}`;
    const chipClass = group.kind === 'type' ? `kb-type-pill kb-type-${group.id}` : 'kb-group-tag';

    return `
      <section class="kb-group-card" data-group-card="${escapeHtml(group.id)}">
        <div class="kb-group-head">
          <div class="kb-group-copy">
            <span class="${chipClass}">${group.icon} ${escapeHtml(group.label)}</span>
            <div class="kb-group-summary">${group.summary}</div>
          </div>
          <div class="kb-group-actions">
            <span class="kb-group-count">${group.sources.length} 项</span>
            <button class="btn-select-group btn btn-secondary btn-xs" data-ids="${group.sources.map(source => source.id).join(',')}" type="button">全选该组</button>
            <button class="btn-toggle-group kb-toggle-btn" data-target="${bodyId}" type="button" aria-label="折叠分组">▾</button>
          </div>
        </div>
        <div id="${bodyId}" class="kb-group-body">
          <div class="table-card kb-table-shell">
            <table class="table kb-table">
              <tbody class="group-tbody">
                ${group.sources.map(sourceRowHtml).join('')}
              </tbody>
            </table>
          </div>
        </div>
      </section>
    `;
  }

  function renderGroupView() {
    const container = document.getElementById('kb-group-view');
    const visibleSources = getVisibleSources();
    currentPageSources = [];

    if (!visibleSources.length) {
      container.innerHTML = blockEmptyState('当前分组没有内容', '换个分类、标签或关键词，看看别的来源。');
      return;
    }

    const groups = viewMode === 'type' ? buildTypeGroups(visibleSources) : buildTagGroups(visibleSources);
    container.innerHTML = groups.map(groupSectionHtml).join('');

    container.querySelectorAll('.group-tbody').forEach(tbody => bindTableEvents(tbody));

    container.querySelectorAll('.btn-select-group').forEach(button => {
      button.addEventListener('click', event => {
        event.stopPropagation();
        const ids = button.dataset.ids.split(',').filter(Boolean);
        ids.forEach(id => selectedIds.add(id));
        container.querySelectorAll('.row-chk').forEach(checkbox => {
          if (ids.includes(checkbox.dataset.id)) {
            checkbox.checked = true;
          }
        });
        updateSelectionUI();
      });
    });

    container.querySelectorAll('.btn-toggle-group').forEach(button => {
      button.addEventListener('click', () => {
        const body = document.getElementById(button.dataset.target);
        const card = button.closest('.kb-group-card');
        if (!body || !card) return;
        const collapsed = card.classList.toggle('is-collapsed');
        body.classList.toggle('hidden', collapsed);
      });
    });
  }

  function render() {
    renderCategoryStrip();
    renderResultMeta();

    const listView = document.getElementById('kb-list-view');
    const groupView = document.getElementById('kb-group-view');
    if (viewMode === 'list') {
      listView.classList.remove('hidden');
      groupView.classList.add('hidden');
      renderListView();
    } else {
      listView.classList.add('hidden');
      groupView.classList.remove('hidden');
      renderGroupView();
    }
  }

  async function refreshAll({ silent = false } = {}) {
    try {
      await Promise.all([loadStats(), loadTagFilter(), loadCatalog()]);
      render();
      if (!silent) toast('知识库列表已刷新', 'success');
    } catch (error) {
      document.getElementById('kb-tbody').innerHTML = tableEmptyRow('无法加载知识库列表', '请检查后端连接或数据文件。');
      document.getElementById('kb-group-view').innerHTML = blockEmptyState('无法加载知识库列表', '请检查后端连接或数据文件。');
      document.getElementById('kb-result-meta').textContent = `加载失败：${error.message}`;
    }
  }

  document.querySelectorAll('.view-btn').forEach(button => {
    button.addEventListener('click', () => {
      document.querySelectorAll('.view-btn').forEach(entry => entry.classList.remove('active'));
      button.classList.add('active');
      viewMode = button.id.replace('btn-view-', '');
      page = 0;
      clearSelection();
      render();
    });
  });

  document.getElementById('chk-select-all').addEventListener('change', event => {
    currentPageSources.forEach(source => {
      if (event.target.checked) selectedIds.add(source.id);
      else selectedIds.delete(source.id);
    });
    document.querySelectorAll('#kb-tbody .row-chk').forEach(checkbox => {
      checkbox.checked = event.target.checked;
    });
    updateSelectionUI();
  });

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

  async function openChunksDrawer(sourceId, sourceName) {
    const drawer = document.getElementById('chunks-drawer');
    const content = document.getElementById('drawer-content');
    document.getElementById('drawer-title').textContent = sourceName;
    content.innerHTML = '<p style="font-size:13px;color:var(--t4);">加载片段中…</p>';
    drawer.classList.remove('hidden');
    try {
      const data = await apiJson(`/kb/sources/${sourceId}/chunks?limit=50`);
      const chunks = data.chunks || [];
      if (!chunks.length) {
        content.innerHTML = '<p style="font-size:13px;color:var(--t4);">未找到片段</p>';
        return;
      }
      content.innerHTML = chunks.map(chunk => `
        <div class="stat-card p-3">
          <div class="flex items-center justify-between mb-1.5">
            <span style="font-size:11.5px;color:var(--t3);">片段 #${chunk.chunk_index}</span>
            <span style="font-size:11px;font-family:var(--font-mono);color:var(--t4);">${chunk.id.slice(0, 8)}</span>
          </div>
          <p style="font-size:12.5px;color:var(--t2);line-height:1.6;white-space:pre-wrap;">${escapeHtml(chunk.content.slice(0, 500))}${chunk.content.length > 500 ? '…' : ''}</p>
        </div>
      `).join('');
    } catch {
      content.innerHTML = '<p style="font-size:13px;color:var(--c-err);">加载片段失败</p>';
    }
  }

  function closeDrawer() {
    document.getElementById('chunks-drawer').classList.add('hidden');
  }

  document.getElementById('btn-close-drawer').addEventListener('click', closeDrawer);
  document.getElementById('drawer-backdrop').addEventListener('click', closeDrawer);

  function openTagEdit(id, name, tagsJson) {
    tagEditTargetId = id;
    document.getElementById('tag-edit-source-name').textContent = name;
    let tags = [];
    try {
      tags = JSON.parse(tagsJson);
    } catch {}
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
      await refreshAll({ silent: true });
    } catch {
      toast('更新标签失败', 'error');
    }
  });

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
      await refreshAll({ silent: true });
      if (window.OmniKBApp?.refreshStats) window.OmniKBApp.refreshStats();
      else if (typeof refreshStats === 'function') refreshStats();
    } catch {
      toast('删除失败', 'error');
    }
  });

  document.getElementById('btn-export').addEventListener('click', () => {
    document.getElementById('export-menu').classList.toggle('hidden');
  });

  document.addEventListener('click', event => {
    const wrap = document.getElementById('export-wrap');
    if (wrap && !wrap.contains(event.target)) {
      document.getElementById('export-menu').classList.add('hidden');
    }
  });

  ['json', 'csv', 'zip'].forEach(format => {
    document.getElementById(`export-${format}`).addEventListener('click', event => {
      event.preventDefault();
      const base = typeof getApiBase === 'function' ? getApiBase() : 'http://localhost:8000';
      window.open(`${base}/kb/export?fmt=${format}`, '_blank');
      document.getElementById('export-menu').classList.add('hidden');
    });
  });

  document.getElementById('kb-prev').addEventListener('click', () => {
    if (page === 0) return;
    page -= 1;
    renderListView();
  });

  document.getElementById('kb-next').addEventListener('click', () => {
    page += 1;
    renderListView();
  });

  document.getElementById('btn-kb-refresh').addEventListener('click', () => {
    clearSelection();
    refreshAll();
  });

  document.getElementById('kb-search').addEventListener('input', event => {
    filterText = event.target.value.trim().toLowerCase();
    page = 0;
    clearSelection();
    render();
  });

  document.getElementById('kb-tag-filter').addEventListener('change', event => {
    filterTag = event.target.value;
    page = 0;
    clearSelection();
    render();
  });

  document.addEventListener('tab:shown', event => {
    if (event.detail === 'kb') {
      refreshAll({ silent: true });
    }
  });

  refreshAll({ silent: true });
})();
