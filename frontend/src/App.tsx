import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BookPair } from "./components/BookPair";
import { useBookSocket } from "./hooks/useBookSocket";
// import { Input } from "@/components/ui/input";
// import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { RecentTradesTable, type Trade } from "./components/RecentTradesTable";
import { Navbar } from "./components/Navbar";
import { PositionsTable, type PositionRow } from "./components/PositionsTable";
import { LiveEventsStrip } from "./components/LiveEventsStrip";
import { OrdersPanel, type OrderView } from "./components/OrdersPanel";
import { LogChart, type LogPoint } from "./components/LogChart";
import { Event } from "./components/Event";

const normalizeQuestion = (q: string | undefined): string =>
  (q ?? "")
    .replace(/_/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();

const datePattern = /\b\d{4}-\d{2}-\d{2}\b/;
const extractDate = (slug: string): string => {
  const match = slug.match(datePattern);
  return match ? match[0] : "";
};

const extractSport = (slug: string): string => {
  const base = slug.split("/")[0] ?? slug;
  const chunk = base.split("-")[0] ?? base;
  return chunk.split("_")[0] ?? "";
};

const toStringList = (value: unknown): string[] => {
  if (Array.isArray(value)) return value.map((v) => String(v));
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) return parsed.map((v) => String(v));
    } catch {
      return [];
    }
  }
  return [];
};


interface Market {
  question: string;
  gameStartTime?: string;
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
  gameStartTime?: string;
}

interface LogEntry {
  slug: string;
  question: string;
}

interface BalanceInfo {
  balance: number;
}

interface AutoStatusPair {
  pair_key: string;
  assets: string[];
  disabled_assets: string[];
  enabled: boolean;
  strategy?: string;
}

function toExpiration(order: OrderView): OrderView {
  const raw = (order as unknown as { expiration?: number | string }).expiration;
  const exp = Number(raw ?? 0);
  return {
    ...order,
    expiration: Number.isFinite(exp) ? exp : 0,
  };
}

function clampOrders(list: OrderView[]): OrderView[] {
  return [...list].sort((a, b) => b.updatedAt - a.updatedAt).slice(0, 50);
}

type UserSocketMessage =
  | { type: "new_markets"; markets: Market[] }
  | { type: "recent_trades"; trades: Trade[] };

function loadSettings(): {
  defaultShares: string;
  defaultTtl: string;
  minVolume: number;
  eventsWindowBefore: string;
  eventsWindowAfter: string;
  autoBuyMaxCents: string;
  autoSellMinCents: string;
  autoSellMinShares: string;
  defaultAutoStrategy: string;
} {
  const fallback = {
    defaultShares: "10",
    defaultTtl: "8",
    minVolume: 1000,
    eventsWindowBefore: "3",
    eventsWindowAfter: "24",
    autoBuyMaxCents: "97",
    autoSellMinCents: "103",
    autoSellMinShares: "20",
    defaultAutoStrategy: "default",
  };
  try {
    const raw = localStorage.getItem("pm_settings");
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Partial<typeof fallback>;
    return {
      defaultShares: typeof parsed.defaultShares === "string" ? parsed.defaultShares : fallback.defaultShares,
      defaultTtl: typeof parsed.defaultTtl === "string" ? parsed.defaultTtl : fallback.defaultTtl,
      minVolume: typeof parsed.minVolume === "number" ? parsed.minVolume : fallback.minVolume,
      eventsWindowBefore: typeof parsed.eventsWindowBefore === "string" ? parsed.eventsWindowBefore : fallback.eventsWindowBefore,
      eventsWindowAfter: typeof parsed.eventsWindowAfter === "string" ? parsed.eventsWindowAfter : fallback.eventsWindowAfter,
      autoBuyMaxCents: typeof parsed.autoBuyMaxCents === "string" ? parsed.autoBuyMaxCents : fallback.autoBuyMaxCents,
      autoSellMinCents: typeof parsed.autoSellMinCents === "string" ? parsed.autoSellMinCents : fallback.autoSellMinCents,
      autoSellMinShares:
        typeof parsed.autoSellMinShares === "string" ? parsed.autoSellMinShares : fallback.autoSellMinShares,
      defaultAutoStrategy:
        typeof parsed.defaultAutoStrategy === "string" ? parsed.defaultAutoStrategy : fallback.defaultAutoStrategy,
    };
  } catch {
    return fallback;
  }
}

function App() {
  const logRender = import.meta.env.DEV;
  if (logRender) {
    console.time("render:App");
  }
  const settings = useMemo(() => loadSettings(), []);
  const [url, setUrl] = useState("0x507e52ef684ca2dd91f90a9d26d149dd3288beae");
  const [minVolume, setMinVolume] = useState(settings.minVolume);
  const [loading, setLoading] = useState(false);
  const [eventDataList, setEventDataList] = useState<EventData[]>([]);
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
  const [viewMode, setViewMode] = useState<"main" | "logs">("main");
  const [searchHistory, setSearchHistory] = useState<string[]>([]);
  const cashSfxRef = useRef<HTMLAudioElement | null>(null);
  const prevCashRef = useRef<number | null>(null);
  const tradeSfxRef = useRef<HTMLAudioElement | null>(null);
  const [defaultShares, setDefaultShares] = useState(settings.defaultShares);
  const [defaultTtl, setDefaultTtl] = useState(settings.defaultTtl);
  const [defaultAutoStrategy, setDefaultAutoStrategy] = useState(settings.defaultAutoStrategy);
  const [autoBuyMaxCents, setAutoBuyMaxCents] = useState(settings.autoBuyMaxCents);
  const [autoSellMinCents, setAutoSellMinCents] = useState(settings.autoSellMinCents);
  const [autoSellMinShares, setAutoSellMinShares] = useState(settings.autoSellMinShares);
  const [eventsWindowBefore, setEventsWindowBefore] = useState(settings.eventsWindowBefore);
  const [eventsWindowAfter, setEventsWindowAfter] = useState(settings.eventsWindowAfter);
  const [liveEvents, setLiveEvents] = useState<EventData[]>([]);
  const [subscribedSlugs, setSubscribedSlugs] = useState<Set<string>>(new Set());
  const [orders, setOrders] = useState<OrderView[]>([]);
  const [ordersServerNowSec, setOrdersServerNowSec] = useState<number | null>(null);
  const [ordersServerNowLocalMs, setOrdersServerNowLocalMs] = useState<number | null>(null);
  const [ordersWsStatus, setOrdersWsStatus] = useState<"connecting" | "open" | "closed" | "error">("connecting");
  const [ordersWsEvents, setOrdersWsEvents] = useState(0);
  const [ordersWsLastType, setOrdersWsLastType] = useState<string | null>(null);
  const ordersWsEventsRef = useRef(0);
  const ordersWsLastTypeRef = useRef<string | null>(null);
  const ordersWsUiUpdateRef = useRef(0);
  const [ordersWsServerPid, setOrdersWsServerPid] = useState<number | null>(null);
  const [ordersWsCloseInfo, setOrdersWsCloseInfo] = useState<string | null>(null);
  const [ordersWsErrorInfo, setOrdersWsErrorInfo] = useState<string | null>(null);
  const seenTradeIdsRef = useRef<Set<string>>(new Set());
  const [draggedWidgetKey, setDraggedWidgetKey] = useState<string | null>(null);

  const [autoPairs, setAutoPairs] = useState<Set<string>>(new Set());
  const [autoDisabledAssets, setAutoDisabledAssets] = useState<Set<string>>(new Set());
  const [autoPairStrategies, setAutoPairStrategies] = useState<Record<string, string>>({});
  const [autoStrategyOptions, setAutoStrategyOptions] = useState<string[]>(["default"]);
  const [recentFills, setRecentFills] = useState<OrderView[]>([]);
  const [backendBooksCount, setBackendBooksCount] = useState<number | null>(null);
  const [backendLatencyMs, setBackendLatencyMs] = useState<number | null>(null);
  const [assetLevels, setAssetLevels] = useState<Record<string, number>>(() => {
    try {
      const raw = localStorage.getItem("pm_asset_levels");
      if (!raw) return {};
      const parsed = JSON.parse(raw) as Record<string, number>;
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch {
      return {};
    }
  });
  const [ordersWsReconnectSeq, setOrdersWsReconnectSeq] = useState(0);
  const ordersWsReconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const ordersWsClosingRef = useRef(false);
  const positionsInitRef = useRef(false);
  const [tradeNotices, setTradeNotices] = useState<
    { id: string; market: string; outcome: string; side: "BUY" | "SELL"; size: string; price: string; ts: number }[]
  >([]);
  const fetchAuthMetricsRef = useRef<() => void>(() => {});
  const memStatsRef = useRef({
    widgets: 0,
    liveEvents: 0,
    orders: 0,
    recentFills: 0,
    recentTrades: 0,
    authPositions: 0,
    positionHistory: 0,
    subscribedSlugs: 0,
    autoPairs: 0,
    autoDisabledAssets: 0,
    tradeNotices: 0,
    ordersWsEvents: 0,
    searchHistory: 0,
  });

  const [highlightedAsset, setHighlightedAsset] = useState<string | null>(null);
  const highlightTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  const userSocketRef = useRef<WebSocket | null>(null);
  const [logIndex, setLogIndex] = useState<LogEntry[]>([]);
  const [logQuery, setLogQuery] = useState("");
  const [logSortBy] = useState<"question" | "slug" | "date">("question");
  const [logSortDir, setLogSortDir] = useState<"asc" | "desc">("asc");
  const [logFilter] = useState<"all" | "open">("all");
  const [logDateFilter, setLogDateFilter] = useState<string>("all");
  const [logSportFilter, setLogSportFilter] = useState<string>("all");
  const [logMlOnly, setLogMlOnly] = useState(false);
  const [logLoading, setLogLoading] = useState(false);
  const [logError, setLogError] = useState<string | null>(null);
  const [logGraphData, setLogGraphData] = useState<LogPoint[]>([]);
  const [logGraphLoading, setLogGraphLoading] = useState(false);
  const [logGraphError, setLogGraphError] = useState<string | null>(null);
  const [logSelection, setLogSelection] = useState<LogEntry | null>(null);
  const [logStartMs, setLogStartMs] = useState<number | null>(null);
  const [minimizedEvents, setMinimizedEvents] = useState<Set<string>>(new Set());
  const [activeEventSlug, setActiveEventSlug] = useState<string | null>(null);
  const socketWidgets = useMemo(() => {
    if (activeEventSlug === null) return [];
    return widgets.filter((w) => (w.sourceSlug ?? "") === activeEventSlug);
  }, [activeEventSlug, widgets]);
  useBookSocket(socketWidgets);
  const autoOpenSyncedRef = useRef(false);
  const [autoStatusPairs, setAutoStatusPairs] = useState<AutoStatusPair[]>([]);
  const logStartLookup = useMemo(() => {
    const map = new Map<string, number>();
    liveEvents.forEach((ev) => {
      const slug = ev.slug;
      const eventStart = ev.startDate ? new Date(ev.startDate).getTime() : null;
      ev.markets?.forEach((m) => {
        const key = `${slug}|${normalizeQuestion(m.question)}`;
        const start = m.gameStartTime ? new Date(m.gameStartTime).getTime() : eventStart;
        if (start && Number.isFinite(start)) {
          map.set(key, start);
        }
      });
    });
    return map;
  }, [liveEvents]);

  const logDates = useMemo(() => {
    const dates = new Set<string>();
    logIndex.forEach((entry) => {
      const d = extractDate(entry.slug);
      if (d) dates.add(d);
    });
    return Array.from(dates).sort().reverse();
  }, [logIndex]);

  const logSports = useMemo(() => {
    const sports = new Set<string>();
    logIndex.forEach((entry) => {
      const sport = extractSport(entry.slug);
      if (sport) sports.add(sport);
    });
    return Array.from(sports).sort();
  }, [logIndex]);
  const updateAssetLevel = useCallback((assetId: string, level: number) => {
    if (!assetId || !Number.isFinite(level)) return;
    setAssetLevels((prev) => {
      if (prev[assetId] === level) return prev;
      return { ...prev, [assetId]: level };
    });
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem("pm_asset_levels", JSON.stringify(assetLevels));
    } catch {
      // ignore storage failures
    }
  }, [assetLevels]);

  const filteredLogs = useMemo(() => {
    let items = logIndex;
    const q = logQuery.trim().toLowerCase();
    if (q) {
      items = items.filter(
        (entry) =>
          entry.slug.toLowerCase().includes(q) || entry.question.toLowerCase().includes(q)
      );
    }
    if (logFilter === "open") {
      items = items.filter((entry) => subscribedSlugs.has(entry.slug));
    }
    if (logDateFilter !== "all") {
      items = items.filter((entry) => extractDate(entry.slug) === logDateFilter);
    }
    if (logSportFilter !== "all") {
      items = items.filter((entry) => extractSport(entry.slug) === logSportFilter);
    }
    if (logMlOnly) {
      items = items.filter((entry) => {
        const name = entry.question.toUpperCase();
        if (name.includes("O_U")) return false;
        return !/[+-]\d+(\.\d+)?/.test(entry.question);
      });
    }
    const sorted = [...items].sort((a, b) => {
      if (logSortBy === "date") {
        const left = extractDate(a.slug);
        const right = extractDate(b.slug);
        const cmp = left.localeCompare(right);
        return logSortDir === "asc" ? cmp : -cmp;
      }
      const left = (logSortBy === "slug" ? a.slug : a.question).toLowerCase();
      const right = (logSortBy === "slug" ? b.slug : b.question).toLowerCase();
      const cmp = left.localeCompare(right);
      return logSortDir === "asc" ? cmp : -cmp;
    });
    return sorted;
  }, [
    logDateFilter,
    logFilter,
    logIndex,
    logQuery,
    logSortBy,
    logSortDir,
    logSportFilter,
    logMlOnly,
    subscribedSlugs,
  ]);
  const visiblePositions = useMemo(() => {
    return authPositions.filter((p) => {
      const value = Number(p.currentValue);
      return Number.isFinite(value) && value > 0.01;
    });
  }, [authPositions]);

  const fullModeKeys = useMemo(() => {
    return new Set(widgets.map((w) => w.uniqueKey));
  }, [widgets]);

  useEffect(() => {
    memStatsRef.current = {
      widgets: widgets.length,
      liveEvents: liveEvents.length,
      orders: orders.length,
      recentFills: recentFills.length,
      recentTrades: recentTrades.length,
      authPositions: authPositions.length,
      positionHistory: Object.keys(positionHistory).length,
      subscribedSlugs: subscribedSlugs.size,
      autoPairs: autoPairs.size,
      autoDisabledAssets: autoDisabledAssets.size,
      tradeNotices: tradeNotices.length,
      ordersWsEvents,
      searchHistory: searchHistory.length,
    };
  }, [
    widgets,
    liveEvents,
    orders,
    recentFills,
    recentTrades,
    authPositions,
    positionHistory,
    subscribedSlugs,
    autoPairs,
    autoDisabledAssets,
    tradeNotices,
    ordersWsEvents,
    searchHistory,
  ]);

  // useEffect(() => {
  //   if (!import.meta.env.DEV) return;
  //   const id = window.setInterval(() => {
  //     const stats = memStatsRef.current;
  //     console.log(
  //       `[mem-debug] widgets=${stats.widgets} liveEvents=${stats.liveEvents} orders=${stats.orders} recentFills=${stats.recentFills} recentTrades=${stats.recentTrades} positions=${stats.authPositions} positionHistory=${stats.positionHistory} subscribedSlugs=${stats.subscribedSlugs} autoPairs=${stats.autoPairs} autoDisabledAssets=${stats.autoDisabledAssets} tradeNotices=${stats.tradeNotices} ordersWsEvents=${stats.ordersWsEvents} searches=${stats.searchHistory}`
  //     );
  //   }, 30000);
  //   return () => window.clearInterval(id);
  // }, []);

  useEffect(() => {
    let mounted = true;
    const fetchBooks = async () => {
      try {
        const res = await fetch("http://localhost:8000/debug/books");
        if (!res.ok) return;
        const data = (await res.json()) as { active_books?: number; tracked_assets?: number };
        if (!mounted) return;
        if (typeof data.tracked_assets === "number") {
          setBackendBooksCount(data.tracked_assets);
        } else if (typeof data.active_books === "number") {
          setBackendBooksCount(data.active_books);
        }
      } catch {
        // ignore
      }
    };
    fetchBooks();
    const id = window.setInterval(fetchBooks, 10000);
    return () => {
      mounted = false;
      window.clearInterval(id);
    };
  }, []);

  useEffect(() => {
    let mounted = true;
    const fetchLatency = async () => {
      try {
        const res = await fetch("http://localhost:8000/metrics/latency");
        if (!res.ok) return;
        const data = (await res.json()) as { latency_ms?: number };
        if (!mounted) return;
        setBackendLatencyMs(typeof data.latency_ms === "number" ? data.latency_ms : null);
      } catch {
        // ignore
      }
    };
    fetchLatency();
    const id = window.setInterval(fetchLatency, 5000);
    return () => {
      mounted = false;
      window.clearInterval(id);
    };
  }, []);

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

  const assetLabels = useMemo(() => {
    const map = new Map<string, { market: string; outcome: string }>();
    widgets.forEach((w) => map.set(w.assetId, { market: w.marketQuestion, outcome: w.outcomeName }));
    authPositions.forEach((p) => {
      const market = p.title || "Unknown market";
      const outcome = p.outcome || p.asset;
      map.set(p.asset, { market, outcome });
    });
    return map;
  }, [widgets, authPositions]);

  const pushTradeNotice = useCallback(
    (order: OrderView) => {
      const label =
        assetLabels.get(order.asset_id) ??
        (order.market || order.outcome
          ? {
              market: order.market || "Unknown market",
              outcome: order.outcome || order.asset_id.slice(0, 10),
            }
          : {
              market: "Unknown market",
              outcome: order.asset_id.slice(0, 10),
            });
      const id = `${order.orderID}-${Date.now()}`;
      const notice = {
        id,
        market: label.market,
        outcome: label.outcome,
        side: order.side,
        size: order.size,
        price: order.price,
        ts: Date.now(),
      };
      setTradeNotices((prev) => [notice, ...prev].slice(0, 3));
      window.setTimeout(() => {
        setTradeNotices((prev) => prev.filter((n) => n.id !== id));
      }, 6000);
    },
    [assetLabels]
  );

  const recentFillsDisplay = useMemo(() => {
    return recentFills.map((fill) => {
      const label = assetLabels.get(fill.asset_id);
      if (!label) return fill;
      return {
        ...fill,
        market: label.market,
        outcome: label.outcome,
      };
    });
  }, [assetLabels, recentFills]);

  const handleCloseWidget = useCallback((assetId: string) => {
    dismissedAssetsRef.current = { ...dismissedAssetsRef.current, [assetId]: true };
    setWidgets((prev) => prev.filter((w) => w.assetId !== assetId));
    setHighlightedAsset((prev) => (prev === assetId ? null : prev));
  }, []);

  const handleClosePair = useCallback((pairKey: string) => {
    setWidgets((prev) => {
      const next = prev.filter((w) => w.marketQuestion !== pairKey);
      const dismissed = { ...dismissedAssetsRef.current };
      prev.forEach((w) => {
        if (w.marketQuestion === pairKey) dismissed[w.assetId] = true;
      });
      dismissedAssetsRef.current = dismissed;
      return next;
    });
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

  const toggleAutoPair = useCallback((pairKey: string) => {
    setAutoPairs((prev) => {
      const next = new Set(prev);
      if (next.has(pairKey)) next.delete(pairKey);
      else next.add(pairKey);
      return next;
    });
  }, []);

  const toggleAutoAsset = useCallback((assetId: string) => {
    setAutoDisabledAssets((prev) => {
      const next = new Set(prev);
      if (next.has(assetId)) next.delete(assetId);
      else next.add(assetId);
      return next;
    });
  }, []);

  const toggleEventMinimized = useCallback((slug: string) => {
    setMinimizedEvents((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) {
        next.delete(slug);
        eventDataList.forEach((ev) => {
          if (ev.slug && ev.slug !== slug) {
            next.add(ev.slug);
          }
        });
        setActiveEventSlug(slug);
      } else {
        next.add(slug);
        if (activeEventSlug === slug) {
          setActiveEventSlug(null);
        }
      }
      return next;
    });
  }, [activeEventSlug, eventDataList]);

  const closeEventWindow = useCallback((slug: string) => {
    setEventDataList((prev) => prev.filter((ev) => ev.slug !== slug));
    setWidgets((prev) => prev.filter((w) => w.sourceSlug !== slug));
    setMinimizedEvents((prev) => {
      if (!prev.has(slug)) return prev;
      const next = new Set(prev);
      next.delete(slug);
      return next;
    });
    if (activeEventSlug === slug) {
      setActiveEventSlug(null);
    }
  }, [activeEventSlug]);

  const killAutotrader = useCallback(async () => {
    try {
      await fetch("http://localhost:8000/auto/kill", { method: "POST" });
    } catch {
      // ignore kill failures
    } finally {
      setAutoPairs(new Set());
      setAutoDisabledAssets(new Set());
      setAutoPairStrategies({});
      setAutoStatusPairs([]);
    }
  }, []);

  const setAutoStrategy = useCallback((pairKey: string, strategy: string) => {
    setAutoPairStrategies((prev) => ({ ...prev, [pairKey]: strategy }));
  }, []);


  useEffect(() => {
    let mounted = true;
    const fetchAutoStatus = async () => {
      try {
        const res = await fetch("http://localhost:8000/auto/status");
        if (!res.ok) return;
        const data = (await res.json()) as {
          pairs?: Array<AutoStatusPair>;
        };
        if (!mounted || !Array.isArray(data.pairs)) return;
        const nextPairs = new Set<string>();
        const nextDisabled = new Set<string>();
        const nextStrategies: Record<string, string> = {};
        data.pairs.forEach((pair) => {
          if (!pair?.pair_key || pair.enabled === false) return;
          nextPairs.add(pair.pair_key);
          (pair.disabled_assets || []).forEach((asset) => nextDisabled.add(asset));
          if (pair.strategy) {
            nextStrategies[pair.pair_key] = pair.strategy;
          }
        });
        setAutoPairs(nextPairs);
        setAutoDisabledAssets(nextDisabled);
        setAutoPairStrategies(nextStrategies);
        setAutoStatusPairs(data.pairs.filter((pair) => pair?.pair_key));
      } catch {
        // ignore auto status failures
      }
    };
    fetchAutoStatus();
    return () => {
      mounted = false;
    };
  }, []);


  useEffect(() => {
    let mounted = true;
    const loadStrategies = async () => {
      try {
        const res = await fetch("http://localhost:8000/auto/strategies");
        if (!res.ok) return;
        const data = (await res.json()) as { strategies?: string[] };
        if (!mounted || !Array.isArray(data.strategies) || data.strategies.length === 0) return;
        setAutoStrategyOptions(data.strategies);
      } catch {
        // ignore strategy load failures
      }
    };
    loadStrategies();
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    if (autoOpenSyncedRef.current) return;
    if (autoPairs.size === 0) return;
    const slugsToOpen = new Set<string>();
    widgets.forEach((w) => {
      if (autoPairs.has(w.marketQuestion) && w.sourceSlug) {
        slugsToOpen.add(w.sourceSlug);
      }
    });
    if (slugsToOpen.size === 0) return;
    setMinimizedEvents((prev) => {
      let changed = false;
      const next = new Set(prev);
      slugsToOpen.forEach((slug) => {
        if (next.has(slug)) {
          next.delete(slug);
          changed = true;
        }
      });
      return changed ? next : prev;
    });
    autoOpenSyncedRef.current = true;
  }, [autoPairs, widgets]);

  useEffect(() => {
  return () => {
      if (userSocketRef.current) userSocketRef.current.close();
      if (ordersWsReconnectTimerRef.current) window.clearTimeout(ordersWsReconnectTimerRef.current);
      ordersWsClosingRef.current = true;
      if (highlightTimeout.current) window.clearTimeout(highlightTimeout.current);
      if (closePositionsTimerRef.current) window.clearTimeout(closePositionsTimerRef.current);
      if (closeOrdersTimerRef.current) window.clearTimeout(closeOrdersTimerRef.current);
      if (closeSettingsTimerRef.current) window.clearTimeout(closeSettingsTimerRef.current);
    };
  }, []);


  useEffect(() => {
    if (userSocketRef.current) {
      userSocketRef.current.close();
    }
    ordersWsClosingRef.current = false;
    setOrdersWsStatus("connecting");
    setOrdersWsCloseInfo(null);
    setOrdersWsErrorInfo(null);
    const ws = new WebSocket("ws://localhost:8000/ws/user");
    userSocketRef.current = ws;

    ws.onopen = () => {
      setOrdersWsStatus("open");
      setOrdersWsCloseInfo(null);
      setOrdersWsErrorInfo(null);
    };
    ws.onclose = (event) => {
      setOrdersWsStatus("closed");
      setOrdersWsCloseInfo(`code=${event.code} reason=${event.reason || "none"}`);
      if (ordersWsClosingRef.current) return;
      if (event.code === 1000 || event.code === 1005) {
        return;
      }
      if (ordersWsReconnectTimerRef.current) {
        window.clearTimeout(ordersWsReconnectTimerRef.current);
      }
      ordersWsReconnectTimerRef.current = window.setTimeout(
        () => setOrdersWsReconnectSeq((prev) => prev + 1),
        3000
      );
    };
    ws.onerror = (event) => {
      console.error("Orders WS error", event);
      setOrdersWsStatus("error");
      setOrdersWsErrorInfo("WebSocket error");
      if (ordersWsClosingRef.current) return;
      if (ordersWsReconnectTimerRef.current) {
        window.clearTimeout(ordersWsReconnectTimerRef.current);
      }
      ordersWsReconnectTimerRef.current = window.setTimeout(
        () => setOrdersWsReconnectSeq((prev) => prev + 1),
        1000
      );
    };
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data) as
        | { type: "snapshot"; orders: OrderView[]; server_now?: number }
        | { type: "opened"; order: OrderView; server_now?: number }
        | { type: "closed"; order: OrderView; event?: string; server_now?: number; trade_id?: string; trade_status?: string }
        | { type: "update"; order: OrderView; event?: string; server_now?: number }
        | { type: "status"; status: string; pid?: number; server_now?: number }
        | { type: "error"; error: string }
        | { type: "ping"; server_now?: number };
      if ("server_now" in data && typeof data.server_now === "number") {
        setOrdersServerNowSec(data.server_now);
        setOrdersServerNowLocalMs(Date.now());
      }
      if (data.type === "ping") {
        return;
      }
      ordersWsEventsRef.current += 1;
      ordersWsLastTypeRef.current = data.type;
      const now = Date.now();
      if (now - ordersWsUiUpdateRef.current >= 1000) {
        ordersWsUiUpdateRef.current = now;
        setOrdersWsEvents(ordersWsEventsRef.current);
        setOrdersWsLastType(ordersWsLastTypeRef.current);
      }

      if (data.type === "snapshot") {
        const now = Date.now();
        const next = data.orders.map((o) => ({
          ...toExpiration(o),
          status: "open" as const,
          updatedAt: now,
        }));
        setOrders((prev) => {
          const optimistic = prev.filter((o) => o.orderID.startsWith("optimistic-"));
          return clampOrders([...next, ...optimistic]);
        });
      } else if (data.type === "opened") {
        const now = Date.now();
        setOrders((prev) => {
          if (prev.some((o) => o.orderID === data.order.orderID)) return prev;
          const filtered = prev.filter((o) => !o.orderID.startsWith("optimistic-"));
          return clampOrders([{ ...toExpiration(data.order), status: "open" as const, updatedAt: now }, ...filtered]);
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
              pushTradeNotice(data.order);
              setRecentFills((prev) => {
                const next = [{ ...data.order, status: "closed" as const, updatedAt: Date.now() }, ...prev];
                return next.slice(0, 20);
              });
            }
          } else {
            playTradeFilled();
            pushTradeNotice(data.order);
            setRecentFills((prev) => {
              const next = [{ ...data.order, status: "closed" as const, updatedAt: Date.now() }, ...prev];
              return next.slice(0, 20);
            });
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
          return clampOrders(updated);
        });
      } else if (data.type === "update") {
        const now = Date.now();
        setOrders((prev) => {
          const updated = prev.map((o) =>
            o.orderID === data.order.orderID
              ? { ...o, updatedAt: now }
              : o
          );
          return clampOrders(updated);
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
      ordersWsClosingRef.current = true;
      ws.close();
      if (userSocketRef.current === ws) {
        userSocketRef.current = null;
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ordersWsReconnectSeq]);


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

  useEffect(() => {
    try {
      const raw = localStorage.getItem("pm_settings");
      if (!raw) return;
      const parsed = JSON.parse(raw) as Partial<{
        defaultShares: string;
        defaultTtl: string;
        minVolume: number;
        eventsWindowBefore: string;
        eventsWindowAfter: string;
        autoBuyMaxCents: string;
        autoSellMinCents: string;
        autoSellMinShares: string;
        defaultAutoStrategy: string;
      }>;
      if (typeof parsed.defaultShares === "string") setDefaultShares(parsed.defaultShares);
      if (typeof parsed.defaultTtl === "string") setDefaultTtl(parsed.defaultTtl);
      if (typeof parsed.minVolume === "number") setMinVolume(parsed.minVolume);
      if (typeof parsed.eventsWindowBefore === "string") setEventsWindowBefore(parsed.eventsWindowBefore);
      if (typeof parsed.eventsWindowAfter === "string") setEventsWindowAfter(parsed.eventsWindowAfter);
      if (typeof parsed.autoBuyMaxCents === "string") setAutoBuyMaxCents(parsed.autoBuyMaxCents);
      if (typeof parsed.autoSellMinCents === "string") setAutoSellMinCents(parsed.autoSellMinCents);
      if (typeof parsed.autoSellMinShares === "string") setAutoSellMinShares(parsed.autoSellMinShares);
      if (typeof parsed.defaultAutoStrategy === "string") setDefaultAutoStrategy(parsed.defaultAutoStrategy);
    } catch {
      // ignore bad local storage
    }
  }, []);

  useEffect(() => {
    const payload = {
      defaultShares,
      defaultTtl,
      minVolume,
      eventsWindowBefore,
      eventsWindowAfter,
      autoBuyMaxCents,
      autoSellMinCents,
      autoSellMinShares,
      defaultAutoStrategy,
    };
    try {
      localStorage.setItem("pm_settings", JSON.stringify(payload));
    } catch {
      // ignore storage failures
    }
  }, [
    defaultShares,
    defaultTtl,
    minVolume,
    eventsWindowBefore,
    eventsWindowAfter,
    autoBuyMaxCents,
    autoSellMinCents,
    autoSellMinShares,
    defaultAutoStrategy,
  ]);

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
    fetchAuthMetricsRef.current = () => void fetchAuthMetrics();
  }, [fetchAuthMetrics]);

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
        const beforeNum = Number(eventsWindowBefore);
        const afterNum = Number(eventsWindowAfter);
        const before = Number.isFinite(beforeNum) ? beforeNum : 0;
        const after = Number.isFinite(afterNum) ? afterNum : 24;
        const res = await fetch(
          `${baseUrl}/events/list?limit=120&window_before_hours=${before}&window_hours=${after}`
        );
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
  }, [eventsWindowBefore, eventsWindowAfter]);

  const resolveInput = useCallback(async (mode: "replace" | "add", override?: string) => {
    const input = (override ?? url).trim();
    if (!input) return;
    pushHistory(input);

    const isAddress = input.startsWith("0x") && input.length === 42;

      if (mode === "replace") {
        if (userSocketRef.current) {
          userSocketRef.current.close();
          userSocketRef.current = null;
        }
        setEventDataList([]);
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

      setEventDataList([
        { title: `Monitor: ${input.slice(0, 6)}...${input.slice(-4)}`, slug: "", markets: [] },
      ]);
      setMinimizedEvents(new Set());
      setActiveEventSlug("");

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
                gameStartTime: market.gameStartTime,
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
            const entries = Object.entries(updated);
            if (entries.length <= 50) return updated;
            entries.sort((a, b) => (b[1]?.timestamp ?? 0) - (a[1]?.timestamp ?? 0));
            return Object.fromEntries(entries.slice(0, 50));
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
      setEventDataList((prev) => {
        if (mode === "replace") {
          return [data];
        }
        const exists = prev.some((item) => item.slug === data.slug);
        return exists ? prev : [...prev, data];
      });
      if (data.slug) {
        setActiveEventSlug(data.slug);
        setMinimizedEvents(() => {
          const slugs = eventDataList.map((ev) => ev.slug).filter(Boolean);
          const next = new Set<string>();
          slugs.forEach((slug) => {
            if (slug && slug !== data.slug) {
              next.add(slug);
            }
          });
          return next;
        });
      }
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
            gameStartTime: market.gameStartTime,
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
  }, [eventDataList, fetchUserMetrics, minVolume, pushHistory, url]);

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
    setEventDataList((prev) => prev.filter((ev) => ev.slug !== slug));
  };

  useEffect(() => {
    if (positionsInitRef.current) return;
    if (!authPositions.length) return;
    const slugs = new Set<string>();
    authPositions.forEach((pos) => {
      const valueNum = Number(pos.currentValue);
      if (!Number.isFinite(valueNum) || valueNum <= 0.01) return;
      const slug = pos.eventSlug || pos.slug;
      if (slug) slugs.add(slug);
    });
    if (slugs.size === 0) return;
    positionsInitRef.current = true;
    slugs.forEach((slug) => {
      void resolveInput("add", slug);
    });
  }, [authPositions, resolveInput]);

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

  const openLogs = () => {
    setViewMode("logs");
  };

  const closeLogs = () => {
    setViewMode("main");
  };

  useEffect(() => {
    if (viewMode !== "logs") return;
    const loadIndex = async () => {
      setLogLoading(true);
      setLogError(null);
      try {
        const res = await fetch("http://localhost:8000/logs/index");
        if (!res.ok) throw new Error("Failed to load logs");
        const data = (await res.json()) as LogEntry[];
        setLogIndex(data);
      } catch (err) {
        setLogError(err instanceof Error ? err.message : "Failed to load logs");
      } finally {
        setLogLoading(false);
      }
    };
    void loadIndex();
  }, [viewMode]);

  const loadLogGraph = async (entry: LogEntry) => {
    setLogSelection(entry);
    setLogGraphLoading(true);
    setLogGraphError(null);
    try {
      const params = new URLSearchParams({
        slug: entry.slug,
        question: entry.question,
        max_rows: "2000",
      });
      const res = await fetch(`http://localhost:8000/logs/market?${params.toString()}`);
      if (!res.ok) throw new Error("Log not found");
      const payload = (await res.json()) as { rows?: Array<Record<string, string>> };
      const rows = payload.rows ?? [];
      const lookupKey = `${entry.slug}|${normalizeQuestion(entry.question)}`;
      const startMs = logStartLookup.get(lookupKey) ?? null;
      const times = rows
        .map((row) => new Date(row.timestamp ?? "").getTime())
        .filter((t) => Number.isFinite(t) && t > 0);
      const t0 = times.length ? Math.min(...times) : Date.now();
      const parsed = rows.map((row) => {
        const rel = Number(row.time_since_gameStartTime);
        const hasRelative = Number.isFinite(rel);
        const ts = new Date(row.timestamp ?? "").getTime();
        const t = hasRelative ? rel : Number.isFinite(ts) ? Math.max(0, Math.round((ts - t0) / 1000)) : 0;
        const tsMs = hasRelative && Number.isFinite(startMs || NaN) ? (startMs as number) + rel * 1000 : Number.isFinite(ts) ? ts : 0;
        const bid1 = Number(row.best_bid_1);
        const ask1 = Number(row.best_ask_1);
        const bid2 = Number(row.best_bid_2);
        const ask2 = Number(row.best_ask_2);
        return {
          t,
          tsMs,
          condition_1: row.condition_1 ?? "",
          condition_2: row.condition_2 ?? "",
          best_bid_1: Number.isFinite(bid1) ? bid1 : null,
          best_ask_1: Number.isFinite(ask1) ? ask1 : null,
          best_bid_2: Number.isFinite(bid2) ? bid2 : null,
          best_ask_2: Number.isFinite(ask2) ? ask2 : null,
        };
      });
      setLogStartMs(Number.isFinite(startMs || NaN) ? (startMs as number) : null);
      setLogGraphData(parsed);
    } catch (err) {
      setLogGraphError(err instanceof Error ? err.message : "Failed to load graph");
      setLogGraphData([]);
    } finally {
      setLogGraphLoading(false);
    }
  };

  const content = (
  <div className="h-screen w-full bg-black font-sans text-slate-200 overflow-hidden flex flex-col">
    {tradeNotices.length > 0 && (
      <div className="fixed top-32 left-1/2 -translate-x-1/2 z-50 flex flex-col gap-3 items-center">
        {tradeNotices.map((notice) => (
          <Card key={notice.id} className="border-slate-800 bg-slate-950/90 shadow-lg w-[380px]">
            <CardContent className="p-4 text-sm">
              <div className="flex items-center justify-between gap-3">
                <div className="flex flex-col min-w-0">
                  <span className="text-slate-200 font-semibold truncate max-w-[300px]">
                    {notice.market}
                  </span>
                  <span className="text-[11px] text-slate-400 truncate max-w-[300px]">
                    {notice.outcome}
                  </span>
                </div>
                <Badge
                  className={`text-[10px] uppercase ${
                    notice.side === "BUY"
                      ? "bg-blue-600/20 text-blue-300"
                      : "bg-red-600/20 text-red-300"
                  }`}
                >
                  {notice.side}
                </Badge>
              </div>
              <div className="mt-2 text-[11px] text-slate-400 font-mono">
                {Number(notice.size).toFixed(2)} sh @ {(Number(notice.price)*100).toFixed(0)}¢
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    )}
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
      onLogsClick={openLogs}
      logsCount={logIndex.length || null}
      ordersCount={orders.filter((o) => o.status === "open").length}
      backendBooksCount={backendBooksCount}
      backendLatencyMs={backendLatencyMs}
      notificationsCount={recentFills.length}
      recentFills={recentFillsDisplay}
      ordersWsStatus={ordersWsStatus}
      ordersWsEvents={ordersWsEvents}
      ordersWsLastType={ordersWsLastType}
      ordersWsServerPid={ordersWsServerPid}
      ordersWsCloseInfo={ordersWsCloseInfo}
      ordersWsErrorInfo={ordersWsErrorInfo}
      recentSearches={searchHistory}
      onSelectSearch={handleSelectSearch}
    />

    {viewMode === "logs" && (
      <div className="flex-1 w-full overflow-hidden">
        <div className="h-full w-full px-4 py-4">
          <div className="flex items-center justify-between">
            <div className="text-sm uppercase tracking-widest text-slate-400 font-bold">Logs</div>
            <Button
              onClick={closeLogs}
              className="h-7 px-3 text-[10px] uppercase font-bold border border-slate-800 bg-slate-950 text-slate-300 hover:text-white hover:border-slate-700 transition-colors"
            >
              Back
            </Button>
          </div>
          <div className="mt-4 grid h-[calc(100%-2.5rem)] grid-cols-[320px_minmax(0,1fr)] gap-4">
            <div className="rounded-md border border-slate-800 bg-slate-950/95 p-3">
              <div className="mb-2 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Button
                    onClick={() => {
                      setLogSortDir((prev) => (prev === "asc" ? "desc" : "asc"));
                    }}
                    className="h-7 px-2 text-[10px] uppercase font-bold border border-slate-800 bg-slate-950 text-slate-300 hover:text-white hover:border-slate-700 transition-colors"
                  >
                    {logSortDir === "asc" ? "Asc" : "Desc"}
                  </Button>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    onClick={() => {
                      setLogMlOnly((prev) => !prev);
                    }}
                    className={`h-7 px-2 text-[10px] uppercase font-bold border transition-colors ${
                      logMlOnly
                        ? "border-emerald-700 bg-emerald-900/40 text-emerald-100"
                        : "border-slate-800 bg-slate-950 text-slate-300 hover:text-white hover:border-slate-700"
                    }`}
                  >
                    ML Only
                  </Button>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button className="h-7 px-2 text-[10px] uppercase font-bold border border-slate-800 bg-slate-950 text-slate-300 hover:text-white hover:border-slate-700 transition-colors">
                        Sport {logSportFilter === "all" ? "All" : logSportFilter}
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent sideOffset={6} align="end">
                      <DropdownMenuLabel>Sport</DropdownMenuLabel>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem onClick={() => setLogSportFilter("all")}>
                        All
                      </DropdownMenuItem>
                      {logSports.map((sport) => (
                        <DropdownMenuItem
                          key={sport}
                          onClick={() => setLogSportFilter(sport)}
                        >
                          {sport}
                        </DropdownMenuItem>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button className="h-7 px-2 text-[10px] uppercase font-bold border border-slate-800 bg-slate-950 text-slate-300 hover:text-white hover:border-slate-700 transition-colors">
                        Date {logDateFilter === "all" ? "All" : logDateFilter}
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent sideOffset={6} align="end">
                      <DropdownMenuLabel>Date</DropdownMenuLabel>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem onClick={() => setLogDateFilter("all")}>
                        All
                      </DropdownMenuItem>
                      {logDates.map((date) => (
                        <DropdownMenuItem
                          key={date}
                          onClick={() => setLogDateFilter(date)}
                        >
                          {date}
                        </DropdownMenuItem>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              </div>
              <Input
                value={logQuery}
                onChange={(e) => setLogQuery(e.target.value)}
                placeholder="Search logs..."
                className="h-8 bg-black border-slate-800 text-xs"
              />
              <div className="mt-3">
                {logError ? (
                  <div className="text-[11px] text-amber-400">{logError}</div>
                ) : logLoading ? (
                  <div className="text-[11px] text-slate-400">Loading logs...</div>
                ) : (
                  <div className="h-[calc(100vh-240px)] overflow-y-auto [&::-webkit-scrollbar]:hidden">
                    <div className="space-y-1">
                      {filteredLogs.map((entry) => (
                        <button
                          onClick={() => loadLogGraph(entry)}
                          className={`w-full rounded-md px-2 py-1 text-left text-[11px] text-slate-200 hover:bg-slate-900 ${
                            logSelection?.slug === entry.slug && logSelection?.question === entry.question
                              ? "bg-slate-900/70"
                              : ""
                          }`}
                        >
                          <div className="truncate font-semibold">{entry.question.replace(/_/g, " ")}</div>
                          <div className="text-[10px] text-slate-500">{entry.slug}</div>
                        </button>
                      ))}
                      {filteredLogs.length === 0 && (
                        <div className="text-[11px] text-slate-500">No logs match your search.</div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </div>
            <div className="rounded-md border border-slate-800 bg-slate-950/40 p-3">
              <div className="text-[10px] uppercase tracking-widest text-slate-400 font-bold">
                {logSelection ? logSelection.question.replace(/_/g, " ") : "Select a log"}
              </div>
              <div className="mt-3 h-[70vh] rounded-md border border-slate-800 bg-slate-950/85 p-2">
                {logGraphError ? (
                  <div className="text-[11px] text-amber-400">{logGraphError}</div>
                ) : logGraphLoading ? (
                  <div className="text-[11px] text-slate-400">Loading chart...</div>
                ) : logGraphData.length === 0 ? (
                  <div className="text-[11px] text-slate-500">Pick a log to view its chart.</div>
                ) : (
                  <LogChart data={logGraphData} startMs={logStartMs} loading={logGraphLoading} error={logGraphError} emptyMessage="Pick a log to view its chart." heightClass="h-full" />
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    )}
    
    {viewMode === "main" && (
      <>
        {/* Live Events Strip */}
        {liveEvents.length > 0 && (
          <div className="px-4 pt-2">
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
                  outcomes: Array.isArray((m as { outcomes?: string[] }).outcomes)
                    ? (m as { outcomes?: string[] }).outcomes
                    : toStringList((m as { outcomes?: unknown }).outcomes),
                  clobTokenIds: Array.isArray((m as { clobTokenIds?: string[] }).clobTokenIds)
                    ? (m as { clobTokenIds?: string[] }).clobTokenIds
                    : toStringList((m as { clobTokenIds?: unknown }).clobTokenIds),
                })),
                raw: ev,
              }))}
              subscribed={subscribedSlugs}
              onAdd={handleAddSlug}
              onRemove={handleRemoveSlug}
            />
          </div>
        )}

        <div className="flex-1 w-full overflow-y-auto [&::-webkit-scrollbar]:hidden">
          {/* Horizontal Dashboard Space */}
          <div className="p-4 max-w-none mx-auto space-y-4 w-full">
            {/* Header Section: Event Title & Compact Trades Table */}
            {eventDataList.map((eventData) => {
              const eventGroups = widgets
                .filter((w) => w.sourceSlug === eventData.slug)
                .reduce<Record<string, TokenWidget[]>>((acc, w) => {
                  const key = w.marketQuestion || "Unknown";
                  if (!acc[key]) acc[key] = [];
                  acc[key].push(w);
                  return acc;
                }, {});
              const pairCount = Object.keys(eventGroups).length;
              const minimized = minimizedEvents.has(eventData.slug);

              return (
                  <Event
                    key={eventData.slug || eventData.title}
                    title={eventData.title}
                    slug={eventData.slug}
                    pairCount={pairCount}
                    minVolumeLabel={`Min Vol $${Math.round(minVolume / 1000)}k+`}
                    minimized={minimized}
                    onToggleMinimize={() => toggleEventMinimized(eventData.slug)}
                    onClose={() => closeEventWindow(eventData.slug)}
                    raw={eventData}
                  >
                  {eventData.slug === "" && recentTrades.length > 0 ? (
                    <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
                      <div className="lg:col-span-2">
                        <RecentTradesTable
                          trades={recentTrades}
                          onInteract={triggerHighlight}
                        />
                      </div>
                    </div>
                  ) : null}

                  <div className="grid grid-cols-1 sm:grid-cols-1 lg:grid-cols-2 xl:grid-cols-2 2xl:grid-cols-3 gap-4 pb-0">
                    {Object.entries(eventGroups).map(([pairKey, group]) => (
                      <BookPair
                        key={pairKey}
                        pairKey={pairKey}
                        group={group}
                        autoPairs={autoPairs}
                        autoDisabledAssets={autoDisabledAssets}
                        autoBuyMaxCents={autoBuyMaxCents}
                        autoSellMinCents={autoSellMinCents}
                      autoSellMinShares={autoSellMinShares}
                      autoStrategy={autoPairStrategies[pairKey] || defaultAutoStrategy || "default"}
                      onSelectAutoStrategy={setAutoStrategy}
                      autoStrategyOptions={autoStrategyOptions}
                      positionHistory={positionHistory}
                      authPositions={authPositions}
                      orders={orders}
                      highlightedAsset={highlightedAsset}
                      defaultShares={defaultShares}
                      defaultTtl={defaultTtl}
                      assetLevels={assetLevels}
                      onLevelChange={updateAssetLevel}
                      draggedWidgetKey={draggedWidgetKey}
                      setDraggedWidgetKey={setDraggedWidgetKey}
                      swapWidgets={swapWidgets}
                        toggleAutoPair={toggleAutoPair}
                        toggleAutoAsset={toggleAutoAsset}
                        handleClosePair={handleClosePair}
                        handleCloseWidget={handleCloseWidget}
                        fullModeKeys={fullModeKeys}
                        ordersServerNowSec={ordersServerNowSec}
                        ordersServerNowLocalMs={ordersServerNowLocalMs}
                        apiBaseUrl="http://localhost:8000"
                      />
                    ))}
                  </div>
                </Event>
              );
            })}

            {/* High-Density Order Book Grid */}
            <div className="grid grid-cols-1 sm:grid-cols-1 lg:grid-cols-2 xl:grid-cols-2 2xl:grid-cols-3 gap-4 pb-0">
              {Object.entries(
                widgets
                  .filter((w) => {
                    if (!w.sourceSlug) return true;
                    return !eventDataList.some((ev) => ev.slug === w.sourceSlug);
                  })
                  .reduce<Record<string, TokenWidget[]>>((acc, w) => {
                    const key = w.marketQuestion || "Unknown";
                    if (!acc[key]) acc[key] = [];
                    acc[key].push(w);
                    return acc;
                  }, {})
              ).map(([pairKey, group]) => (
                <BookPair
                  key={pairKey}
                  pairKey={pairKey}
                  group={group}
                  autoPairs={autoPairs}
                  autoDisabledAssets={autoDisabledAssets}
                  autoBuyMaxCents={autoBuyMaxCents}
                  autoSellMinCents={autoSellMinCents}
                  autoSellMinShares={autoSellMinShares}
                  autoStrategy={autoPairStrategies[pairKey] || defaultAutoStrategy || "default"}
                  onSelectAutoStrategy={setAutoStrategy}
                  autoStrategyOptions={autoStrategyOptions}
                  positionHistory={positionHistory}
                  authPositions={authPositions}
                  orders={orders}
                  highlightedAsset={highlightedAsset}
                  defaultShares={defaultShares}
                  defaultTtl={defaultTtl}
                  assetLevels={assetLevels}
                  onLevelChange={updateAssetLevel}
                  draggedWidgetKey={draggedWidgetKey}
                  setDraggedWidgetKey={setDraggedWidgetKey}
                  swapWidgets={swapWidgets}
                  toggleAutoPair={toggleAutoPair}
                  toggleAutoAsset={toggleAutoAsset}
                  handleClosePair={handleClosePair}
                  handleCloseWidget={handleCloseWidget}
                  fullModeKeys={fullModeKeys}
                  ordersServerNowSec={ordersServerNowSec}
                  ordersServerNowLocalMs={ordersServerNowLocalMs}
                  apiBaseUrl="http://localhost:8000"
                />
              ))}
            </div>
          </div>
        </div>
      </>
    )}
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
            positions={visiblePositions}
            onSelect={(pos) => {
              const assetsToAdd: Array<{ assetId: string; outcomeName: string }> = [
                { assetId: pos.asset, outcomeName: pos.outcome || "Outcome" },
              ];
              if (pos.oppositeAsset) {
                assetsToAdd.push({
                  assetId: pos.oppositeAsset,
                  outcomeName: pos.oppositeOutcome || "Opposite",
                });
              }

              const dismissed = { ...dismissedAssetsRef.current };
              assetsToAdd.forEach(({ assetId }) => {
                if (dismissed[assetId]) delete dismissed[assetId];
              });
              dismissedAssetsRef.current = dismissed;

              setWidgets((prev) => {
                const existing = new Set(prev.map((w) => w.assetId));
                const marketQuestion = pos.title || "Position";
                const volume = Number(pos.currentValue);
                const marketVolume = Number.isFinite(volume) ? volume : 0;
                const additions = assetsToAdd
                  .filter(({ assetId }) => !existing.has(assetId))
                  .map(({ assetId, outcomeName }) => ({
                    uniqueKey: assetId,
                    assetId,
                    outcomeName,
                    marketQuestion,
                    marketVolume,
                  }));
                if (additions.length === 0) return prev;
                return [...additions, ...prev];
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
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-[10px] text-slate-500 uppercase font-bold">Auto Buy Max (¢)</label>
                <Input
                  value={autoBuyMaxCents}
                  onChange={(e) => setAutoBuyMaxCents(e.target.value)}
                  onFocus={(e) => e.currentTarget.select()}
                  className="h-8 bg-black border-slate-800 font-mono text-sm"
                />
              </div>
              <div className="space-y-1">
                <label className="text-[10px] text-slate-500 uppercase font-bold">Auto Sell Min (¢)</label>
                <Input
                  value={autoSellMinCents}
                  onChange={(e) => setAutoSellMinCents(e.target.value)}
                  onFocus={(e) => e.currentTarget.select()}
                  className="h-8 bg-black border-slate-800 font-mono text-sm"
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-[10px] text-slate-500 uppercase font-bold">Auto Sell Min Shares</label>
                <Input
                  value={autoSellMinShares}
                  onChange={(e) => setAutoSellMinShares(e.target.value)}
                  onFocus={(e) => e.currentTarget.select()}
                  className="h-8 bg-black border-slate-800 font-mono text-sm"
                />
              </div>
            </div>
            <div className="space-y-1">
              <label className="text-[10px] text-slate-500 uppercase font-bold">Default Auto Strategy</label>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button className="h-8 w-full justify-between border border-slate-800 bg-black text-xs uppercase font-bold text-slate-300 hover:text-white">
                    {defaultAutoStrategy || "default"}
                    <span className="text-[10px] text-slate-500">▼</span>
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent sideOffset={6} align="end">
                  <DropdownMenuLabel>Auto Strategy</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  {autoStrategyOptions.map((strategy) => (
                    <DropdownMenuItem
                      key={strategy}
                      onClick={() => setDefaultAutoStrategy(strategy)}
                    >
                      {strategy}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-[10px] text-slate-500 uppercase font-bold">Events Window Before (h)</label>
                <Input
                  value={eventsWindowBefore}
                  onChange={(e) => setEventsWindowBefore(e.target.value)}
                  onFocus={(e) => e.currentTarget.select()}
                  className="h-8 bg-black border-slate-800 font-mono text-sm"
                />
              </div>
              <div className="space-y-1">
                <label className="text-[10px] text-slate-500 uppercase font-bold">Events Window After (h)</label>
                <Input
                  value={eventsWindowAfter}
                  onChange={(e) => setEventsWindowAfter(e.target.value)}
                  onFocus={(e) => e.currentTarget.select()}
                  className="h-8 bg-black border-slate-800 font-mono text-sm"
                />
              </div>
            </div>
            <div className="border-t border-slate-800 pt-3 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[10px] uppercase tracking-widest text-slate-400 font-bold">Auto Monitor</span>
                <Button
                  onClick={killAutotrader}
                  className="h-7 px-2 text-[10px] uppercase font-bold border border-red-900/60 bg-red-900/20 text-red-200 hover:text-white hover:border-red-700"
                >
                  Kill Auto
                </Button>
              </div>
              {autoStatusPairs.length === 0 ? (
                <div className="text-[11px] text-slate-500">No active auto pairs.</div>
              ) : (
                <div className="space-y-2 max-h-[200px] overflow-auto pr-1">
                  {autoStatusPairs.map((pair) => (
                    <div key={pair.pair_key} className="rounded border border-slate-800 bg-slate-950/60 p-2">
                      <div className="text-[11px] text-slate-200 font-semibold truncate">
                        {pair.pair_key}
                      </div>
                      <div className="mt-1 space-y-1">
                        {pair.assets.map((asset) => {
                          const label = assetLabels.get(asset);
                          const disabled = pair.disabled_assets.includes(asset);
                          return (
                            <div key={asset} className="flex items-center justify-between text-[10px]">
                              <span className="text-slate-400 truncate max-w-[220px]">
                                {label?.outcome || asset}
                              </span>
                              <span className={disabled ? "text-slate-500" : "text-emerald-400"}>
                                {disabled ? "off" : "on"}
                              </span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    )}
  </div>
  );
  if (logRender) {
    console.timeEnd("render:App");
  }
  return content;
}

export default App;


