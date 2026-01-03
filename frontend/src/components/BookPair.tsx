import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { LogChart, type LogPoint } from "./LogChart";
import { OrderBookWidget, type UserPosition } from "./OrderBookWidget";
import type { OrderView } from "./OrdersPanel";
import type { PositionRow } from "./PositionsTable";
import type { Trade } from "./RecentTradesTable";

interface TokenWidget {
  uniqueKey: string;
  outcomeName: string;
  assetId: string;
  marketQuestion: string;
  marketVolume: number;
  sourceSlug?: string;
}

interface BookPairProps {
  pairKey: string;
  group: TokenWidget[];
  widgets: TokenWidget[];
  bookQuotes: Record<string, { bid: number | null; ask: number | null }>;
  autoPairs: Set<string>;
  autoDisabledAssets: Set<string>;
  autoBuyMaxCents: string;
  autoSellMinCents: string;
  autoSellMinShares: string;
  autoStrategy: string;
  onSelectAutoStrategy: (pairKey: string, strategy: string) => void;
  autoStrategyOptions: string[];
  positionHistory: Record<string, Trade>;
  authPositions: PositionRow[];
  orders: OrderView[];
  highlightedAsset: string | null;
  defaultShares: string;
  defaultTtl: string;
  draggedWidgetKey: string | null;
  setDraggedWidgetKey: (value: string | null) => void;
  swapWidgets: (fromKey: string, toKey: string) => void;
  toggleAutoPair: (pairKey: string) => void;
  toggleAutoAsset: (assetId: string) => void;
  handleClosePair: (pairKey: string) => void;
  handleCloseWidget: (assetId: string) => void;
  handleBookUpdate: (assetId: string, bid: number | null, ask: number | null) => void;
  fullModeKeys: Set<string>;
  ordersServerNowSec?: number | null;
  ordersServerNowLocalMs?: number | null;
  apiBaseUrl?: string;
}

export function BookPair({
  pairKey,
  group,
  // widgets,
  bookQuotes,
  autoPairs,
  autoDisabledAssets,
  autoBuyMaxCents,
  autoSellMinCents,
  autoSellMinShares,
  autoStrategy,
  onSelectAutoStrategy,
  autoStrategyOptions,
  positionHistory,
  authPositions,
  orders,
  highlightedAsset,
  defaultShares,
  defaultTtl,
  draggedWidgetKey,
  setDraggedWidgetKey,
  swapWidgets,
  toggleAutoPair,
  toggleAutoAsset,
  handleClosePair,
  handleCloseWidget,
  handleBookUpdate,
  fullModeKeys,
  ordersServerNowSec,
  ordersServerNowLocalMs,
  apiBaseUrl = "http://localhost:8000",
}: BookPairProps) {
  const isPair = group.length >= 2;
  const isAutoOn = autoPairs.has(pairKey);
  const strategyLabel = autoStrategy || "default";
  const buyLimit = Number(autoBuyMaxCents);
  const sellLimit = Number(autoSellMinCents);
  const sellSharesLimit = Number(autoSellMinShares);
  const buyThreshold = Number.isFinite(buyLimit) ? buyLimit : 97;
  const sellThreshold = Number.isFinite(sellLimit) ? sellLimit : 103;
  const sellSharesThreshold = Number.isFinite(sellSharesLimit) ? sellSharesLimit : 20;
  const assetIds = group.map((g) => g.assetId);
  const pairBidSum =
    assetIds.length >= 2
      ? assetIds.reduce((sum, id) => sum + (bookQuotes[id]?.bid ?? NaN), 0)
      : NaN;
  const pairAskSum =
    assetIds.length >= 2
      ? assetIds.reduce((sum, id) => sum + (bookQuotes[id]?.ask ?? NaN), 0)
      : NaN;
  const buyAllowedForPair = Number.isFinite(pairBidSum)
    ? pairBidSum * 100 <= buyThreshold
    : false;
  const sellAllowedForPair = Number.isFinite(pairAskSum)
    ? pairAskSum * 100 >= sellThreshold
    : false;
  const [graphOpen, setGraphOpen] = useState(false);
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphError, setGraphError] = useState<string | null>(null);
  // const [graphPos, setGraphPos] = useState({ x: 8, y: 32 });
  const [graphData, setGraphData] = useState<LogPoint[]>([]);
  const [autoSettingsByAsset, setAutoSettingsByAsset] = useState<
    Record<string, { shares: number; ttl: number; level: number }>
  >({});
  const lastAutoPayloadRef = useRef<string | null>(null);
  const lastAutoEnabledRef = useRef(false);
  const disabledAssetsKey = useMemo(
    () => Array.from(autoDisabledAssets).sort().join("|"),
    [autoDisabledAssets]
  );
  const handleToggleGraph = async () => {
    const next = !graphOpen;
    setGraphOpen(next);
    if (!next) {
      setGraphData([]);
      setGraphError(null);
      setGraphLoading(false);
      return;
    }
    const slug = group[0]?.sourceSlug;
    const question = group[0]?.marketQuestion;
    if (!slug || !question) {
      setGraphError("Missing slug/question");
      return;
    }
    setGraphLoading(true);
    setGraphError(null);
    try {
      const params = new URLSearchParams({
        slug,
        question,
      });
      const res = await fetch(`http://localhost:8000/logs/market?${params.toString()}`);
      if (!res.ok) {
        setGraphError("No log data");
        setGraphData([]);
        return;
      }
      const payload = (await res.json()) as { rows?: Array<Record<string, string>> };
      const rows = payload.rows ?? [];
      const times = rows
        .map((row) => new Date(row.timestamp ?? "").getTime())
        .filter((t) => Number.isFinite(t) && t > 0);
      const t0 = times.length ? Math.min(...times) : Date.now();
      const parsed = rows.map((row) => {
        const ts = new Date(row.timestamp ?? "").getTime();
        const t = Number.isFinite(ts) ? Math.max(0, Math.round((ts - t0) / 1000)) : 0;
        const bid1 = Number(row.best_bid_1);
        const ask1 = Number(row.best_ask_1);
        const bid2 = Number(row.best_bid_2);
        const ask2 = Number(row.best_ask_2);
        return {
          t,
          tsMs: Number.isFinite(ts) ? ts : 0,
          condition_1: row.condition_1 ?? "",
          condition_2: row.condition_2 ?? "",
          best_bid_1: Number.isFinite(bid1) ? bid1 : null,
          best_ask_1: Number.isFinite(ask1) ? ask1 : null,
          best_bid_2: Number.isFinite(bid2) ? bid2 : null,
          best_ask_2: Number.isFinite(ask2) ? ask2 : null,
        };
      });
      setGraphData(parsed);
    } catch {
      setGraphError("Failed to load log");
      setGraphData([]);
    } finally {
      setGraphLoading(false);
    }
  };

  const handleAutoSettingsChange = useCallback(
    (assetId: string, settings: { shares: number; ttl: number; level: number }) => {
      setAutoSettingsByAsset((prev) => ({ ...prev, [assetId]: settings }));
    },
    []
  );

  const sendAutoConfig = useCallback(
    async (enabled: boolean) => {
      if (!assetIds.length) return;
      const settings = assetIds.map((assetId) => {
        const cached = autoSettingsByAsset[assetId];
        const shares = Number.isFinite(cached?.shares ?? NaN) ? (cached?.shares as number) : Number(defaultShares) || 0;
        const ttl = Number.isFinite(cached?.ttl ?? NaN) ? (cached?.ttl as number) : Number(defaultTtl) || 0;
        const level = Number.isFinite(cached?.level ?? NaN) ? (cached?.level as number) : 0;
        return {
          asset_id: assetId,
          shares: shares > 0 ? shares : 1,
          ttl_seconds: Math.max(0, Math.round(ttl)),
          level: Math.round(level),
          enabled: !autoDisabledAssets.has(assetId),
        };
      });
      const payload = {
        pair_key: pairKey,
        assets: assetIds,
        asset_settings: settings,
        disabled_assets: Array.from(autoDisabledAssets),
        auto_buy_max_cents: buyThreshold,
        auto_sell_min_cents: sellThreshold,
        auto_sell_min_shares: sellSharesThreshold,
        strategy: strategyLabel,
        enabled,
      };
      const serialized = JSON.stringify(payload);
      if (serialized === lastAutoPayloadRef.current) return;
      lastAutoPayloadRef.current = serialized;
      try {
        await fetch(`${apiBaseUrl}/auto/pair`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: serialized,
        });
      } catch {
        // ignore transient errors
      }
    },
    [
      assetIds,
      autoDisabledAssets,
      autoSettingsByAsset,
      buyThreshold,
      sellThreshold,
      sellSharesThreshold,
      pairKey,
      strategyLabel,
      defaultShares,
      defaultTtl,
      apiBaseUrl,
    ]
  );

  useEffect(() => {
    if (!isAutoOn) {
      if (lastAutoEnabledRef.current) {
        lastAutoEnabledRef.current = false;
        void sendAutoConfig(false);
      }
      return;
    }
    lastAutoEnabledRef.current = true;
    const id = window.setTimeout(() => {
      void sendAutoConfig(true);
    }, 150);
    return () => window.clearTimeout(id);
  }, [isAutoOn, disabledAssetsKey, autoSettingsByAsset, buyThreshold, sellThreshold, sellSharesThreshold, sendAutoConfig]);

  return (
    <div
      className={`relative rounded-md p-2 ${
        isPair ? (isAutoOn ? "bg-slate-800/70" : "bg-slate-900/50") : ""
      }`}
    >
      {isPair && (
        <div className="absolute -top-2 right-2 flex items-center gap-2">
          <Button
            onClick={handleToggleGraph}
            className={`h-6 px-2 text-[10px] uppercase font-bold border ${
              graphOpen ? "bg-blue-600/80 border-blue-500 text-white" : "border-slate-800 bg-slate-950 text-slate-300 hover:text-white"
            }`}
          >
            Graph
          </Button>
          <div className="flex items-center">
            <Button
              onClick={() => toggleAutoPair(pairKey)}
              className={`h-6 rounded-r-none px-2 text-[10px] uppercase font-bold border ${
                isAutoOn ? "bg-emerald-600/80 border-emerald-500 text-white" : "bg-slate-950 border-slate-800 text-slate-300"
              }`}
            >
              Auto · {strategyLabel}
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  className={`h-6 w-7 rounded-l-none px-0 text-[10px] uppercase font-bold border border-l-0 ${
                    isAutoOn ? "bg-emerald-600/80 border-emerald-500 text-white" : "bg-slate-950 border-slate-800 text-slate-300"
                  }`}
                >
                  ▼
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent sideOffset={6} align="end">
                <DropdownMenuLabel>Auto Strategy</DropdownMenuLabel>
                <DropdownMenuSeparator />
                {autoStrategyOptions.map((strategy) => (
                  <DropdownMenuItem
                    key={strategy}
                    onClick={() => onSelectAutoStrategy(pairKey, strategy)}
                  >
                    {strategy}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
          <Button
            onClick={() => handleClosePair(pairKey)}
            className="h-6 w-6 rounded-full border border-slate-800 bg-slate-950 text-slate-300 hover:text-white"
          >
            X
          </Button>
        </div>
      )}
      {group[0] && (
        <div className="flex items-center gap-2 pb-0 -mb-1">
          <span className="text-[10px] text-slate-500 uppercase font-bold truncate px-1">
            {group[0].marketQuestion}
          </span>
          <span className="text-[10px] text-slate-400 font-mono">
            ${Math.round(group[0].marketVolume).toLocaleString()}
          </span>
        </div>
      )}
      {graphOpen && (
        <div className="absolute inset-0 z-20 rounded-md border border-slate-800 bg-slate-950/50 p-2 shadow-xl pointer-events-none">
          <div className="mb-2 flex items-center justify-between text-[10px] uppercase tracking-wide text-slate-400 pointer-events-auto">
            <span>Graph</span>
            <Button
              onClick={() => setGraphOpen(false)}
              className="h-6 w-6 rounded-full border border-slate-800 bg-slate-950 text-slate-300 hover:text-white"
            >
              X
            </Button>
          </div>
          <LogChart
            data={graphData}
            loading={graphLoading}
            error={graphError}
            emptyMessage="No chart data yet."
            heightClass="h-[calc(100%-28px)]"
          />
        </div>
      )}

      <div className="grid grid-cols-2 gap-2">
        {group.map((w) => {
          const match = positionHistory[w.assetId];

          let userPos: UserPosition | null = null;
          if (match) {
            const shares = Number(match.size);
            const value = Number(match.usdcSize);
            const price = shares > 0 ? value / shares : 0;
            userPos = { side: match.side, price, shares };
          }

          const heldPosition = authPositions.find((p) => p.asset === w.assetId);
          const heldShares = heldPosition ? Number(heldPosition.size) : null;
          const heldAvg = heldPosition ? Number(heldPosition.avgPrice) : null;
          const otherAssetId = group.find((g) => g.assetId !== w.assetId)?.assetId;
          const otherHeldPosition = otherAssetId
            ? authPositions.find((p) => p.asset === otherAssetId)
            : undefined;
          const otherHeldShares = otherHeldPosition ? Number(otherHeldPosition.size) : null;
          const currentShares = Number.isFinite(heldShares ?? NaN) ? (heldShares as number) : 0;
          const otherShares = Number.isFinite(otherHeldShares ?? NaN) ? (otherHeldShares as number) : 0;
          const exposureDiff = currentShares - otherShares;
          const autoTradeSide: "BUY" | "SELL" =
            currentShares >= sellSharesThreshold && otherShares >= sellSharesThreshold
              ? "SELL"
              : exposureDiff >= sellSharesThreshold
              ? "SELL"
              : "BUY";
          const openOrders = orders.filter((o) => o.asset_id === w.assetId && o.status === "open");
          const isAutoAssetOn = isAutoOn && !autoDisabledAssets.has(w.assetId);

          const isFullMode = fullModeKeys.has(w.uniqueKey);

          return (
            <div
              key={w.uniqueKey}
              className={`flex flex-col gap-1 ${draggedWidgetKey === w.uniqueKey ? "opacity-10" : ""}`}
              draggable
              onDragStart={(event) => {
                setDraggedWidgetKey(w.uniqueKey);
                event.dataTransfer.effectAllowed = "move";
                event.dataTransfer.setData("text/plain", w.uniqueKey);
              }}
              onDragEnd={() => setDraggedWidgetKey(null)}
              onDragOver={(event) => {
                event.preventDefault();
                event.dataTransfer.dropEffect = "move";
              }}
              onDrop={(event) => {
                event.preventDefault();
                const fromKey = event.dataTransfer.getData("text/plain");
                if (fromKey) swapWidgets(fromKey, w.uniqueKey);
                setDraggedWidgetKey(null);
              }}
            >
              <span
                className="text-[9px] text-slate-500 uppercase font-bold truncate px-1 opacity-0 -mt-1"
                title={w.marketQuestion}
              >
                {w.marketQuestion}
              </span>
              <OrderBookWidget
                assetId={w.assetId}
                outcomeName={w.outcomeName}
                marketQuestion={w.marketQuestion}
                sourceSlug={w.sourceSlug}
                volume={w.marketVolume}
                userPosition={userPos}
                positionShares={Number.isFinite(heldShares ?? NaN) ? heldShares : null}
                positionAvgPrice={Number.isFinite(heldAvg ?? NaN) ? heldAvg : null}
                otherAssetPositionShares={
                  Number.isFinite(otherHeldShares ?? NaN) ? otherHeldShares : null
                }
                openOrders={openOrders}
                ordersServerNowSec={ordersServerNowSec}
                ordersServerNowLocalMs={ordersServerNowLocalMs}
                defaultShares={defaultShares}
                defaultTtl={defaultTtl}
                auto={isAutoAssetOn}
                autoBuyAllowed={buyAllowedForPair}
                autoSellAllowed={sellAllowedForPair}
                autoTradeSide={autoTradeSide}
                autoMode="server"
                onAutoSettingsChange={handleAutoSettingsChange}
                onHeaderClick={() => {
                  if (!isAutoOn) return;
                  toggleAutoAsset(w.assetId);
                }}
                isHighlighted={highlightedAsset === w.assetId}
                viewMode={isFullMode ? "full" : "mini"}
                onClose={isPair ? undefined : handleCloseWidget}
                onBookUpdate={handleBookUpdate}
                apiBaseUrl={apiBaseUrl}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}






