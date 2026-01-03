import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface OrderLevel {
  price: number;
  size: number;
  cum: number;
}

interface BookState {
  ready: boolean;
  msg_count: number;
  bids: OrderLevel[];
  asks: OrderLevel[];
  tick_size: number;
  last_trade?: LastTrade;
}

export interface UserPosition {
  price: number;
  side: "BUY" | "SELL";
  shares: number;
}

interface OpenOrder {
  orderID: string;
  asset_id: string;
  side: "BUY" | "SELL";
  price: string;
  size: string;
  expiration?: number;
}

interface WidgetProps {
  assetId: string;
  outcomeName: string;
  volume: number;
  marketQuestion?: string;
  sourceSlug?: string;
  userPosition?: UserPosition | null;
  positionShares?: number | null;
  positionAvgPrice?: number | null;
  otherAssetPositionShares?: number | null; // NEW: Add other asset's position
  openOrders?: OpenOrder[];
  ordersServerNowSec?: number | null;
  ordersServerNowLocalMs?: number | null;
  defaultShares?: string;
  defaultTtl?: string;
  auto?: boolean;
  autoBuyAllowed?: boolean;
  autoSellAllowed?: boolean;
  autoTradeSide?: "BUY" | "SELL";
  autoMode?: "client" | "server";
  isHighlighted?: boolean;
  viewMode?: "full" | "mini";
  onBookUpdate?: (assetId: string, bestBid: number | null, bestAsk: number | null) => void;
  onHeaderClick?: (assetId: string) => void;
  onClose?: (assetId: string) => void;
  apiBaseUrl?: string;
  onAutoSettingsChange?: (assetId: string, settings: { shares: number; ttl: number; level: number }) => void;
}

interface LastTrade {
  price: number;
  size: number;
  side: "BUY" | "SELL";
  timestamp: number;
}
/* ---------- Strict Runtime Guards ---------- */
function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null;
}

function isOrderLevel(v: unknown): v is OrderLevel {
  if (!isRecord(v)) return false;
  return typeof v.price === "number" && typeof v.size === "number" && typeof v.cum === "number";
}

function parseBookState(payload: unknown): BookState | null {
  if (!isRecord(payload)) return null;
  if (payload.status === "loading") return null;

  const { ready, msg_count, bids, asks, tick_size } = payload;
  if (typeof ready !== "boolean" || typeof msg_count !== "number") return null;
  if (!Array.isArray(bids) || !Array.isArray(asks)) return null;

  let lastTrade: LastTrade | undefined;
  const rawLast = (payload as { last_trade?: unknown }).last_trade;
  if (isRecord(rawLast)) {
    const price = Number(rawLast.price);
    const size = Number(rawLast.size);
    const timestamp = Number(rawLast.timestamp);
    const side = String(rawLast.side || "").toUpperCase();
    if (
      Number.isFinite(price) &&
      Number.isFinite(size) &&
      Number.isFinite(timestamp) &&
      (side === "BUY" || side === "SELL")
    ) {
      lastTrade = { price, size, timestamp, side } as LastTrade;
    }
  }

  return {
    ready,
    msg_count,
    bids: bids.filter(isOrderLevel),
    asks: asks.filter(isOrderLevel),
    tick_size: typeof tick_size === "number" ? tick_size : 0.01,
    last_trade: lastTrade,
  };
}

/* ---------- Utilities ---------- */
async function copyToClipboard(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const el = document.createElement("textarea");
    el.value = text;
    el.style.position = "fixed";
    el.style.left = "-9999px";
    document.body.appendChild(el);
    el.focus();
    el.select();
    document.execCommand("copy");
    document.body.removeChild(el);
  }
}

function clampInt(n: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, n));
}

function decimalsForTick(tickSize: number): number {
  if (!Number.isFinite(tickSize) || tickSize <= 0) return 2;
  const text = tickSize.toFixed(10).replace(/0+$/, "");
  const parts = text.split(".");
  const decimals = parts.length > 1 ? parts[1].length : 0;
  return Math.max(0, Math.min(6, decimals));
}

function formatPrice(price: number, tickSize: number): string {
  const decimals = decimalsForTick(tickSize);
  return price.toFixed(decimals);
}

function formatCents(price: number, tickSize: number): string {
  const centsTick = tickSize * 100;
  const decimals = decimalsForTick(centsTick);
  return (price * 100).toFixed(decimals);
}

function formatOrderKey(price: number, tickSize: number): string {
  return formatPrice(price, tickSize);
}

function formatVol(num: number): string {
  if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(1)}M`;
  if (num >= 1_000) return `${(num / 1_000).toFixed(1)}k`;
  return num.toFixed(0);
}

export function OrderBookWidget({
  assetId,
  outcomeName,
  volume,
  marketQuestion,
  // sourceSlug,
  userPosition,
  positionShares,
  positionAvgPrice,
  otherAssetPositionShares = null, // NEW: Default to null
  openOrders = [],
  ordersServerNowSec,
  ordersServerNowLocalMs,
  defaultShares = "5",
  defaultTtl = "10",
  auto = false,
  autoBuyAllowed = true,
  autoSellAllowed = true,
  autoTradeSide,
  autoMode = "client",
  isHighlighted,
  viewMode = "full",
  onBookUpdate,
  onHeaderClick,
  onClose,
  apiBaseUrl = "http://localhost:8000",
  sourceSlug,
  onAutoSettingsChange,
}: WidgetProps) {
  const [data, setData] = useState<BookState | null>(null);
  const [status, setStatus] = useState<"connecting" | "live" | "error">("connecting");
  const [copied, setCopied] = useState(false);
  
  const ws = useRef<WebSocket | null>(null);
  const spreadRef = useRef<HTMLTableRowElement>(null);
  const lastSpreadScrollRef = useRef(0);
  const autoPlacedRef = useRef(false); // Track if auto order has been placed
  const lastParseErrorRef = useRef(0);
  const parseErrorCountRef = useRef(0);
  const scrollTimerRef = useRef<number | null>(null);
  const lastTradeTsRef = useRef(0);
  // const tradeFlashTimerRef = useRef<number | null>(null);
  const [tradeFlashes, setTradeFlashes] = useState<
    Array<{ value: number; side: "BUY" | "SELL"; timestamp: number }>
  >([]);

  const [sharesRaw, setSharesRaw] = useState(defaultShares);
  const [ttlRaw, setTtlRaw] = useState(defaultTtl);
  const [sharesTouched, setSharesTouched] = useState(false);
  const [ttlTouched, setTtlTouched] = useState(false);
  const [level, setLevel] = useState(0);
  const [placing, setPlacing] = useState<"idle" | "buy" | "sell">("idle");
  const lastOrderTsRef = useRef<number>(0);
  const minOrderIntervalMs = 500;
  const serverOffsetSec = useMemo(() => {
    if (ordersServerNowSec && ordersServerNowLocalMs) {
      return ordersServerNowSec - Math.floor(ordersServerNowLocalMs / 1000);
    }
    return 0;
  }, [ordersServerNowSec, ordersServerNowLocalMs]);
  const [nowSec, setNowSec] = useState(() => Math.floor(Date.now() / 1000) + serverOffsetSec);

  const bestBid = data?.bids?.[0]?.price ?? null;
  const bestAsk = data?.asks?.[0]?.price ?? null;
  const tickSize = data?.tick_size ?? 0.01;
  useEffect(() => {
    onBookUpdate?.(assetId, bestBid, bestAsk);
  }, [assetId, bestBid, bestAsk, onBookUpdate]);
  const tradeFlashLabels = useMemo(() => {
    return tradeFlashes
      .filter((flash) => Number.isFinite(flash.value) && flash.value > 0)
      .map((flash) => {
        const sign = flash.side === "BUY" ? "+" : "-";
        return { ...flash, label: `${sign}$${flash.value.toFixed(0)}` };
      });
  }, [tradeFlashes]);

  const openOrderMap = useMemo(() => {
    const buys = new Map<string, number>();
    const sells = new Map<string, number>();
    const buyExp = new Map<string, number>();
    const sellExp = new Map<string, number>();
    const buyIds = new Map<string, string[]>();
    const sellIds = new Map<string, string[]>();
    for (const o of openOrders) {
      const priceNum = Number(o.price);
      const sizeNum = Number(o.size);
      const expirationNum = Number(o.expiration ?? 0);
      if (!Number.isFinite(priceNum) || !Number.isFinite(sizeNum)) continue;
      const key = formatOrderKey(priceNum, tickSize);
      const isBuy = o.side === "BUY";
      const target = isBuy ? buys : sells;
      const targetExp = isBuy ? buyExp : sellExp;
      const targetIds = isBuy ? buyIds : sellIds;
      target.set(key, (target.get(key) ?? 0) + sizeNum);
      const existingIds = targetIds.get(key) ?? [];
      existingIds.push(o.orderID);
      targetIds.set(key, existingIds);
      if (Number.isFinite(expirationNum) && expirationNum > 0) {
        const prev = targetExp.get(key);
        if (!prev || expirationNum < prev) targetExp.set(key, expirationNum);
      }
    }
    return { buys, sells, buyExp, sellExp, buyIds, sellIds };
  }, [openOrders, tickSize]);

  const shouldTick = useMemo(
    () => openOrders.some((o) => Number(o.expiration ?? 0) > 0),
    [openOrders]
  );

  useEffect(() => {
    if (!shouldTick) return;
    const timer = window.setInterval(() => {
      setNowSec(Math.floor(Date.now() / 1000) + serverOffsetSec);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [serverOffsetSec, shouldTick]);

  useEffect(() => {
    if (!shouldTick) return;
    setNowSec(Math.floor(Date.now() / 1000) + serverOffsetSec);
  }, [serverOffsetSec, shouldTick]);

  useEffect(() => {
    if (!onAutoSettingsChange) return;
    const shares = Number(sharesRaw);
    const ttl = Number(ttlRaw);
    onAutoSettingsChange(assetId, {
      shares: Number.isFinite(shares) ? shares : 0,
      ttl: Number.isFinite(ttl) ? ttl : 0,
      level,
    });
  }, [assetId, level, onAutoSettingsChange, sharesRaw, ttlRaw]);

  useEffect(() => {
    if (!sharesTouched) setSharesRaw(defaultShares);
  }, [defaultShares, sharesTouched]);

  useEffect(() => {
    if (!ttlTouched) setTtlRaw(defaultTtl);
  }, [defaultTtl, ttlTouched]);

  const formatRemaining = useCallback(
    (exp: number | undefined) => {
      if (!exp) return "";
      const remaining = exp - nowSec - 60;
      if (!Number.isFinite(remaining)) return "";
      if (remaining <= 0) return "exp";
      return `${remaining}s`;
    },
    [nowSec]
  );

  useEffect(() => {
    let isMounted = true;
    let reconnectTimer: number | null = null;
    let reconnectAttempts = 0;

    const params = new URLSearchParams();
    if (sourceSlug) params.set("slug", sourceSlug);
    if (marketQuestion) params.set("market_question", marketQuestion);
    if (outcomeName) params.set("outcome", outcomeName);

    const scheduleReconnect = () => {
      if (reconnectTimer !== null || !isMounted) return;
      const backoff = Math.min(5000, 500 * Math.pow(2, reconnectAttempts));
      const jitter = Math.floor(Math.random() * 250);
      reconnectAttempts += 1;
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        connect();
      }, backoff + jitter);
    };

    const connect = () => {
      if (!isMounted) return;
      setStatus("connecting");
      const socket = new WebSocket(`ws://localhost:8000/ws/${assetId}?${params.toString()}`);
      ws.current = socket;

      socket.onopen = () => {
        reconnectAttempts = 0;
        if (isMounted) setStatus("live");
      };
      socket.onclose = () => {
        if (isMounted) setStatus("connecting");
        scheduleReconnect();
      };
      socket.onerror = () => {
        if (isMounted) setStatus("error");
      };

      socket.onmessage = (event) => {
        if (!isMounted) return;
        try {
          if (typeof event.data !== "string") return;
          const trimmed = event.data.trim();
          if (!trimmed || (trimmed[0] !== "{" && trimmed[0] !== "[")) return;
          const parsed: unknown = JSON.parse(trimmed);
          const next = parseBookState(parsed);
          if (next) setData(next);
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        } catch (e) {
          parseErrorCountRef.current += 1;
          lastParseErrorRef.current = Date.now();
        }
      };
    };

    connect();

    return () => {
      isMounted = false;
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
      }
      const socket = ws.current;
      if (socket) {
        socket.onopen = null;
        socket.onclose = null;
        socket.onerror = null;
        socket.onmessage = null;
        socket.close();
      }
      ws.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assetId, marketQuestion, outcomeName, sourceSlug]);

  useEffect(() => {
    if (viewMode !== "full" || !data?.ready || !spreadRef.current) return;
    const now = Date.now();
    if (now - lastSpreadScrollRef.current < 200) return;
    lastSpreadScrollRef.current = now;
    if (scrollTimerRef.current !== null) {
      window.clearTimeout(scrollTimerRef.current);
    }
    scrollTimerRef.current = window.setTimeout(() => {
      const row = spreadRef.current;
      const viewport = row?.closest("[data-radix-scroll-area-viewport]") as HTMLElement | null;
      if (row && viewport) {
        viewport.scrollTop = row.offsetTop - viewport.clientHeight / 2 + row.offsetHeight / 2;
      }
      scrollTimerRef.current = null;
    }, 0);
    return () => {
      if (scrollTimerRef.current !== null) {
        window.clearTimeout(scrollTimerRef.current);
        scrollTimerRef.current = null;
      }
    };
  }, [data?.ready, data?.asks.length, data?.bids.length, viewMode]);

  useEffect(() => {
    const last = data?.last_trade;
    if (!last) return;
    if (!Number.isFinite(last.timestamp) || last.timestamp <= 0) return;
    if (last.timestamp === lastTradeTsRef.current) return;
    lastTradeTsRef.current = last.timestamp;
    const value = Math.max(0, last.price * last.size);
    const flash = { value, side: last.side, timestamp: last.timestamp };
    setTradeFlashes((prev) => [flash, ...prev].slice(0, 5));
    const timerId = window.setTimeout(() => {
      setTradeFlashes((prev) => prev.filter((item) => item.timestamp !== last.timestamp));
    }, 3000);
    return () => {
      window.clearTimeout(timerId);
    };
  }, [data?.last_trade]);

  const placeLimitOrder = async (side: "BUY" | "SELL"): Promise<void> => {
    try {
      const now = Date.now();
      if (now - lastOrderTsRef.current < minOrderIntervalMs) {
        return;
      }
      lastOrderTsRef.current = now;
      setPlacing(side === "BUY" ? "buy" : "sell");
      const calculatedOffset = side === "BUY" ? buyOffsetCents : sellOffsetCents;

      const payload = {
        token_id: assetId,
        side,
        size: Number(sharesRaw),
        ttl_seconds: ttlRaw === "" ? 0 : Number(ttlRaw),
        price_offset_cents: calculatedOffset,
      };

      await fetch(`${apiBaseUrl}/orders/limit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } catch (e) {
      console.error("Order failed", { e });
    } finally {
      setPlacing("idle");
    }
  };

  const buildBidPlacementPrices = (prices: number[], tick: number): number[] => {
    const out: number[] = [];
    let prev: number | null = null;
    const rounded = (val: number) => Number(val.toFixed(decimalsForTick(tick)));
    const pushUnique = (val: number) => {
      if (out.length === 0) {
        out.push(val);
        return;
      }
      if (Math.abs(out[out.length - 1] - val) >= tick / 2) {
        out.push(val);
      }
    };
    for (const price of prices) {
      if (prev !== null && prev - price > tick) {
        pushUnique(rounded(price + tick));
        pushUnique(rounded(price));
      } else {
        pushUnique(rounded(price));
      }
      prev = price;
    }
    return out;
  };

  const buildAskPlacementPrices = (prices: number[], tick: number): number[] => {
    const out: number[] = [];
    let prev: number | null = null;
    const rounded = (val: number) => Number(val.toFixed(decimalsForTick(tick)));
    const pushUnique = (val: number) => {
      if (out.length === 0) {
        out.push(val);
        return;
      }
      if (Math.abs(out[out.length - 1] - val) >= tick / 2) {
        out.push(val);
      }
    };
    for (const price of prices) {
      if (prev !== null && price - prev > tick) {
        pushUnique(rounded(prev + tick));
        pushUnique(rounded(price));
      } else {
        pushUnique(rounded(price));
      }
      prev = price;
    }
    return out;
  };

  const bidPlacements = useMemo(() => {
    if (!data?.bids?.length) return [];
    const tick = tickSize || 0.01;
    return buildBidPlacementPrices(
      data.bids.map((b) => b.price),
      tick
    );
  }, [data?.bids, tickSize]);

  const askPlacements = useMemo(() => {
    if (!data?.asks?.length) return [];
    const tick = tickSize || 0.01;
    return buildAskPlacementPrices(
      data.asks.map((a) => a.price),
      tick
    );
  }, [data?.asks, tickSize]);

  const maxNegativeLevel = useMemo(() => {
    const maxIndex = Math.max(bidPlacements.length, askPlacements.length) - 1;
    return Math.max(0, maxIndex);
  }, [bidPlacements.length, askPlacements.length]);

  const maxPositiveLevel = useMemo(() => {
    if (bestBid === null || bestAsk === null) return 0;
    const tick = tickSize || 0.01;
    const steps = Math.floor((bestAsk - bestBid) / tick) - 1;
    return Math.max(0, steps);
  }, [bestAsk, bestBid, tickSize]);

  useEffect(() => {
    setLevel((v) => Math.max(-maxNegativeLevel, Math.min(maxPositiveLevel, v)));
  }, [maxNegativeLevel, maxPositiveLevel]);

  const clampedLevel = Math.max(-maxNegativeLevel, Math.min(maxPositiveLevel, level));
  const levelIndex = Math.min(Math.abs(clampedLevel), maxNegativeLevel);
  const tick = tickSize || 0.01;
  let buyPrice = bidPlacements[levelIndex] ?? bestBid;
  let sellPrice = askPlacements[levelIndex] ?? bestAsk;
  if (clampedLevel > 0 && bestBid !== null && bestAsk !== null) {
    buyPrice = Math.min(bestAsk - tick, bestBid + clampedLevel * tick);
    sellPrice = Math.max(bestBid + tick, bestAsk - clampedLevel * tick);
  }
  const buyOffsetCents = clampInt(
    bestBid !== null && buyPrice !== null ? Math.round((buyPrice - bestBid) * 100) : 0,
    -50,
    50
  );
  const sellOffsetCents = clampInt(
    bestAsk !== null && sellPrice !== null ? Math.round((sellPrice - bestAsk) * 100) : 0,
    -50,
    50
  );

  const setNextBestOffsetDown = useCallback(() => {
    setLevel((v) => Math.max(-maxNegativeLevel, v - 1));
  }, [maxNegativeLevel]);

  const setNextBestOffsetUp = useCallback(() => {
    setLevel((v) => Math.min(maxPositiveLevel, v + 1));
  }, [maxPositiveLevel]);

  // Calculate exposure difference
  const getExposureDifference = useCallback((): number => {
    const currentPosition = positionShares ?? 0;
    const otherPosition = otherAssetPositionShares ?? 0;
    return currentPosition - otherPosition;
  }, [positionShares, otherAssetPositionShares]);

  // Determine which side to trade based on exposure
  const getAutoTradeSide = useCallback((): "BUY" | "SELL" => {
    const currentPosition = positionShares ?? 0;
    const otherPosition = otherAssetPositionShares ?? 0;
    // New rule: if both legs hold at least 20 shares, favor selling to reduce exposure on both.
    if (currentPosition >= 20 && otherPosition >= 20) {
      return "SELL";
    }

    const exposureDiff = getExposureDifference();
    
    // If we have more than 20 shares of this asset compared to the other
    if (exposureDiff >= 20) {
      return "SELL"; // Sell to reduce exposure
    } 
    // If we have more than 20 shares less of this asset compared to the other
    else if (exposureDiff <= -20) {
      return "BUY"; // Buy to increase exposure
    }
    // Within acceptable range, place BUY order by default
    else {
      return "BUY";
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [getExposureDifference]);

  // NEW: Auto-trading logic - place order when auto is true and no open orders exist
  useEffect(() => {
    // Only run in full view mode with auto enabled
    if (autoMode === "server" || viewMode !== "full" || !auto) {
      autoPlacedRef.current = false; // Reset when auto is disabled
      return;
    }

    // Check if data is ready and we have market prices
    if (data?.ready && bestBid !== null && bestAsk !== null) {
      // Check if there are no open orders
      const hasOpenOrders = openOrders.length > 0;
      
      // If no open orders and we haven't placed an auto order yet
      if (!hasOpenOrders && !autoPlacedRef.current && placing === "idle") {
        // Determine which side to trade based on exposure
        const tradeSide = autoTradeSide ?? getAutoTradeSide();
        if (tradeSide === "BUY" && !autoBuyAllowed) return;
        if (tradeSide === "SELL" && !autoSellAllowed) return;

        autoPlacedRef.current = true; // Mark as placed
        placeLimitOrder(tradeSide).catch(console.error);
      } else if (hasOpenOrders) {
        // Reset the flag when new orders appear (so we can place again when they're gone)
        autoPlacedRef.current = false;
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    data?.ready, 
    bestBid, 
    bestAsk, 
    openOrders.length, 
    auto, 
    viewMode, 
    placing, 
    assetId,
    autoTradeSide,
    getAutoTradeSide, // Add dependency
  ]);

  // NEW: Reset auto placement flag when auto prop changes
  useEffect(() => {
    if (!auto || autoMode === "server") {
      autoPlacedRef.current = false;
    }
  }, [auto, autoMode]);

  // Add exposure indicator to the UI
  const exposureDiff = useMemo(() => getExposureDifference(), [getExposureDifference]);
  const exposureStatus = useMemo(() => {
    if (exposureDiff >= 20) return { text: "OVEREXPOSED", color: "text-red-400", bg: "bg-red-950/30" };
    if (exposureDiff <= -20) return { text: "UNDEREXPOSED", color: "text-amber-400", bg: "bg-amber-950/30" };
    return { text: "BALANCED", color: "text-emerald-400", bg: "bg-emerald-950/30" };
  }, [exposureDiff]);

  const placeMarketOrder = async (side: "BUY" | "SELL"): Promise<void> => {
    try {
      const amountNum = Number(sharesRaw);
      if (!Number.isFinite(amountNum) || amountNum <= 0) return;
      const bestAskNum = typeof bestAsk === "number" ? bestAsk : null;
      const rawMarketAmount =
        side === "BUY" && bestAskNum && bestAskNum > 0 ? amountNum * bestAskNum : amountNum;
      const marketAmount =
        side === "BUY" ? Math.max(rawMarketAmount - 0.02, 0.01) : rawMarketAmount;
      const confirmText =
        side === "BUY"
          ? `Market BUY $${marketAmount.toFixed(2)} USDC at best ask?`
          : `Market SELL ${amountNum} shares at best bid?`;
      if (!window.confirm(confirmText)) return;

      const resp = await fetch(`${apiBaseUrl}/orders/market`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          token_id: assetId,
          side,
          amount: marketAmount,
          fok_only: true,
        }),
      });
      if (!resp.ok) {
        await resp.json().catch(() => null);
        return;
      }
      await resp.json().catch(() => null);
    } catch (e) {
      console.error("Market order failed", { e });
    }
  };

  const cancelOrdersAtPrice = async (side: "BUY" | "SELL", priceKey: string): Promise<void> => {
    const idsMap = side === "BUY" ? openOrderMap.buyIds : openOrderMap.sellIds;
    const ids = idsMap.get(priceKey) ?? [];
    if (!ids.length) return;
    const confirmText = `Cancel ${ids.length} ${side} order${ids.length > 1 ? "s" : ""} at ${priceKey}¢?`;
    if (!window.confirm(confirmText)) return;

    await Promise.all(
      ids.map((orderId) =>
        fetch(`${apiBaseUrl}/orders/cancel`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ order_id: orderId }),
        }).catch(() => {})
      )
    );
  };

  const btnStyles = "hover:cursor-pointer font-bold bg-sky-500 hover:bg-sky-400 border-b-4 border-sky-700 hover:translate-y-0.5 hover:border-b-2 active:translate-y-1 active:border-b-0 transition-all text-white disabled:opacity-50 disabled:translate-y-0 disabled:border-b-4";

  const handleCopyAssetId = useCallback(async (): Promise<void> => {
    await copyToClipboard(assetId);
    setCopied(true);
    setTimeout(() => setCopied(false), 900);
  }, [assetId]);

 

  // const placeLimitOrder = async (side: "BUY" | "SELL"): Promise<void> => {
  //   try {
  //     setPlacing(side === "BUY" ? "buy" : "sell");
  //     const payload = {
  //       token_id: assetId,
  //       side,
  //       size: Number(sharesRaw),
  //       ttl_seconds: ttlRaw === "" ? 0 : Number(ttlRaw),
  //       price_offset_cents: buyOffsetCents,
  //     };

  //     await fetch(`${apiBaseUrl}/orders/limit`, {
  //       method: "POST",
  //       headers: { "Content-Type": "application/json" },
  //       body: JSON.stringify(payload),
  //     });
  //   } catch (e) {
  //     console.error("Order failed - see server terminal.", {e});
  //   } finally {
  //     setPlacing("idle");
  //   }
  // };

  if (viewMode === "mini") {
    const holdingLabel =
      positionShares && positionShares > 0 ? `${positionShares.toFixed(2)} sh` : null;
    const avgLabel =
      positionAvgPrice && positionAvgPrice > 0 ? `${formatCents(positionAvgPrice, tickSize)}¢` : null;
    return (
      <div className="relative">
        {onClose && (
          <button onClick={() => onClose(assetId)} className="absolute -top-3 right-3 z-20 h-7 w-7 rounded-full border border-slate-800 bg-slate-950 text-slate-300 hover:text-white">×</button>
        )}
        <Card
          className={`border-slate-800 bg-slate-950 text-slate-200 w-full h-[140px] flex flex-col shrink-0 transition-all ${
            isHighlighted ? "ring-2 ring-blue-500" : ""
          } ${auto ? "ring-2 ring-amber-400/80" : ""}`}
        >
          <CardHeader
            className="pb-2 pt-4 px-4 bg-slate-950 rounded-t-lg cursor-pointer"
            onClick={() => onHeaderClick?.(assetId)}
          >
            <div className="flex justify-between items-start gap-2">
              <div className="flex flex-col overflow-hidden">
                <CardTitle className="text-sm font-bold text-white truncate">{outcomeName}</CardTitle>
                <div className="flex items-center gap-2 mt-1">
                  <button
                    onClick={(event) => {
                      event.stopPropagation();
                      handleCopyAssetId();
                    }}
                    className="text-[10px] text-slate-600 font-mono hover:text-slate-200"
                  >
                    {assetId.slice(0, 8)}...
                  </button>
                  {copied && <span className="text-[10px] font-mono text-green-400">Copied</span>}
                </div>
              </div>
              <div className="flex items-center gap-1.5">
                <span className={`h-1.5 w-1.5 rounded-full ${status === "live" ? "bg-green-500" : "bg-red-500"}`} />
                <span className="text-[10px] text-blue-400 font-mono">${formatVol(volume)}</span>
              </div>
            </div>
            {holdingLabel && (
              <div className="mt-2 text-[10px] font-mono text-emerald-400">
                HOLD {holdingLabel}{avgLabel ? ` @ ${avgLabel}` : ""}
              </div>
            )}
          </CardHeader>
          <CardContent className="px-4 pb-4 pt-0 flex items-center justify-between gap-2 h-full">
            <div className="flex-1 bg-green-950/20 border border-green-900/30 rounded p-2 flex flex-col items-center">
              <span className="text-[10px] text-green-600 uppercase font-bold">Bid</span>
              <span className="text-xl font-mono text-green-400">{bestBid !== null ? formatPrice(bestBid, tickSize) : "-"}</span>
            </div>
            <div className="flex-1 bg-red-950/20 border border-red-900/30 rounded p-2 flex flex-col items-center">
              <span className="text-[10px] text-red-600 uppercase font-bold">Ask</span>
              <span className="text-xl font-mono text-red-400">{bestAsk !== null ? formatPrice(bestAsk, tickSize) : "-"}</span>
            </div>
          </CardContent>
        </Card>
        {tradeFlashLabels.map((flash, idx) => (
          <div
            key={`trade-${flash.timestamp}`}
            className={`pointer-events-none absolute left-4 top-4 text-sm font-bold ${
              flash.side === "BUY" ? "text-emerald-400" : "text-red-400"
            } trade-flash`}
            style={{ ["--flash-offset" as string]: `${idx * 16}px` }}
          >
            {flash.label}
          </div>
        ))}
        <style>{`
          @keyframes trade-flash-rise {
            0% { opacity: 0; transform: translateY(calc(var(--flash-offset) + 6px)); }
            15% { opacity: 1; transform: translateY(var(--flash-offset)); }
            100% { opacity: 0; transform: translateY(calc(var(--flash-offset) - 10px)); }
          }
          .trade-flash {
            animation: trade-flash-rise 3s ease-out forwards;
          }
        `}</style>
      </div>
    );
  }

  return (
    <div className="relative">
      {onClose && (
        <button onClick={() => onClose(assetId)} className="absolute -top-3 right-3 z-20 h-7 w-7 rounded-full border border-slate-800 bg-slate-950 text-slate-300 hover:text-white shadow">×</button>
      )}
      <Card
        className={`border-slate-800 bg-slate-950 text-slate-200 shadow-xl flex flex-col w-full h-[470px] transition-all ${
          isHighlighted ? "ring-2 ring-blue-500 shadow-blue-500/20" : ""
        } ${auto ? "ring-2 ring-amber-400/80" : ""}`}
      >
        <CardHeader
          className="pb-2 pt-4 px-4 bg-slate-950 border-b border-slate-900 shrink-0 cursor-pointer"
          onClick={() => onHeaderClick?.(assetId)}
        >
          <div className="flex justify-between items-start">
            <div className="flex flex-col overflow-hidden">
              <CardTitle className="text-md font-bold text-white truncate">{outcomeName}</CardTitle>
              <button
                onClick={(event) => {
                  event.stopPropagation();
                  handleCopyAssetId();
                }}
                className="text-[10px] text-slate-600 font-mono hover:text-slate-200 text-left mt-1"
              >
                {assetId.slice(0, 12)}...
              </button>
            </div>
            <div className="flex flex-col items-end gap-1.5">
              <div className="flex items-center gap-1.5">
                <span className={`h-1.5 w-1.5 rounded-full ${status === "live" ? "bg-green-500" : "bg-red-500"}`} />
                <Badge variant="outline" className="text-[10px] bg-slate-900 text-blue-400 border-slate-800">${formatVol(volume)} Vol</Badge>
              </div>
              {/* Exposure status badge - only show when auto trading is enabled */}
              {auto && otherAssetPositionShares !== undefined && (
                <div className={`text-[10px] px-1.5 py-0.5 rounded font-mono border ${exposureStatus.bg} border-slate-800 ${exposureStatus.color}`}>
                  {exposureStatus.text} ({exposureDiff > 0 ? "+" : ""}{exposureDiff.toFixed(1)})
                </div>
              )}
              {userPosition && (
                <div className={`text-[10px] px-1.5 py-0.5 rounded font-mono border ${userPosition.side === "BUY" ? "bg-blue-950/30 border-blue-900 text-blue-300" : "bg-red-950/30 border-red-900 text-red-300"}`}>
                  <span className="font-bold">{userPosition.side}</span> @ <span className="text-white">{formatCents(userPosition.price, tickSize)}¢</span>
                </div>
              )}
              {positionShares && positionShares > 0 && (
                <div className="text-[10px] px-1.5 py-0.5 rounded font-mono border bg-emerald-950/30 border-emerald-900 text-emerald-300">
                  HOLD {positionShares.toFixed(2)} sh
                  {positionAvgPrice && positionAvgPrice > 0 ? ` @ ${formatCents(positionAvgPrice, tickSize)}¢` : ""}
                </div>
              )}
            </div>
          </div>
        </CardHeader>

        <CardContent className="p-0 flex flex-col flex-1 overflow-hidden">
          {!data?.ready ? (
            <div className="flex flex-col items-center justify-center h-full text-slate-500 gap-3">
              <div className="h-5 w-5 animate-spin rounded-full border-2 border-slate-800 border-t-blue-500" />
              <span className="text-[10px] uppercase">Connecting...</span>
            </div>
          ) : (
            <>
              <ScrollArea className="flex-1 w-full">
                <Table className="table-fixed">
                  <TableBody className="text-xs font-mono">
                    {data.asks.slice().reverse().map((row, i) => {
                      const isBestAsk = i === data.asks.length - 1;
                      const priceKey = formatOrderKey(row.price, tickSize);
                      const hasOrders = openOrderMap.sells.has(priceKey);
                      return (
                      <TableRow
                        key={`ask-${i}`}
                        onClick={
                          hasOrders
                            ? () => void cancelOrdersAtPrice("SELL", priceKey)
                            : isBestAsk
                            ? () => void placeMarketOrder("BUY")
                            : undefined
                        }
                        className={`border-0 h-5 ${
                          hasOrders
                            ? "cursor-pointer hover:bg-red-950/40"
                            : isBestAsk
                            ? "cursor-pointer hover:bg-blue-950/30"
                            : "hover:bg-red-950/10"
                        } ${
                          openOrderMap.sells.has(priceKey)
                            ? "bg-red-950/30"
                            : ""
                        }`}
                      >
                        <TableCell className="text-left text-emerald-400 py-0.5 w-7">
                          {openOrderMap.sells.has(priceKey) ? (
                            <div className="flex items-center gap-1">
                              <span>{openOrderMap.sells.get(priceKey)?.toFixed(2)}</span>
                              <span className="text-[9px] text-slate-500">
                                {formatRemaining(openOrderMap.sellExp.get(priceKey))}
                              </span>
                            </div>
                          ) : (
                            ""
                          )}
                        </TableCell>
                        <TableCell className="text-right text-red-400 py-0.5 w-20">{formatPrice(row.price, tickSize)}</TableCell>
                        <TableCell className="text-right py-0.5 text-slate-400">{row.size.toFixed(1)}</TableCell>
                        <TableCell className="text-right text-slate-600 py-0.5 pr-4">${row.cum.toFixed(2)}</TableCell>
                      </TableRow>
                      );
                    })}
                    <TableRow ref={spreadRef} className="bg-slate-900 h-1.5"><TableCell colSpan={4} className="py-0 border-y border-slate-800/40" /></TableRow>
                    {data.bids.map((row, i) => {
                      const isBestBid = i === 0;
                      const priceKey = formatOrderKey(row.price, tickSize);
                      const hasOrders = openOrderMap.buys.has(priceKey);
                      return (
                      <TableRow
                        key={`bid-${i}`}
                        onClick={
                          hasOrders
                            ? () => void cancelOrdersAtPrice("BUY", priceKey)
                            : isBestBid
                            ? () => void placeMarketOrder("SELL")
                            : undefined
                        }
                        className={`border-0 h-5 ${
                          hasOrders
                            ? "cursor-pointer hover:bg-green-950/40"
                            : isBestBid
                            ? "cursor-pointer hover:bg-amber-950/30"
                            : "hover:bg-green-950/10"
                        } ${
                          openOrderMap.buys.has(priceKey)
                            ? "bg-green-950/30"
                            : ""
                        }`}
                      >
                        <TableCell className="text-left text-emerald-400 py-0.5 w-10">
                          {openOrderMap.buys.has(priceKey) ? (
                            <div className="flex items-center gap-1">
                              <span>{openOrderMap.buys.get(priceKey)?.toFixed(2)}</span>
                              <span className="text-[9px] text-slate-500">
                                {formatRemaining(openOrderMap.buyExp.get(priceKey))}
                              </span>
                            </div>
                          ) : (
                            ""
                          )}
                        </TableCell>
                        <TableCell className="text-right text-green-400 py-0.5 w-20">{formatPrice(row.price, tickSize)}</TableCell>
                        <TableCell className="text-right py-0.5 text-slate-400">{row.size.toFixed(1)}</TableCell>
                        <TableCell className="text-right text-slate-600 py-0.5 pr-4">${row.cum.toFixed(2)}</TableCell>
                      </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </ScrollArea>

                <div className="mt-0 grid grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <label className="text-[10px] text-slate-500 uppercase font-bold">Shares</label>
                    <Input
                      value={sharesRaw}
                      onChange={(e) => {
                        setSharesRaw(e.target.value);
                        setSharesTouched(true);
                      }}
                      onFocus={(e) => e.currentTarget.select()}
                      className="h-8 bg-black border-slate-800 font-mono text-sm"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="text-[10px] text-slate-500 uppercase font-bold">TTL (seconds)</label>
                    <Input
                      value={ttlRaw}
                      onChange={(e) => {
                        setTtlRaw(e.target.value);
                        setTtlTouched(true);
                      }}
                      onFocus={(e) => e.currentTarget.select()}
                      className="h-8 bg-black border-slate-800 font-mono text-sm"
                    />
                  </div>
                </div>

              {/* Trade Panel: Flush with bottom */}
              <div className=" bg-slate-950/80 p-3 shrink-0">
                <div className="flex items-center justify-between">
                  <div className="flex gap-2 items-center">
                    <Button 
                      size="sm" 
                      className={`${btnStyles} h-7 px-4 text-xs`}
                      onClick={setNextBestOffsetUp}
                    >
                      +1¢
                    </Button>
                    <Button 
                      size="sm" 
                      className={`${btnStyles} h-7 px-4 text-xs`}
                      onClick={setNextBestOffsetDown}
                    >
                      -1¢
                    </Button>
                    <Button
                      size="sm"
                      className={`${btnStyles} h-7 px-4 text-xs`}
                      onClick={() => {
                        setLevel(0);
                      }}
                    >
                      Clear
                    </Button>
                  </div>
                  <div className="h-7 px-3 flex items-center rounded border border-slate-800 bg-slate-950 text-[10px] font-mono text-slate-200">
                    level {clampedLevel >= 0 ? "+" : ""}{clampedLevel}
                  </div>
                </div>

                <div className="mt-3 grid grid-cols-2 gap-3">
                  <Button disabled={placing !== "idle" || !bestBid} onClick={() => void placeLimitOrder("BUY")} className="hover:cursor-pointer h-10 font-bold bg-sky-500 hover:bg-sky-400 border-b-4 border-sky-700 hover:translate-y-0.5 hover:border-b-2 active:translate-y-1 active:border-b-0 transition-all text-white">
                    {placing === "buy" ? "..." : `BUY @ ${buyPrice !== null ? formatCents(buyPrice, tickSize) : "—"}¢`}
                  </Button>
                  <Button disabled={placing !== "idle" || !bestAsk} onClick={() => void placeLimitOrder("SELL")} className="hover:cursor-pointer h-10 font-bold bg-sky-500 hover:bg-sky-400 border-b-4 border-sky-700 hover:translate-y-0.5 hover:border-b-2 active:translate-y-1 active:border-b-0 transition-all text-white">
                    {placing === "sell" ? "..." : `SELL @ ${sellPrice !== null ? formatCents(sellPrice, tickSize) : "—"}¢`}
                  </Button>
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>
      {tradeFlashLabels.map((flash, idx) => (
        <div
          key={`trade-${flash.timestamp}`}
          className={`pointer-events-none absolute left-4 top-4 text-sm font-bold ${
            flash.side === "BUY" ? "text-emerald-400" : "text-red-400"
          } trade-flash`}
          style={{ ["--flash-offset" as string]: `${idx * 16}px` }}
        >
          {flash.label}
        </div>
      ))}
      <style>{`
        @keyframes trade-flash-rise {
          0% { opacity: 0; transform: translateY(calc(var(--flash-offset) + 6px)); }
          15% { opacity: 1; transform: translateY(var(--flash-offset)); }
          100% { opacity: 0; transform: translateY(calc(var(--flash-offset) - 10px)); }
        }
        .trade-flash {
          animation: trade-flash-rise 3s ease-out forwards;
        }
      `}</style>
    </div>
  );
}
