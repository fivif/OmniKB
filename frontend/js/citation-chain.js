/**
 * citation-chain.js — UI.5
 * Reusable visual rendering for RAG citation references.
 *
 * Public API exposed as `window.OmnikbCitations`:
 *   render(targetEl, citations)   — append staggered citation bubbles
 *   clear(targetEl)               — remove all citation bubbles inside target
 *
 * Citation entry shape (matches backend chat.py SSE payload):
 *   {
 *     index:    1,                       // 1-based reference number
 *     chunk_id: 'uuid-...',               // backend chunk identifier
 *     content:  'snippet text',           // preview text (≤300 chars)
 *     source:   'System_Arch.md',         // human-readable source name
 *     score:    0.98                      // relevance score (0..1)
 *   }
 *
 * Hover behaviour: shows preview card after 300 ms.
 * Click behaviour: dispatches `omnikb:citation-click` CustomEvent on document
 *   with detail = { chunk_id, source, ref, content }.
 *
 * Depends on Anime.js + Lucide (loaded by UI.1's CDN imports).
 */
(function () {
  'use strict';

  if (window.OmnikbCitations) return;  // idempotent

  const HOVER_DELAY = 300;     // ms before preview card appears
  const STAGGER_INTERVAL = 150; // ms between bubble entries

  /* ─── Preview card singleton ─────────────────────────────── */
  let _previewCard = null;
  let _hoverTimer = null;

  function _ensurePreviewCard() {
    if (_previewCard) return _previewCard;
    _previewCard = document.createElement('div');
    _previewCard.className = 'citation-preview-card';
    _previewCard.innerHTML = `
      <div class="preview-source"></div>
      <div class="preview-content"></div>
    `;
    document.body.appendChild(_previewCard);
    return _previewCard;
  }

  function _showPreview(bubbleEl, entry) {
    const card = _ensurePreviewCard();
    card.querySelector('.preview-source').textContent =
      `[${entry.index}] ${entry.source}` +
      (typeof entry.score === 'number' ? ` · ${(entry.score * 100).toFixed(0)}%` : '');
    card.querySelector('.preview-content').textContent =
      String(entry.content || '').slice(0, 280);

    const r = bubbleEl.getBoundingClientRect();
    // Position above the bubble; clamp to viewport
    const cardRect = card.getBoundingClientRect();
    const top = Math.max(8, r.top - (cardRect.height || 80) - 8);
    let left = r.left;
    const maxLeft = window.innerWidth - 380;
    if (left > maxLeft) left = maxLeft;
    card.style.left = `${left}px`;
    card.style.top = `${top}px`;
    card.classList.add('visible');
  }

  function _hidePreview() {
    if (_previewCard) _previewCard.classList.remove('visible');
  }

  /* ─── Render ────────────────────────────────────────────── */

  function _esc(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function _bubbleHtml(entry) {
    const scorePct = typeof entry.score === 'number'
      ? `<span class="citation-score">${(entry.score * 100).toFixed(0)}%</span>`
      : '';
    return `<i data-lucide="file-text" class="citation-icon"></i>` +
           `<span class="citation-name">${_esc(entry.source || `chunk ${entry.index}`)}</span>` +
           scorePct;
  }

  function render(targetEl, citations) {
    if (!targetEl || !Array.isArray(citations) || citations.length === 0) return;

    // Build a chain wrapper if none exists (so multiple render() calls append)
    let chain = targetEl.querySelector(':scope > .citation-chain');
    if (!chain) {
      chain = document.createElement('span');
      chain.className = 'citation-chain';
      targetEl.appendChild(chain);
    }

    const newBubbles = [];
    citations.forEach((c) => {
      const el = document.createElement('span');
      el.className = 'citation-bubble';
      el.dataset.ref = String(c.index);
      el.dataset.chunkId = c.chunk_id || '';
      el.innerHTML = _bubbleHtml(c);

      // Hover preview
      el.addEventListener('mouseenter', () => {
        clearTimeout(_hoverTimer);
        _hoverTimer = setTimeout(() => _showPreview(el, c), HOVER_DELAY);
      });
      el.addEventListener('mouseleave', () => {
        clearTimeout(_hoverTimer);
        _hidePreview();
      });

      // Click → dispatch global event for UI.3 to wire
      el.addEventListener('click', (ev) => {
        ev.stopPropagation();
        document.dispatchEvent(new CustomEvent('omnikb:citation-click', {
          detail: {
            chunk_id: c.chunk_id,
            source: c.source,
            ref: c.index,
            content: c.content,
          },
        }));
      });

      chain.appendChild(el);
      newBubbles.push(el);
    });

    // Render Lucide icons in the new bubbles
    if (window.lucide && typeof window.lucide.createIcons === 'function') {
      window.lucide.createIcons({ nameAttr: 'data-lucide' });
    }

    // Stagger fade-up animation via Anime.js if available; fallback to CSS class.
    if (window.anime) {
      window.anime({
        targets: newBubbles,
        opacity: [0, 1],
        translateY: [10, 0],
        scale: [0.9, 1],
        duration: 400,
        delay: window.anime.stagger(STAGGER_INTERVAL, { start: 50 }),
        easing: 'easeOutBack',
      });
    } else {
      newBubbles.forEach((el, i) => {
        setTimeout(() => {
          el.style.opacity = '1';
          el.style.transform = 'translateY(0) scale(1)';
        }, 50 + i * STAGGER_INTERVAL);
      });
    }
  }

  function clear(targetEl) {
    if (!targetEl) return;
    targetEl.querySelectorAll(':scope > .citation-chain').forEach((el) => el.remove());
  }

  window.OmnikbCitations = { render, clear };
})();
