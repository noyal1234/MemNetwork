/**
 * "Ask your brain" — WebLLM (in-browser) + FTS5 RAG via /api/search.
 */

const MODEL_IDS = [
  'Llama-3.2-1B-Instruct-q4f16_1-MLC',
  'Llama-3.2-3B-Instruct-q4f16_1-MLC',
  'SmolLM2-360M-Instruct-q4f16_1-MLC',
];

const SYSTEM_PROMPT = `You are MemNetwork's local project brain assistant.
Answer using ONLY the provided neuron context from this project's brain.db.
Cite neurons inline as [id:NODE_ID] when you use them.
If the context is insufficient, say what is missing. Be concise and concrete.
Never invent file paths or decisions that are not in the context.`;

export function createChatController({ getNodeById, onCite }) {
  let engine = null;
  let loading = false;
  let generating = false;
  let abortFlag = false;
  let webllm = null;
  let supported = null;

  const els = {};

  function setStatus(text, kind = '') {
    if (!els.status) return;
    els.status.textContent = text;
    els.status.className = kind ? kind : '';
    els.status.id = 'chat-status';
    if (kind) els.status.classList.add(kind);
  }

  function appendMessage(role, text, { citations = [] } = {}) {
    const div = document.createElement('div');
    div.className = `chat-msg ${role}`;
    if (role === 'assistant' && citations.length) {
      const body = document.createElement('div');
      body.textContent = stripCiteMarkers(text);
      div.appendChild(body);
      const citeRow = document.createElement('div');
      citeRow.style.marginTop = '8px';
      for (const id of citations) {
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'cite-chip';
        const node = getNodeById(id);
        chip.textContent = node?.title ? truncate(node.title, 28) : id.slice(0, 12);
        chip.title = id;
        chip.addEventListener('click', () => onCite(id));
        citeRow.appendChild(chip);
      }
      div.appendChild(citeRow);
    } else {
      div.textContent = text;
    }
    els.messages.appendChild(div);
    els.messages.scrollTop = els.messages.scrollHeight;
    return div;
  }

  function truncate(s, n) {
    return s.length > n ? `${s.slice(0, n - 1)}…` : s;
  }

  function stripCiteMarkers(text) {
    return text.replace(/\[id:([^\]]+)\]/g, '[$1]');
  }

  function extractCitations(text, fallbackIds = []) {
    const found = [...text.matchAll(/\[id:([^\]]+)\]/g)].map((m) => m[1]);
    const ids = found.length ? found : fallbackIds;
    return [...new Set(ids)];
  }

  async function detectWebGPU() {
    if (supported != null) return supported;
    try {
      if (!navigator.gpu) {
        supported = false;
        return false;
      }
      const adapter = await navigator.gpu.requestAdapter();
      supported = !!adapter;
      return supported;
    } catch {
      supported = false;
      return false;
    }
  }

  async function loadWebLLM() {
    if (webllm) return webllm;
    // ESM CDN — cached by the browser after first fetch
    webllm = await import('https://esm.run/@mlc-ai/web-llm@0.2.79');
    return webllm;
  }

  function withAuth(path) {
    const token = new URLSearchParams(window.location.search).get('token');
    if (!token) return path;
    const url = new URL(path, window.location.origin);
    url.searchParams.set('token', token);
    return url.pathname + url.search;
  }

  async function fetchWebllmConfig() {
    try {
      const res = await fetch(withAuth('/api/webllm-config'));
      if (!res.ok) return null;
      return await res.json();
    } catch {
      return null;
    }
  }

  async function loadModel(modelId) {
    if (loading) return;
    loading = true;
    els.loadBtn.disabled = true;
    els.progressWrap.classList.add('visible');
    setStatus('Checking WebGPU…');

    const ok = await detectWebGPU();
    if (!ok) {
      setStatus('WebGPU unavailable — use Chrome/Edge 113+ for chat', 'error');
      appendMessage(
        'system',
        'Chat needs WebGPU. The graph explorer still works without it.',
      );
      loading = false;
      els.loadBtn.disabled = false;
      return;
    }

    try {
      setStatus('Loading WebLLM runtime…');
      const lib = await loadWebLLM();
      const cfg = await fetchWebllmConfig();
      let id = MODEL_IDS.includes(modelId) ? modelId : MODEL_IDS[0];
      if (cfg?.preferred_model && MODEL_IDS.includes(cfg.preferred_model) && !modelId) {
        id = cfg.preferred_model;
      }

      const useLocal = !!(cfg?.use_local && cfg?.app_config && cfg.preferred_model === id);
      setStatus(
        useLocal
          ? `Loading ${id} from local cache…`
          : `Downloading ${id}…`,
      );
      const progressCb = (report) => {
        const pct = Math.round((report.progress || 0) * 100);
        els.progressFill.style.width = `${pct}%`;
        els.progressText.textContent = report.text || `${pct}%`;
      };

      const engineOpts = { initProgressCallback: progressCb };
      if (useLocal) {
        engineOpts.appConfig = cfg.app_config;
      }

      // Prefer Web Worker so the 3D scene stays smooth; fall back to main thread.
      try {
        const worker = new Worker(new URL('./webllm-worker.js', import.meta.url), {
          type: 'module',
        });
        engine = await lib.CreateWebWorkerMLCEngine(worker, id, engineOpts);
      } catch (workerErr) {
        console.warn('WebWorkerMLCEngine failed, falling back to main thread', workerErr);
        engine = await lib.CreateMLCEngine(id, engineOpts);
      }

      setStatus(
        useLocal ? 'Ready — from local cache (wizard prefetch)' : 'Ready — private, on-device',
        'ready',
      );
      els.input.disabled = false;
      els.send.disabled = false;
      appendMessage(
        'system',
        useLocal
          ? `Model ready from local cache: ${id}`
          : `Model ready: ${id}`,
      );
    } catch (err) {
      console.error(err);
      setStatus(`Load failed: ${err.message}`, 'error');
      appendMessage('system', `Could not load model: ${err.message}`);
    } finally {
      loading = false;
      els.loadBtn.disabled = false;
    }
  }

  async function fetchContext(query, limit = 8) {
    const res = await fetch(
      withAuth(`/api/search?q=${encodeURIComponent(query)}&limit=${limit}`),
    );
    if (!res.ok) throw new Error(`search HTTP ${res.status}`);
    const data = await res.json();
    return data.results || [];
  }

  function packContext(results) {
    const parts = [];
    let chars = 0;
    const budget = 3500;
    for (const r of results) {
      const block =
        `### ${r.title} [id:${r.id}]\n` +
        `kind=${r.kind}${r.subtype ? '/' + r.subtype : ''}` +
        (r.path ? ` path=${r.path}` : '') +
        `\n${r.content || ''}\n`;
      if (chars + block.length > budget) break;
      parts.push(block);
      chars += block.length;
    }
    return parts.join('\n');
  }

  async function ask(question, { extraContext = '' } = {}) {
    if (!engine || generating) return;
    generating = true;
    abortFlag = false;
    els.send.style.display = 'none';
    els.stop.style.display = '';
    els.input.disabled = true;

    appendMessage('user', question);
    const assistantEl = appendMessage('assistant', '…');

    let results = [];
    try {
      results = await fetchContext(question, 8);
    } catch (err) {
      assistantEl.textContent = `Search failed: ${err.message}`;
      finishGen();
      return;
    }

    const ctx = packContext(results);
    const contextBlock =
      (extraContext ? `${extraContext}\n\n` : '') +
      (ctx || '(no matching neurons)');

    const messages = [
      { role: 'system', content: SYSTEM_PROMPT },
      {
        role: 'user',
        content:
          `Neuron context:\n${contextBlock}\n\nQuestion: ${question}\n` +
          `Cite used neurons as [id:NODE_ID].`,
      },
    ];

    let answer = '';
    try {
      const chunks = await engine.chat.completions.create({
        messages,
        stream: true,
        temperature: 0.4,
      });
      for await (const chunk of chunks) {
        if (abortFlag) break;
        const delta = chunk.choices?.[0]?.delta?.content || '';
        answer += delta;
        assistantEl.textContent = answer || '…';
        els.messages.scrollTop = els.messages.scrollHeight;
      }
    } catch (err) {
      assistantEl.textContent = `Generation error: ${err.message}`;
      finishGen();
      return;
    }

    const citations = extractCitations(answer, results.map((r) => r.id).slice(0, 4));
    assistantEl.innerHTML = '';
    const body = document.createElement('div');
    body.textContent = stripCiteMarkers(answer || '(no response)');
    assistantEl.appendChild(body);
    if (citations.length) {
      const citeRow = document.createElement('div');
      citeRow.style.marginTop = '8px';
      for (const id of citations) {
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'cite-chip';
        const node = getNodeById(id);
        chip.textContent = node?.title ? truncate(node.title, 28) : id.slice(0, 12);
        chip.title = id;
        chip.addEventListener('click', () => onCite(id));
        citeRow.appendChild(chip);
      }
      assistantEl.appendChild(citeRow);
    }
    finishGen();
  }

  function finishGen() {
    generating = false;
    els.send.style.display = '';
    els.stop.style.display = 'none';
    els.input.disabled = !engine;
    els.send.disabled = !engine;
  }

  async function explainNode(node, neighbors) {
    open();
    if (!engine) {
      appendMessage(
        'system',
        'Load a local model first, then click Explain again.',
      );
      return;
    }
    const neighborBlock = neighbors
      .slice(0, 12)
      .map(
        (n) =>
          `- ${n.title} [id:${n.id}] (${n.kind}${n.subtype ? '/' + n.subtype : ''})`,
      )
      .join('\n');
    const extra =
      `Focus node:\n### ${node.title} [id:${node.id}]\n` +
      `kind=${node.kind}${node.subtype ? '/' + node.subtype : ''}` +
      (node.path ? ` path=${node.path}` : '') +
      `\n${node.content || ''}\n\nNeighbors:\n${neighborBlock || '(none)'}`;
    await ask(
      `Explain the role of this node in the project brain in plain English. What is it, why does it matter, and how does it connect?`,
      { extraContext: extra },
    );
  }

  function open() {
    els.panel.classList.add('open');
    els.onOpenChange?.();
  }

  function close() {
    els.panel.classList.remove('open');
    els.onOpenChange?.();
  }

  function bindUi({ onOpenChange } = {}) {
    els.panel = document.getElementById('chat-panel');
    els.status = document.getElementById('chat-status');
    els.messages = document.getElementById('chat-messages');
    els.input = document.getElementById('chat-input');
    els.send = document.getElementById('chat-send');
    els.stop = document.getElementById('chat-stop');
    els.loadBtn = document.getElementById('chat-load-btn');
    els.model = document.getElementById('chat-model');
    els.progressWrap = document.getElementById('chat-progress-wrap');
    els.progressFill = document.getElementById('chat-progress-fill');
    els.progressText = document.getElementById('chat-progress-text');
    els.onOpenChange = onOpenChange;

    document.getElementById('chat-toggle').addEventListener('click', () => {
      if (els.panel.classList.contains('open')) close();
      else open();
    });
    document.getElementById('chat-close').addEventListener('click', close);

    els.loadBtn.addEventListener('click', () => loadModel(els.model.value));
    els.send.addEventListener('click', () => {
      const q = els.input.value.trim();
      if (!q) return;
      els.input.value = '';
      ask(q);
    });
    els.stop.addEventListener('click', () => {
      abortFlag = true;
    });
    els.input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        els.send.click();
      }
    });

    detectWebGPU().then((ok) => {
      if (!ok) {
        setStatus('WebGPU unavailable — chat disabled on this browser', 'error');
        els.loadBtn.disabled = true;
      }
    });

    fetchWebllmConfig().then((cfg) => {
      if (!cfg) return;
      if (cfg.preferred_model && MODEL_IDS.includes(cfg.preferred_model)) {
        els.model.value = cfg.preferred_model;
      }
      for (const opt of els.model.options) {
        const info = (cfg.models || []).find((m) => m.id === opt.value);
        if (info?.cached) {
          if (!opt.textContent.includes('(cached)')) {
            opt.textContent = `${opt.textContent} · cached`;
          }
        }
      }
      if (cfg.use_local) {
        setStatus('Local weight cache ready — click Load model', 'ready');
        appendMessage(
          'system',
          `Wizard prefetched weights for ${cfg.preferred_model}. Click Load model (Chrome/Edge + WebGPU).`,
        );
      }
    });
  }

  return { bindUi, open, close, ask, explainNode, loadModel };
}
