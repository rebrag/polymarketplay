import type { BookState } from "../lib/bookPayload";
import { parseBookState } from "../lib/bookPayload";

type WorkerMessage =
  | { type: "payload"; payload: string }
  | { type: "flush" };

const FLUSH_INTERVAL_MS = 200;

let pending: Record<string, BookState> = {};
let flushTimer: number | null = null;

function scheduleFlush(): void {
  if (flushTimer !== null) return;
  flushTimer = self.setTimeout(() => {
    flushTimer = null;
    const updates = pending;
    pending = {};
    const keys = Object.keys(updates);
    if (!keys.length) return;
    self.postMessage({ type: "batch", updates });
  }, FLUSH_INTERVAL_MS);
}

self.onmessage = (event: MessageEvent<WorkerMessage>) => {
  const data = event.data;
  if (!data || data.type !== "payload") return;
  const trimmed = data.payload.trim();
  if (!trimmed || (trimmed[0] !== "{" && trimmed[0] !== "[")) return;
  try {
    const payload = JSON.parse(trimmed) as
      | { type?: string; updates?: unknown[] }
      | Record<string, unknown>;
    const updates = Array.isArray((payload as { updates?: unknown[] }).updates)
      ? (payload as { updates: unknown[] }).updates
      : [payload];
    updates.forEach((update) => {
      if (!update || typeof update !== "object") return;
      const assetId = (update as { asset_id?: string }).asset_id;
      if (!assetId) return;
      const parsed = parseBookState(update);
      if (parsed) {
        pending[assetId] = parsed;
      }
    });
    scheduleFlush();
  } catch {
    return;
  }
};
