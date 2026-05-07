/* ── Global app state & utilities ──────────────────────────── */

const API_BASE = (() => {
  const s = localStorage.getItem('omnikb_settings');
  if (s) {
    try { return JSON.parse(s).api_base || 'http://localhost:8000'; } catch {}
  }
  return 'http://localhost:8000';
})();

// ── Settings store ──────────────────────────────────────────
function loadSettings() {
  try { return JSON.parse(localStorage.getItem('omnikb_settings') || '{}'); } catch { return {}; }
}
function saveSettings(obj) {
  const cur = loadSettings();
  localStorage.setItem('omnikb_settings', JSON.stringify({ ...cur, ...obj }));
}

// ── API helper ──────────────────────────────────────────────
async function api(path, options = {}) {
  const base = loadSettings().api_base || 'http://localhost:8000';
  const url = base + path;
  try {
    const res = await fetch(url, {
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || res.statusText);
    }
    return res;
  } catch (e) {
    toast(e.message, 'error');
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
  const colors = { info: 'bg-slate-700', error: 'bg-red-900/80', success: 'bg-green-900/80' };
  el.className = `pointer-events-auto px-4 py-3 rounded-lg text-sm shadow-xl ${colors[type] || colors.info} text-white max-w-xs`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

// ── Tab routing ──────────────────────────────────────────────
function showTab(name) {
  document.querySelectorAll('.tab-panel').forEach(p => {
    p.classList.add('hidden');
    p.classList.remove('flex');
  });
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));

  const panel = document.getElementById(`tab-${name}`);
  if (panel) {
    panel.classList.remove('hidden');
    if (panel.dataset.flex) panel.classList.add('flex');
  }
  const btn = document.querySelector(`[data-tab="${name}"]`);
  if (btn) btn.classList.add('active');

  window.location.hash = name;
  document.dispatchEvent(new CustomEvent('tab:shown', { detail: name }));
}

document.querySelectorAll('.nav-btn').forEach(btn => {
  btn.addEventListener('click', () => showTab(btn.dataset.tab));
});

// Chat panel uses flex layout
document.getElementById('tab-chat').dataset.flex = '1';

// Route on load
const initialTab = window.location.hash.replace('#', '') || 'upload';
showTab(initialTab);

// ── Refresh sidebar stats ────────────────────────────────────
async function refreshStats() {
  try {
    const data = await apiJson('/kb/stats');
    document.getElementById('stat-sources').textContent = `${data.total_sources} 来源`;
    document.getElementById('stat-chunks').textContent = `${data.total_chunks} 片段`;
  } catch {}
}
refreshStats();

// ── Status badge helper ──────────────────────────────────────
function statusBadge(status) {
  const statusMap = { pending: '待处理', processing: '处理中', done: '已完成', error: '失败' };
  return `<span class="badge-${status} text-xs px-2 py-0.5 rounded-full font-medium">${statusMap[status] || status}</span>`;
}
