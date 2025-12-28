import { useCallback, useEffect, useRef, useState } from "react";
import { OrderBookWidget, type UserPosition } from "./components/OrderBookWidget";
// import { Input } from "@/components/ui/input";
// import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { RecentTradesTable, type Trade } from "./components/RecentTradesTable";
import { Navbar } from "./components/Navbar";
import { PositionsTable, type PositionRow } from "./components/PositionsTable";
import { LiveEventsStrip } from "./components/LiveEventsStrip";
import { OrdersPanel, type OrderView } from "./components/OrdersPanel";

interface Market {
  question: string;
  slug?: string;
  outcomes: string[];
  clobTokenIds: string[];
  volume: number;
}

interface EventData {
  title: string;
  slug: string;
  volume24hr?: number;
  startDate?: string;
  endDate?: string;
  markets: Market[];
}

interface TokenWidget {
  uniqueKey: string;
  outcomeName: string;
  assetId: string;
  marketQuestion: string;
  marketVolume: number;
  sourceSlug?: string;
}

interface BalanceInfo {
  balance: number;
}

function toExpiration(order: OrderView): OrderView {
  const raw = (order as unknown as { expiration?: number | string }).expiration;
  const exp = Number(raw ?? 0);
  return {
    ...order,
    expiration: Number.isFinite(exp) ? exp : 0,
  };
}

type UserSocketMessage =
  | { type: "new_markets"; markets: Market[] }
  | { type: "recent_trades"; trades: Trade[] };

function App() {
  const [url, setUrl] = useState("0x507e52ef684ca2dd91f90a9d26d149dd3288beae");
  const [minVolume, setMinVolume] = useState(1000);
  const [loading, setLoading] = useState(false);
  const [eventData, setEventData] = useState<EventData | null>(null);
  const [widgets, setWidgets] = useState<TokenWidget[]>([]);
  const dismissedAssetsRef = useRef<Record<string, true>>({});

  const [recentTrades, setRecentTrades] = useState<Trade[]>([]);
  const [positionHistory, setPositionHistory] = useState<Record<string, Trade>>({});
  const [authBalance, setAuthBalance] = useState<BalanceInfo | null>(null);
  const [authPositions, setAuthPositions] = useState<PositionRow[]>([]);
  const [activeAddress, setActiveAddress] = useState<string | null>(null);
  const [showPositions, setShowPositions] = useState(false);
  const [closingPositions, setClosingPositions] = useState(false);
  const closePositionsTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [showOrders, setShowOrders] = useState(false);
  const [closingOrders, setClosingOrders] = useState(false);
  const closeOrdersTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [closingSettings, setClosingSettings] = useState(false);
  const closeSettingsTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [searchHistory, setSearchHistory] = useState<string[]>([]);
  const cashSfxRef = useRef<HTMLAudioElement | null>(null);
  const prevCashRef = useRef<number | null>(null);
  const tradeSfxRef = useRef<HTMLAudioElement | null>(null);
  const [defaultShares, setDefaultShares] = useState("5");
  const [defaultTtl, setDefaultTtl] = useState("10");
  const [liveEvents, setLiveEvents] = useState<EventData[]>([]);
  const [subscribedSlugs, setSubscribedSlugs] = useState<Set<string>>(new Set());
  const [orders, setOrders] = useState<OrderView[]>([]);
  const [ordersServerNowSec, setOrdersServerNowSec] = useState<number | null>(null);
  const [ordersServerNowLocalMs, setOrdersServerNowLocalMs] = useState<number | null>(null);
  const [ordersWsStatus, setOrdersWsStatus] = useState<"connecting" | "open" | "closed" | "error">("connecting");
  const [ordersWsEvents, setOrdersWsEvents] = useState(0);
  const [ordersWsLastType, setOrdersWsLastType] = useState<string | null>(null);
  const [ordersWsServerPid, setOrdersWsServerPid] = useState<number | null>(null);
  const [ordersWsCloseInfo, setOrdersWsCloseInfo] = useState<string | null>(null);
  const [ordersWsErrorInfo, setOrdersWsErrorInfo] = useState<string | null>(null);
  const seenTradeIdsRef = useRef<Set<string>>(new Set());
  const [draggedWidgetKey, setDraggedWidgetKey] = useState<string | null>(null);

  const [highlightedAsset, setHighlightedAsset] = useState<string | null>(null);
  const highlightTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  const userSocketRef = useRef<WebSocket | null>(null);

  const triggerHighlight = (assetId: string) => {
    setHighlightedAsset(assetId)
    if (highlightTimeout.current) window.clearTimeout(highlightTimeout.current);
    highlightTimeout.current = window.setTimeout(() => setHighlightedAsset(null), 700);
  };

  const playTradeFilled = useCallback(() => {
    if (!tradeSfxRef.current) {
      tradeSfxRef.current = new Audio("/src/assets/trade_filled.mp3");
      tradeSfxRef.current.volume = 0.5;
    }
    const sfx = tradeSfxRef.current;
    if (!sfx) return;
    sfx.currentTime = 0;
    sfx.play().catch(() => {});
  }, []);

  const handleCloseWidget = useCallback((assetId: string) => {
    dismissedAssetsRef.current = { ...dismissedAssetsRef.current, [assetId]: true };
    setWidgets((prev) => prev.filter((w) => w.assetId !== assetId));
    setHighlightedAsset((prev) => (prev === assetId ? null : prev));
  }, []);

  const swapWidgets = useCallback((fromKey: string, toKey: string) => {
    if (fromKey === toKey) return;
    setWidgets((prev) => {
      const fromIndex = prev.findIndex((w) => w.uniqueKey === fromKey);
      const toIndex = prev.findIndex((w) => w.uniqueKey === toKey);
      if (fromIndex < 0 || toIndex < 0) return prev;
      const next = [...prev];
      const temp = next[fromIndex];
      next[fromIndex] = next[toIndex];
      next[toIndex] = temp;
      return next;
    });
  }, []);

  useEffect(() => {
    return () => {
      if (userSocketRef.current) userSocketRef.current.close();
      if (highlightTimeout.current) window.clearTimeout(highlightTimeout.current);
      if (closePositionsTimerRef.current) window.clearTimeout(closePositionsTimerRef.current);
      if (closeOrdersTimerRef.current) window.clearTimeout(closeOrdersTimerRef.current);
      if (closeSettingsTimerRef.current) window.clearTimeout(closeSettingsTimerRef.current);
    };
  }, []);

  useEffect(() => {
    setOrdersWsStatus("connecting");
    setOrdersWsCloseInfo(null);
    setOrdersWsErrorInfo(null);
    const ws = new WebSocket("ws://localhost:8000/ws/user");

    ws.onopen = () => {
      console.log("Orders WS open");
      setOrdersWsStatus("open");
      setOrdersWsCloseInfo(null);
      setOrdersWsErrorInfo(null);
    };
    ws.onclose = (event) => {
      console.log("Orders WS closed", event);
      setOrdersWsStatus("closed");
      setOrdersWsCloseInfo(`code=${event.code} reason=${event.reason || "none"}`);
    };
    ws.onerror = (event) => {
      console.error("Orders WS error", event);
      setOrdersWsStatus("error");
      setOrdersWsErrorInfo("WebSocket error");
    };
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data) as
        | { type: "snapshot"; orders: OrderView[]; server_now?: number }
        | { type: "opened"; order: OrderView; server_now?: number }
        | { type: "closed"; order: OrderView; event?: string; server_now?: number; trade_id?: string; trade_status?: string }
        | { type: "update"; order: OrderView; event?: string; server_now?: number }
        | { type: "status"; status: string; pid?: number; server_now?: number }
        | { type: "error"; error: string };
      if (typeof data.server_now === "number") {
        setOrdersServerNowSec(data.server_now);
        setOrdersServerNowLocalMs(Date.now());
      }
      setOrdersWsEvents((prev) => prev + 1);
      setOrdersWsLastType(data.type);

      if (data.type === "snapshot") {
        const now = Date.now();
        const next = data.orders.map((o) => ({
          ...toExpiration(o),
          status: "open" as const,
          updatedAt: now,
        }));
        setOrders((prev) => {
          const optimistic = prev.filter((o) => o.orderID.startsWith("optimistic-"));
          return [...next, ...optimistic];
        });
      } else if (data.type === "opened") {
        const now = Date.now();
        setOrders((prev) => {
          if (prev.some((o) => o.orderID === data.order.orderID)) return prev;
          const filtered = prev.filter((o) => !o.orderID.startsWith("optimistic-"));
          return [{ ...toExpiration(data.order), status: "open" as const, updatedAt: now }, ...filtered];
        });
      } else if (data.type === "closed") {
        const now = Date.now();
        if (data.event === "TRADE") {
          const tradeId = data.trade_id;
          if (tradeId) {
            const seen = seenTradeIdsRef.current;
            if (!seen.has(tradeId)) {
              seen.add(tradeId);
              if (seen.size > 200) {
                const [first] = seen;
                if (first) seen.delete(first);
              }
              playTradeFilled();
            }
          } else {
            playTradeFilled();
          }
        }
        setOrders((prev) => {
          const seen = new Set(prev.map((o) => o.orderID));
          const updated = prev.map((o) =>
            o.orderID === data.order.orderID
              ? { ...o, status: "closed" as const, updatedAt: now }
              : o
          );
          if (!seen.has(data.order.orderID)) {
            updated.unshift({
              ...toExpiration(data.order),
              status: "closed" as const,
              updatedAt: now,
            });
          }
          return updated;
        });
      } else if (data.type === "update") {
        const now = Date.now();
        setOrders((prev) => {
          const updated = prev.map((o) =>
            o.orderID === data.order.orderID
              ? { ...o, updatedAt: now }
              : o
          );
          return updated;
        });
      } else if (data.type === "status") {
        if (data.status === "subscribed") {
          setOrdersWsStatus("open");
        }
        if (typeof data.pid === "number") {
          setOrdersWsServerPid(data.pid);
        }
      }
    };

    return () => {
      ws.close();
    };
  }, []);


  useEffect(() => {
    if (!cashSfxRef.current) {
      cashSfxRef.current = new Audio("/src/assets/your-sound.mp3");
      cashSfxRef.current.volume = 0.2;
    }
    const current = authBalance?.balance ?? null;
    if (
      current !== null &&
      prevCashRef.current !== null &&
      current > prevCashRef.current
    ) {
      const sfx = cashSfxRef.current;
      if (sfx) {
        sfx.currentTime = 0;
        sfx.play().catch(() => {});
      }
    }
    prevCashRef.current = current;
  }, [authBalance?.balance]);

  useEffect(() => {
    try {
      const raw = localStorage.getItem("pm_recent_searches");
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        setSearchHistory(parsed.filter((v) => typeof v === "string"));
      }
    } catch {
      setSearchHistory([]);
    }
  }, []);

  const pushHistory = useCallback((value: string) => {
    const trimmed = value.trim();
    if (!trimmed) return;
    setSearchHistory((prev) => {
      const next = [trimmed, ...prev.filter((v) => v !== trimmed)].slice(0, 8);
      localStorage.setItem("pm_recent_searches", JSON.stringify(next));
      return next;
    });
  }, []);

  const fetchUserMetrics = useCallback(async (address: string) => {
    const baseUrl = "http://localhost:8000";
    try {
      const encoded = encodeURIComponent(address);
      const positionsRes = await fetch(`${baseUrl}/user/positions?address=${encoded}&limit=200`);
      if (!positionsRes.ok) {
        console.error("Failed to fetch user positions");
      }
    } catch (err) {
      console.error("Failed to fetch user metrics", err);
    }
  }, []);

  const fetchAuthMetrics = useCallback(async () => {
    const baseUrl = "http://localhost:8000";
    try {
      const [balanceRes, positionsRes] = await Promise.all([
        fetch(`${baseUrl}/user/balance`),
        fetch(`${baseUrl}/user/positions/auth?limit=200`),
      ]);

      if (balanceRes.ok) {
        const data = (await balanceRes.json()) as { balance: string };
        const balance = Number(data.balance);
        setAuthBalance({
          balance: Number.isFinite(balance) ? balance : 0,
        });
      } else {
        setAuthBalance(null);
      }

      if (positionsRes.ok) {
        const data = (await positionsRes.json()) as PositionRow[];
        setAuthPositions(data);
      } else {
        setAuthPositions([]);
      }
    } catch (err) {
      console.error("Failed to fetch auth metrics", err);
      setAuthBalance(null);
      setAuthPositions([]);
    }
  }, []);

  useEffect(() => {
    if (!activeAddress) return;
    void fetchUserMetrics(activeAddress);
    const interval = window.setInterval(() => void fetchUserMetrics(activeAddress), 30000);
    return () => window.clearInterval(interval);
  }, [activeAddress, fetchUserMetrics]);

  useEffect(() => {
    void fetchAuthMetrics();
    const interval = window.setInterval(() => void fetchAuthMetrics(), 30000);
    return () => window.clearInterval(interval);
  }, [fetchAuthMetrics]);

  useEffect(() => {
    const baseUrl = "http://localhost:8000";
    const loadLive = async () => {
      try {
        const res = await fetch(`${baseUrl}/events/list?limit=120`);
        if (!res.ok) return;
        const data = (await res.json()) as EventData[];
        setLiveEvents(data);
      } catch (err) {
        console.error("Failed to load live events", err);
      }
    };
    void loadLive();
    const interval = window.setInterval(() => void loadLive(), 60000);
    return () => window.clearInterval(interval);
  }, []);

  const resolveInput = async (mode: "replace" | "add", override?: string) => {
    const input = (override ?? url).trim();
    if (!input) return;
    pushHistory(input);

    const isAddress = input.startsWith("0x") && input.length === 42;

      if (mode === "replace") {
        if (userSocketRef.current) {
          userSocketRef.current.close();
          userSocketRef.current = null;
        }
        setEventData(null);
        setWidgets([]);
        dismissedAssetsRef.current = {};
        setRecentTrades([]);
        setPositionHistory({});
        setActiveAddress(null);
        setSubscribedSlugs(new Set());
      }

    setLoading(true);

    if (isAddress) {
      if (mode === "add") {
        alert("Add supports only market URLs or slugs.");
        setLoading(false);
        return;
      }

      setActiveAddress(input);
      void fetchUserMetrics(input);

      const wsUrl = `ws://localhost:8000/ws/watch/user/${input}?min_volume=${minVolume}`;
      const ws = new WebSocket(wsUrl);
      userSocketRef.current = ws;

      setEventData({ title: `Monitor: ${input.slice(0, 6)}...${input.slice(-4)}`, slug: "", markets: [] });

      ws.onopen = () => setLoading(false);

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data) as UserSocketMessage;

        if (data.type === "new_markets") {
          const newWidgets: TokenWidget[] = [];

          data.markets.forEach((market) => {
            market.clobTokenIds.forEach((assetId, index) => {
              if (dismissedAssetsRef.current[assetId]) return;
              const outcomeName = market.outcomes[index] || `Outcome ${index + 1}`;
              newWidgets.push({
                uniqueKey: assetId,
                assetId,
                outcomeName,
                marketQuestion: market.question,
                marketVolume: market.volume,
              });
            });
          });

          setWidgets((prev) => {
            const exists = new Set(prev.map((w) => w.uniqueKey));
            const uniqueNew = newWidgets.filter((w) => !exists.has(w.uniqueKey));
            const combined = [...uniqueNew, ...prev];
            return combined.sort((a, b) => b.marketVolume - a.marketVolume);
          });
        }

        if (data.type === "recent_trades") {
          setRecentTrades((prev) => {
            // 1. Create a map of existing hashes for O(1) lookup
            const existingHashes = new Set(prev.map((t) => t.transactionHash));
            
            // 2. Only keep trades we haven't seen yet
            const newUniqueTrades = data.trades.filter(
              (t) => !existingHashes.has(t.transactionHash)
            );

            // 3. Prepend new trades to the front so they appear at the top
            // Then slice to keep the list performant (e.g., last 50 trades)
            return [...newUniqueTrades, ...prev].slice(0, 50);
          });

          setPositionHistory((prev) => {
            const updated = { ...prev };
            data.trades.forEach((t) => {
              // Always update with the latest trade data for an asset 
              // to ensure 'userPosition' in widgets is accurate
              updated[t.asset] = t;
            });
            return updated;
          });
        }
      };

      ws.onerror = () => {
        alert("Error connecting to user stream. Check server console.");
        setLoading(false);
      };

      return;
    }

    // URL / slug resolve mode
    const fullUrl = `http://localhost:8000/events/resolve?query=${encodeURIComponent(input)}&min_volume=${minVolume}`;

    try {
      const res = await fetch(fullUrl);
      if (!res.ok) throw new Error("Failed to resolve target");

      const data = (await res.json()) as EventData;
      setEventData((prev) => (mode === "replace" ? data : prev ?? data));
      if (data.slug) {
        setSubscribedSlugs((prev) => {
          const next = new Set(prev);
          if (mode === "replace") next.clear();
          next.add(data.slug);
          return next;
        });
      }

      const newWidgets: TokenWidget[] = [];
      data.markets.forEach((market) => {
        market.clobTokenIds.forEach((assetId, index) => {
          if (dismissedAssetsRef.current[assetId]) return;
          const outcomeName = market.outcomes[index] || `Outcome ${index + 1}`;
          newWidgets.push({
            uniqueKey: assetId,
            assetId,
            outcomeName,
            marketQuestion: market.question,
            marketVolume: market.volume,
            sourceSlug: data.slug,
          });
        });
      });

      setWidgets((prev) => {
        const exists = new Set(prev.map((w) => w.uniqueKey));
        const uniqueNew = newWidgets.filter((w) => !exists.has(w.uniqueKey));
        const combined = mode === "replace" ? uniqueNew : [...uniqueNew, ...prev];
        return combined.sort((a, b) => b.marketVolume - a.marketVolume);
      });
    } catch (err) {
      console.error(err);
      alert("Error finding event.");
    } finally {
      setLoading(false);
    }
  };

  const handleResolve = () => {
    void resolveInput("replace");
  };

  const handleAdd = () => {
    void resolveInput("add");
  };

  const handleSelectSearch = (value: string) => {
    setUrl(value);
    void resolveInput("replace", value);
  };

  const handleAddSlug = (slug: string) => {
    void resolveInput("add", slug);
  };

  const handleRemoveSlug = (slug: string) => {
    setSubscribedSlugs((prev) => {
      const next = new Set(prev);
      next.delete(slug);
      return next;
    });
    setWidgets((prev) => prev.filter((w) => w.sourceSlug !== slug));
  };

  const openPositions = () => {
    if (closePositionsTimerRef.current) window.clearTimeout(closePositionsTimerRef.current);
    setClosingPositions(false);
    setShowPositions(true);
  };

  const closePositions = () => {
    setClosingPositions(true);
    if (closePositionsTimerRef.current) window.clearTimeout(closePositionsTimerRef.current);
    closePositionsTimerRef.current = window.setTimeout(() => {
      setShowPositions(false);
      setClosingPositions(false);
    }, 200);
  };

  const openOrders = () => {
    if (closeOrdersTimerRef.current) window.clearTimeout(closeOrdersTimerRef.current);
    setClosingOrders(false);
    setShowOrders(true);
  };

  const closeOrders = () => {
    setClosingOrders(true);
    if (closeOrdersTimerRef.current) window.clearTimeout(closeOrdersTimerRef.current);
    closeOrdersTimerRef.current = window.setTimeout(() => {
      setShowOrders(false);
      setClosingOrders(false);
    }, 200);
  };

  const openSettings = () => {
    if (closeSettingsTimerRef.current) window.clearTimeout(closeSettingsTimerRef.current);
    setClosingSettings(false);
    setShowSettings(true);
  };

  const closeSettings = () => {
    setClosingSettings(true);
    if (closeSettingsTimerRef.current) window.clearTimeout(closeSettingsTimerRef.current);
    closeSettingsTimerRef.current = window.setTimeout(() => {
      setShowSettings(false);
      setClosingSettings(false);
    }, 200);
  };

  return (
  <div className="h-screen w-full bg-black font-sans text-slate-200 overflow-hidden flex flex-col">
    {/* Top Navbar with Integrated Search & Balance Monitor */}
    <Navbar 
      userAddress={url.startsWith("0x") ? url : "0x507e52ef684ca2dd91f90a9d26d149dd3288beae"}
      inputValue={url}
      setInputValue={setUrl}
      onResolve={handleResolve}
      onAdd={handleAdd}
      loading={loading}
      balance={authBalance?.balance ?? null}
      portfolio={(() => {
        if (!authBalance) return null;
        const cash = authBalance.balance ?? 0;
        const positionsValue = authPositions.reduce((sum, p) => {
          const value = Number(p.currentValue);
          return Number.isFinite(value) ? sum + value : sum;
        }, 0);
        return cash + positionsValue;
      })()}
      positionsCount={(() => {
        return authPositions.filter((p) => {
          const value = Number(p.currentValue);
          return Number.isFinite(value) && value > 0.01;
        }).length;
      })()}
      onPositionsClick={openPositions}
      onOrdersClick={openOrders}
      onSettingsClick={openSettings}
      ordersCount={orders.filter((o) => o.status === "open").length}
      ordersWsStatus={ordersWsStatus}
      ordersWsEvents={ordersWsEvents}
      ordersWsLastType={ordersWsLastType}
      ordersWsServerPid={ordersWsServerPid}
      ordersWsCloseInfo={ordersWsCloseInfo}
      ordersWsErrorInfo={ordersWsErrorInfo}
      ordersServerNowSec={ordersServerNowSec}
      recentSearches={searchHistory}
      onSelectSearch={handleSelectSearch}
    />
    
    {/* Live Events Strip */}
    {liveEvents.length > 0 && (
      <div className="px-4 pt-4">
        <LiveEventsStrip
          events={liveEvents.map((ev) => ({
            id: ev.slug,
            slug: ev.slug,
            title: ev.title,
            volume: (ev as unknown as { volume?: number }).volume,
            startDate: (ev as unknown as { startDate?: string }).startDate,
            endDate: (ev as unknown as { endDate?: string }).endDate,
            markets: (ev.markets || []).map((m) => ({
              question: m.question,
              volume: m.volume,
              gameStartTime: (m as { gameStartTime?: string }).gameStartTime,
            })),
            raw: ev,
          }))}
          subscribed={subscribedSlugs}
          onAdd={handleAddSlug}
          onRemove={handleRemoveSlug}
        />
      </div>
    )}

    <ScrollArea className="flex-1 w-full">
      {/* Horizontal Dashboard Space */}
      <div className="p-4 max-w-none mx-auto space-y-4 w-full">
        {/* Header Section: Event Title & Compact Trades Table */}
        {eventData && (
          <div className="flex flex-col gap-3 bg-slate-900/20 p-0 rounded-lg">
            <div className="flex flex-col lg:flex-row gap-3 justify-between items-start">
              <div className="flex-shrink-0">
                <h2 className="text-xl font-bold text-white uppercase tracking-tighter">
                  {eventData.title}
                </h2>
                <div className="flex items-center gap-4 mt-1">
                  <Badge variant="outline" className="text-[10px] text-blue-400 border-blue-900 bg-blue-900/10">
                    {widgets.length} BOOKS
                  </Badge>
                  <div className="flex items-center gap-2 min-w-[150px]">
                    <span className="text-[10px] text-slate-500 font-mono">
                      Min Vol ${Math.round(minVolume / 1000)}k+
                    </span>
                  </div>
                </div>
              </div>
              <div className="w-full lg:w-auto flex items-center justify-end" />
            </div>

            {recentTrades.length > 0 ? (
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
                <div className="lg:col-span-2">
                  <RecentTradesTable 
                    trades={recentTrades} 
                    onInteract={triggerHighlight} 
                  />
                </div>
              </div>
            ) : null}
          </div>
        )}

        {/* High-Density Order Book Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6 gap-4 pb-3">
          {widgets.map((w, index) => {
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
            const openOrders = orders.filter((o) => o.asset_id === w.assetId && o.status === "open");

            // High-density optimization: first 10 books are "full", rest are "mini"
            const isFullMode = index < 10;

            return (
              <div
                key={w.uniqueKey}
                className={`flex flex-col gap-1 ${draggedWidgetKey === w.uniqueKey ? "opacity-60" : ""}`}
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
                  className="text-[9px] text-slate-500 uppercase font-bold truncate px-1" 
                  title={w.marketQuestion}
                >
                  {w.marketQuestion}
                </span>
                <OrderBookWidget
                  assetId={w.assetId}
                  outcomeName={w.outcomeName}
                  volume={w.marketVolume}
                  userPosition={userPos}
                  positionShares={Number.isFinite(heldShares ?? NaN) ? heldShares : null}
                  positionAvgPrice={Number.isFinite(heldAvg ?? NaN) ? heldAvg : null}
                  openOrders={openOrders}
                  ordersServerNowSec={ordersServerNowSec}
                  ordersServerNowLocalMs={ordersServerNowLocalMs}
                  defaultShares={defaultShares}
                  defaultTtl={defaultTtl}
                  isHighlighted={highlightedAsset === w.assetId}
                  viewMode={isFullMode ? "full" : "mini"}
                  onClose={handleCloseWidget}
                  apiBaseUrl="http://localhost:8000"
                />
              </div>
            );
          })}
        </div>
      </div>
    </ScrollArea>
    {showPositions && (
      <div
        className={`fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm transition-opacity duration-200 ${closingPositions ? "opacity-0" : "opacity-100"}`}
        onClick={closePositions}
      >
        <div
          className={`relative w-[95vw] max-w-3xl transition-all duration-200 ${closingPositions ? "scale-95 opacity-0" : "scale-100 opacity-100"}`}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="absolute right-3 top-3 z-10">
            <Button
              onClick={closePositions}
              className="h-8 w-8 rounded-full border border-slate-800 bg-slate-950 text-slate-300 hover:text-white"
            >
              X
            </Button>
          </div>
          <PositionsTable
            positions={authPositions.filter((p) => {
              const value = Number(p.currentValue);
              return Number.isFinite(value) && value > 0.01;
            })}
            onSelect={(pos) => {
              if (dismissedAssetsRef.current[pos.asset]) {
                const next = { ...dismissedAssetsRef.current };
                delete next[pos.asset];
                dismissedAssetsRef.current = next;
              }
              setWidgets((prev) => {
                if (prev.some((w) => w.assetId === pos.asset)) return prev;
                const outcomeName = pos.outcome || "Outcome";
                const marketQuestion = pos.title || "Position";
                const volume = Number(pos.currentValue);
                return [
                  {
                    uniqueKey: pos.asset,
                    assetId: pos.asset,
                    outcomeName,
                    marketQuestion,
                    marketVolume: Number.isFinite(volume) ? volume : 0,
                  },
                  ...prev,
                ];
              });
              closePositions();
            }}
          />
        </div>
      </div>
    )}
    {showOrders && (
      <div
        className={`fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm transition-opacity duration-200 ${closingOrders ? "opacity-0" : "opacity-100"}`}
        onClick={closeOrders}
      >
        <div
          className={`relative w-[95vw] max-w-xl transition-all duration-200 ${closingOrders ? "scale-95 opacity-0" : "scale-100 opacity-100"}`}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="absolute right-3 top-3 z-10">
            <Button
              onClick={closeOrders}
              className="h-8 w-8 rounded-full border border-slate-800 bg-slate-950 text-slate-300 hover:text-white"
            >
              X
            </Button>
          </div>
          <OrdersPanel orders={orders} />
        </div>
      </div>
    )}
    {showSettings && (
      <div
        className={`fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm transition-opacity duration-200 ${closingSettings ? "opacity-0" : "opacity-100"}`}
        onClick={closeSettings}
      >
        <div
          className={`relative w-[95vw] max-w-md transition-all duration-200 ${closingSettings ? "scale-95 opacity-0" : "scale-100 opacity-100"}`}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="absolute right-3 top-3 z-10">
            <Button
              onClick={closeSettings}
              className="h-8 w-8 rounded-full border border-slate-800 bg-slate-950 text-slate-300 hover:text-white"
            >
              X
            </Button>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-950 p-4 space-y-4">
            <div className="text-xs uppercase tracking-widest text-slate-400 font-bold">Settings</div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-[10px] text-slate-500 uppercase font-bold">Default Shares</label>
                <Input
                  value={defaultShares}
                  onChange={(e) => setDefaultShares(e.target.value)}
                  onFocus={(e) => e.currentTarget.select()}
                  className="h-8 bg-black border-slate-800 font-mono text-sm"
                />
              </div>
              <div className="space-y-1">
                <label className="text-[10px] text-slate-500 uppercase font-bold">Default TTL (sec)</label>
                <Input
                  value={defaultTtl}
                  onChange={(e) => setDefaultTtl(e.target.value)}
                  onFocus={(e) => e.currentTarget.select()}
                  className="h-8 bg-black border-slate-800 font-mono text-sm"
                />
              </div>
            </div>
            <div className="space-y-1">
              <label className="text-[10px] text-slate-500 uppercase font-bold">Min Book Volume</label>
              <Input
                value={String(minVolume)}
                onChange={(e) => setMinVolume(Number(e.target.value) || 0)}
                onFocus={(e) => e.currentTarget.select()}
                className="h-8 bg-black border-slate-800 font-mono text-sm"
              />
            </div>
          </div>
        </div>
      </div>
    )}
  </div>
);
}

export default App;
