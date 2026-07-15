/**
 * Mission Control — app bootstrap & state.
 */
import { createGraphController } from './graph.js';
import { createInspector } from './inspector.js';
import { createPalette, parseTraverse } from './palette.js';
import { askBrain, explainNode } from './chat.js';

const KINDS = ['memory', 'code', 'procedure', 'session'];
const VERSION_POLL_MS = 10000;

const state = {
  nodes: [],
  edges: [],
  sessions: [],
  views: [],
  kinds: new Set(KINDS),
  rels: new Set(),
  allRels: [],
  showArchived: false,
  colorBy: 'kind',
  confMin: 0,
  subtype: null,
  recentDays: null,
  selectedId: null,
  focusIds: null,
  sessionFilter: null,
  versionKey: null,
};

const statusEl = document.getElementById('graph-status');
const loading = document.getElementById('loading');
const loadingText = document.getElementById('loading-text');

function setStatus(text) {
  statusEl.textContent = text;
}

function readTheme() {
  return document.documentElement.getAttribute('data-theme') || 'dark';
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('brainkm-mission-theme', theme);
}

function initTheme() {
  const saved = localStorage.getItem('brainkm-mission-theme');
  if (saved === 'light' || saved === 'dark') {
    applyTheme(saved);
    return;
  }
  applyTheme(window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
}

function nodeVisible(n) {
  if (!state.kinds.has(n.kind)) return false;
  if (!state.showArchived && n.valid_until) return false;
  if (state.subtype && n.subtype !== state.subtype) return false;
  if (state.confMin > 0 && (Number(n.confidence) || 0) * 100 < state.confMin) return false;
  if (state.recentDays) {
    const t = Date.parse(n.updated_at || n.valid_from || n.created_at || '');
    if (!Number.isFinite(t) || Date.now() - t > state.recentDays * 86400000) return false;
  }
  if (state.sessionFilter && n.session_id !== state.sessionFilter) return false;
  if (state.focusIds && !state.focusIds.has(n.id)) return false;
  return true;
}

function visiblePayload() {
  const nodes = state.nodes.filter(nodeVisible);
  const ids = new Set(nodes.map((n) => n.id));
  const edges = state.edges.filter((e) => {
    if (!ids.has(e.from_id) || !ids.has(e.to_id)) return false;
    if (state.rels.size && !state.rels.has(e.relationship || 'linked')) return false;
    return true;
  });
  return { nodes, edges };
}

function edgesForNode(id) {
  return state.edges.filter((e) => e.from_id === id || e.to_id === id);
}

function writeHash() {
  const payload = {
    kinds: [...state.kinds],
    rels: [...state.rels],
    colorBy: state.colorBy,
    showArchived: state.showArchived,
    confMin: state.confMin,
    subtype: state.subtype,
    recentDays: state.recentDays,
    session: state.sessionFilter,
    selected: state.selectedId,
  };
  const hash = encodeURIComponent(JSON.stringify(payload));
  history.replaceState(null, '', `#${hash}`);
}

function readHash() {
  const raw = location.hash.replace(/^#/, '');
  if (!raw) return;
  try {
    const data = JSON.parse(decodeURIComponent(raw));
    if (Array.isArray(data.kinds)) state.kinds = new Set(data.kinds);
    if (Array.isArray(data.rels)) state.rels = new Set(data.rels);
    if (data.colorBy) state.colorBy = data.colorBy;
    if (typeof data.showArchived === 'boolean') state.showArchived = data.showArchived;
    if (typeof data.confMin === 'number') state.confMin = data.confMin;
    state.subtype = data.subtype || null;
    state.recentDays = data.recentDays || null;
    state.sessionFilter = data.session || null;
    state.selectedId = data.selected || null;
  } catch {
    /* ignore bad hash */
  }
}

const graph = createGraphController({
  container: document.getElementById('graph-container'),
  onSelect: (id) => selectNode(id),
  onBackground: () => selectNode(null),
  onContextMenu: (id, _node, pos) => showContext(id, pos),
});

const inspector = createInspector({
  onOpenNode: (id) => selectNode(id, { fly: true }),
  onExplain: async (node) => {
    inspector.setExplainText('Loading model / retrieving context…');
    try {
      const neighbors = edgesForNode(node.id)
        .map((e) => (e.from_id === node.id ? e.to_id : e.from_id))
        .map((id) => state.nodes.find((n) => n.id === id))
        .filter(Boolean);
      const { text } = await explainNode(node, neighbors, {
        onProgress: (t) => inspector.setExplainText(t),
      });
      inspector.setExplainText(text);
    } catch (err) {
      inspector.setExplainText(`Explain failed: ${err.message || err}`);
    }
  },
});

const palette = createPalette({
  getNodes: () => state.nodes,
  getEdges: () => state.edges,
  onSelectNode: (id) => selectNode(id, { fly: true }),
  onAction: (id) => runAction(id),
  onChat: async (q) => {
    try {
      const { text } = await askBrain(q);
      return text;
    } catch (err) {
      return `Chat failed: ${err.message || err}`;
    }
  },
  onTraverse: (q) => {
    const found = parseTraverse(q, state.nodes, state.edges);
    if (!found) {
      setStatus('Traverse: no match');
      return;
    }
    state.focusIds = new Set(found.ids);
    refreshVisible({ layout: false });
    selectNode(found.seedId, { fly: true });
    setStatus(`Traverse ${found.relationship || '*'} → ${found.ids.length} nodes`);
  },
});

function selectNode(id, { fly = false } = {}) {
  state.selectedId = id;
  graph.setSelection(id);
  writeHash();
  // Keep WebGL viewport in sync when the inspector reflows
  requestAnimationFrame(() => graph.resize());
  if (!id) {
    inspector.clear();
    document.getElementById('stat-visible').textContent = String(visiblePayload().nodes.length);
    return;
  }
  const node = state.nodes.find((n) => n.id === id);
  if (!node) return;
  const nodesById = new Map(state.nodes.map((n) => [n.id, n]));
  const connected = edgesForNode(id).filter((e) => {
    if (!state.rels.size) return true;
    return state.rels.has(e.relationship || 'linked');
  });
  inspector.show(node, { connected, nodesById, allEdges: state.edges });
  if (fly) graph.cameraToNode(id);
}

async function refreshVisible({ layout = false } = {}) {
  const { nodes, edges } = visiblePayload();
  document.getElementById('stat-visible').textContent = String(nodes.length);
  setStatus(layout ? `Laying out ${nodes.length} nodes…` : `${nodes.length} visible`);
  await graph.setGraphData(nodes, edges, { layout });
  graph.setColorBy(state.colorBy);
  graph.setFocusIds(state.focusIds);
  if (state.selectedId) graph.setSelection(state.selectedId);
  graph.resize();
  setStatus(`${nodes.length} visible · layout frozen`);
  writeHash();
}

function renderKindFilters() {
  const host = document.getElementById('kind-filters');
  host.innerHTML = '';
  for (const k of KINDS) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `chip ${state.kinds.has(k) ? 'active' : 'inactive'}`;
    btn.textContent = k;
    btn.addEventListener('click', () => {
      if (state.kinds.has(k)) state.kinds.delete(k);
      else state.kinds.add(k);
      btn.classList.toggle('active', state.kinds.has(k));
      btn.classList.toggle('inactive', !state.kinds.has(k));
      refreshVisible({ layout: false });
    });
    host.appendChild(btn);
  }
}

function renderRelFilters() {
  const host = document.getElementById('rel-filters');
  host.innerHTML = '';
  for (const rel of state.allRels) {
    const btn = document.createElement('button');
    btn.type = 'button';
    const on = !state.rels.size || state.rels.has(rel);
    btn.className = `chip ${on ? 'active' : 'inactive'}`;
    btn.textContent = rel;
    btn.addEventListener('click', () => {
      if (!state.rels.size) state.rels = new Set(state.allRels);
      if (state.rels.has(rel)) state.rels.delete(rel);
      else state.rels.add(rel);
      renderRelFilters();
      refreshVisible({ layout: false });
    });
    host.appendChild(btn);
  }
}

function renderViews() {
  const host = document.getElementById('views-list');
  host.innerHTML = '';
  for (const v of state.views) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'view-item';
    btn.innerHTML = `<span>${v.name}</span>${v.builtin ? '<span style="color:var(--text-muted);font-size:11px">built-in</span>' : ''}`;
    btn.addEventListener('click', () => applyView(v));
    host.appendChild(btn);
  }
}

function renderSessions() {
  const host = document.getElementById('sessions-list');
  host.innerHTML = '';
  const clear = document.createElement('button');
  clear.type = 'button';
  clear.className = 'session-item';
  clear.textContent = state.sessionFilter ? 'Clear session filter' : 'All sessions';
  clear.addEventListener('click', () => {
    state.sessionFilter = null;
    refreshVisible({ layout: false });
    renderSessions();
  });
  host.appendChild(clear);
  for (const s of state.sessions.slice(0, 40)) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `session-item${state.sessionFilter === s.session_id ? ' active' : ''}`;
    btn.innerHTML = `<div><div>${s.session_id}</div><div style="font-size:11px;color:var(--text-muted)">${s.node_count} nodes · ${(s.t_start || '').toString().slice(0, 10)}</div></div>`;
    btn.addEventListener('click', () => {
      state.sessionFilter = s.session_id;
      renderSessions();
      refreshVisible({ layout: false });
    });
    host.appendChild(btn);
  }
}

function applyView(view) {
  const s = view.state || {};
  state.kinds = new Set(s.kinds?.length ? s.kinds : KINDS);
  state.rels = new Set(s.rels || []);
  state.colorBy = s.colorBy || 'kind';
  state.showArchived = !!s.showArchived;
  state.subtype = s.subtype || null;
  state.recentDays = s.recentDays || null;
  document.getElementById('show-archived').checked = state.showArchived;
  document.getElementById('color-by').value = state.colorBy;
  renderKindFilters();
  renderRelFilters();
  graph.setColorBy(state.colorBy);
  refreshVisible({ layout: true });
  setStatus(`View: ${view.name}`);
}

async function saveCurrentView() {
  const name = window.prompt('Name this view');
  if (!name) return;
  const body = {
    name,
    state: {
      kinds: [...state.kinds],
      rels: [...state.rels],
      colorBy: state.colorBy,
      showArchived: state.showArchived,
      subtype: state.subtype,
      recentDays: state.recentDays,
      camera: graph.exportPositions(),
      selected: state.selectedId,
    },
  };
  const res = await fetch('/api/views', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    setStatus('Save view failed');
    return;
  }
  await loadViews();
  setStatus(`Saved view “${name}”`);
}

function runAction(id) {
  if (id === 'theme') {
    applyTheme(readTheme() === 'dark' ? 'light' : 'dark');
    graph.setColorBy(state.colorBy);
  } else if (id === 'relayout') {
    refreshVisible({ layout: true });
  } else if (id === 'fit') {
    graph.fitView();
  } else if (id === 'save-view') {
    saveCurrentView();
  } else if (id === 'export-json') {
    const payload = visiblePayload();
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'brainkm-graph.json';
    a.click();
  } else if (id === 'cinema') {
    location.href = '/';
  } else if (id === 'archived') {
    state.showArchived = !state.showArchived;
    document.getElementById('show-archived').checked = state.showArchived;
    refreshVisible({ layout: false });
  } else if (id === 'nav') {
    document.getElementById('shell').classList.toggle('nav-collapsed');
  } else if (id === 'inspect') {
    document.getElementById('shell').classList.toggle('inspect-collapsed');
  }
}

function showContext(id, pos) {
  const menu = document.getElementById('context-menu');
  menu.innerHTML = '';
  const actions = [
    ['Focus neighborhood', () => {
      const ids = new Set([id]);
      for (const e of edgesForNode(id)) {
        ids.add(e.from_id);
        ids.add(e.to_id);
      }
      state.focusIds = ids;
      refreshVisible({ layout: false });
      selectNode(id, { fly: true });
    }],
    ['Clear focus', () => {
      state.focusIds = null;
      refreshVisible({ layout: false });
    }],
    ['Explain', () => {
      selectNode(id);
      document.querySelector('#inspector-tabs [data-tab="explain"]').click();
      document.getElementById('btn-explain').click();
    }],
    ['Open in cinema', () => {
      location.href = `/#${encodeURIComponent(id)}`;
    }],
  ];
  for (const [label, fn] of actions) {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = label;
    b.addEventListener('click', () => {
      menu.classList.remove('visible');
      fn();
    });
    menu.appendChild(b);
  }
  menu.style.left = `${pos.x}px`;
  menu.style.top = `${pos.y}px`;
  menu.classList.add('visible');
}

document.addEventListener('click', () => {
  document.getElementById('context-menu').classList.remove('visible');
});

async function loadViews() {
  const res = await fetch('/api/views');
  const data = await res.json();
  state.views = data.views || [];
  renderViews();
}

async function loadSessions() {
  const res = await fetch('/api/sessions');
  const data = await res.json();
  state.sessions = data.sessions || [];
  renderSessions();
}

async function loadGraph() {
  const res = await fetch('/api/graph');
  const data = await res.json();
  state.nodes = data.nodes || [];
  state.edges = (data.edges || []).map((e) => ({
    ...e,
    from_id: e.from_id,
    to_id: e.to_id,
  }));
  state.allRels = [...new Set(state.edges.map((e) => e.relationship || 'linked'))].sort();
  if (!state.rels.size) {
    /* empty = all */
  }
  document.getElementById('stat-nodes').textContent = String(state.nodes.length);
  document.getElementById('stat-edges').textContent = String(state.edges.length);
  renderRelFilters();
}

async function pollVersion() {
  try {
    const res = await fetch('/api/version');
    const v = await res.json();
    const key = `${v.node_count}|${v.edge_count}|${v.max_updated}`;
    if (state.versionKey && key !== state.versionKey) {
      await loadGraph();
      await loadSessions();
      await refreshVisible({ layout: false });
    }
    state.versionKey = key;
  } catch {
    /* ignore */
  }
}

function wireChrome() {
  document.getElementById('btn-palette').addEventListener('click', () => palette.open());
  document.getElementById('btn-theme').addEventListener('click', () => runAction('theme'));
  document.getElementById('btn-nav').addEventListener('click', () => runAction('nav'));
  document.getElementById('btn-inspect').addEventListener('click', () => runAction('inspect'));
  document.getElementById('btn-fit').addEventListener('click', () => graph.fitView());
  document.getElementById('btn-relayout').addEventListener('click', () => refreshVisible({ layout: true }));
  document.getElementById('btn-save-view').addEventListener('click', () => saveCurrentView());
  document.getElementById('show-archived').addEventListener('change', (e) => {
    state.showArchived = e.target.checked;
    refreshVisible({ layout: false });
  });
  document.getElementById('color-by').addEventListener('change', (e) => {
    state.colorBy = e.target.value;
    graph.setColorBy(state.colorBy);
    writeHash();
  });
  document.getElementById('conf-min').addEventListener('input', (e) => {
    state.confMin = Number(e.target.value);
    document.getElementById('conf-min-label').textContent = `${state.confMin}%`;
    refreshVisible({ layout: false });
  });

  window.addEventListener('keydown', (e) => {
    const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName);
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      palette.toggle();
      return;
    }
    if (e.key === 'Escape') {
      if (palette.isOpen()) {
        palette.close();
        return;
      }
      if (state.focusIds) {
        state.focusIds = null;
        refreshVisible({ layout: false });
        return;
      }
      selectNode(null);
    }
    if (!typing && e.key === '/') {
      e.preventDefault();
      palette.open();
    }
  });

  window.addEventListener('resize', () => {
    graph.resize();
  });
}

async function boot() {
  initTheme();
  wireChrome();
  readHash();
  document.getElementById('show-archived').checked = state.showArchived;
  document.getElementById('color-by').value = state.colorBy;
  document.getElementById('conf-min').value = String(state.confMin);
  document.getElementById('conf-min-label').textContent = `${state.confMin}%`;
  renderKindFilters();

  try {
    loadingText.textContent = 'Fetching graph…';
    await loadGraph();
    await Promise.all([loadViews(), loadSessions()]);
    loadingText.textContent = `Layout ${state.nodes.length} nodes…`;
    await refreshVisible({ layout: true });
    if (state.selectedId) selectNode(state.selectedId, { fly: true });
    graph.resize();
    loading.classList.add('hidden');
    setTimeout(() => loading.remove(), 400);
    setInterval(pollVersion, VERSION_POLL_MS);
  } catch (err) {
    loadingText.textContent = `Error: ${err.message || err}`;
    loadingText.style.color = 'var(--danger)';
    console.error(err);
  }
}

boot();
