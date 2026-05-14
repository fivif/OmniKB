/* ── Search Panel ───────────────────────────────────────────── */

(function initSearch() {
  const panel = document.getElementById('tab-search');
  let currentMode = 'hybrid';
  let sourceOptionsLoaded = false;

  panel.innerHTML = `
    <div class="panel-shell search-shell">
      <section class="section-card">
        <div class="section-card-body stack-md">
          <div class="section-head">
            <div>
              <div class="section-title">检索控制台</div>
              <div class="section-subtitle">真正可用的筛选项都在这里，之前那些摆着好看但不接后端的控件已经拿掉了。</div>
            </div>
          </div>

          <div class="search-query-row">
            <div class="input-group search-query-input-wrap">
              <span class="input-prefix search-query-prefix">
                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.7" d="M21 21l-4.35-4.35M16 10.5a5.5 5.5 0 11-11 0 5.5 5.5 0 0111 0z" />
                </svg>
              </span>
              <input id="search-input" class="input input-lg search-query-input" type="search" placeholder="输入问题、关键词、日期或某个具体概念…" />
            </div>
            <button id="btn-search" class="btn btn-primary search-submit" type="button">开始检索</button>
          </div>

          <div class="search-mode-row">
            <button class="search-mode-btn active" data-mode="hybrid" type="button">Hybrid</button>
            <button class="search-mode-btn" data-mode="semantic" type="button">Semantic</button>
            <button class="search-mode-btn" data-mode="bm25" type="button">BM25</button>
          </div>

          <div class="field-grid">
            <div class="stack-sm">
              <label class="form-label">来源过滤</label>
              <select id="search-filter-source" class="select">
                <option value="">全部来源</option>
              </select>
            </div>
            <div class="stack-sm">
              <label class="form-label">类型过滤</label>
              <select id="search-filter-type" class="select">
                <option value="">全部类型</option>
              </select>
            </div>
            <div class="stack-sm">
              <label class="form-label">Top-K</label>
              <input id="search-topk" class="input" type="number" min="1" max="30" value="8" />
            </div>
            <div class="stack-sm">
              <label class="form-label">最低分阈值</label>
              <input id="search-threshold" class="input" type="number" min="0" max="1" step="0.05" value="0" />
            </div>
          </div>

          <div class="toolbar-row">
            <div class="chip-row">
              <button class="search-preset" type="button" data-query="产品线里都有哪些模型？">模型系列</button>
              <button class="search-preset" type="button" data-query="API 的 Base URL 和认证方式是什么？">接口配置</button>
              <button class="search-preset" type="button" data-query="发布时间线">时间线</button>
            </div>
            <label class="search-toggle">
              <input type="checkbox" id="search-rerank" class="input-check" />
              <span>启用重排序</span>
            </label>
          </div>
        </div>
      </section>

      <section class="section-card">
        <div class="section-card-body stack-md">
          <div class="section-head search-results-head">
            <div>
              <div class="section-title">检索结果</div>
              <div id="search-result-meta" class="section-subtitle">输入查询后会在这里呈现结果、相关度与来源信息。</div>
            </div>
          </div>
          <div id="search-results" class="search-results-grid">
            <div class="search-empty-state">还没有查询。先输入一个问题，或者点上面的预设检索。</div>
          </div>
        </div>
      </section>
    </div>
  `;

  const resultsEl = document.getElementById('search-results');
  const resultMetaEl = document.getElementById('search-result-meta');
  const sourceSelect = document.getElementById('search-filter-source');
  const typeSelect = document.getElementById('search-filter-type');

  function escapeHtml(value) {
    return String(value || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function setMode(mode) {
    currentMode = mode;
    panel.querySelectorAll('.search-mode-btn').forEach(button => {
      button.classList.toggle('active', button.dataset.mode === mode);
    });
  }

  panel.querySelectorAll('.search-mode-btn').forEach(button => {
    button.addEventListener('click', () => setMode(button.dataset.mode));
  });

  panel.querySelectorAll('.search-preset').forEach(button => {
    button.addEventListener('click', () => {
      document.getElementById('search-input').value = button.dataset.query || '';
      doSearch();
    });
  });

  async function loadFilters() {
    if (sourceOptionsLoaded) return;
    try {
      const data = await apiJson('/kb/sources?limit=200');
      const types = new Set();
      (data.sources || []).forEach(source => {
        const option = document.createElement('option');
        option.value = source.id;
        option.textContent = source.name.length > 42 ? `${source.name.slice(0, 40)}…` : source.name;
        sourceSelect.appendChild(option);
        if (source.type) types.add(source.type);
      });
      Array.from(types).sort().forEach(type => {
        const option = document.createElement('option');
        option.value = type;
        option.textContent = type.toUpperCase();
        typeSelect.appendChild(option);
      });
      sourceOptionsLoaded = true;
    } catch {}
  }

  function renderLoading() {
    resultsEl.innerHTML = Array.from({ length: 3 }, () => `
      <div class="search-result-card search-result-card--loading">
        <div class="skeleton" style="height:14px;width:26%;"></div>
        <div class="skeleton" style="height:12px;width:100%;margin-top:14px;"></div>
        <div class="skeleton" style="height:12px;width:88%;margin-top:10px;"></div>
        <div class="skeleton" style="height:12px;width:72%;margin-top:10px;"></div>
      </div>
    `).join('');
  }

  function renderEmpty(message) {
    resultsEl.innerHTML = `<div class="search-empty-state">${escapeHtml(message)}</div>`;
  }

  function renderResults(results, query, mode) {
    if (!results.length) {
      renderEmpty('没有命中结果。试试换个问法、放宽过滤条件，或者切到不同检索模式。');
      resultMetaEl.textContent = `查询“${query}”没有返回结果。`;
      return;
    }

    resultMetaEl.textContent = `查询“${query}”共返回 ${results.length} 条结果，当前模式：${mode}。`;
    resultsEl.innerHTML = results.map((result, index) => {
      const source = escapeHtml(result.metadata.source_name || result.metadata.source_url || result.metadata.source_id || '未知来源');
      const type = escapeHtml(result.metadata.source_type || result.metadata.file_type || 'unknown');
      const scoreBase = typeof result.rerank_score === 'number' ? result.rerank_score : result.score;
      const score = Math.max(0, Math.min(100, Number(scoreBase || 0) * 100)).toFixed(1);
      const snippet = result.highlight || escapeHtml(String(result.content || '').slice(0, 420));
      const tags = Array.isArray(result.metadata.tags) ? result.metadata.tags : [];
      const tagsHtml = tags.length
        ? `<div class="search-result-tags">${tags.map(tag => `<span class="tag-pill">${escapeHtml(tag)}</span>`).join('')}</div>`
        : '';

      return `
        <article class="search-result-card">
          <div class="search-result-head">
            <div class="search-result-rank">#${index + 1}</div>
            <div class="search-result-title-block">
              <div class="search-result-source">${source}</div>
              <div class="search-result-meta-line">${type.toUpperCase()}</div>
            </div>
            <div class="search-result-score">${score}%</div>
          </div>
          <div class="search-result-snippet">${snippet}</div>
          ${tagsHtml}
        </article>
      `;
    }).join('');
  }

  async function doSearch() {
    const query = document.getElementById('search-input').value.trim();
    if (!query) {
      toast('请输入查询内容', 'error');
      return;
    }

    renderLoading();
    const topK = Math.max(1, parseInt(document.getElementById('search-topk').value, 10) || 8);
    const minScore = Math.max(0, parseFloat(document.getElementById('search-threshold').value) || 0);
    const filterSource = sourceSelect.value;
    const filterType = typeSelect.value;
    const rerank = document.getElementById('search-rerank').checked;

    try {
      let path = `/search?q=${encodeURIComponent(query)}&top_k=${topK}&mode=${currentMode}&rerank=${rerank}`;
      if (filterSource) path += `&filter_source=${encodeURIComponent(filterSource)}`;
      if (filterType) path += `&filter_type=${encodeURIComponent(filterType)}`;
      const data = await apiJson(path);
      const results = (data.results || []).filter(item => Number(item.score || 0) >= minScore);
      renderResults(results, query, data.mode || currentMode);
    } catch {
      renderEmpty('搜索请求失败。请检查后端状态、索引或当前过滤条件。');
    }
  }

  document.getElementById('btn-search').addEventListener('click', doSearch);
  document.getElementById('search-input').addEventListener('keydown', event => {
    if (event.key === 'Enter') doSearch();
  });

  document.addEventListener('tab:shown', event => {
    if (event.detail === 'search') loadFilters();
  });

  loadFilters();
})();
