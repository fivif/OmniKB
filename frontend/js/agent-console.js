/**
 * agent-console.js — v2
 * Bottom glassmorphism Agent Activity console.
 * Primary: GET /agent/v2/events (typed events with full content).
 * Fallback: GET /agent/events (v1 flat events).
 *
 * Shows the full agent interaction flow: LLM responses, tool calls,
 * tool results, turn transitions, and lifecycle events.
 */
(function () {
  'use strict';

  /* ─── Constants ───────────────────────────────────────────── */
  const MAX_MESSAGES    = 120;
  const MSG_TTL_MS      = 0;       // 0 = keep until max count (v2 messages are valuable)
  const PANEL_H_OPEN    = 320;
  const PANEL_H_MIN     = 36;
  const PANEL_SAFE_GAP  = 12;
  const RECONNECT_BASE  = 1500;
  const RECONNECT_MAX   = 30000;
  const LLM_PREVIEW_LEN = 500;     // chars of LLM content to show before truncation
  const TOOL_PREVIEW_LEN = 300;    // chars of tool result to show

  /* ─── Colour map ──────────────────────────────────────────── */
  const KIND_STYLE = {
    info:     { bg: 'var(--agc-info-bg)', dot: 'var(--agc-muted)', txt: 'var(--agc-text)' },
    progress: { bg: 'var(--agc-progress-bg)', dot: 'var(--accent)', txt: 'var(--agc-text)' },
    success:  { bg: 'var(--agc-success-bg)', dot: 'var(--c-ok-t)', txt: 'var(--agc-text)' },
    warning:  { bg: 'var(--agc-warning-bg)', dot: 'var(--c-warn)', txt: 'var(--agc-text)' },
    error:    { bg: 'var(--agc-error-bg)', dot: 'var(--c-err-t)', txt: 'var(--agc-text)' },
  };

  const TYPE_STYLE = {
    agent_start:          { icon: '🚀', label: 'Agent',  kind: 'info' },
    turn_start:           { icon: '▶',  label: 'Turn',   kind: 'info' },
    message_start:        { icon: '💬', label: 'LLM',    kind: 'progress' },
    message_update:       { icon: '…',  label: 'stream', kind: 'progress' },
    message_end:          { icon: '💬', label: 'LLM',    kind: 'success' },
    tool_execution_start: { icon: '🔧', label: 'Tool',   kind: 'progress' },
    tool_execution_end:   { icon: '✓',  label: 'Tool',   kind: 'success' },
    turn_end:             { icon: '◀',  label: 'Turn',   kind: 'info' },
    agent_end:            { icon: '🏁', label: 'Agent',  kind: 'success' },
  };

  /* ─── Inject styles ───────────────────────────────────────── */
  const CSS = `
#agent-console {
  --agc-panel-bg: var(--bg-overlay);
  --agc-panel-border: var(--accent-bd);
  --agc-panel-shadow: var(--sh-lg);
  --agc-bar-bg: var(--bg-glass);
  --agc-bar-hover-bg: var(--bg-hover);
  --agc-text: var(--t-primary);
  --agc-subtle-text: var(--t-secondary);
  --agc-muted: var(--t-tertiary);
  --agc-soft-border: var(--bd-subtle);
  --agc-info-bg: var(--bg-hover);
  --agc-progress-bg: var(--accent-bg);
  --agc-success-bg: var(--success-bg);
  --agc-warning-bg: var(--warning-bg);
  --agc-error-bg: var(--danger-bg);
  position: fixed;
  bottom: 0; right: 0; z-index: 1000;
  display: flex; flex-direction: column;
  background: var(--agc-panel-bg);
  backdrop-filter: blur(22px) saturate(160%);
  -webkit-backdrop-filter: blur(22px) saturate(160%);
  border-top: 1px solid var(--agc-panel-border);
  border-left: 1px solid var(--agc-panel-border);
  border-radius: 12px 0 0 0;
  transition: height .3s cubic-bezier(.4,0,.2,1), left .3s cubic-bezier(.4,0,.2,1), right .3s cubic-bezier(.4,0,.2,1), width .3s cubic-bezier(.4,0,.2,1), border-radius .3s cubic-bezier(.4,0,.2,1);
  box-shadow: var(--agc-panel-shadow);
  overflow: hidden;
  font-family: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
  font-size: 11px;
  color: var(--agc-text);
}
@media (min-width: 640px)  { #agent-console { left: 64px; } }
@media (min-width: 1024px) { #agent-console { left: 224px; } }

	/* Collapsed: compact floating pill */
	#agent-console.collapsed {
	  left: auto !important;
	  right: 12px;
	  width: auto;
	  border-radius: 20px;
    border: 1px solid var(--agc-panel-border);
    box-shadow: var(--sh-md);
	}
	#agent-console.collapsed #agc-bar {
	  border-bottom: none;
	  padding: 0 10px;
	  gap: 6px;
	}
	#agent-console.collapsed #agc-title,
	#agent-console.collapsed #agc-count,
	#agent-console.collapsed #agc-source { display: none; }

#agc-bar {
  flex-shrink: 0; height: 36px;
  display: flex; align-items: center; padding: 0 12px;
  cursor: pointer; gap: 8px; user-select: none;
  background: var(--agc-bar-bg);
  border-bottom: 1px solid var(--agc-soft-border);
  transition: padding .25s;
}
#agc-bar:hover { background: var(--agc-bar-hover-bg); }
#agc-pulse {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--c-ok-t); box-shadow: 0 0 6px var(--c-ok-t);
  flex-shrink: 0; transition: background .3s, box-shadow .3s;
}
#agc-pulse.error { background: var(--c-err-t); box-shadow: 0 0 6px var(--c-err-t); }
#agc-pulse.idle  { background: var(--agc-muted); box-shadow: none; }
#agc-pulse.live  { animation: agc-blink 1.4s ease-in-out infinite; }
@keyframes agc-blink { 0%,100% { opacity: 1; } 50% { opacity: .35; } }
#agc-title { flex: 1; font-size: 11px; color: var(--agc-muted); letter-spacing: .04em; }
#agc-count { font-size: 10px; color: var(--agc-muted); min-width: 20px; text-align: right; }
#agc-toggle { font-size: 14px; color: var(--agc-muted); line-height: 1; padding: 0 2px;
  transition: transform .25s; }
#agc-source {
  font-size: 9px; color: var(--agc-muted); padding: 1px 4px;
  border: 1px solid var(--agc-panel-border); border-radius: 3px;
}

#agc-body {
  flex: 1; overflow-y: auto; overflow-x: hidden;
  padding: 4px 0;
  display: flex; flex-direction: column;
  justify-content: flex-end;
  scrollbar-width: thin;
  scrollbar-color: var(--agc-panel-border) transparent;
}
#agc-body::-webkit-scrollbar { width: 4px; }
#agc-body::-webkit-scrollbar-track { background: transparent; }
#agc-body::-webkit-scrollbar-thumb { background: var(--agc-panel-border); border-radius: 2px; }

.agc-msg {
  display: flex; align-items: flex-start; gap: 6px;
  padding: 2px 10px; margin: 1px 4px; border-radius: 5px;
  line-height: 1.45;
  animation: agc-rise .3s cubic-bezier(.34,1.56,.64,1) both;
  transition: opacity .5s, transform .5s;
}
.agc-msg.expiring { opacity: 0; transform: translateY(-6px); }
@keyframes agc-rise {
  from { opacity: 0; transform: translateY(10px) scale(.97); }
  to   { opacity: 1; transform: translateY(0)   scale(1); }
}

/* v2 rich messages */
.agc-rich { flex-direction: column; padding: 4px 10px; margin: 2px 4px; gap: 2px; }
.agc-rich-header { display: flex; align-items: center; gap: 6px; width: 100%; }
.agc-rich-icon { flex-shrink: 0; font-size: 12px; }
.agc-rich-type { font-weight: 600; font-size: 10px; opacity: .7; }
.agc-rich-summary { flex: 1; font-size: 10px; opacity: .9; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.agc-rich-ts { font-size: 9px; opacity: .4; flex-shrink: 0; }

.agc-rich-body { padding-left: 18px; font-size: 10px; line-height: 1.4; }
.agc-rich-body pre {
  margin: 2px 0; padding: 4px 8px;
  background: var(--bg-muted); border-radius: 4px;
  white-space: pre-wrap; word-break: break-all;
  max-height: 160px; overflow-y: auto;
  font-family: inherit; font-size: 10px;
}
.agc-expand-btn {
  cursor: pointer; color: var(--accent); font-size: 10px;
  user-select: none; margin-left: 4px;
}
.agc-expand-btn:hover { color: var(--accent-hover); }
.agc-divider {
  display: flex; align-items: center; gap: 8px;
  padding: 3px 12px; margin: 4px 6px;
  color: var(--agc-muted); font-size: 10px;
}
.agc-divider::before, .agc-divider::after {
  content: ''; flex: 1; height: 1px;
  background: linear-gradient(to right, transparent, var(--agc-panel-border), transparent);
}
.agc-error-block {
  color: var(--c-err-t); background: var(--danger-bg);
  padding: 2px 8px; border-radius: 3px; margin: 2px 0;
}
`;

  const style = document.createElement('style');
  style.textContent = CSS;
  document.head.appendChild(style);

  /* ─── DOM ────────────────────────────────────────────────── */
  const panel = document.createElement('div');
  panel.id = 'agent-console';
  panel.style.height = PANEL_H_MIN + 'px';

  panel.innerHTML = `
    <div id="agc-bar">
      <span id="agc-pulse" class="idle"></span>
      <span id="agc-title">AGENT ACTIVITY</span>
      <span id="agc-source"></span>
      <span id="agc-count">0</span>
      <span id="agc-toggle">▾</span>
    </div>
    <div id="agc-body"></div>
  `;
  document.body.appendChild(panel);

  const $bar    = document.getElementById('agc-bar');
  const $pulse  = document.getElementById('agc-pulse');
  const $title  = document.getElementById('agc-title');
  const $source = document.getElementById('agc-source');
  const $count  = document.getElementById('agc-count');
  const $toggle = document.getElementById('agc-toggle');
  const $body   = document.getElementById('agc-body');

  function _syncReserveSpace(nextHeight) {
    const measured = typeof nextHeight === 'number'
      ? nextHeight
      : Math.ceil(panel.getBoundingClientRect().height || PANEL_H_MIN);
    const reserve = Math.max(PANEL_H_MIN, measured) + PANEL_SAFE_GAP;
    document.documentElement.style.setProperty('--agc-reserve-space', reserve + 'px');
  }

  _syncReserveSpace(PANEL_H_MIN);

  if (typeof ResizeObserver === 'function') {
    const ro = new ResizeObserver(() => _syncReserveSpace());
    ro.observe(panel);
  }
  window.addEventListener('resize', () => _syncReserveSpace());

  /* ─── Collapse / expand ───────────────────────────────────── */
  let _open = false;
  panel.classList.add('collapsed');
  $toggle.style.transform = 'rotate(-90deg)';
  $bar.addEventListener('click', () => {
    _open = !_open;
    const nextHeight = _open ? PANEL_H_OPEN : PANEL_H_MIN;
    panel.style.height = nextHeight + 'px';
    if (_open) {
      panel.classList.remove('collapsed');
    } else {
      panel.classList.add('collapsed');
    }
    $toggle.style.transform = _open ? '' : 'rotate(-90deg)';
    _syncReserveSpace(nextHeight);
  });

  /* ─── Message queue ───────────────────────────────────────── */
  const _msgs = [];   // { el, timer? }
  let _total = 0;

  function _fmtTime(ts) {
    const d = new Date(ts * 1000 || Date.now());
    return d.toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }

  function _esc(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function _trunc(s, n) {
    const t = String(s);
    return t.length > n ? t.slice(0, n) + '…' : t;
  }

  function _append(el) {
    $body.appendChild(el);
    _msgs.push({ el });
    _total++;
    $count.textContent = _total;

    while (_msgs.length > MAX_MESSAGES) {
      const old = _msgs.shift();
      if (old.timer) clearTimeout(old.timer);
      old.el.remove();
    }

    const atBottom = $body.scrollHeight - $body.scrollTop - $body.clientHeight < 80;
    if (atBottom) $body.scrollTop = $body.scrollHeight;
  }

  /* ─── v1 flat event render ────────────────────────────────── */
  function _pushV1(evt) {
    const ks  = KIND_STYLE[evt.kind] || KIND_STYLE.info;
    const icon = evt.icon || '⚙️';
    const label = evt.label || evt.agent || 'system';

    const el = document.createElement('div');
    el.className = 'agc-msg';
    el.style.background = ks.bg;
    el.innerHTML = `
      <span class="agc-icon" style="font-size:13px">${icon}</span>
      <div class="agc-body-inner" style="flex:1;min-width:0">
        <div class="agc-meta" style="display:flex;gap:6px;align-items:baseline;font-size:10px;opacity:.55;margin-bottom:1px">
          <span class="agc-label" style="color:${ks.dot};font-weight:600">${_esc(label)}</span>
          <span class="agc-time">${_fmtTime(evt.t || Date.now())}</span>
        </div>
        <div class="agc-text" style="color:${ks.txt};word-break:break-all;white-space:pre-wrap">${_esc(evt.msg || '')}</div>
      </div>`;
    _append(el);
  }

  /* ─── v2 typed event render ───────────────────────────────── */
  function _pushV2(evt) {
    const type = evt.type;
    const data = evt.data || {};
    const ts = _fmtTime(evt.timestamp || Date.now() / 1000);
    const tstyle = TYPE_STYLE[type] || { icon: '•', label: type, kind: 'info' };

    // ── Divider events ──────────────────────────────
    if (type === 'turn_start') {
      const el = document.createElement('div');
      el.className = 'agc-divider';
      el.innerHTML = `<span>Turn ${data.turn + 1}</span>`;
      _append(el);
      return;
    }
    if (type === 'turn_end') {
      const el = document.createElement('div');
      el.className = 'agc-divider';
      const dur = data.duration_ms ? ` · ${data.duration_ms}ms` : '';
      const comp = data.compaction_triggered ? ' · compacted' : '';
      el.innerHTML = `<span>Turn ${(data.turn || 0) + 1} done${dur}${comp}</span>`;
      _append(el);
      return;
    }

    if (type === 'agent_start') {
      const el = document.createElement('div');
      el.className = 'agc-msg agc-rich';
      el.style.background = 'var(--agc-progress-bg)';
      el.style.borderLeft = '2px solid var(--agc-panel-border)';
      el.innerHTML = `
        <div class="agc-rich-header">
          <span class="agc-rich-icon">🚀</span>
          <span class="agc-rich-type" style="color:var(--accent)">Agent started</span>
          <span class="agc-rich-summary">model=${_esc(data.model || '?')}</span>
          <span class="agc-rich-ts">${ts}</span>
        </div>`;
      _append(el);
      return;
    }

    if (type === 'agent_end') {
      const status = data.final_status || '?';
      const isErr = status === 'failed' || status === 'error' || data.error;
      const el = document.createElement('div');
      el.className = 'agc-msg agc-rich';
      el.style.background = isErr ? 'var(--danger-bg)' : 'var(--success-bg)';
      el.style.borderLeft = `2px solid ${isErr ? 'var(--c-err-t)' : 'var(--c-ok-t)'}`;
      const tokens = data.total_tokens;
      const tokStr = tokens ? `${tokens.input}↑ ${tokens.output}↓` : '';
      const cacheStr = data.cache_hit_rate != null ? `cache=${(data.cache_hit_rate * 100).toFixed(0)}%` : '';
      el.innerHTML = `
        <div class="agc-rich-header">
          <span class="agc-rich-icon">🏁</span>
          <span class="agc-rich-type" style="color:${isErr ? 'var(--c-err-t)' : 'var(--c-ok-t)'}">Agent ${status}</span>
          <span class="agc-rich-summary">${data.total_turns || '?'} turns · ${tokStr} · ${cacheStr}</span>
          <span class="agc-rich-ts">${ts}</span>
        </div>
        ${data.error ? `<div class="agc-error-block">${_esc(data.error)}</div>` : ''}`;
      _append(el);
      return;
    }

    // ── LLM response ───────────────────────────────
    if (type === 'message_end' && !data.error) {
      const content = data.content || '';
      const tcs = data.tool_calls || [];
      const tokInfo = data.tokens ? `${data.tokens.input}↑ ${data.tokens.output}↓` : '';

      const el = document.createElement('div');
      el.className = 'agc-msg agc-rich';
      el.style.background = 'var(--agc-progress-bg)';

      let bodyHtml = '';
      if (content && content.trim()) {
        const short = _trunc(content, LLM_PREVIEW_LEN);
        const needsExpand = content.length > LLM_PREVIEW_LEN;
        bodyHtml += `
          <div class="agc-rich-body">
            <pre>${_esc(short)}</pre>
            ${needsExpand ? `<span class="agc-expand-btn" data-full="${_esc(content).replace(/"/g, '&quot;')}">展开全部 (${content.length} 字)</span>` : ''}
          </div>`;
      }
      if (tcs.length) {
        bodyHtml += `<div class="agc-rich-body" style="color:var(--accent)">🔧 调用工具: ${tcs.map(t => _esc(t.name + '(' + _trunc(JSON.stringify(t.args || {}), 60) + ')')).join(', ')}</div>`;
      }

      el.innerHTML = `
        <div class="agc-rich-header">
          <span class="agc-rich-icon">💬</span>
          <span class="agc-rich-type" style="color:var(--accent)">LLM</span>
          <span class="agc-rich-summary">${tokInfo} ${content ? _trunc(content.replace(/\n/g, ' '), 80) : '(tool calls only)'}</span>
          <span class="agc-rich-ts">${ts}</span>
        </div>${bodyHtml}`;
      _append(el);
      return;
    }

    // LLM error
    if (type === 'message_end' && data.error) {
      const el = document.createElement('div');
      el.className = 'agc-msg agc-rich';
      el.style.background = 'var(--danger-bg)';
      el.innerHTML = `
        <div class="agc-rich-header">
          <span class="agc-rich-icon">💬</span>
          <span class="agc-rich-type" style="color:var(--c-err-t)">LLM error</span>
          <span class="agc-rich-summary">${_esc(data.error.message || data.error.code || 'unknown')}</span>
          <span class="agc-rich-ts">${ts}</span>
        </div>`;
      _append(el);
      return;
    }

    // ── Tool execution ─────────────────────────────
    if (type === 'tool_execution_start') {
      const argsPreview = data.args_preview || _trunc(JSON.stringify(data.args || {}), 80);
      const el = document.createElement('div');
      el.className = 'agc-msg agc-rich';
      el.style.background = 'var(--warning-bg)';
      el.innerHTML = `
        <div class="agc-rich-header">
          <span class="agc-rich-icon">🔧</span>
          <span class="agc-rich-type" style="color:var(--warning-t)">${_esc(data.tool_name || '?')}</span>
          <span class="agc-rich-summary">${_esc(argsPreview)}</span>
          <span class="agc-rich-ts">${ts}</span>
        </div>`;
      _append(el);
      return;
    }

    if (type === 'tool_execution_end') {
      const isErr = data.status === 'error';
      const preview = data.result_preview || '';
      const dur = data.duration_ms ? `${data.duration_ms}ms` : '';
      const trunc = data.result_truncated ? ' [截断]' : '';

      const el = document.createElement('div');
      el.className = 'agc-msg agc-rich';
      el.style.background = isErr ? 'var(--danger-bg)' : 'var(--success-bg)';

      let bodyHtml = '';
      if (preview) {
        const short = _trunc(preview, TOOL_PREVIEW_LEN);
        const needsExpand = preview.length > TOOL_PREVIEW_LEN;
        bodyHtml += `
          <div class="agc-rich-body">
            <pre>${_esc(short)}</pre>
            ${needsExpand ? `<span class="agc-expand-btn" data-full="${_esc(preview).replace(/"/g, '&quot;')}">展开全部 (${preview.length} 字)</span>` : ''}
          </div>`;
      }
      if (data.error) {
        bodyHtml += `<div class="agc-error-block">${_esc(data.error.message || data.error.code || '')}</div>`;
      }

      el.innerHTML = `
        <div class="agc-rich-header">
          <span class="agc-rich-icon">${isErr ? '✗' : '✓'}</span>
          <span class="agc-rich-type" style="color:${isErr ? 'var(--c-err-t)' : 'var(--c-ok-t)'}">${_esc(data.tool_name || '?')}</span>
          <span class="agc-rich-summary">${dur}${trunc}</span>
          <span class="agc-rich-ts">${ts}</span>
        </div>${bodyHtml}`;
      _append(el);
      return;
    }

    // fallback for any unhandled event type
    const ks = tstyle ? KIND_STYLE[tstyle.kind] || KIND_STYLE.info : KIND_STYLE.info;
    const el = document.createElement('div');
    el.className = 'agc-msg';
    el.style.background = ks.bg;
    el.innerHTML = `
      <span class="agc-icon" style="font-size:13px">${tstyle.icon}</span>
      <div style="flex:1;min-width:0">
        <span style="color:${ks.dot};font-weight:600;font-size:10px">${tstyle.label}</span>
        <span style="color:${ks.txt};word-break:break-all;white-space:pre-wrap">${_esc(JSON.stringify(data).slice(0, 200))}</span>
      </div>`;
    _append(el);
  }

  /* ─── Expand/collapse handler ─────────────────────────────── */
  $body.addEventListener('click', (e) => {
    if (!e.target.classList.contains('agc-expand-btn')) return;
    const btn = e.target;
    const full = btn.dataset.full;
    if (!full) return;
    const pre = btn.previousElementSibling;
    if (!pre || pre.tagName !== 'PRE') return;

    if (btn.dataset.expanded === '1') {
      pre.textContent = _trunc(pre.dataset.original || '', pre.dataset.origLen || LLM_PREVIEW_LEN);
      btn.textContent = `展开全部 (${pre.dataset.origLen} 字)`;
      btn.dataset.expanded = '0';
    } else {
      if (!pre.dataset.original) {
        pre.dataset.original = pre.textContent;
        pre.dataset.origLen = pre.textContent.length;
      }
      const decoded = new DOMParser().parseFromString(full, 'text/html').documentElement.textContent;
      pre.textContent = decoded;
      btn.textContent = '收起';
      btn.dataset.expanded = '1';
    }
  });

  /* ─── SSE connections ─────────────────────────────────────── */
  let _esV2 = null;
  let _esV1 = null;
  let _reconnectDelay = RECONNECT_BASE;
  let _reconnectTimer = null;
  let _useV2 = false;

  function _setStatus(status) {
    $pulse.className = '';
    if (status === 'live') {
      $pulse.classList.add('live');
      $title.textContent = 'AGENT ACTIVITY  •  LIVE';
    } else if (status === 'error') {
      $pulse.classList.add('error');
      $title.textContent = 'AGENT ACTIVITY  •  RECONNECTING…';
    } else {
      $pulse.classList.add('idle');
      $title.textContent = 'AGENT ACTIVITY';
    }
  }

  function _connectV2() {
    if (_esV2) { _esV2.close(); _esV2 = null; }

    _esV2 = new EventSource('/agent/v2/events');

    _esV2.addEventListener('open', () => {
      _useV2 = true;
      _setStatus('live');
      _reconnectDelay = RECONNECT_BASE;
      $source.textContent = 'v2';
      $source.style.color = 'var(--c-ok-t)';
      $source.style.borderColor = 'var(--c-ok-t)';
    });

    _esV2.addEventListener('message', (e) => {
      let evt;
      try { evt = JSON.parse(e.data); } catch { return; }
      if (!evt.type) return;
      _pushV2(evt);
    });

    _esV2.addEventListener('error', () => {
      _esV2.close();
      _esV2 = null;
      if (_useV2) {
        // v2 failed after working — reconnect with backoff
        _setStatus('error');
        _reconnectTimer = setTimeout(() => {
          _reconnectDelay = Math.min(_reconnectDelay * 2, RECONNECT_MAX);
          _connectV2();
        }, _reconnectDelay);
      } else {
        // v2 never worked — fall back to v1
        _connectV1();
      }
    });
  }

  function _connectV1() {
    if (_esV1) { _esV1.close(); _esV1 = null; }

    _esV1 = new EventSource('/agent/events');

    _esV1.addEventListener('open', () => {
      _useV2 = false;
      _setStatus('live');
      _reconnectDelay = RECONNECT_BASE;
      $source.textContent = 'v1';
      $source.style.color = 'var(--warning-t)';
      $source.style.borderColor = 'var(--warning-t)';
    });

    _esV1.addEventListener('message', (e) => {
      let evt;
      try { evt = JSON.parse(e.data); } catch { return; }
      if (evt.ping) return;
      _pushV1(evt);
    });

    _esV1.addEventListener('error', () => {
      _esV1.close();
      _esV1 = null;
      _setStatus('error');
      _reconnectTimer = setTimeout(() => {
        _reconnectDelay = Math.min(_reconnectDelay * 2, RECONNECT_MAX);
        // Try v2 first on reconnect
        _connectV2();
      }, _reconnectDelay);
    });
  }

  // Probe v2 availability, fall back to v1
  function _probeAndConnect() {
    fetch('/agent/v2/events', { method: 'HEAD' })
      .then(r => {
        if (r.ok) { _connectV2(); } else { _connectV1(); }
      })
      .catch(() => { _connectV1(); });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _probeAndConnect);
  } else {
    _probeAndConnect();
  }

  window.addEventListener('beforeunload', () => {
    clearTimeout(_reconnectTimer);
    if (_esV2) _esV2.close();
    if (_esV1) _esV1.close();
  });

  /* ─── Public API ──────────────────────────────────────────── */
  window.agentConsole = {
    pushV1: _pushV1,
    pushV2: _pushV2,
    clear: () => {
      _msgs.forEach(m => { if (m.timer) clearTimeout(m.timer); m.el.remove(); });
      _msgs.length = 0;
      _total = 0;
      $count.textContent = '0';
    },
  };
})();
