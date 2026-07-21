/**
 * MemNetwork Neural Cosmos — graph UI (ES module, no build step).
 */
import { createChatController } from './chat.js';

/** Append ?token= from the page URL so /api calls pass viz auth. */
function withAuth(path) {
  const token = new URLSearchParams(window.location.search).get('token');
  if (!token) return path;
  const url = new URL(path, window.location.origin);
  url.searchParams.set('token', token);
  return url.pathname + url.search;
}

const KIND_COLORS = {
  memory: '#8b5cf6',
  code: '#06b6d4',
  procedure: '#f59e0b',
  session: '#10b981',
  commit: '#e11d48',
};
const CODE_SUBTYPE_COLORS = {
  file: '#06b6d4',
  module: '#06b6d4',
  class: '#6366f1',
  function: '#f472b6',
};
const MEMORY_SUBTYPE_COLORS = {
  fact: '#c4b5fd',
  decision: '#f97316',
  rule: '#eab308',
  error: '#ef4444',
  pattern: '#d946ef',
  context: '#14b8a6',
  pivot: '#fb7185',
};
const KIND_DEFAULT = '#6b7280';
const SELECTED_COLOR = '#fbbf24';
const FORCE_CHARGE = -120;
const LARGE_GRAPH_THRESHOLD = 3000;
const VERSION_POLL_MS = 5000;

const DIR_PALETTE = [
  '#06b6d4', '#8b5cf6', '#f59e0b', '#10b981', '#f472b6',
  '#6366f1', '#14b8a6', '#fb7185', '#a78bfa', '#38bdf8',
];
const TAG_PALETTE = DIR_PALETTE;

const REL_COLORS = {
  supersedes: '#f87171',
  calls: '#06b6d4',
  imports: '#38bdf8',
  influences: '#8b5cf6',
  constrains: '#c084fc',
  spawned: '#f59e0b',
  produced: '#10b981',
  supports: '#34d399',
  related_to: '#94a3b8',
  targets: '#fbbf24',
  co_activated: '#fb923c',
};

/**
 * Map stored edge weight → ~0..1 for layout/line width.
 * Code edges are usually ≤1; co_activated weights are co-hit *counts* (often 2–20+).
 * Using raw counts as force distance / line width collapses nodes into a glowing tube.
 */
function visualWeight(e) {
  const w = Number(e?.weight);
  if (!Number.isFinite(w) || w <= 0) return 0.4;
  if (e.relationship === 'co_activated' || w > 1.5) {
    // log2(1+15)/5 ≈ 0.8 — stronger co-hits look a bit thicker, never extreme
    return Math.min(1, Math.log2(1 + w) / 5);
  }
  return Math.min(1, Math.max(0.05, w));
}

const FORCE_LINK_DISTANCE = (e) => 55 + (1 - visualWeight(e)) * 45;

// ── State ────────────────────────────────────────────────────
let allNodes = [];
let allEdges = [];
let activeKinds = new Set(['memory', 'code', 'procedure', 'session', 'commit']);
let activeRels = new Set();
let searchQuery = '';
let searchHits = [];
let searchHitIndex = -1;
let timelineCutoff = null;
let selectedId = null;
let focusId = null;
let focusDepth = 1;
let showArchived = false;
let colorMode = 'kind';
let graph = null;
let motionPaused = false;
let reducedEffects = false;
let selectedNeighborIds = null;
let graphVersion = null;
let lastPositions = new Map();

const chat = createChatController({
  getNodeById: (id) => allNodes.find((n) => n.id === id),
  onCite: (id) => {
    const node = allNodes.find((n) => n.id === id);
    if (node) {
      openDetail(node);
      flyToNode(node);
    }
  },
  onExplainDone: () => {},
});

// ── Color helpers ────────────────────────────────────────────
const getColor = (k) => KIND_COLORS[k] || KIND_DEFAULT;

function hashHue(str) {
  let h = 0;
  for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) >>> 0;
  return h;
}

function topDirectory(path) {
  if (!path) return '(no path)';
  const parts = String(path).replace(/\\/g, '/').split('/').filter(Boolean);
  return parts[0] || '(no path)';
}

function firstTag(tags) {
  if (!tags) return '(untagged)';
  const t = String(tags).split(',').map((s) => s.trim()).filter(Boolean);
  return t[0] || '(untagged)';
}

function getNodeColor(node) {
  if (colorMode === 'directory') {
    const key = topDirectory(node.path || (node.kind === 'code' ? node.title : null));
    return DIR_PALETTE[hashHue(key) % DIR_PALETTE.length];
  }
  if (colorMode === 'tag') {
    const key = firstTag(node.tags);
    return TAG_PALETTE[hashHue(key) % TAG_PALETTE.length];
  }
  if (node?.kind === 'code' && node.subtype && CODE_SUBTYPE_COLORS[node.subtype]) {
    return CODE_SUBTYPE_COLORS[node.subtype];
  }
  if (node?.kind === 'memory' && node.subtype && MEMORY_SUBTYPE_COLORS[node.subtype]) {
    return MEMORY_SUBTYPE_COLORS[node.subtype];
  }
  return getColor(node?.kind);
}

function nodeSize(n) {
  const min = 8;
  const max = 18;
  return Math.min(min + Math.log1p(n.use_count || 0) * 2.5, max);
}

function edgeId(v) {
  return v && typeof v === 'object' ? v.id : v;
}

function linkColorFor(e, highlighted = false) {
  const w = visualWeight(e);
  const alpha = highlighted
    ? 'ff'
    : Math.floor(Math.min(40 + w * 120, 160)).toString(16).padStart(2, '0');
  const base = REL_COLORS[e.relationship] || '#94a3b8';
  return base + alpha;
}

function linkWidthFor(e, highlighted = false) {
  const w = visualWeight(e);
  return highlighted ? 0.9 + w * 1.6 : 0.35 + w * 1.0;
}

function adjacency() {
  const map = new Map();
  for (const e of allEdges) {
    const s = edgeId(e.source);
    const t = edgeId(e.target);
    if (!map.has(s)) map.set(s, new Set());
    if (!map.has(t)) map.set(t, new Set());
    map.get(s).add(t);
    map.get(t).add(s);
  }
  return map;
}

function neighborhoodIds(seedId, depth) {
  const adj = adjacency();
  const seen = new Set([seedId]);
  let frontier = [seedId];
  for (let d = 0; d < depth; d++) {
    const next = [];
    for (const id of frontier) {
      for (const n of adj.get(id) || []) {
        if (!seen.has(n)) {
          seen.add(n);
          next.push(n);
        }
      }
    }
    frontier = next;
  }
  return seen;
}

function isNeighbourOf(nodeId, focus) {
  if (focus === selectedId && selectedNeighborIds) {
    return selectedNeighborIds.has(nodeId);
  }
  return allEdges.some(
    (e) =>
      (edgeId(e.source) === focus && edgeId(e.target) === nodeId) ||
      (edgeId(e.target) === focus && edgeId(e.source) === nodeId),
  );
}

function setSelection(nodeId) {
  selectedId = nodeId;
  if (!nodeId) {
    selectedNeighborIds = null;
    return;
  }
  const neigh = new Set([nodeId]);
  for (const e of allEdges) {
    const s = edgeId(e.source);
    const t = edgeId(e.target);
    if (s === nodeId) neigh.add(t);
    else if (t === nodeId) neigh.add(s);
  }
  selectedNeighborIds = neigh;
}

function linkTouchesSelection(e) {
  if (!selectedId) return true;
  return edgeId(e.source) === selectedId || edgeId(e.target) === selectedId;
}

/** Visual-only selection — no graphData rebuild. */
function paintSelection() {
  if (!graph) return;
  updateAllNodeVisuals();
  const highlighted = !!selectedId;
  graph
    .linkVisibility((e) => !selectedId || linkTouchesSelection(e))
    .linkColor((e) => linkColorFor(e, highlighted && linkTouchesSelection(e)))
    .linkWidth((e) => linkWidthFor(e, highlighted && linkTouchesSelection(e)))
    .linkOpacity(highlighted ? 1.0 : 0.8);
  if (typeof graph.linkDirectionalParticles === 'function') {
    graph
      .linkDirectionalParticles(reducedEffects ? 0 : (e) => {
        if (!highlighted) return visualWeight(e) > 0.75 ? 2 : 1;
        return linkTouchesSelection(e) ? 2 : 0;
      })
      .linkDirectionalParticleWidth((e) => (highlighted ? 1.6 : 1.0 + visualWeight(e) * 0.6))
      .linkDirectionalParticleColor((e) => REL_COLORS[e.relationship] || '#94a3b8');
  }
}

function edgesForNode(nodeId) {
  return allEdges.filter(
    (e) => edgeId(e.source) === nodeId || edgeId(e.target) === nodeId,
  );
}

function nodeVisualState(node) {
  const base = getNodeColor(node);
  const isArchived = !!node.valid_until;

  if (selectedId) {
    if (node.id === selectedId) {
      return { color: SELECTED_COLOR, opacity: 1, emissiveIntensity: 0.95, haloOpacity: 0.2 };
    }
    if (isNeighbourOf(node.id, selectedId)) {
      return { color: base, opacity: 1, emissiveIntensity: 0.88, haloOpacity: 0.14 };
    }
    return { color: base, opacity: 0.18, emissiveIntensity: 0.08, haloOpacity: 0 };
  }

  if (searchQuery && !matchesSearch(node)) {
    return { color: base, opacity: 0.15, emissiveIntensity: 0.08, haloOpacity: 0 };
  }

  return {
    color: base,
    opacity: isArchived ? 0.3 : 1,
    emissiveIntensity: isArchived ? 0.2 : 0.6,
    haloOpacity: reducedEffects || isArchived ? 0 : 0.08,
  };
}

function applyNodeVisual(obj, node) {
  if (!obj?.children?.length) return;
  const v = nodeVisualState(node);
  for (const child of obj.children) {
    if (child.userData?.role === 'core' && child.material) {
      child.material.color.set(v.color);
      child.material.emissive.set(v.color);
      child.material.emissiveIntensity = v.emissiveIntensity;
      child.material.opacity = v.opacity;
    }
    if (child.userData?.role === 'halo' && child.material) {
      child.material.color.set(v.color);
      child.material.opacity = v.haloOpacity;
      child.visible = v.haloOpacity > 0;
    }
  }
}

function freezeSimulation() {
  if (!graph) return;
  graph.cooldownTicks?.(0);
  graph.d3Force?.('charge')?.strength?.(0);
  graph.d3Force?.('link')?.strength?.(0);
}

function unfreezeSimulation() {
  if (!graph) return;
  graph.d3Force?.('charge')?.strength?.(FORCE_CHARGE);
  graph.d3Force?.('link')?.strength?.(1);
  graph.d3Force?.('link')?.distance?.(FORCE_LINK_DISTANCE);
  graph.cooldownTicks?.(Infinity);
  graph.d3ReheatSimulation?.();
}

function updateAllNodeVisuals() {
  if (!graph) return;
  graph.graphData().nodes.forEach((n) => {
    const obj = n.__vizObj || n.__threeObj;
    if (obj) applyNodeVisual(obj, n);
  });
}

function buildNodeObject(n) {
  const group = new THREE.Group();
  const v = nodeVisualState(n);
  const size = nodeSize(n);

  const geo = new THREE.SphereGeometry(size, reducedEffects ? 8 : 16, reducedEffects ? 8 : 16);
  const mat = new THREE.MeshStandardMaterial({
    color: v.color,
    emissive: v.color,
    emissiveIntensity: v.emissiveIntensity,
    transparent: true,
    opacity: v.opacity,
    roughness: 0.2,
    metalness: 0.3,
  });
  const core = new THREE.Mesh(geo, mat);
  core.userData.role = 'core';
  group.add(core);

  if (!reducedEffects) {
    const haloGeo = new THREE.SphereGeometry(size * 1.6, 16, 16);
    const haloMat = new THREE.MeshBasicMaterial({
      color: v.color,
      transparent: true,
      opacity: v.haloOpacity,
      side: THREE.BackSide,
    });
    const halo = new THREE.Mesh(haloGeo, haloMat);
    halo.userData.role = 'halo';
    halo.visible = v.haloOpacity > 0;
    group.add(halo);
  }

  if (n.user_pinned) {
    const ringGeo = new THREE.TorusGeometry(size * 1.5, 0.8, 8, 32);
    const ringMat = new THREE.MeshBasicMaterial({ color: '#fbbf24', transparent: true, opacity: 0.9 });
    const ring = new THREE.Mesh(ringGeo, ringMat);
    ring.rotation.x = Math.PI / 2;
    ring.userData.role = 'ring';
    group.add(ring);
  }

  n.__vizObj = group;
  return group;
}

// ── Motion ───────────────────────────────────────────────────
const motionToggleBtn = document.getElementById('motion-toggle');
const motionToggleIcon = document.getElementById('motion-toggle-icon');
const motionToggleLabel = document.getElementById('motion-toggle-label');

function setMotionPaused(paused) {
  motionPaused = paused;
  if (graph) {
    const controls = graph.controls?.();
    if (controls) controls.autoRotate = !paused;
    if (paused) freezeSimulation();
    else unfreezeSimulation();
  }
  motionToggleBtn.classList.toggle('active', paused);
  motionToggleIcon.textContent = paused ? '▶' : '⏸';
  motionToggleLabel.textContent = paused ? 'Play' : 'Pause';
}

motionToggleBtn.addEventListener('click', () => setMotionPaused(!motionPaused));

// ── Tooltip ──────────────────────────────────────────────────
const tooltip = document.getElementById('tooltip');
const tooltipTitle = document.getElementById('tooltip-title');
const tooltipKind = document.getElementById('tooltip-kind');

function showTooltip(node, x, y) {
  tooltipTitle.textContent = node.title;
  tooltipKind.textContent = `${node.kind}${node.subtype ? ' · ' + node.subtype : ''}`;
  tooltipTitle.style.color = nodeVisualState(node).color;
  tooltip.style.left = `${x}px`;
  tooltip.style.top = `${y}px`;
  tooltip.classList.add('visible');
}

function hideTooltip() {
  tooltip.classList.remove('visible');
}

window.addEventListener('mousemove', (e) => {
  if (tooltip.classList.contains('visible')) {
    tooltip.style.left = `${e.clientX + 14}px`;
    tooltip.style.top = `${e.clientY - 20}px`;
  }
});

// ── Detail panel ─────────────────────────────────────────────
const detailPanel = document.getElementById('detail-panel');
const detailClose = document.getElementById('detail-close');
const detailBadge = document.getElementById('detail-kind-badge');
const detailTitle = document.getElementById('detail-title');
const detailMeta = document.getElementById('detail-meta');
const detailContent = document.getElementById('detail-content');
const detailConns = document.getElementById('detail-connections');

function clearSelection() {
  detailPanel.classList.remove('open');
  setSelection(null);
  document.getElementById('stat-links-wrap').style.display = 'none';
  paintSelection();
}

detailClose.addEventListener('click', clearSelection);

function renderDetailBadge(node) {
  const kindColor = getColor(node.kind);
  const kindLabel = node.kind.toUpperCase();
  if (node.subtype) {
    const subtypeColor = getNodeColor(node);
    detailBadge.innerHTML =
      `<span style="color:${kindColor}">${kindLabel}</span>` +
      `<span class="detail-kind-sep"> · </span>` +
      `<span style="color:${subtypeColor}">${node.subtype.toUpperCase()}</span>`;
    detailBadge.style.background = `${kindColor}22`;
    detailBadge.style.border = `1px solid ${kindColor}44`;
    return;
  }
  detailBadge.textContent = kindLabel;
  detailBadge.style.background = `${kindColor}22`;
  detailBadge.style.color = kindColor;
  detailBadge.style.border = `1px solid ${kindColor}44`;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function openDetail(node) {
  setSelection(node.id);
  const isArchived = !!node.valid_until;
  renderDetailBadge(node);
  detailTitle.innerHTML =
    escapeHtml(node.title) + (isArchived ? '<span class="archived-badge">ARCHIVED</span>' : '');

  const pills = [];
  if (node.confidence != null) pills.push(`conf ${(node.confidence * 100).toFixed(0)}%`);
  if (node.use_count) pills.push(`↑ ${node.use_count} uses`);
  if (node.user_pinned) pills.push('📌 pinned');
  if (node.path) {
    const href = `cursor://file/${encodeURI(node.path)}`;
    pills.push(`<a href="${href}" title="Open in editor">${escapeHtml(node.path)}</a>`);
  }
  if (node.source) pills.push(`src ${escapeHtml(node.source)}`);
  if (node.session_id) pills.push(`sess ${escapeHtml(node.session_id)}`);
  if (node.created_at) pills.push(`created ${escapeHtml(String(node.created_at).slice(0, 10))}`);
  if (node.updated_at) pills.push(`updated ${escapeHtml(String(node.updated_at).slice(0, 10))}`);
  if (node.tags) {
    node.tags.split(',').forEach((t) => t.trim() && pills.push(escapeHtml(t.trim())));
  }
  detailMeta.innerHTML = pills.map((p) => `<span class="meta-pill">${p}</span>`).join('');
  detailContent.textContent = node.content || '(no content)';

  const connected = edgesForNode(node.id);
  const nodeById = Object.fromEntries(allNodes.map((n) => [n.id, n]));
  if (connected.length === 0) {
    detailConns.innerHTML = '<div style="font-size:12px;color:var(--text-muted)">No connections.</div>';
  } else {
    const groups = new Map();
    for (const e of connected) {
      const rel = e.relationship || 'linked';
      if (!groups.has(rel)) groups.set(rel, []);
      groups.get(rel).push(e);
    }
    let html = '';
    for (const [rel, edges] of [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
      html += `<div class="conn-group-title">${escapeHtml(rel)} (${edges.length})</div>`;
      html += edges
        .map((e) => {
          const srcId = edgeId(e.source);
          const otherId = srcId === node.id ? edgeId(e.target) : srcId;
          const other = nodeById[otherId] || {};
          const ocolor = getNodeColor(other);
          const dir = srcId === node.id ? '→' : '←';
          return `
            <div class="conn-item" data-id="${escapeHtml(otherId)}">
              <div class="conn-dot" style="background:${ocolor}"></div>
              <div>
                <div class="conn-title" style="color:${ocolor}">${escapeHtml(other.title || otherId)}</div>
                <div class="conn-rel">${dir} weight ${(e.weight || 1).toFixed(0)}${e.relationship === 'co_activated' ? ' co-hits' : ''}</div>
              </div>
            </div>`;
        })
        .join('');
    }
    detailConns.innerHTML = html;
    detailConns.querySelectorAll('.conn-item').forEach((el) => {
      el.addEventListener('click', () => {
        const target = allNodes.find((n) => n.id === el.dataset.id);
        if (target) {
          openDetail(target);
          flyToNode(target);
        }
      });
    });
  }

  detailPanel.classList.add('open');
  syncDetailChatLayout();
  document.getElementById('stat-links').textContent = connected.length;
  document.getElementById('stat-links-wrap').style.display = '';
  paintSelection();
}

document.getElementById('explain-btn').addEventListener('click', () => {
  if (!selectedId) return;
  const node = allNodes.find((n) => n.id === selectedId);
  if (!node) return;
  const neighbors = edgesForNode(node.id).map((e) => {
    const otherId = edgeId(e.source) === node.id ? edgeId(e.target) : edgeId(e.source);
    return allNodes.find((n) => n.id === otherId);
  }).filter(Boolean);
  chat.open();
  chat.explainNode(node, neighbors);
});

function syncDetailChatLayout() {
  const chatOpen = document.getElementById('chat-panel').classList.contains('open');
  detailPanel.classList.toggle('with-chat', chatOpen);
}

// ── Filters ──────────────────────────────────────────────────
function matchesSearch(node) {
  if (!searchQuery) return true;
  const q = searchQuery.toLowerCase();
  const haystack = `${node.title} ${node.tags || ''} ${node.content || ''} ${node.path || ''}`.toLowerCase();
  return haystack.includes(q);
}

function isVisible(node) {
  if (!activeKinds.has(node.kind)) return false;
  if (!showArchived && node.valid_until) return false;
  if (timelineCutoff && node.valid_from && node.valid_from > timelineCutoff) return false;
  if (searchQuery && !matchesSearch(node)) return false;
  if (focusId) {
    const ids = neighborhoodIds(focusId, focusDepth);
    if (!ids.has(node.id)) return false;
  }
  return true;
}

function visibleNodes() {
  return allNodes.filter(isVisible);
}

function visibleEdges(visSet) {
  return allEdges.filter((e) => {
    const src = edgeId(e.source);
    const tgt = edgeId(e.target);
    if (!visSet.has(src) || !visSet.has(tgt)) return false;
    const rel = e.relationship || 'linked';
    if (activeRels.size && !activeRels.has(rel)) return false;
    return true;
  });
}

function applyLinkStyles(highlighted) {
  if (!graph) return;
  const particles = reducedEffects ? 0 : highlighted ? 2 : 1;
  graph
    .linkColor((e) => linkColorFor(e, highlighted))
    .linkWidth((e) => linkWidthFor(e, highlighted))
    .linkOpacity(highlighted ? 1.0 : 0.8);
  if (typeof graph.linkDirectionalParticles === 'function') {
    graph
      .linkDirectionalParticles(reducedEffects ? 0 : (e) => (highlighted ? 2 : visualWeight(e) > 0.75 ? 2 : particles))
      .linkDirectionalParticleWidth((e) => (highlighted ? 1.6 : 1.0 + visualWeight(e) * 0.6))
      .linkDirectionalParticleColor((e) => REL_COLORS[e.relationship] || '#94a3b8');
  }
}

function savePositions() {
  if (!graph) return;
  lastPositions.clear();
  for (const n of graph.graphData().nodes || []) {
    if (n.x != null) {
      lastPositions.set(n.id, { x: n.x, y: n.y, z: n.z });
    }
  }
}

function restorePositions(nodes) {
  for (const n of nodes) {
    const p = lastPositions.get(n.id);
    if (p) {
      n.x = p.x;
      n.y = p.y;
      if (p.z != null) n.z = p.z;
    }
  }
}

function refreshGraph({ preserve = true } = {}) {
  if (!graph) return;
  if (preserve) savePositions();
  const vnodes = visibleNodes();
  restorePositions(vnodes);
  const visSet = new Set(vnodes.map((n) => n.id));
  const vedges = visibleEdges(visSet);
  graph.graphData({ nodes: vnodes, links: vedges });
  if (motionPaused) freezeSimulation();
  document.getElementById('stat-visible').textContent = vnodes.length;
  paintSelection();
}

function updateCounts() {
  ['memory', 'code', 'procedure', 'session', 'commit'].forEach((k) => {
    document.getElementById(`count-${k}`).textContent =
      allNodes.filter((n) => n.kind === k && (showArchived || !n.valid_until)).length;
  });
  document.getElementById('stat-nodes').textContent = allNodes.length;
  document.getElementById('stat-edges').textContent = allEdges.length;
  document.getElementById('stat-visible').textContent = visibleNodes().length;
}

function rebuildEdgeFilters() {
  const rels = [...new Set(allEdges.map((e) => e.relationship || 'linked'))].sort();
  if (!activeRels.size) activeRels = new Set(rels);
  const host = document.getElementById('edge-filters');
  host.innerHTML = '';
  for (const rel of rels) {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = `filter-chip ${activeRels.has(rel) ? 'active' : 'inactive'}`;
    chip.textContent = rel;
    chip.style.borderColor = (REL_COLORS[rel] || '#94a3b8') + '66';
    chip.addEventListener('click', () => {
      if (activeRels.has(rel)) activeRels.delete(rel);
      else activeRels.add(rel);
      chip.classList.toggle('active', activeRels.has(rel));
      chip.classList.toggle('inactive', !activeRels.has(rel));
      refreshGraph();
    });
    host.appendChild(chip);
  }
}

function initTimeline() {
  const dates = allNodes.map((n) => n.valid_from).filter(Boolean).sort();
  if (!dates.length) return;
  const minDate = dates[0];
  const maxDate = dates[dates.length - 1];
  document.getElementById('timeline-min').textContent = minDate.slice(0, 10);
  document.getElementById('timeline-max').textContent = maxDate.slice(0, 10);
  const slider = document.getElementById('timeline-slider');
  slider.oninput = () => {
    const pct = slider.value / 100;
    const minT = new Date(minDate).getTime();
    const maxT = new Date(maxDate).getTime();
    const cutDate = new Date(minT + (maxT - minT) * pct);
    timelineCutoff = cutDate.toISOString();
    document.getElementById('timeline-value').textContent =
      pct >= 0.999 ? 'All time' : cutDate.toISOString().slice(0, 10);
    if (pct >= 0.999) timelineCutoff = null;
    refreshGraph();
  };
}

function updateFocusBar() {
  const bar = document.getElementById('focus-bar');
  if (focusId) {
    const node = allNodes.find((n) => n.id === focusId);
    bar.classList.add('visible');
    document.getElementById('focus-label').textContent =
      `Focus: ${node?.title || focusId} · depth ${focusDepth}`;
  } else {
    bar.classList.remove('visible');
  }
}

function enterFocus(nodeId) {
  focusId = nodeId;
  updateFocusBar();
  refreshGraph();
}

function exitFocus() {
  focusId = null;
  updateFocusBar();
  refreshGraph();
}

document.getElementById('focus-exit').addEventListener('click', exitFocus);
document.getElementById('focus-depth').addEventListener('input', (e) => {
  focusDepth = Number(e.target.value);
  document.getElementById('focus-depth-label').textContent = String(focusDepth);
  if (focusId) refreshGraph();
  updateFocusBar();
});

document.getElementById('show-archived').addEventListener('change', (e) => {
  showArchived = e.target.checked;
  updateCounts();
  refreshGraph();
});

document.getElementById('color-mode').addEventListener('change', (e) => {
  colorMode = e.target.value;
  paintSelection();
});

// ── Graph create / destroy ───────────────────────────────────
function destroyGraph() {
  savePositions();
  if (graph) {
    try {
      graph._destructor?.();
      graph.pauseAnimation?.();
    } catch {
      /* ignore */
    }
    graph = null;
  }
  const container = document.getElementById('graph-container');
  container.innerHTML = '';
}

function flyToNode(node) {
  if (!graph || !node || typeof graph.cameraPosition !== 'function') return;
  const dist = 180;
  graph.cameraPosition(
    { x: (node.x || 0) + dist, y: (node.y || 0) + dist / 2, z: (node.z || 0) + dist },
    node,
    800,
  );
}

function createGraph3D(container) {
  graph = ForceGraph3D({ controlType: 'orbit' })(container)
    .width(window.innerWidth)
    .height(window.innerHeight)
    .backgroundColor('#050508')
    .numDimensions(3)
    .nodeVal((n) => {
      const s = nodeSize(n);
      return s * s;
    })
    .nodeColor((n) => getNodeColor(n))
    .nodeOpacity(0.95)
    .nodeResolution(reducedEffects ? 8 : 16)
    .nodeThreeObject(buildNodeObject)
    .nodeThreeObjectExtend(false)
    .linkColor((e) => linkColorFor(e, false))
    .linkWidth((e) => linkWidthFor(e, false))
    .linkOpacity(0.8)
    .linkDirectionalParticles(reducedEffects ? 0 : (e) => (visualWeight(e) > 0.75 ? 2 : 1))
    .linkDirectionalParticleWidth((e) => 1.0 + visualWeight(e) * 0.6)
    .linkDirectionalParticleSpeed(0.004)
    .linkDirectionalParticleColor((e) => REL_COLORS[e.relationship] || '#94a3b8')
    .onNodeHover((node) => {
      container.style.cursor = node ? 'pointer' : 'default';
      if (node) showTooltip(node, window.innerWidth / 2, window.innerHeight / 2);
      else hideTooltip();
    })
    .onNodeClick((node) => {
      hideTooltip();
      openDetail(node);
    })
    .onBackgroundClick(() => clearSelection());

  const scene = graph.scene();
  scene.add(new THREE.AmbientLight(0xffffff, 0.3));
  if (!reducedEffects) {
    const ptLight1 = new THREE.PointLight(0x8b5cf6, 2, 400);
    ptLight1.position.set(100, 100, 100);
    scene.add(ptLight1);
    const ptLight2 = new THREE.PointLight(0x06b6d4, 1.5, 400);
    ptLight2.position.set(-100, -80, -100);
    scene.add(ptLight2);
    const starGeo = new THREE.BufferGeometry();
    const starCount = 1500;
    const positions = new Float32Array(starCount * 3);
    for (let i = 0; i < starCount; i++) {
      positions[i * 3] = (Math.random() - 0.5) * 2000;
      positions[i * 3 + 1] = (Math.random() - 0.5) * 2000;
      positions[i * 3 + 2] = (Math.random() - 0.5) * 2000;
    }
    starGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    scene.add(
      new THREE.Points(
        starGeo,
        new THREE.PointsMaterial({ color: 0xffffff, size: 0.6, transparent: true, opacity: 0.5 }),
      ),
    );
  }

  graph.controls().autoRotate = true;
  graph.controls().autoRotateSpeed = 0.4;
  graph.controls().enableDamping = true;

  container.addEventListener('dblclick', () => {
    if (selectedId) enterFocus(selectedId);
  });
}

function createGraph() {
  const container = document.getElementById('graph-container');
  createGraph3D(container);

  graph.d3Force?.('charge')?.strength?.(FORCE_CHARGE);
  graph.d3Force?.('link')?.distance?.(FORCE_LINK_DISTANCE);

  setMotionPaused(motionPaused);
  refreshGraph({ preserve: true });
}

function applyPerfGuard(nodeCount) {
  const hint = document.getElementById('perf-hint');
  if (nodeCount > LARGE_GRAPH_THRESHOLD) {
    reducedEffects = true;
    hint.textContent =
      `Large graph (${nodeCount} nodes) — reduced visual effects for performance.`;
    hint.classList.add('visible');
  } else {
    reducedEffects = false;
    hint.classList.remove('visible');
  }
}

// ── Data load / merge / poll ─────────────────────────────────
function ingestGraphData(data, { merge = false } = {}) {
  if (merge) savePositions();
  allNodes = (data.nodes || []).map((n) => ({ ...n }));
  allEdges = (data.edges || []).map((e) => ({
    ...e,
    source: e.from_id ?? e.source,
    target: e.to_id ?? e.target,
  }));
  rebuildEdgeFilters();
  updateCounts();
  if (!merge) initTimeline();
  if (graph) refreshGraph({ preserve: merge });
}

async function fetchGraph() {
  const res = await fetch(withAuth('/api/graph'));
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function fetchVersion() {
  const res = await fetch(withAuth('/api/version'));
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function versionKey(v) {
  return `${v.node_count}|${v.edge_count}|${v.max_updated}`;
}

async function pollVersion() {
  try {
    const v = await fetchVersion();
    const key = versionKey(v);
    if (graphVersion && key !== graphVersion) {
      const data = await fetchGraph();
      ingestGraphData(data, { merge: true });
    }
    graphVersion = key;
  } catch (err) {
    console.warn('version poll failed', err);
  }
}

// ── Search hits cycling ──────────────────────────────────────
function recomputeSearchHits() {
  if (!searchQuery) {
    searchHits = [];
    searchHitIndex = -1;
    return;
  }
  searchHits = visibleNodes().filter(matchesSearch);
  searchHitIndex = searchHits.length ? 0 : -1;
}

function cycleSearchHit(delta) {
  if (!searchHits.length) return;
  searchHitIndex = (searchHitIndex + delta + searchHits.length) % searchHits.length;
  const node = searchHits[searchHitIndex];
  openDetail(node);
  flyToNode(node);
}

// ── Kind filters + search ────────────────────────────────────
document.querySelectorAll('.kind-toggle').forEach((el) => {
  el.addEventListener('click', () => {
    const k = el.dataset.kind;
    if (activeKinds.has(k)) {
      activeKinds.delete(k);
      el.classList.remove('active');
      el.classList.add('inactive');
    } else {
      activeKinds.add(k);
      el.classList.remove('inactive');
      el.classList.add('active');
    }
    refreshGraph();
  });
});

let searchDebounce;
document.getElementById('search-input').addEventListener('input', (e) => {
  clearTimeout(searchDebounce);
  searchDebounce = setTimeout(() => {
    searchQuery = e.target.value.trim();
    recomputeSearchHits();
    refreshGraph();
  }, 200);
});

document.addEventListener('keydown', (e) => {
  const tag = e.target.tagName;
  const typing = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';

  if (e.code === 'Space' && !typing) {
    e.preventDefault();
    setMotionPaused(!motionPaused);
    return;
  }
  if (e.key === '/' && !typing) {
    e.preventDefault();
    document.getElementById('search-input').focus();
    return;
  }
  if (e.key === 'Escape') {
    if (document.activeElement === document.getElementById('search-input')) {
      document.getElementById('search-input').blur();
      searchQuery = '';
      document.getElementById('search-input').value = '';
      recomputeSearchHits();
      refreshGraph();
      return;
    }
    if (focusId) {
      exitFocus();
      return;
    }
    clearSelection();
    return;
  }
  if (!typing && (e.key === 'ArrowDown' || e.key === 'ArrowUp') && searchHits.length) {
    e.preventDefault();
    cycleSearchHit(e.key === 'ArrowDown' ? 1 : -1);
  }
});

window.addEventListener('resize', () => {
  if (graph) graph.width(window.innerWidth).height(window.innerHeight);
});

// ── Boot ─────────────────────────────────────────────────────
async function boot() {
  const loading = document.getElementById('loading');
  const loadText = document.getElementById('loading-text');
  chat.bindUi({ onOpenChange: syncDetailChatLayout });

  try {
    loadText.textContent = 'Fetching neuron graph…';
    const [data, version] = await Promise.all([fetchGraph(), fetchVersion()]);
    graphVersion = versionKey(version);

    applyPerfGuard(data.nodes.length);
    loadText.textContent = `Building cosmos — ${data.nodes.length} neurons…`;
    await new Promise((r) => setTimeout(r, 200));

    ingestGraphData(data, { merge: false });
    createGraph();

    loading.classList.add('hidden');
    setTimeout(() => loading.remove(), 600);
    setInterval(pollVersion, VERSION_POLL_MS);
  } catch (err) {
    loadText.textContent = `Error: ${err.message}`;
    loadText.style.color = '#f87171';
    console.error(err);
  }
}

boot();
