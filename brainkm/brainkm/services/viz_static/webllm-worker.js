/**
 * WebLLM engine worker — keeps model inference off the UI thread.
 * Loaded by chat.js via CreateWebWorkerMLCEngine.
 */
import { WebWorkerMLCEngineHandler } from 'https://esm.run/@mlc-ai/web-llm@0.2.79';

const handler = new WebWorkerMLCEngineHandler();
self.onmessage = (msg) => {
  handler.onmessage(msg);
};
