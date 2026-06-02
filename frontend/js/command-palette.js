/* OmniKB Command Palette — Raycast-style global ⌘K */
(function () {
  'use strict';

  const TAB_LABELS = {
    upload: '上传', search: '搜索', chat: '对话',
    kb: '知识库', scenarios: '问答管理', settings: '设置'
  };

  function el(tag, attrs, ...children) {
    const e = document.createElement(tag);
    if (attrs) {
      for (const k in attrs) {
        if (k === 'className') e.className = attrs[k];
        else if (k === 'innerHTML') e.innerHTML = attrs[k];
        else if (k.startsWith('on')) e.addEventListener(k.slice(2).toLowerCase(), attrs[k]);
        else if (attrs[k] !== null && attrs[k] !== undefined) e.setAttribute(k, attrs[k]);
      }
    }
    for (const c of children) {
      if (c == null) continue;
      e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    }
    return e;
  }

  const state = {
    open: false,
    query: '',
    items: [],
    selected: 0,
    debounceT: null,
    extraCommands: [],
  };

  let backdrop = null, input = null, results = null, footer = null;

  function buildDom() {
    backdrop = el('div', { className: 'cmd-backdrop' });
    const palette = el('div', { className: 'cmd-palette' });

    const inputWrap = el('div', { className: 'cmd-input-wrapper' });
    inputWrap.innerHTML = '<i data-lucide="search" class="cmd-input-icon"></i>';
    input = el('input', {
      className: 'cmd-input',
      placeholder: '搜索来源、切换页面、运行命令…',
      autocomplete: 'off',
      spellcheck: 'false',
    });
    inputWrap.appendChild(input);
    palette.appendChild(inputWrap);

    results = el('div', { className: 'cmd-results' });
    palette.appendChild(results);

    footer = el('div', { className: 'cmd-footer' });
    footer.innerHTML =
      '<span><kbd>↑</kbd><kbd>↓</kbd> 导航</span>' +
      '<span><kbd>Enter</kbd> 执行</span>' +
      '<span><kbd>Esc</kbd> 关闭</span>';
    palette.appendChild(footer);

    backdrop.appendChild(palette);

    backdrop.addEventListener('click', (e) => {
      if (e.target === backdrop) close();
    });

    input.addEventListener('input', (e) => {
      state.query = e.target.value;
      clearTimeout(state.debounceT);
      state.debounceT = setTimeout(refresh, 200);
    });

    input.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { e.preventDefault(); close(); }
      else if (e.key === 'ArrowDown') { e.preventDefault(); moveSel(1); }
      else if (e.key === 'ArrowUp')   { e.preventDefault(); moveSel(-1); }
      else if (e.key === 'Enter')     { e.preventDefault(); runSelected(); }
    });
  }

  function moveSel(delta) {
    if (!state.items.length) return;
    state.selected = (state.selected + delta + state.items.length) % state.items.length;
    renderItems();
    const sel = results.querySelector('.cmd-item.selected');
    if (sel) sel.scrollIntoView({ block: 'nearest' });
  }

  function runSelected() {
    const it = state.items[state.selected];
    if (it && typeof it.run === 'function') {
      try { it.run(); } catch (e) { console.error(e); }
      close();
    }
  }

  function getBuiltins() {
    const nav = Object.keys(TAB_LABELS).map((tab) => ({
      group: '导航',
      label: '前往 ' + TAB_LABELS[tab],
      icon: 'corner-down-right',
      run: () => {
        const btn = document.querySelector('.nav-btn[data-tab="' + tab + '"]');
        if (btn) btn.click();
      },
    }));

    const actions = [
      {
        group: '快捷操作',
        label: '快速摄入 URL…',
        icon: 'link',
        run: () => {
          const btn = document.querySelector('.nav-btn[data-tab="upload"]');
          if (btn) btn.click();
        },
      },
      {
        group: '快捷操作',
        label: '新建对话',
        icon: 'plus',
        run: () => {
          const btn = document.querySelector('.nav-btn[data-tab="chat"]');
          if (btn) btn.click();
        },
      },
      {
        group: '快捷操作',
        label: '刷新 KB 统计',
        icon: 'refresh-cw',
        run: () => { if (window.refreshKbStats) window.refreshKbStats(); },
      },
    ];

    const theme = [
      { group: '主题', label: '切换浅色模式', icon: 'sun',     run: () => window.OmniTheme && window.OmniTheme.set('light') },
      { group: '主题', label: '切换深色模式', icon: 'moon',    run: () => window.OmniTheme && window.OmniTheme.set('dark') },
      { group: '主题', label: '跟随系统',     icon: 'monitor', run: () => window.OmniTheme && window.OmniTheme.set('system') },
    ];

    return [...nav, ...actions, ...theme, ...state.extraCommands];
  }

  function fuzzy(q, s) {
    if (!q) return 1;
    q = q.toLowerCase(); s = s.toLowerCase();
    if (s.includes(q)) return 2;
    let qi = 0;
    for (let i = 0; i < s.length && qi < q.length; i++) {
      if (s[i] === q[qi]) qi++;
    }
    return qi === q.length ? 1 : 0;
  }

  async function searchSources(q) {
    if (!q || q.length < 3) return [];
    try {
      const r = await fetch(getApiBase() + '/search?q=' + encodeURIComponent(q) + '&top_k=5');
      if (!r.ok) return [];
      const data = await r.json();
      const hits = (data.results || data.hits || []).slice(0, 5);
      return hits.map((h) => ({
        group: '检索结果',
        label: ((h.content || h.text || '') + '').slice(0, 60) + '…',
        icon: 'file-text',
        hint: h.source_url || h.source || '',
        run: () => {
          const btn = document.querySelector('.nav-btn[data-tab="search"]');
          if (btn) btn.click();
          setTimeout(() => {
            const si = document.querySelector('.search-input');
            if (si) {
              si.value = q;
              si.dispatchEvent(new Event('input'));
              si.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
            }
          }, 50);
        },
      }));
    } catch (e) {
      return [];
    }
  }

  async function refresh() {
    const q = state.query.trim();
    const builtins = getBuiltins().filter((it) => fuzzy(q, it.label));
    let items = builtins;
    if (q.length >= 3) {
      const hits = await searchSources(q);
      items = builtins.concat(hits);
    }
    state.items = items;
    if (state.selected >= state.items.length) state.selected = 0;
    renderItems();
  }

  function renderItems() {
    results.innerHTML = '';
    if (!state.items.length) {
      results.appendChild(el('div', { className: 'cmd-empty' }, '没有匹配项'));
      return;
    }
    let lastGroup = null;
    state.items.forEach((it, idx) => {
      if (it.group !== lastGroup) {
        const g = el('div', { className: 'cmd-group-title' }, it.group);
        results.appendChild(g);
        lastGroup = it.group;
      }
      const row = el('div', { className: 'cmd-item' + (idx === state.selected ? ' selected' : '') });
      row.innerHTML =
        '<i data-lucide="' + (it.icon || 'chevron-right') + '" class="cmd-item-icon"></i>' +
        '<span class="cmd-item-label"></span>' +
        (it.hint ? '<span class="cmd-item-hint"></span>' : '');
      row.querySelector('.cmd-item-label').textContent = it.label;
      if (it.hint) row.querySelector('.cmd-item-hint').textContent = it.hint;
      row.addEventListener('mouseenter', () => { state.selected = idx; renderItems(); });
      row.addEventListener('click', () => { state.selected = idx; runSelected(); });
      results.appendChild(row);
    });
    if (window.lucide) window.lucide.createIcons();
  }

  function open() {
    if (state.open) return;
    if (!backdrop) buildDom();
    document.body.appendChild(backdrop);
    state.open = true;
    state.query = '';
    state.selected = 0;
    input.value = '';
    refresh();
    setTimeout(() => input.focus(), 60);
    if (window.lucide) window.lucide.createIcons();
  }

  function close() {
    if (!state.open || !backdrop) return;
    backdrop.classList.add('closing');
    setTimeout(() => {
      if (backdrop.parentNode) backdrop.parentNode.removeChild(backdrop);
      backdrop.classList.remove('closing');
      state.open = false;
    }, 180);
  }

  function register(cmd) {
    if (!cmd || !cmd.label || typeof cmd.run !== 'function') return;
    if (!cmd.group) cmd.group = '扩展';
    state.extraCommands.push(cmd);
  }

  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
      e.preventDefault();
      state.open ? close() : open();
    }
  });

  window.OmniCommand = { open, close, register };
})();
