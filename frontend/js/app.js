/* ── Global app state & utilities ──────────────────────────── */

function getApiBase() {
  try {
    const s = JSON.parse(localStorage.getItem('omnikb_settings') || '{}');
    return s.api_base || '';
  } catch {
    return '';
  }
}
const API_BASE = getApiBase();

const TAB_META = {
  upload: {
    title: '上传与摄入',
    subtitle: '向知识库添加文件、网页和文本内容',
  },
  search: {
    title: '检索工作台',
    subtitle: '混合语义检索、重排序与结果复核都在这里完成',
  },
  chat: {
    title: 'Wiki 管理',
    subtitle: '用自然语言管理你的知识库 — 创建、更新、检索、分析 Wiki 页面',
  },
  kb: {
    title: '知识库管理',
    subtitle: '查看来源、标签、片段规模，并执行批量管理',
  },
  wiki: {
    title: 'Wiki 知识图谱',
    subtitle: 'LLM 持续维护的二级索引：实体 / 概念 / 来源页面 + 关系图',
  },
  scenarios: {
    title: '问答发布',
    subtitle: '配置公共场景、API 密钥和对外问答体验',
  },
  settings: {
    title: '运行设置',
    subtitle: '管理连接、代理、模型下载和对话默认配置',
  },
};

// ── Settings store ──────────────────────────────────────────
function loadSettings() {
  try {
    return JSON.parse(localStorage.getItem('omnikb_settings') || '{}');
  } catch {
    return {};
  }
}
function saveSettings(obj) {
  if (!obj || typeof obj !== 'object') return;
  const cur = loadSettings();
  localStorage.setItem('omnikb_settings', JSON.stringify({ ...cur, ...obj }));
}

// ── API helper ──────────────────────────────────────────────
async function api(path, options = {}) {
  let base = loadSettings().api_base || '';
  if (base.includes('localhost') || base.includes('127.0.0.1')) base = '';
  const url = base + path;
  try {
    const res = await fetch(url, {
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    });
    if (!res.ok) {
      if (res.status === 401 && !window.location.pathname.includes('login')) {
        window.location.href = '/login.html';
        throw new Error('请先登录');
      }
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || res.statusText);
    }
    return res;
  } catch (e) {
    if (e.message !== '请先登录') toast(e.message, 'error');
    throw e;
  }
}

async function apiJson(path, options = {}) {
  const res = await api(path, options);
  return res.json();
}

// ── Toast ────────────────────────────────────────────────────
function toast(msg, type = 'info') {
  const container = document.getElementById('toast-container');
  const el = document.createElement('div');
  el.className = 'toast ' + type;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => {
    el.style.opacity = '0';
    el.style.transform = 'translateY(-8px)';
    el.style.transition = 'all 200ms ease';
    setTimeout(() => el.remove(), 200);
  }, 4000);
}

function setTopbarState(name) {
  const meta = TAB_META[name] || { title: name, subtitle: '' };
  const title = document.getElementById('topbar-breadcrumb');
  const subtitle = document.getElementById('topbar-subtitle');
  const sidebarLabel = document.getElementById('sidebar-current-tab');

  if (title) title.textContent = meta.title;
  if (subtitle) subtitle.textContent = meta.subtitle;
  if (sidebarLabel) sidebarLabel.textContent = meta.title;
  document.title = `OmniKB · ${meta.title}`;
}

// ── Tab routing ──────────────────────────────────────────────
function showTab(name) {
  document.querySelectorAll('.tab-panel').forEach(panel => {
    panel.classList.add('hidden');
    panel.classList.remove('flex');
    panel.style.display = '';
  });
  document.querySelectorAll('.nav-btn').forEach(button => button.classList.remove('active'));

  const panel = document.getElementById(`tab-${name}`);
  if (panel) {
    panel.classList.remove('hidden');
    if (panel.classList.contains('tab-panel-flex')) {
      panel.style.display = 'flex';
    }
  }
  const btn = document.querySelector(`[data-tab="${name}"]`);
  if (btn) btn.classList.add('active');

  window.location.hash = name;
  setTopbarState(name);
  document.dispatchEvent(new CustomEvent('tab:shown', { detail: name }));
}

document.querySelectorAll('.nav-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    showTab(btn.dataset.tab);
    closeSidebarDrawer();   // tapping a nav item on mobile dismisses the drawer
  });
});

// ── Mobile drawer (sidebar) ───────────────────────────────────
// Only meaningful at <= 760px; on desktop the burger button is CSS-hidden
// and the sidebar is always visible. We still register the handlers
// universally — they're cheap and keep the resize-from-mobile-to-desktop
// case clean (closing the drawer just removes a class that has no effect
// at desktop widths).
const _burger = document.getElementById('topbar-burger');
const _drawer = document.getElementById('omni-sidebar');
const _backdrop = document.getElementById('sidebar-backdrop');

function openSidebarDrawer() {
  if (!_drawer || !_backdrop) return;
  _drawer.classList.add('is-open');
  _backdrop.hidden = false;
  // Force a reflow so the opacity transition actually plays.
  void _backdrop.offsetWidth;
  _backdrop.classList.add('is-visible');
  if (_burger) _burger.setAttribute('aria-expanded', 'true');
  document.body.style.overflow = 'hidden';
}

function closeSidebarDrawer() {
  if (!_drawer || !_backdrop) return;
  _drawer.classList.remove('is-open');
  _backdrop.classList.remove('is-visible');
  if (_burger) _burger.setAttribute('aria-expanded', 'false');
  document.body.style.overflow = '';
  // Hide backdrop after the fade-out transition finishes (180ms by default).
  // Falling back to a setTimeout instead of transitionend keeps things
  // simple and tolerates 'prefers-reduced-motion: reduce' (no event fires).
  setTimeout(() => { if (!_drawer.classList.contains('is-open')) _backdrop.hidden = true; }, 200);
}

if (_burger) _burger.addEventListener('click', () => {
  if (_drawer && _drawer.classList.contains('is-open')) closeSidebarDrawer();
  else openSidebarDrawer();
});
if (_backdrop) _backdrop.addEventListener('click', closeSidebarDrawer);
document.addEventListener('keydown', (ev) => {
  if (ev.key === 'Escape' && _drawer && _drawer.classList.contains('is-open')) {
    closeSidebarDrawer();
  }
});
// Resizing past the desktop breakpoint should release any open drawer state
// so the user doesn't end up with a 'drawer-open' body when going from
// portrait phone → landscape tablet.
window.addEventListener('resize', () => {
  if (window.innerWidth > 760 && _drawer && _drawer.classList.contains('is-open')) {
    closeSidebarDrawer();
  }
});

// Chat & Scenarios & Wiki panels use flex layout
document.getElementById('tab-chat').dataset.flex = '1';
document.getElementById('tab-scenarios').dataset.flex = '1';
const _wikiTab = document.getElementById('tab-wiki');
if (_wikiTab) _wikiTab.dataset.flex = '1';

// ── Collapsible sidebar toggle ──────────────────────────────
(function initSidebarCollapse() {
  const sidebar = document.getElementById('omni-sidebar');
  const btn = document.getElementById('sidebar-collapse-btn');
  if (!sidebar || !btn) return;

  // Restore persisted state
  if (localStorage.getItem('omnikb-sidebar-collapsed') === '1') {
    sidebar.classList.add('collapsed');
  }

  btn.addEventListener('click', () => {
    const isNowCollapsed = sidebar.classList.toggle('collapsed');
    localStorage.setItem('omnikb-sidebar-collapsed', isNowCollapsed ? '1' : '0');
    // Re-render Lucide icons after the chevron rotates
    if (window.lucide && typeof window.lucide.createIcons === 'function') {
      setTimeout(() => window.lucide.createIcons(), 50);
    }
  });
})();

// Route on load
const initialTab = window.location.hash.replace('#', '') || 'upload';
showTab(initialTab);

// ── Refresh sidebar stats ────────────────────────────────────
async function refreshStats() {
  try {
    const data = await apiJson('/kb/stats');
    document.getElementById('stat-sources').textContent = `${data.total_sources} 来源`;
    try {
      const wiki = await apiJson('/wiki/stats');
      document.getElementById('stat-chunks').textContent = `${wiki.total_pages || 0} Wiki 页`;
    } catch {
      document.getElementById('stat-chunks').textContent = '—';
    }
  } catch {}
}
refreshStats();

let backendStatusTimer = null;

async function refreshBackendStatus(forceToast = false) {
  const pill = document.getElementById('topbar-status-pill');
  const label = document.getElementById('topbar-status-label');
  const base = loadSettings().api_base || '';
  if (!pill || !label) return false;

  pill.classList.remove('is-online', 'is-offline', 'is-warning');
  pill.classList.add('is-warning');
  label.textContent = '检测中';

  try {
    const res = await fetch(`${base}/health`, { cache: 'no-store' });
    if (!res.ok) throw new Error(res.statusText || 'health check failed');
    const data = await res.json().catch(() => ({}));
    pill.classList.remove('is-warning');
    pill.classList.add('is-online');
    label.textContent = `在线 · ${data.version || 'unknown'}`;
    pill.dataset.tooltip = `后端在线：${base}`;
    return true;
  } catch (error) {
    pill.classList.remove('is-warning');
    pill.classList.add('is-offline');
    label.textContent = '连接失败';
    pill.dataset.tooltip = `无法连接后端：${base}`;
    if (forceToast) {
      toast(`后端连接失败：${error.message}`, 'error');
    }
    return false;
  }
}

function startBackendStatusPolling() {
  clearInterval(backendStatusTimer);
  refreshBackendStatus(false);
  backendStatusTimer = setInterval(() => refreshBackendStatus(false), 30000);
}
startBackendStatusPolling();

// ── Status badge helper ──────────────────────────────────────
function statusBadge(status) {
  const statusMap = { pending: '待处理', processing: '处理中', done: '已完成', error: '失败' };
  return `<span class="badge-${status} text-xs px-2 py-0.5 rounded-full font-medium">${statusMap[status] || status}</span>`;
}

/* ─── UI.1: v2 protocol detection + Lucide bootstrap ─────────── */
window.__omnikb_protocol_v2 = false;

async function detectOmnikbV2() {
  try {
    const base = loadSettings().api_base || '';
    const r = await fetch(base + '/agent/v2/events?probe=1', { method: 'HEAD' });
    window.__omnikb_protocol_v2 = r.ok;
  } catch {
    window.__omnikb_protocol_v2 = false;
  }
  console.debug('[OmniKB] v2 protocol available:', window.__omnikb_protocol_v2);
}

function bootstrapLucide() {
  if (window.lucide && typeof window.lucide.createIcons === 'function') {
    window.lucide.createIcons();
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    detectOmnikbV2();
    bootstrapLucide();
  });
} else {
  detectOmnikbV2();
  bootstrapLucide();
}

window.OmniKBApp = {
  refreshBackendStatus,
  refreshStats,
  showTab,
  loadSettings,
  saveSettings,
};
