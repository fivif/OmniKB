/**
 * agent-console.js
 * 底部固定玻璃态 Agent 活动控制台。
 * 连接 GET /agent/events (SSE)，消息从底部向上浮现。
 */
(function () {
  'use strict';

  /* ─── 常量 ─────────────────────────────────────────────── */
  const MAX_MESSAGES    = 80;    // 保留最近 N 条
  const MSG_TTL_MS      = 28000; // 单条消息存活时间（ms）
  const PANEL_H_OPEN    = 220;   // 展开高度 (px)
  const PANEL_H_MIN     = 36;    // 收起高度 (px)
  const RECONNECT_BASE  = 1500;  // SSE 断线重连基础延迟 (ms)
  const RECONNECT_MAX   = 30000; // 最大重连延迟
  const SSE_URL         = '/agent/events';

  /* ─── 颜色映射 ──────────────────────────────────────────── */
  const KIND_STYLE = {
    info:     { bg: 'rgba(100,116,139,.18)', dot: '#94a3b8', txt: '#cbd5e1' },
    progress: { bg: 'rgba(99,102,241,.18)', dot: '#818cf8', txt: '#c7d2fe' },
    success:  { bg: 'rgba(34,197,94,.14)',  dot: '#4ade80', txt: '#bbf7d0' },
    warning:  { bg: 'rgba(234,179,8,.14)',  dot: '#facc15', txt: '#fef08a' },
    error:    { bg: 'rgba(239,68,68,.16)',  dot: '#f87171', txt: '#fecaca' },
  };

  const AGENT_ICON = {
    agent_browser: '🌐', jshook: '🪝',  scrapling: '🕷️',
    llm:           '🧠', embedder: '🔢', orchestrator: '🔄',
    doc_agent:     '📄', media_agent: '🎞️', vision_agent: '👁️',
    ingest:        '📥', system: '⚙️',
  };

  /* ─── 注入样式 ───────────────────────────────────────────── */
  const CSS = `
#agent-console {
  position: fixed;
  bottom: 0;
  right: 0;
  z-index: 1000;
  display: flex;
  flex-direction: column;
  background: rgba(8,12,24,.84);
  backdrop-filter: blur(22px) saturate(160%);
  -webkit-backdrop-filter: blur(22px) saturate(160%);
  border-top: 1px solid rgba(99,102,241,.28);
  border-left: 1px solid rgba(99,102,241,.15);
  border-radius: 12px 0 0 0;
  transition: height .3s cubic-bezier(.4,0,.2,1),
              left   .3s cubic-bezier(.4,0,.2,1);
  box-shadow: 0 -4px 40px rgba(0,0,0,.55), inset 0 1px 0 rgba(255,255,255,.04);
  overflow: hidden;
  font-family: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
  font-size: 12px;
  color: #cbd5e1;
}
/* sidebar offsets */
@media (min-width: 640px)  { #agent-console { left: 64px; } }
@media (min-width: 1024px) { #agent-console { left: 224px; } }

/* ── title bar ── */
#agc-bar {
  flex-shrink: 0;
  height: 36px;
  display: flex;
  align-items: center;
  padding: 0 12px;
  cursor: pointer;
  gap: 8px;
  user-select: none;
  background: rgba(15,20,40,.5);
  border-bottom: 1px solid rgba(99,102,241,.18);
}
#agc-bar:hover { background: rgba(99,102,241,.1); }
#agc-pulse {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: #4ade80;
  box-shadow: 0 0 6px #4ade80;
  flex-shrink: 0;
  transition: background .3s, box-shadow .3s;
}
#agc-pulse.error   { background: #f87171; box-shadow: 0 0 6px #f87171; }
#agc-pulse.idle    { background: #64748b; box-shadow: none; }
#agc-pulse.live    { animation: agc-blink 1.4s ease-in-out infinite; }
@keyframes agc-blink {
  0%,100% { opacity: 1; } 50% { opacity: .35; }
}
#agc-title { flex: 1; font-size: 11px; color: #64748b; letter-spacing: .04em; }
#agc-count {
  font-size: 10px;
  color: #4f5d73;
  min-width: 20px;
  text-align: right;
}
#agc-toggle {
  font-size: 14px;
  color: #4f5d73;
  line-height: 1;
  padding: 0 2px;
  transition: transform .25s;
}

/* ── message viewport ── */
#agc-body {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 6px 0 4px;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  scrollbar-width: thin;
  scrollbar-color: rgba(99,102,241,.3) transparent;
}
#agc-body::-webkit-scrollbar { width: 4px; }
#agc-body::-webkit-scrollbar-track { background: transparent; }
#agc-body::-webkit-scrollbar-thumb { background: rgba(99,102,241,.3); border-radius: 2px; }

/* ── single message ── */
.agc-msg {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  padding: 3px 12px;
  margin: 1px 6px;
  border-radius: 6px;
  line-height: 1.5;
  animation: agc-rise .38s cubic-bezier(.34,1.56,.64,1) both;
  transition: opacity .6s, transform .6s;
}
.agc-msg.expiring {
  opacity: 0;
  transform: translateY(-6px);
}
@keyframes agc-rise {
  from { opacity: 0; transform: translateY(14px) scale(.97); }
  to   { opacity: 1; transform: translateY(0)   scale(1);    }
}
.agc-icon { flex-shrink: 0; font-size: 13px; margin-top: 1px; }
.agc-body-inner { flex: 1; min-width: 0; }
.agc-meta {
  display: flex; gap: 6px; align-items: baseline;
  font-size: 10px; opacity: .55; margin-bottom: 1px;
}
.agc-label { font-weight: 600; }
.agc-time  {}
.agc-text  {
  word-break: break-all;
  white-space: pre-wrap;
}
`;

  const style = document.createElement('style');
  style.textContent = CSS;
  document.head.appendChild(style);

  /* ─── DOM ────────────────────────────────────────────────── */
  const panel = document.createElement('div');
  panel.id = 'agent-console';
  panel.style.height = PANEL_H_OPEN + 'px';

  panel.innerHTML = `
    <div id="agc-bar">
      <span id="agc-pulse" class="idle"></span>
      <span id="agc-title">AGENT ACTIVITY</span>
      <span id="agc-count">0</span>
      <span id="agc-toggle">▾</span>
    </div>
    <div id="agc-body"></div>
  `;
  document.body.appendChild(panel);

  const $bar    = document.getElementById('agc-bar');
  const $pulse  = document.getElementById('agc-pulse');
  const $title  = document.getElementById('agc-title');
  const $count  = document.getElementById('agc-count');
  const $toggle = document.getElementById('agc-toggle');
  const $body   = document.getElementById('agc-body');

  /* ─── 折叠/展开 ──────────────────────────────────────────── */
  let _open = true;
  $bar.addEventListener('click', () => {
    _open = !_open;
    panel.style.height = (_open ? PANEL_H_OPEN : PANEL_H_MIN) + 'px';
    $toggle.style.transform = _open ? '' : 'rotate(-90deg)';
  });

  /* ─── 消息队列 ───────────────────────────────────────────── */
  const _msgs = [];   // { el, timer }
  let _total = 0;

  function _fmt_time(ts) {
    const d = new Date(ts);
    return d.toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }

  function _push(evt) {
    const ks  = KIND_STYLE[evt.kind] || KIND_STYLE.info;
    const icon = evt.icon || AGENT_ICON[evt.agent] || '⚙️';
    const label = evt.label || evt.agent || 'system';

    const el = document.createElement('div');
    el.className = 'agc-msg';
    el.style.background = ks.bg;
    el.innerHTML = `
      <span class="agc-icon">${icon}</span>
      <div class="agc-body-inner">
        <div class="agc-meta">
          <span class="agc-label" style="color:${ks.dot}">${_esc(label)}</span>
          <span class="agc-time">${_fmt_time(evt.t || Date.now())}</span>
        </div>
        <div class="agc-text" style="color:${ks.txt}">${_esc(evt.msg || '')}</div>
      </div>`;

    $body.appendChild(el);

    const timer = setTimeout(() => _expire(entry), MSG_TTL_MS);
    const entry = { el, timer };
    _msgs.push(entry);
    _total++;
    $count.textContent = _total;

    // 超出上限时移除最旧的
    while (_msgs.length > MAX_MESSAGES) {
      const old = _msgs.shift();
      clearTimeout(old.timer);
      old.el.remove();
    }

    // 自动滚底（只在已经接近底部时）
    const atBottom = $body.scrollHeight - $body.scrollTop - $body.clientHeight < 60;
    if (atBottom) $body.scrollTop = $body.scrollHeight;
  }

  function _expire(entry) {
    const idx = _msgs.indexOf(entry);
    if (idx !== -1) _msgs.splice(idx, 1);
    entry.el.classList.add('expiring');
    setTimeout(() => entry.el.remove(), 650);
  }

  function _esc(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /* ─── SSE 连接 ───────────────────────────────────────────── */
  let _es = null;
  let _reconnectDelay = RECONNECT_BASE;
  let _reconnectTimer = null;

  function _setStatus(status) {
    $pulse.className = '';
    if (status === 'live') {
      $pulse.classList.add('live');
      $title.textContent = 'AGENT ACTIVITY  •  LIVE';
    } else if (status === 'error') {
      $pulse.classList.add('error');
      $title.textContent = 'AGENT ACTIVITY  •  重连中…';
    } else {
      $pulse.classList.add('idle');
      $title.textContent = 'AGENT ACTIVITY';
    }
  }

  function _connect() {
    if (_es) { _es.close(); _es = null; }
    _setStatus('idle');

    _es = new EventSource(SSE_URL);

    _es.addEventListener('open', () => {
      _setStatus('live');
      _reconnectDelay = RECONNECT_BASE;
      _push({ t: Date.now(), msg: '已连接 Agent 活动流', kind: 'info', agent: 'system', icon: '⚙️', label: 'system' });
    });

    _es.addEventListener('message', (e) => {
      let evt;
      try { evt = JSON.parse(e.data); } catch { return; }
      if (evt.ping) return;  // heartbeat
      _push(evt);
    });

    _es.addEventListener('error', () => {
      _es.close();
      _es = null;
      _setStatus('error');
      _push({ t: Date.now(), msg: `连接断开，${Math.round(_reconnectDelay/1000)}s 后重连`, kind: 'warning', agent: 'system', icon: '⚙️', label: 'system' });
      _reconnectTimer = setTimeout(() => {
        _reconnectDelay = Math.min(_reconnectDelay * 2, RECONNECT_MAX);
        _connect();
      }, _reconnectDelay);
    });
  }

  // 页面完全加载后启动
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _connect);
  } else {
    _connect();
  }

  // 页面卸载时关闭 SSE
  window.addEventListener('beforeunload', () => {
    clearTimeout(_reconnectTimer);
    if (_es) _es.close();
  });

  /* ─── 暴露给其他脚本（可选） ─────────────────────────────── */
  window.agentConsole = {
    emit : _push,
    clear: () => { _msgs.forEach(m => { clearTimeout(m.timer); m.el.remove(); }); _msgs.length = 0; },
  };
})();
