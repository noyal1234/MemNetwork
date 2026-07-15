/**
 * ForceAtlas2 layout worker — imports CDN ESM directly (no bundler).
 */
import Graph from 'https://cdn.jsdelivr.net/npm/graphology@0.25.4/+esm';
import forceAtlas2 from 'https://cdn.jsdelivr.net/npm/graphology-layout-forceatlas2@0.10.1/+esm';

self.onmessage = (ev) => {
  const { nodes, edges, iterations = 120, seed = 1 } = ev.data || {};
  try {
    const graph = new Graph({ multi: false, type: 'undirected', allowSelfLoops: false });
    let i = 0;
    for (const n of nodes || []) {
      const angle = ((seed * 17 + i) % 360) * (Math.PI / 180);
      const r = 40 + (i % 40);
      graph.addNode(n.id, {
        x: Math.cos(angle) * r + (i % 7),
        y: Math.sin(angle) * r + (i % 5),
        size: n.size || 4,
      });
      i += 1;
    }
    for (const e of edges || []) {
      if (!graph.hasNode(e.source) || !graph.hasNode(e.target)) continue;
      if (graph.hasEdge(e.source, e.target) || graph.hasEdge(e.target, e.source)) continue;
      try {
        graph.addEdge(e.source, e.target, { weight: e.weight || 1 });
      } catch {
        /* ignore parallel */
      }
    }
    const settings = forceAtlas2.inferSettings(graph);
    forceAtlas2.assign(graph, {
      iterations: Math.max(20, Math.min(iterations, 400)),
      settings: { ...settings, gravity: 1, scalingRatio: 10, barnesHutOptimize: graph.order > 500 },
    });
    const positions = {};
    graph.forEachNode((id, attrs) => {
      positions[id] = { x: attrs.x, y: attrs.y };
    });
    self.postMessage({ ok: true, positions });
  } catch (err) {
    self.postMessage({ ok: false, error: String(err?.message || err) });
  }
};
