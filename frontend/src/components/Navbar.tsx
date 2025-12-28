import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

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
  ordersWsStatus?: "connecting" | "open" | "closed" | "error";
  ordersWsEvents?: number;
  ordersWsLastType?: string | null;
  ordersWsServerPid?: number | null;
  ordersWsCloseInfo?: string | null;
  ordersWsErrorInfo?: string | null;
  recentSearches?: string[];
  onSelectSearch?: (value: string) => void;
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
  onSettingsClick,
  ordersCount,
//   ordersWsStatus,
//   ordersWsEvents,
//   ordersWsLastType,
//   ordersWsServerPid,
//   ordersWsCloseInfo,
//   ordersWsErrorInfo,
  recentSearches = [],
  onSelectSearch,
}: NavbarProps) {
  const [historyOpen, setHistoryOpen] = useState(false);
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
        <div className="flex items-center gap-2">
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
