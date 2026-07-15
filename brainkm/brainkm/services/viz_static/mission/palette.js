/**
 * Cmd+K command palette — search / actions / chat / traverse.
 */

function fuzzyScore(hay, needle) {
  const h = hay.toLowerCase();
  const n = needle.toLowerCase();
  if (!n) return 1;
  if (h.includes(n)) return 2 + (h.startsWith(n) ? 1 : 0);
  let hi = 0;
  for (const ch of n) {
    hi = h.indexOf(ch, hi);
    if (hi < 0) return 0;
    hi += 1;
  }
  return 0.5;
}

export function createPalette({
  getNodes,
  getEdges,
  onSelectNode,
  onAction,
  onChat,
  onTraverse,
}) {
  const backdrop = document.getElementById('palette-backdrop');
  const input = document.getElementById('palette-input');
  const results = document.getElementById('palette-results');
  const chatEl = document.getElementById('palette-chat');
  let open = false;
  let items = [];
  let active = 0;
  let mode = 'search';

  const ACTIONS = [
    { id: 'theme', label: 'Toggle theme', run: () => onAction?.('theme') },
    { id: 'relayout', label: 'Re-layout graph', run: () => onAction?.('relayout') },
    { id: 'fit', label: 'Fit camera', run: () => onAction?.('fit') },
    { id: 'save-view', label: 'Save current view', run: () => onAction?.('save-view') },
    { id: 'export-json', label: 'Export visible graph JSON', run: () => onAction?.('export-json') },
    { id: 'cinema', label: 'Open cinema mode (3D)', run: () => onAction?.('cinema') },
    { id: 'archived', label: 'Toggle show archived', run: () => onAction?.('archived') },
    { id: 'nav', label: 'Toggle navigator', run: () => onAction?.('nav') },
    { id: 'inspect', label: 'Toggle inspector', run: () => onAction?.('inspect') },
  ];

  function setOpen(next) {
    open = next;
    backdrop.classList.toggle('visible', open);
    backdrop.setAttribute('aria-hidden', open ? 'false' : 'true');
    if (open) {
      input.value = '';
      chatEl.classList.remove('visible');
      chatEl.innerHTML = '';
      refresh('');
      input.focus();
    }
  }

  function render() {
    results.innerHTML = '';
    let lastGroup = null;
    items.forEach((item, idx) => {
      if (item.group !== lastGroup) {
        const g = document.createElement('div');
        g.className = 'palette-group';
        g.textContent = item.group;
        results.appendChild(g);
        lastGroup = item.group;
      }
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = `palette-item${idx === active ? ' active' : ''}`;
      btn.innerHTML = `<span class="kind">${item.kind || ''}</span><span>${item.label}</span>`;
      btn.addEventListener('click', () => choose(idx));
      results.appendChild(btn);
    });
  }

  async function refresh(raw) {
    const q = raw.trim();
    items = [];
    active = 0;

    if (q.startsWith('>')) {
      mode = 'actions';
      const needle = q.slice(1).trim();
      for (const a of ACTIONS) {
        if (!needle || fuzzyScore(a.label, needle)) {
          items.push({ group: 'Actions', kind: 'action', label: a.label, action: a });
        }
      }
      render();
      return;
    }

    if (q.startsWith('?')) {
      mode = 'chat';
      items.push({
        group: 'Chat',
        kind: 'chat',
        label: q.length > 1 ? `Ask: ${q.slice(1).trim()}` : 'Type a question after ?',
        chat: q.slice(1).trim(),
      });
      render();
      return;
    }

    if (q.toLowerCase().startsWith('via:')) {
      mode = 'traverse';
      const body = q.slice(4).trim();
      items.push({
        group: 'Traverse',
        kind: 'via',
        label: body || 'via:relationship nodeTitle',
        traverse: body,
      });
      render();
      return;
    }

    mode = 'search';
    const nodes = getNodes?.() || [];
    const local = [];
    for (const n of nodes) {
      const score = fuzzyScore(`${n.title} ${n.tags || ''} ${n.path || ''}`, q);
      if (!q || score > 0) local.push({ n, score });
    }
    local.sort((a, b) => b.score - a.score);
    for (const { n } of local.slice(0, 12)) {
      items.push({
        group: 'Local titles',
        kind: n.kind,
        label: n.title || n.id,
        nodeId: n.id,
      });
    }

    if (q.length >= 2) {
      try {
        const res = await fetch(`/api/search?q=${encodeURIComponent(q)}&limit=10`);
        const data = await res.json();
        for (const r of data.results || []) {
          if (items.some((i) => i.nodeId === r.id)) continue;
          items.push({
            group: 'FTS5',
            kind: r.kind,
            label: r.title || r.id,
            nodeId: r.id,
          });
        }
      } catch {
        /* ignore */
      }
    }
    render();
  }

  async function choose(idx) {
    const item = items[idx];
    if (!item) return;
    if (item.action) {
      item.action.run();
      setOpen(false);
      return;
    }
    if (item.nodeId) {
      onSelectNode?.(item.nodeId);
      setOpen(false);
      return;
    }
    if (mode === 'chat' && item.chat) {
      chatEl.classList.add('visible');
      chatEl.textContent = 'Thinking…';
      const answer = await onChat?.(item.chat);
      chatEl.textContent = answer || '(no answer)';
      return;
    }
    if (mode === 'traverse') {
      onTraverse?.(item.traverse || '');
      setOpen(false);
    }
  }

  input.addEventListener('input', () => {
    refresh(input.value);
  });

  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      active = Math.min(items.length - 1, active + 1);
      render();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      active = Math.max(0, active - 1);
      render();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      choose(active);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      setOpen(false);
    }
  });

  backdrop.addEventListener('click', (e) => {
    if (e.target === backdrop) setOpen(false);
  });

  return {
    open: () => setOpen(true),
    close: () => setOpen(false),
    isOpen: () => open,
    toggle: () => setOpen(!open),
  };
}

export function parseTraverse(query, nodes, edges) {
  // via:calls parse_config  OR via:imports foo
  const parts = String(query || '').trim().split(/\s+/);
  if (!parts.length) return null;
  let rel = null;
  let rest = parts.join(' ');
  if (parts[0].includes(':')) {
    // already stripped via: in caller — relationship may be first token with optional colon form
  }
  if (parts.length >= 2 && /^[a-z_]+$/i.test(parts[0])) {
    rel = parts[0].toLowerCase();
    rest = parts.slice(1).join(' ');
  }
  const needle = rest.toLowerCase();
  const seed = nodes.find((n) => (n.title || '').toLowerCase().includes(needle));
  if (!seed) return null;
  const ids = new Set([seed.id]);
  for (const e of edges) {
    const matchRel = !rel || (e.relationship || '').toLowerCase() === rel;
    if (!matchRel) continue;
    if (e.from_id === seed.id) ids.add(e.to_id);
    if (e.to_id === seed.id) ids.add(e.from_id);
  }
  return { seedId: seed.id, ids: [...ids], relationship: rel };
}
