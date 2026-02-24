import { useEffect, useMemo, useRef } from "react";

import type { BookState } from "@/lib/bookPayload";
import { useBookStore } from "@/stores/bookStore";

interface WidgetAssetMeta {
  asset_id: string;
  slug?: string;
  question?: string;
  outcome?: string;
  gameStartTime?: string;
}

interface TokenWidget {
  assetId: string;
  sourceSlug?: string;
  marketQuestion?: string;
  outcomeName?: string;
  gameStartTime?: string;
}

// Browser -> backend books stream socket (not the backend's upstream Polymarket feed).
const SERVER_BOOKS_WS_URL = "ws://localhost:8000/ws/books/stream";
const RECONNECT_BASE_MS = 500;
const RECONNECT_MAX_MS = 5000;

function buildAssetMeta(widgets: TokenWidget[]): WidgetAssetMeta[] {
  return widgets.map((w) => ({
    asset_id: w.assetId,
    slug: w.sourceSlug,
    question: w.marketQuestion,
    outcome: w.outcomeName,
    gameStartTime: w.gameStartTime,
  }));
}

export function useServerBooksSocket(widgets: TokenWidget[]): void {
  const serverWsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const assetsRef = useRef<Map<string, WidgetAssetMeta>>(new Map());
  const pendingSubscribeRef = useRef<WidgetAssetMeta[]>([]);
  const workerRef = useRef<Worker | null>(null);
  const pendingUpdatesRef = useRef<Record<string, BookState> | null>(null);
  const applyTimerRef = useRef<number | null>(null);

  const setBooksBulk = useBookStore((state) => state.setBooksBulk);
  const bumpFrame = useBookStore((state) => state.bumpFrame);
  const setStatusBulk = useBookStore((state) => state.setStatusBulk);
  const clearBook = useBookStore((state) => state.clearBook);

  const assetMeta = useMemo(() => buildAssetMeta(widgets), [widgets]);
  const shouldConnect = assetMeta.length > 0;

  useEffect(() => {
    const nextMap = new Map<string, WidgetAssetMeta>();
    assetMeta.forEach((meta) => {
      if (meta.asset_id) nextMap.set(meta.asset_id, meta);
    });

    const prevMap = assetsRef.current;
    const toAdd: WidgetAssetMeta[] = [];
    const toRemove: string[] = [];

    for (const [assetId, meta] of nextMap.entries()) {
      if (!prevMap.has(assetId)) {
        toAdd.push(meta);
      }
    }

    for (const assetId of prevMap.keys()) {
      if (!nextMap.has(assetId)) {
        toRemove.push(assetId);
      }
    }

    assetsRef.current = nextMap;
    if (toAdd.length) {
      pendingSubscribeRef.current = toAdd;
      setStatusBulk(
        toAdd.map((meta) => meta.asset_id),
        "connecting"
      );
    }
    if (toRemove.length) {
      const ws = serverWsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "unsubscribe", assets: toRemove }));
      }
      toRemove.forEach((assetId) => clearBook(assetId));
    }

    const ws = serverWsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN && toAdd.length) {
      ws.send(JSON.stringify({ type: "subscribe", assets: toAdd }));
      pendingSubscribeRef.current = [];
    }
  }, [assetMeta, clearBook, setStatusBulk]);

  useEffect(() => {
    let active = true;

    if (!shouldConnect) {
      const ws = serverWsRef.current;
      if (ws) {
        ws.onopen = null;
        ws.onclose = null;
        ws.onerror = null;
        ws.onmessage = null;
        ws.close();
      }
      serverWsRef.current = null;
      if (workerRef.current) {
        workerRef.current.terminate();
        workerRef.current = null;
      }
      pendingUpdatesRef.current = null;
      if (applyTimerRef.current !== null) {
        window.clearTimeout(applyTimerRef.current);
        applyTimerRef.current = null;
      }
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      return () => {
        active = false;
      };
    }

    const worker = new Worker(new URL("../workers/bookWs.worker.ts", import.meta.url), {
      type: "module",
    });
    workerRef.current = worker;
    worker.onmessage = (event) => {
      const payload = event.data as { type?: string; updates?: Record<string, BookState> };
      if (!payload || payload.type !== "batch" || !payload.updates) return;
      const updates = payload.updates;
      const assetIds = Object.keys(updates);
      if (!assetIds.length) return;
      if (!pendingUpdatesRef.current) {
        pendingUpdatesRef.current = { ...updates };
      } else {
        Object.assign(pendingUpdatesRef.current, updates);
      }
      if (applyTimerRef.current !== null) return;
      applyTimerRef.current = window.setTimeout(() => {
        applyTimerRef.current = null;
        const pending = pendingUpdatesRef.current;
        pendingUpdatesRef.current = null;
        if (!pending) return;
        setBooksBulk(pending, "live");
        bumpFrame();
      }, 200);
    };

    const scheduleReconnect = () => {
      if (!active) return;
      if (reconnectTimerRef.current !== null) return;
      const backoff = Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * 2 ** reconnectAttemptsRef.current);
      const jitter = Math.floor(Math.random() * 200);
      reconnectAttemptsRef.current += 1;
      reconnectTimerRef.current = window.setTimeout(() => {
        reconnectTimerRef.current = null;
        connect();
      }, backoff + jitter);
    };

    const connect = () => {
      if (!active) return;
      const ws = new WebSocket(SERVER_BOOKS_WS_URL);
      serverWsRef.current = ws;

      ws.onopen = () => {
        reconnectAttemptsRef.current = 0;
        const assets = Array.from(assetsRef.current.values());
        if (assets.length) {
          ws.send(JSON.stringify({ type: "subscribe", assets }));
          pendingSubscribeRef.current = [];
        }
      };

      ws.onmessage = (event) => {
        if (!active || typeof event.data !== "string") return;
        workerRef.current?.postMessage({ type: "payload", payload: event.data });
      };

      ws.onclose = () => {
        const assets = assetsRef.current.keys();
        setStatusBulk(assets, "connecting");
        scheduleReconnect();
      };

      ws.onerror = () => {
        const assets = assetsRef.current.keys();
        setStatusBulk(assets, "error");
      };
    };

    connect();

    return () => {
      active = false;
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (applyTimerRef.current !== null) {
        window.clearTimeout(applyTimerRef.current);
        applyTimerRef.current = null;
      }
      worker.terminate();
      workerRef.current = null;
      const ws = serverWsRef.current;
      if (ws) {
        ws.onopen = null;
        ws.onclose = null;
        ws.onerror = null;
        ws.onmessage = null;
        ws.close();
      }
      serverWsRef.current = null;
    };
  }, [bumpFrame, setBooksBulk, setStatusBulk, shouldConnect]);
}
