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
  userPosition?: UserPosition | null;
  positionShares?: number | null;
  positionAvgPrice?: number | null;
  openOrders?: OpenOrder[];
  ordersServerNowSec?: number | null;
  ordersServerNowLocalMs?: number | null;
  defaultShares?: string;
  defaultTtl?: string;
  isHighlighted?: boolean;
  viewMode?: "full" | "mini";
  onClose?: (assetId: string) => void;
  apiBaseUrl?: string;
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

  return {
    ready,
    msg_count,
    bids: bids.filter(isOrderLevel),
    asks: asks.filter(isOrderLevel),
    tick_size: typeof tick_size === "number" ? tick_size : 0.01,
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
  const log = Math.round(-Math.log10(tickSize));
  return Math.max(0, Math.min(6, log));
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
  userPosition,
  positionShares,
  positionAvgPrice,
  openOrders = [],
  ordersServerNowSec,
  ordersServerNowLocalMs,
  defaultShares = "5",
  defaultTtl = "10",
  isHighlighted,
  viewMode = "full",
  onClose,
  apiBaseUrl = "http://localhost:8000",
}: WidgetProps) {
  const [data, setData] = useState<BookState | null>(null);
  const [status, setStatus] = useState<"connecting" | "live" | "error">("connecting");
  const [copied, setCopied] = useState(false);
  
  const ws = useRef<WebSocket | null>(null);
  const spreadRef = useRef<HTMLTableRowElement>(null);
  const hasScrolledRef = useRef(false);

  const [sharesRaw, setSharesRaw] = useState(defaultShares);
  const [ttlRaw, setTtlRaw] = useState(defaultTtl);
  const [sharesTouched, setSharesTouched] = useState(false);
  const [ttlTouched, setTtlTouched] = useState(false);
  const [offsetCents, setOffsetCents] = useState(0); // This now represents "Aggression"
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
  const openOrderMap = useMemo(() => {
    const buys = new Map<string, number>();
    const sells = new Map<string, number>();
    const buyExp = new Map<string, number>();
    const sellExp = new Map<string, number>();
    for (const o of openOrders) {
      const priceNum = Number(o.price);
      const sizeNum = Number(o.size);
      const expirationNum = Number(o.expiration ?? 0);
      if (!Number.isFinite(priceNum) || !Number.isFinite(sizeNum)) continue;
      const key = formatOrderKey(priceNum, tickSize);
      const isBuy = o.side === "BUY";
      const target = isBuy ? buys : sells;
      const targetExp = isBuy ? buyExp : sellExp;
      target.set(key, (target.get(key) ?? 0) + sizeNum);
      if (Number.isFinite(expirationNum) && expirationNum > 0) {
        const prev = targetExp.get(key);
        if (!prev || expirationNum < prev) targetExp.set(key, expirationNum);
      }
    }
    return { buys, sells, buyExp, sellExp };
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

  // Fix 1: WebSocket Cleanup and Reference Guarding
  useEffect(() => {
    let isMounted = true;
    const socket = new WebSocket(`ws://localhost:8000/ws/${assetId}`);
    ws.current = socket;

    socket.onopen = () => { if (isMounted) setStatus("live"); };
    socket.onclose = () => { if (isMounted) setStatus("connecting"); };
    socket.onerror = () => { if (isMounted) setStatus("error"); };
    
    socket.onmessage = (event) => {
      if (!isMounted) return;
      try {
        const parsed: unknown = JSON.parse(event.data);
        const next = parseBookState(parsed);
        if (next) setData(next);
      } catch (e) {
        console.error("Failed to parse WS message", e);
      }
    };

    return () => {
      isMounted = false;
      // Explicitly nulling handlers helps garbage collection
      socket.onopen = null;
      socket.onclose = null;
      socket.onerror = null;
      socket.onmessage = null;
      socket.close();
      ws.current = null;
    };
  }, [assetId]);

  // Fix 2: Timer Cleanup for Auto-Scrolling
  useEffect(() => {
    let scrollTimer: number | null = null;

    if (viewMode === "full" && data?.ready && spreadRef.current && !hasScrolledRef.current) {
      scrollTimer = window.setTimeout(() => {
        const row = spreadRef.current;
        const viewport = row?.closest("[data-radix-scroll-area-viewport]") as HTMLElement | null;
        if (row && viewport) {
          viewport.scrollTop = row.offsetTop - viewport.clientHeight / 2 + row.offsetHeight / 2;
          hasScrolledRef.current = true;
        }
      }, 100);
    }

    return () => {
      if (scrollTimer) window.clearTimeout(scrollTimer);
    };
  }, [data?.ready, viewMode]);

  const placeLimitOrder = async (side: "BUY" | "SELL"): Promise<void> => {
    try {
      const now = Date.now();
      if (now - lastOrderTsRef.current < minOrderIntervalMs) {
        return;
      }
      lastOrderTsRef.current = now;
      setPlacing(side === "BUY" ? "buy" : "sell");
      
      // BUY moves UP with offset, SELL moves DOWN with offset
      const calculatedOffset = side === "BUY" ? offsetCents : -offsetCents;

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

  const placeMarketOrder = async (side: "BUY" | "SELL"): Promise<void> => {
    try {
      const sizeNum = Number(sharesRaw);
      if (!Number.isFinite(sizeNum) || sizeNum <= 0) return;
      const confirmText =
        side === "BUY"
          ? `Market BUY ${sizeNum} shares at best ask?`
          : `Market SELL ${sizeNum} shares at best bid?`;
      if (!window.confirm(confirmText)) return;

      await fetch(`${apiBaseUrl}/orders/market`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          token_id: assetId,
          side,
          size: sizeNum,
        }),
      });
    } catch (e) {
      console.error("Market order failed", { e });
    }
  };

  const btnStyles = "hover:cursor-pointer font-bold bg-sky-500 hover:bg-sky-400 border-b-4 border-sky-700 hover:translate-y-0.5 hover:border-b-2 active:translate-y-1 active:border-b-0 transition-all text-white disabled:opacity-50 disabled:translate-y-0 disabled:border-b-4";

  const handleCopyAssetId = useCallback(async (): Promise<void> => {
    await copyToClipboard(assetId);
    setCopied(true);
    setTimeout(() => setCopied(false), 900);
  }, [assetId]);

  useEffect(() => {
    if (viewMode === "full" && data?.ready && spreadRef.current && !hasScrolledRef.current) {
      window.setTimeout(() => {
        const row = spreadRef.current;
        const viewport = row?.closest("[data-radix-scroll-area-viewport]") as HTMLElement | null;
        if (row && viewport) {
          viewport.scrollTop = row.offsetTop - viewport.clientHeight / 2 + row.offsetHeight / 2;
          hasScrolledRef.current = true;
        }
      }, 100);
    }
  }, [data?.ready, viewMode]);

  // const placeLimitOrder = async (side: "BUY" | "SELL"): Promise<void> => {
  //   try {
  //     setPlacing(side === "BUY" ? "buy" : "sell");
  //     const payload = {
  //       token_id: assetId,
  //       side,
  //       size: Number(sharesRaw),
  //       ttl_seconds: ttlRaw === "" ? 0 : Number(ttlRaw),
  //       price_offset_cents: offsetCents,
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
        <Card className={`border-slate-800 bg-slate-950 text-slate-200 w-full h-[140px] flex flex-col shrink-0 transition-all ${isHighlighted ? "ring-2 ring-blue-500" : ""}`}>
          <CardHeader className="pb-2 pt-4 px-4 bg-slate-950 rounded-t-lg">
            <div className="flex justify-between items-start gap-2">
              <div className="flex flex-col overflow-hidden">
                <CardTitle className="text-sm font-bold text-white truncate">{outcomeName}</CardTitle>
                <div className="flex items-center gap-2 mt-1">
                  <button onClick={handleCopyAssetId} className="text-[10px] text-slate-600 font-mono hover:text-slate-200">{assetId.slice(0, 8)}...</button>
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
      </div>
    );
  }

  return (
    <div className="relative">
      {onClose && (
        <button onClick={() => onClose(assetId)} className="absolute -top-3 right-3 z-20 h-7 w-7 rounded-full border border-slate-800 bg-slate-950 text-slate-300 hover:text-white shadow">×</button>
      )}
      <Card className={`border-slate-800 bg-slate-950 text-slate-200 shadow-xl flex flex-col w-full h-[520px] transition-all ${isHighlighted ? "ring-2 ring-blue-500 shadow-blue-500/20" : ""}`}>
        <CardHeader className="pb-2 pt-4 px-4 bg-slate-950 border-b border-slate-900 shrink-0">
          <div className="flex justify-between items-start">
            <div className="flex flex-col overflow-hidden">
              <CardTitle className="text-md font-bold text-white truncate">{outcomeName}</CardTitle>
              <button onClick={handleCopyAssetId} className="text-[10px] text-slate-600 font-mono hover:text-slate-200 text-left mt-1">{assetId.slice(0, 12)}...</button>
            </div>
            <div className="flex flex-col items-end gap-1.5">
              <div className="flex items-center gap-1.5">
                <span className={`h-1.5 w-1.5 rounded-full ${status === "live" ? "bg-green-500" : "bg-red-500"}`} />
                <Badge variant="outline" className="text-[10px] bg-slate-900 text-blue-400 border-slate-800">${formatVol(volume)} Vol</Badge>
              </div>
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
                      return (
                      <TableRow
                        key={`ask-${i}`}
                        onClick={isBestAsk ? () => void placeMarketOrder("BUY") : undefined}
                        className={`border-0 h-5 ${
                          isBestAsk ? "cursor-pointer hover:bg-blue-950/30" : "hover:bg-red-950/10"
                        } ${
                          openOrderMap.sells.has(formatOrderKey(row.price, tickSize))
                            ? "bg-red-950/30"
                            : ""
                        }`}
                      >
                        <TableCell className="text-left text-emerald-400 py-0.5 w-7">
                          {openOrderMap.sells.has(formatOrderKey(row.price, tickSize)) ? (
                            <div className="flex items-center gap-1">
                              <span>{openOrderMap.sells.get(formatOrderKey(row.price, tickSize))?.toFixed(2)}</span>
                              <span className="text-[9px] text-slate-500">
                                {formatRemaining(openOrderMap.sellExp.get(formatOrderKey(row.price, tickSize)))}
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
                      return (
                      <TableRow
                        key={`bid-${i}`}
                        onClick={isBestBid ? () => void placeMarketOrder("SELL") : undefined}
                        className={`border-0 h-5 ${
                          isBestBid ? "cursor-pointer hover:bg-amber-950/30" : "hover:bg-green-950/10"
                        } ${
                          openOrderMap.buys.has(formatOrderKey(row.price, tickSize))
                            ? "bg-green-950/30"
                            : ""
                        }`}
                      >
                        <TableCell className="text-left text-emerald-400 py-0.5 w-10">
                          {openOrderMap.buys.has(formatOrderKey(row.price, tickSize)) ? (
                            <div className="flex items-center gap-1">
                              <span>{openOrderMap.buys.get(formatOrderKey(row.price, tickSize))?.toFixed(2)}</span>
                              <span className="text-[9px] text-slate-500">
                                {formatRemaining(openOrderMap.buyExp.get(formatOrderKey(row.price, tickSize)))}
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

              {/* Trade Panel: Flush with bottom */}
              <div className="border-t border-slate-800 bg-slate-950/80 p-3 shrink-0">
                <div className="flex items-center justify-between">
                  <div className="flex gap-2 items-center">
                    <Button 
                      size="sm" 
                      className={`${btnStyles} h-7 px-4 text-xs`}
                      onClick={() => setOffsetCents(v => clampInt(v - 1, -20, 20))}
                    >
                      -1¢
                    </Button>
                    <Button 
                      size="sm" 
                      className={`${btnStyles} h-7 px-4 text-xs`}
                      onClick={() => setOffsetCents(v => clampInt(v + 1, -20, 20))}
                    >
                      +1¢
                    </Button><span className="text-[10px] font-mono text-slate-500">offset {offsetCents >= 0 ? "+" : ""}{offsetCents}¢</span>
                  </div>
                  <div className="text-[10px] font-mono text-slate-500">
                    bid {bestBid !== null ? `${formatCents(bestBid, tickSize)}¢` : "—"} / ask {bestAsk !== null ? `${formatCents(bestAsk, tickSize)}¢` : "—"}
                  </div>
                </div>

                <div className="mt-2 grid grid-cols-2 gap-2">
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

                <div className="mt-3 grid grid-cols-2 gap-3">
                  <Button disabled={placing !== "idle" || !bestBid} onClick={() => void placeLimitOrder("BUY")} className="hover:cursor-pointer h-10 font-bold bg-sky-500 hover:bg-sky-400 border-b-4 border-sky-700 hover:translate-y-0.5 hover:border-b-2 active:translate-y-1 active:border-b-0 transition-all text-white">
                    {placing === "buy" ? "..." : `BUY @ ${bestBid !== null ? formatCents(bestBid + offsetCents / 100, tickSize) : "—"}¢`}
                  </Button>
                  <Button disabled={placing !== "idle" || !bestAsk} onClick={() => void placeLimitOrder("SELL")} className="hover:cursor-pointer h-10 font-bold bg-sky-500 hover:bg-sky-400 border-b-4 border-sky-700 hover:translate-y-0.5 hover:border-b-2 active:translate-y-1 active:border-b-0 transition-all text-white">
                    {placing === "sell" ? "..." : `SELL @ ${bestAsk !== null ? formatCents(bestAsk - offsetCents / 100, tickSize) : "—"}¢`}
                  </Button>
                </div>

                {/* {openOrders.length > 0 && (
                  <div className="mt-3 border-t border-slate-800 pt-2 text-[10px] font-mono text-slate-400">
                    <div className="flex items-center justify-between">
                      <span>Open Orders</span>
                      <span>{openOrders.length}</span>
                    </div>
                    <div className="mt-1 space-y-1">
                      {openOrders.slice(0, 3).map((o) => (
                        <div key={o.orderID} className="flex items-center justify-between">
                          <span className={o.side === "BUY" ? "text-blue-300" : "text-red-300"}>
                            {o.side}
                          </span>
                          <span>{formatCents(Number(o.price), tickSize)}¢</span>
                          <span>{Number(o.size).toFixed(2)} sh</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )} */}
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
