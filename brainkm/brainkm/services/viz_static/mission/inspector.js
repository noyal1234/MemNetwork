/**
 * Inspector pane — detail / neighbors / explain / history tabs.
 */

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

export function createInspector({
  onOpenNode,
  onExplain,
  onTabChange,
}) {
  const empty = document.getElementById('inspector-empty');
  const tabs = {
    detail: document.getElementById('tab-detail'),
    neighbors: document.getElementById('tab-neighbors'),
    explain: document.getElementById('tab-explain'),
    history: document.getElementById('tab-history'),
  };
  const explainBtn = document.getElementById('btn-explain');
  const explainOut = document.getElementById('explain-out');
  let activeTab = 'detail';
  let current = null;
  let edges = [];
  let allNodesById = new Map();

  document.querySelectorAll('#inspector-tabs button').forEach((btn) => {
    btn.addEventListener('click', () => setTab(btn.dataset.tab));
  });

  explainBtn.addEventListener('click', () => {
    if (!current) return;
    onExplain?.(current);
  });

  function setTab(name) {
    activeTab = name;
    document.querySelectorAll('#inspector-tabs button').forEach((b) => {
      b.classList.toggle('active', b.dataset.tab === name);
    });
    for (const [key, el] of Object.entries(tabs)) {
      el.hidden = key !== name;
    }
    empty.hidden = !!current;
    onTabChange?.(name);
  }

  function setExplainText(text) {
    explainOut.textContent = text || '';
  }

  function appendExplainText(chunk) {
    explainOut.textContent += chunk;
  }

  function renderDetail(node) {
    const pills = [];
    if (node.kind) pills.push(`${node.kind}${node.subtype ? ` · ${node.subtype}` : ''}`);
    if (node.confidence != null) pills.push(`conf ${(Number(node.confidence) * 100).toFixed(0)}%`);
    if (node.use_count) pills.push(`${node.use_count} uses`);
    if (node.user_pinned) pills.push('pinned');
    if (node.valid_until) pills.push('archived');
    if (node.path) {
      pills.push(`<a href="cursor://file/${encodeURI(node.path)}">${escapeHtml(node.path)}</a>`);
    }
    if (node.session_id) pills.push(`sess ${escapeHtml(node.session_id)}`);
    if (node.tags) {
      String(node.tags).split(',').forEach((t) => t.trim() && pills.push(escapeHtml(t.trim())));
    }
    tabs.detail.innerHTML = `
      <h3 style="margin:0 0 8px;font-size:16px">${escapeHtml(node.title || node.id)}</h3>
      <div>${pills.map((p) => `<span class="meta-pill">${p}</span>`).join('')}</div>
      <pre style="white-space:pre-wrap;font-family:var(--mono);font-size:12px;line-height:1.45;margin-top:12px">${escapeHtml(node.content || '(no content)')}</pre>
    `;
  }

  function renderNeighbors(node, connected) {
    if (!connected.length) {
      tabs.neighbors.innerHTML = '<div style="color:var(--text-muted)">No connections in current filters.</div>';
      return;
    }
    const groups = new Map();
    for (const e of connected) {
      const rel = e.relationship || 'linked';
      if (!groups.has(rel)) groups.set(rel, []);
      groups.get(rel).push(e);
    }
    let html = '';
    for (const [rel, list] of [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
      html += `<div class="conn-group-title">${escapeHtml(rel)} (${list.length})</div>`;
      for (const e of list.slice(0, 40)) {
        const otherId = e.from_id === node.id ? e.to_id : e.from_id;
        const other = allNodesById.get(otherId) || {};
        html += `
          <div class="conn-item" data-id="${escapeHtml(otherId)}">
            <div class="conn-dot" style="background:var(--${other.kind || 'memory'})"></div>
            <div>
              <div>${escapeHtml(other.title || otherId)}</div>
              <div style="font-size:11px;color:var(--text-muted)">weight ${(e.weight || 1).toFixed?.(2) ?? e.weight}</div>
            </div>
          </div>`;
      }
    }
    tabs.neighbors.innerHTML = html;
    tabs.neighbors.querySelectorAll('.conn-item').forEach((el) => {
      el.addEventListener('click', () => onOpenNode?.(el.dataset.id));
    });
  }

  function renderHistory(node) {
    // Walk supersedes edges both directions for a simple chain
    const chain = [];
    const seen = new Set();
    let cursor = node.id;
    // predecessors (things this supersedes)
    const queue = [cursor];
    while (queue.length) {
      const id = queue.shift();
      if (seen.has(id)) continue;
      seen.add(id);
      const n = allNodesById.get(id);
      if (n) chain.push(n);
      for (const e of edges) {
        if (e.relationship === 'supersedes' && e.from_id === id && !seen.has(e.to_id)) {
          queue.push(e.to_id);
        }
      }
    }
    // also nodes that supersede this one
    for (const e of edges) {
      if (e.relationship === 'supersedes' && e.to_id === node.id) {
        const n = allNodesById.get(e.from_id);
        if (n && !seen.has(n.id)) chain.unshift(n);
      }
    }
    if (chain.length <= 1) {
      tabs.history.innerHTML = '<div style="color:var(--text-muted)">No supersedes history for this node.</div>';
      return;
    }
    tabs.history.innerHTML = chain
      .map(
        (n) => `
        <div class="history-item">
          <div style="font-weight:600;cursor:pointer" data-id="${escapeHtml(n.id)}">${escapeHtml(n.title || n.id)}</div>
          <div style="font-size:11px;color:var(--text-muted)">${escapeHtml(n.subtype || n.kind || '')} · ${(n.updated_at || n.valid_from || '').toString().slice(0, 10)}</div>
        </div>`,
      )
      .join('');
    tabs.history.querySelectorAll('[data-id]').forEach((el) => {
      el.addEventListener('click', () => onOpenNode?.(el.dataset.id));
    });
  }

  function show(node, { connected = [], nodesById = new Map(), allEdges = [] } = {}) {
    current = node;
    edges = allEdges;
    allNodesById = nodesById;
    empty.hidden = true;
    explainBtn.disabled = !node;
    renderDetail(node);
    renderNeighbors(node, connected);
    renderHistory(node);
    setTab(activeTab);
  }

  function clear() {
    current = null;
    empty.hidden = false;
    explainBtn.disabled = true;
    explainOut.textContent = '';
    for (const el of Object.values(tabs)) {
      if (el.id !== 'tab-explain') el.innerHTML = '';
      el.hidden = true;
    }
    setTab('detail');
    empty.hidden = false;
  }

  setTab('detail');

  return {
    show,
    clear,
    setExplainText,
    appendExplainText,
    get current() {
      return current;
    },
  };
}
