import { useEffect, useRef, useState } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";

interface NavbarProps {
  userAddress: string;
  inputValue: string;
  setInputValue: (val: string) => void;
  onResolve: () => void;
  onAdd?: () => void;
  loading: boolean;
  apiBaseUrl?: string;
  balance?: number | null;
  portfolio?: number | null;
  positionsCount?: number | null;
  onPositionsClick?: () => void;
  onOrdersClick?: () => void;
  onSettingsClick?: () => void;
  ordersCount?: number | null;
  notificationsCount?: number | null;
  ordersWsStatus?: "connecting" | "open" | "closed" | "error";
  ordersWsEvents?: number;
  ordersWsLastType?: string | null;
  ordersWsServerPid?: number | null;
  ordersWsCloseInfo?: string | null;
  ordersWsErrorInfo?: string | null;
  recentSearches?: string[];
  onSelectSearch?: (value: string) => void;
  onLogsClick?: () => void;
  logsCount?: number | null;
  backendBooksCount?: number | null;
  recentFills?: Array<{
    orderID: string;
    updatedAt?: number | string;
    market?: string;
    outcome?: string;
    asset_id?: string;
    side?: "BUY" | "SELL";
    size?: number | string;
    price?: number | string;
  }>;
}

// interface BalanceData {
//   portfolioValue: number;
//   cash: number;
// }

export function Navbar({ 
//   userAddress, 
  inputValue, 
  setInputValue, 
  onResolve, 
  onAdd,
  loading,
//   apiBaseUrl = "http://localhost:8000" 
  balance,
  portfolio,
  positionsCount,
  onPositionsClick,
  onOrdersClick,
  // onNotificationsClick,
  onSettingsClick,
  ordersCount,
  notificationsCount,
//   ordersWsStatus,
//   ordersWsEvents,
//   ordersWsLastType,
//   ordersWsServerPid,
//   ordersWsCloseInfo,
//   ordersWsErrorInfo,
  recentSearches = [],
  onSelectSearch,
  onLogsClick,
  logsCount,
  backendBooksCount,
  recentFills = [],
}: NavbarProps) {
  const [historyOpen, setHistoryOpen] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const notificationsRef = useRef<HTMLDivElement | null>(null);
  const fills = recentFills;

  useEffect(() => {
    if (!notificationsOpen) return;
    const handleClick = (event: MouseEvent) => {
      if (!notificationsRef.current) return;
      if (notificationsRef.current.contains(event.target as Node)) return;
      setNotificationsOpen(false);
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [notificationsOpen]);
//   const [data, setData] = useState<BalanceData>({ portfolioValue: 0, cash: 0 });

//   useEffect(() => {
//     const fetchBalance = async () => {
//       try {
//         const res = await fetch(`${apiBaseUrl}/user/balance?address=${userAddress}`);
//         const json = await res.json();
//         setData({ portfolioValue: json.portfolio || 0, cash: json.cash || 0 });
//       } catch (e) {
//         console.error("Balance fetch failed", e);
//       }
//     };
//     fetchBalance();
//     const interval = setInterval(fetchBalance, 990000);
//     return () => clearInterval(interval);
//   }, [userAddress, apiBaseUrl]);

  return (
    <nav className="flex items-center justify-between px-3 py-2 border-b border-slate-800 bg-[#0f172a] sticky top-0 z-50 h-16">
      {/* Left: Branding */}
      <div className="flex items-center gap-3 min-w-[180px]">
        <div className="flex -space-x-1">
          <div className="w-3 h-6 bg-blue-600 rounded-full animate-pulse" />
          <div className="w-3 h-6 bg-blue-400 rounded-full" />
        </div>
        <span className="text-lg font-black italic text-white uppercase tracking-tighter">
          Poly<span className="text-blue-500">Terminal</span>
        </span>
      </div>

      {/* Center: Expanded Search Bar */}
      <div className="flex items-center gap-2 flex-1 max-w-4xl px-4">
        <div className="relative w-full">
          <Input
            placeholder="Search URL, Slug, or 0x..."
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onResolve()}
            onFocus={() => setHistoryOpen(true)}
            onBlur={() => setHistoryOpen(false)}
            className="bg-slate-900/50 border-slate-700 h-9 pl-9 text-xs text-slate-200 focus:bg-slate-900 transition-all w-full"
          />
          <span className="absolute left-3 top-2.5 text-slate-500 text-xs">🔍</span>
          {recentSearches.length > 0 && historyOpen && (
            <div className="absolute left-0 right-0 mt-1">
              <div className="rounded-md border border-slate-800 bg-slate-950 shadow-xl overflow-hidden">
                {recentSearches.map((item) => (
                  <button
                    key={item}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      setHistoryOpen(false);
                      onSelectSearch?.(item);
                    }}
                    className="w-full px-3 py-2 text-left text-xs text-slate-200 hover:bg-slate-900"
                  >
                    {item}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
        <Button onClick={onResolve} disabled={loading} className="bg-blue-600 h-8 px-6 text-[11px] font-bold uppercase">
          {loading ? "..." : "Load"}
        </Button>
        <Button
          onClick={onAdd}
          disabled={loading}
          className="bg-slate-800 h-8 px-4 text-[11px] font-bold uppercase border border-slate-700 hover:bg-slate-700"
        >
          Add
        </Button>
      </div>

      {/* Right: Metrics Only */}
      <div className="flex items-center gap-3 justify-end h-full">
        <div className="flex flex-col items-end">
          <span className="text-[9px] text-slate-500 uppercase font-bold">Portfolio</span>
          <span className="text-sm font-bold text-emerald-400 font-mono">
            {portfolio === null || portfolio === undefined ? "--" : `$${portfolio.toFixed(2)}`}
          </span>
        </div>
        <div className="flex flex-col items-end">
          <span className="text-[9px] text-slate-500 uppercase font-bold">Cash</span>
          <span className="text-sm font-bold text-emerald-400 font-mono">
            {balance === null || balance === undefined ? "--" : `$${balance.toFixed(2)}`}
          </span>
        </div>
        <div className="flex flex-col items-end">
          <span className="text-[9px] text-slate-500 uppercase font-bold">Backend Books</span>
          <span className="text-sm font-bold text-slate-200 font-mono">
            {backendBooksCount === null || backendBooksCount === undefined ? "--" : backendBooksCount}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative" ref={notificationsRef}>
            <Button
              onClick={() => setNotificationsOpen((open) => !open)}
              className={`h-7 w-10 px-0 text-[10px] uppercase font-bold border transition-colors flex items-center justify-center relative ${
                notificationsCount
                  ? "border-blue-500/60 bg-blue-500/10 text-blue-200 hover:border-blue-400"
                  : "border-slate-800 bg-slate-950 text-slate-200 hover:text-white hover:border-slate-700"
              }`}
              aria-label="Notifications"
            >
              <svg
                className="h-4 w-4"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M15 17h5l-1.4-1.4A2 2 0 0 1 18 14.2V11a6 6 0 1 0-12 0v3.2a2 2 0 0 1-.6 1.4L4 17h5" />
                <path d="M9 17a3 3 0 0 0 6 0" />
              </svg>
              {notificationsCount ? (
                <>
                  <span className="absolute -top-1 -right-1 h-2 w-2 rounded-full bg-blue-500 animate-pulse" />
                  <span className="ml-1 text-[9px] text-blue-200 font-mono">{notificationsCount}</span>
                </>
              ) : null}
            </Button>
            {notificationsOpen && (
              <div className="absolute right-0 top-10 z-40 w-[380px] rounded-md border border-slate-200 bg-white/90 text-slate-900 shadow-xl">
                <div className="px-3 py-2 text-[10px] uppercase tracking-widest text-slate-500 border-b border-slate-200">
                  Recent Fills
                </div>
                {fills.length === 0 ? (
                  <div className="px-3 py-3 text-xs text-slate-500">No filled orders yet</div>
                ) : (
                  <ScrollArea className="max-h-[320px]">
                    <div className="divide-y divide-slate-200">
                      {fills.map((fill) => (
                        <div
                          key={`${fill.orderID}-${fill.updatedAt ?? ""}`}
                          className="flex items-center justify-between px-3 py-2"
                        >
                          <div className="flex flex-col min-w-0">
                            <span className="text-slate-900 font-semibold truncate max-w-[240px]">
                              {fill.market || "Unknown market"}
                            </span>
                            <span className="text-[11px] text-slate-600 truncate max-w-[240px]">
                              {fill.outcome || fill.asset_id}
                            </span>
                          </div>
                          <div className="flex flex-col items-end gap-1">
                            <span
                              className={`text-[9px] uppercase px-2 py-0.5 rounded ${
                                fill.side === "BUY"
                                  ? "bg-blue-600/15 text-blue-700"
                                  : "bg-red-600/15 text-red-700"
                              }`}
                            >
                              {fill.side}
                            </span>
                            <span className="text-[10px] text-slate-600 font-mono">
                              {Number(fill.size ?? 0).toFixed(2)} sh @ {(Number(fill.price ?? 0) * 100).toFixed(0)}¢
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </ScrollArea>
                )}
              </div>
            )}
          </div>
          <div className="flex flex-col items-end gap-0.5">
            <Button
              onClick={onPositionsClick}
              className="h-7 w-28 px-4 text-[11px] uppercase font-bold border border-slate-800 bg-slate-950 text-slate-200 hover:text-white hover:border-slate-700 transition-colors"
            >
              Positions {positionsCount === null || positionsCount === undefined ? "--" : `(${positionsCount})`}
            </Button>
            <Button
              onClick={onOrdersClick}
              className="h-7 w-28 px-4 text-[11px] uppercase font-bold border border-slate-800 bg-slate-950 text-slate-200 hover:text-white hover:border-slate-700 transition-colors"
            >
              Orders {ordersCount === null || ordersCount === undefined ? "" : `(${ordersCount})`}
            </Button>
          </div>
          <Button
            onClick={onSettingsClick}
            className="h-7 px-3 text-[10px] uppercase font-bold border border-slate-800 bg-slate-950 text-slate-300 hover:text-white hover:border-slate-700 transition-colors"
          >
            Settings
          </Button>
          <Button
            onClick={onLogsClick}
            className="h-7 px-3 text-[10px] uppercase font-bold border border-slate-800 bg-slate-950 text-slate-300 hover:text-white hover:border-slate-700 transition-colors"
          >
            Logs {logsCount === null || logsCount === undefined ? "" : `(${logsCount})`}
          </Button>
          {/* <div className="flex flex-col items-start gap-1 text-[9px] uppercase font-bold text-slate-500">
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                ordersWsStatus === "open"
                  ? "bg-emerald-400"
                  : ordersWsStatus === "error"
                  ? "bg-red-400"
                  : "bg-slate-500"
              }`}
            />
            <span>Orders WS {ordersWsStatus ?? "unknown"}</span>
            {ordersWsEvents !== undefined && <span>{ordersWsEvents}</span>}
            {ordersWsLastType ? <span>({ordersWsLastType})</span> : null}
            {ordersWsServerPid ? <span>pid {ordersWsServerPid}</span> : null}
            {ordersWsStatus !== "open" && ordersWsCloseInfo ? <span>{ordersWsCloseInfo}</span> : null}
            {ordersWsStatus === "error" && ordersWsErrorInfo ? <span>{ordersWsErrorInfo}</span> : null}
          </div> */}
        </div>
      </div>
    </nav>
  );
}
