/**
 * Sigma + graphology canvas controller for Mission Control.
 */
import Graph from 'graphology';
import Sigma from 'sigma';

const KIND_FALLBACK = {
  memory: '#8b5cf6',
  code: '#06b6d4',
  procedure: '#f59e0b',
  session: '#10b981',
};

const DIR_PALETTE = [
  '#06b6d4', '#8b5cf6', '#f59e0b', '#10b981', '#f472b6',
  '#6366f1', '#14b8a6', '#fb7185', '#a78bfa', '#38bdf8',
];

function cssToken(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

function hashHue(str) {
  let h = 0;
  for (let i = 0; i < String(str).length; i++) h = (h * 31 + str.charCodeAt(i)) >>> 0;
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

function visualEdgeWeight(w) {
  const n = Number(w);
  if (!Number.isFinite(n) || n <= 0) return 0.4;
  if (n > 1.5) return Math.min(1, Math.log2(1 + n) / 5);
  return Math.min(1, Math.max(0.05, n));
}

export function createGraphController({
  container,
  onSelect,
  onHover,
  onContextMenu,
  onBackground,
}) {
  const graph = new Graph({ multi: false, type: 'undirected', allowSelfLoops: false });
  let sigma = null;
  let selectedId = null;
  let hoverId = null;
  let focusIds = null;
  let colorBy = 'kind';
  let positionsCache = new Map();
  let nodeMeta = new Map();
  let worker = null;
  let layoutGen = 0;
  let suppressStageClick = false;
  let resizeObserver = null;

  function nodeColor(n) {
    if (colorBy === 'directory') {
      return DIR_PALETTE[hashHue(topDirectory(n.path || n.title)) % DIR_PALETTE.length];
    }
    if (colorBy === 'tag') {
      return DIR_PALETTE[hashHue(firstTag(n.tags)) % DIR_PALETTE.length];
    }
    const kind = n.kind || 'memory';
    return cssToken(`--${kind}`, KIND_FALLBACK[kind] || '#6b7280');
  }

  function nodeSize(n, degree) {
    const base = 3 + Math.min(8, Math.log1p(n.use_count || 0) * 1.4);
    return base + Math.min(4, Math.sqrt(degree || 0) * 0.35);
  }

  function ensureSigma() {
    if (sigma) return sigma;
    sigma = new Sigma(graph, container, {
      allowInvalidContainer: true,
      renderLabels: true,
      labelDensity: 0.07,
      labelRenderedSizeThreshold: 6,
      defaultEdgeColor: cssToken('--edge', '#64748b'),
      defaultNodeColor: cssToken('--text-muted', '#9aa3b5'),
      zIndex: true,
    });

    sigma.setSetting('nodeReducer', (node, data) => {
      const res = { ...data };
      try {
        const focused = !focusIds || focusIds.has(node);
        const selected = node === selectedId;
        if (!focused) {
          res.color = cssToken('--border', '#2a3142');
          res.label = '';
          res.zIndex = 0;
          res.size = Math.max(1, (data.size || 4) * 0.45);
        } else if (selected) {
          res.color = cssToken('--selected', '#fbbf24');
          res.zIndex = 3;
          res.size = Math.max(data.size || 4, 6);
        } else if (node === hoverId) {
          res.zIndex = 2;
        }
      } catch {
        /* keep defaults */
      }
      return res;
    });

    sigma.setSetting('edgeReducer', (edge, data) => {
      const res = { ...data };
      try {
        const [a, b] = graph.extremities(edge);
        const focused = !focusIds || (focusIds.has(a) && focusIds.has(b));
        if (!focused) {
          res.hidden = true;
          return res;
        }
        if (selectedId && (a === selectedId || b === selectedId)) {
          res.color = cssToken('--accent-3', '#f59e0b');
          res.size = Math.max(res.size || 1, 1.6);
          res.zIndex = 2;
        }
      } catch {
        /* keep defaults */
      }
      return res;
    });

    sigma.on('clickNode', ({ node, event }) => {
      // Prevent the follow-up stage click from clearing selection / fighting refresh
      event?.preventSigmaDefault?.();
      suppressStageClick = true;
      setTimeout(() => {
        suppressStageClick = false;
      }, 0);
      selectedId = node;
      sigma.refresh();
      onSelect?.(node, nodeMeta.get(node));
      requestAnimationFrame(() => resize());
    });
    sigma.on('clickStage', () => {
      if (suppressStageClick) return;
      selectedId = null;
      sigma.refresh();
      onBackground?.();
    });
    sigma.on('enterNode', ({ node }) => {
      hoverId = node;
      sigma.refresh();
      onHover?.(node, nodeMeta.get(node));
    });
    sigma.on('leaveNode', () => {
      hoverId = null;
      sigma.refresh();
      onHover?.(null, null);
    });
    sigma.getMouseCaptor().on('rightClick', (event) => {
      event.preventSigmaDefault?.();
      event.original?.preventDefault?.();
    });
    container.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      if (!sigma) return;
      const pos = sigma.viewportToGraph({ x: e.offsetX, y: e.offsetY });
      let nearest = null;
      let best = Infinity;
      graph.forEachNode((id, attrs) => {
        const dx = (attrs.x || 0) - pos.x;
        const dy = (attrs.y || 0) - pos.y;
        const d = dx * dx + dy * dy;
        if (d < best) {
          best = d;
          nearest = id;
        }
      });
      if (nearest != null && best < 25) {
        onContextMenu?.(nearest, nodeMeta.get(nearest), { x: e.clientX, y: e.clientY });
      }
    });

    if (typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(() => resize());
      resizeObserver.observe(container);
      if (container.parentElement) resizeObserver.observe(container.parentElement);
    }

    return sigma;
  }

  function destroyWorker() {
    if (worker) {
      worker.terminate();
      worker = null;
    }
  }

  function runLayout({ iterations } = {}) {
    return new Promise((resolve, reject) => {
      destroyWorker();
      const gen = ++layoutGen;
      const nodes = [];
      const edges = [];
      graph.forEachNode((id, attrs) => {
        nodes.push({ id, size: attrs.size });
      });
      graph.forEachEdge((_e, attrs, source, target) => {
        edges.push({ source, target, weight: attrs.weight || 1 });
      });
      if (!nodes.length) {
        resolve();
        return;
      }
      worker = new Worker('/mission/layout-worker.js', { type: 'module' });
      worker.onmessage = (ev) => {
        const msg = ev.data || {};
        destroyWorker();
        if (gen !== layoutGen) {
          resolve();
          return;
        }
        if (!msg.ok) {
          reject(new Error(msg.error || 'layout failed'));
          return;
        }
        for (const [id, p] of Object.entries(msg.positions || {})) {
          if (!graph.hasNode(id)) continue;
          graph.setNodeAttribute(id, 'x', p.x);
          graph.setNodeAttribute(id, 'y', p.y);
          positionsCache.set(id, p);
        }
        sigma?.refresh();
        resize();
        resolve();
      };
      worker.onerror = (err) => {
        destroyWorker();
        reject(err);
      };
      const n = nodes.length;
      const iters = iterations ?? (n > 2000 ? 80 : n > 800 ? 120 : 180);
      worker.postMessage({ nodes, edges, iterations: iters, seed: 7 });
    });
  }

  function setGraphData(rawNodes, rawEdges, { layout = true } = {}) {
    ensureSigma();
    // Cancel in-flight layout so a late worker can't blank the new graph mid-click
    layoutGen += 1;
    destroyWorker();

    const nextIds = new Set(rawNodes.map((n) => n.id));
    nodeMeta = new Map(rawNodes.map((n) => [n.id, n]));

    const degreeHint = new Map();
    for (const e of rawEdges) {
      const s = e.from_id ?? e.source;
      const t = e.to_id ?? e.target;
      degreeHint.set(s, (degreeHint.get(s) || 0) + 1);
      degreeHint.set(t, (degreeHint.get(t) || 0) + 1);
    }

    // Drop removed nodes (keeps Sigma buffers healthier than graph.clear())
    for (const id of [...graph.nodes()]) {
      if (!nextIds.has(id)) {
        graph.dropNode(id);
        positionsCache.delete(id);
      }
    }

    for (const n of rawNodes) {
      const prior = positionsCache.get(n.id);
      const attrs = {
        label: n.title || n.id,
        size: nodeSize(n, degreeHint.get(n.id) || 0),
        color: nodeColor(n),
        kind: n.kind,
      };
      if (graph.hasNode(n.id)) {
        graph.mergeNodeAttributes(n.id, attrs);
        if (prior) {
          graph.setNodeAttribute(n.id, 'x', prior.x);
          graph.setNodeAttribute(n.id, 'y', prior.y);
        }
      } else {
        graph.addNode(n.id, {
          ...attrs,
          x: prior?.x ?? Math.random() * 100,
          y: prior?.y ?? Math.random() * 100,
        });
      }
    }

    // Rebuild edges for the visible set
    for (const edge of [...graph.edges()]) graph.dropEdge(edge);
    for (const e of rawEdges) {
      const s = e.from_id ?? e.source;
      const t = e.to_id ?? e.target;
      if (!graph.hasNode(s) || !graph.hasNode(t)) continue;
      if (graph.hasEdge(s, t) || graph.hasEdge(t, s)) continue;
      const vw = visualEdgeWeight(e.weight);
      try {
        graph.addEdge(s, t, {
          size: 0.4 + vw,
          color: cssToken('--edge', '#64748b'),
          weight: e.weight || 1,
          relationship: e.relationship || 'linked',
        });
      } catch {
        /* ignore */
      }
    }

    resize();
    if (layout) return runLayout();
    return Promise.resolve();
  }

  function setColorBy(mode) {
    colorBy = mode;
    graph.forEachNode((id) => {
      const n = nodeMeta.get(id);
      if (n) graph.setNodeAttribute(id, 'color', nodeColor(n));
    });
    sigma?.refresh();
  }

  function setSelection(id) {
    selectedId = id;
    sigma?.refresh();
  }

  function setFocusIds(ids) {
    focusIds = ids && ids.size ? new Set(ids) : null;
    sigma?.refresh();
  }

  function cameraToNode(id, { duration = 350 } = {}) {
    if (!sigma || !graph.hasNode(id)) return;
    const attrs = graph.getNodeAttributes(id);
    if (attrs.x == null || attrs.y == null) return;
    const cam = sigma.getCamera();
    cam.animate(
      { x: attrs.x, y: attrs.y, ratio: Math.min(cam.ratio, 0.45) },
      { duration },
    );
  }

  function fitView() {
    if (!sigma) return;
    sigma.getCamera().animatedReset({ duration: 300 });
  }

  function resize() {
    if (!sigma) return;
    try {
      sigma.resize();
      sigma.refresh();
    } catch {
      /* ignore */
    }
  }

  function exportPositions() {
    const out = {};
    graph.forEachNode((id, attrs) => {
      out[id] = { x: attrs.x, y: attrs.y };
    });
    return out;
  }

  function applyPositions(map) {
    if (!map) return;
    for (const [id, p] of Object.entries(map)) {
      if (!graph.hasNode(id)) continue;
      graph.setNodeAttribute(id, 'x', p.x);
      graph.setNodeAttribute(id, 'y', p.y);
      positionsCache.set(id, p);
    }
    sigma?.refresh();
  }

  function getNode(id) {
    return nodeMeta.get(id);
  }

  function neighbors(id) {
    if (!graph.hasNode(id)) return [];
    return graph.neighbors(id).map((nid) => ({
      id: nid,
      node: nodeMeta.get(nid),
      edges: graph.edges(id, nid).map((eid) => graph.getEdgeAttributes(eid)),
    }));
  }

  function destroy() {
    destroyWorker();
    resizeObserver?.disconnect();
    resizeObserver = null;
    sigma?.kill();
    sigma = null;
    graph.clear();
  }

  return {
    setGraphData,
    setColorBy,
    setSelection,
    setFocusIds,
    cameraToNode,
    fitView,
    resize,
    runLayout,
    exportPositions,
    applyPositions,
    getNode,
    neighbors,
    destroy,
    get graph() {
      return graph;
    },
  };
}
