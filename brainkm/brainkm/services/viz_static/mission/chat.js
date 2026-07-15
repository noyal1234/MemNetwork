/**
 * Thin WebLLM bridge for Mission Control Explain + palette chat.
 * Reuses patterns from /chat.js but with minimal UI coupling.
 */

const SYSTEM_PROMPT = `You are MemNetwork's local project brain assistant.
Answer using ONLY the provided neuron context from this project's brain.db.
Cite neurons inline as [id:NODE_ID] when you use them.
If the context is insufficient, say what is missing. Be concise and concrete.`;

let engine = null;
let webllm = null;

async function loadWebLLM() {
  if (webllm) return webllm;
  webllm = await import('https://esm.run/@mlc-ai/web-llm@0.2.79');
  return webllm;
}

async function ensureEngine(onProgress) {
  if (engine) return engine;
  const wl = await loadWebLLM();
  const cfgRes = await fetch('/api/webllm-config');
  const cfg = await cfgRes.json();
  const model = cfg.preferred_model || 'Llama-3.2-1B-Instruct-q4f16_1-MLC';
  const progress = (report) => {
    if (report?.text) onProgress?.(report.text);
  };
  if (cfg.use_local && cfg.app_config) {
    engine = await wl.CreateMLCEngine(model, {
      appConfig: cfg.app_config,
      initProgressCallback: progress,
    });
  } else {
    engine = await wl.CreateMLCEngine(model, { initProgressCallback: progress });
  }
  return engine;
}

async function ragContext(query, limit = 8) {
  const res = await fetch(`/api/search?q=${encodeURIComponent(query)}&limit=${limit}`);
  const data = await res.json();
  const results = data.results || [];
  const block = results
    .map((r) => `[id:${r.id}] (${r.kind}${r.subtype ? '/' + r.subtype : ''}) ${r.title}\n${r.content || ''}`)
    .join('\n\n');
  return { block, ids: results.map((r) => r.id) };
}

export async function askBrain(question, { onProgress } = {}) {
  const { block, ids } = await ragContext(question);
  const eng = await ensureEngine(onProgress);
  const messages = [
    { role: 'system', content: SYSTEM_PROMPT },
    {
      role: 'user',
      content: `Context:\n${block || '(none)'}\n\nQuestion: ${question}`,
    },
  ];
  const out = await eng.chat.completions.create({ messages, stream: false });
  const text = out?.choices?.[0]?.message?.content || '';
  return { text, ids };
}

export async function explainNode(node, neighbors = [], { onProgress } = {}) {
  const neighborText = neighbors
    .slice(0, 12)
    .map((n) => `- ${n.title || n.id} (${n.kind})`)
    .join('\n');
  const question = `Explain this neuron and how it relates to neighbors:\nTitle: ${node.title}\nKind: ${node.kind}/${node.subtype || ''}\nContent: ${node.content || ''}\nNeighbors:\n${neighborText}`;
  return askBrain(question, { onProgress });
}

export function isEngineReady() {
  return !!engine;
}
